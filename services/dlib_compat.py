"""
services/dlib_compat.py
---------------------------
Compatibility shim for dlib's compute_face_descriptor() API.

dlib 20.0.0/20.0.1 changed compute_face_descriptor()'s pybind11 call
signature. face_recognition 1.3.0 (unmaintained since ~2021) calls it
the pre-20.0.0 way, so that combination raises a TypeError on every
single face encoding attempt.

requirements.txt now pins dlib<20.0.0 as the primary fix - anyone doing
a clean install never hits this. This module is the second line of
defense for anyone who already has an incompatible dlib installed (or a
future dlib release that breaks the signature again): it tries
face_recognition's normal call path first (zero overhead, unchanged
behavior when versions are compatible), and only falls back to manual
signature adaptation if that raises the specific TypeError this break
causes.

This is the ONLY place in the project that reaches around
face_recognition's public API into dlib's face_recognition_model_v1
directly - everything else still goes through
services/face_recognition_engine.py, which is the only file that
imports face_recognition/dlib at all.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from utils.logger import get_logger

logger = get_logger(__name__)

try:
    import face_recognition
    _FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    face_recognition = None  # type: ignore[assignment]
    _FACE_RECOGNITION_AVAILABLE = False

# face_recognition.api (needed for the FALLBACK path's direct
# compute_face_descriptor access) is imported lazily inside
# _get_fallback_api(), not here at module level. This matters: the fast
# path below only ever touches face_recognition.face_encodings(), the
# exact same single dependency face_recognition_engine.py already
# requires - importing face_recognition.api eagerly here would make
# this module's availability depend on dlib's internals even when the
# fast path (the common case) never needs them.
_fr_api = None  # populated on first fallback attempt, cached after

# Cached once we know which call pattern actually works on this machine's
# dlib build, so we don't re-probe every single frame during live
# recognition - that would add real latency to the recognition loop.
_working_call_pattern: Optional[str] = None


def _get_fallback_api():
    """Lazily imports face_recognition.api on first fallback attempt.
    Raising here (rather than at module import time) means the fast
    path's failure modes are identical to before this shim existed -
    only code that actually reaches the fallback branch needs dlib's
    internals to be importable.
    """
    global _fr_api
    if _fr_api is None:
        import face_recognition.api as fr_api  # noqa: PLC0415 - intentionally lazy
        _fr_api = fr_api
    return _fr_api


def _raw_landmarks(face_image: np.ndarray, face_locations) -> list:
    """Mirrors face_recognition.api._raw_face_landmarks() - builds the
    68-point landmark shapes compute_face_descriptor needs. This part of
    the API has been stable across dlib versions; only
    compute_face_descriptor's own signature changed.
    """
    api = _get_fallback_api()
    face_locations_dlib = [api._css_to_rect(loc) for loc in face_locations]
    return [api.pose_predictor_68_point(face_image, loc) for loc in face_locations_dlib]


def _try_call_patterns(encoder, face_image: np.ndarray, landmark, num_jitters: int):
    """Tries several known-plausible compute_face_descriptor call shapes,
    in order from "current face_recognition-style" to "newer dlib
    keyword-based", and remembers whichever one works.

    Each pattern is wrapped individually so a TypeError from one doesn't
    prevent trying the next - only the LAST failure's exception is
    surfaced if every pattern fails, since that's the most informative
    one for debugging an unknown future signature change.
    """
    global _working_call_pattern

    patterns = {
        "positional_jitters": lambda: encoder.compute_face_descriptor(face_image, landmark, num_jitters),
        "keyword_jitters": lambda: encoder.compute_face_descriptor(
            face_image, landmark, num_jitters=num_jitters
        ),
        "keyword_jitters_padding": lambda: encoder.compute_face_descriptor(
            face_image, landmark, num_jitters=num_jitters, padding=0.25
        ),
        "positional_jitters_padding": lambda: encoder.compute_face_descriptor(
            face_image, landmark, num_jitters, 0.25
        ),
    }

    # If we already know which pattern works on this machine, try it
    # first so subsequent calls (i.e. every frame in the live recognition
    # loop) pay no repeated-probing cost.
    ordered_names = list(patterns.keys())
    if _working_call_pattern in ordered_names:
        ordered_names.remove(_working_call_pattern)
        ordered_names.insert(0, _working_call_pattern)

    last_exc: Optional[Exception] = None
    for name in ordered_names:
        try:
            result = patterns[name]()
            if _working_call_pattern != name:
                logger.warning(
                    "dlib compatibility shim: compute_face_descriptor() required call "
                    "pattern '%s' instead of face_recognition's default. This means your "
                    "installed dlib version has a different API than face_recognition "
                    "1.3.0 expects - requirements.txt pins dlib<20.0.0 to avoid this; "
                    "consider reinstalling with `pip install \"dlib<20.0.0\"` when convenient.",
                    name,
                )
                _working_call_pattern = name
            return result
        except TypeError as exc:
            last_exc = exc
            continue

    raise RuntimeError(
        "dlib compatibility shim: compute_face_descriptor() rejected every known call "
        "pattern. Your dlib version's API has changed in a way this shim doesn't yet "
        "handle. Run `pip install \"dlib<20.0.0\"` to install a known-compatible version."
    ) from last_exc


def _typeerror_originated_in_compute_face_descriptor(exc: TypeError) -> bool:
    """Walks the exception's traceback looking for a frame whose function
    is named compute_face_descriptor. This is far more reliable than
    string-matching the exception's message text: a real TypeError about
    a wrong argument count names the function that rejected the call
    (e.g. "strict_new_style_compute() takes 2 positional arguments"),
    NOT "compute_face_descriptor" - the message content varies across
    Python/pybind11 versions in ways a substring check can't keep up
    with. Walking frames checks WHERE the error happened, not how it's
    worded, which is exactly what distinguishes "the known dlib break"
    from "some unrelated bug that happens to also raise TypeError".
    """
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_name == "compute_face_descriptor":
            return True
        tb = tb.tb_next
    return False


def safe_face_encodings(
    face_image: np.ndarray, known_face_locations: list, num_jitters: int = 1
) -> list[np.ndarray]:
    """Drop-in replacement for face_recognition.face_encodings() that
    self-heals against the dlib 20.0.0+/face_recognition 1.3.0
    compute_face_descriptor() signature break.

    Fast path: calls face_recognition.face_encodings() directly (zero
    overhead, byte-identical behavior to before this shim existed) and
    only engages the fallback if that raises a TypeError that actually
    originated inside compute_face_descriptor() - a TypeError from
    somewhere else (bad input shape, etc.) propagates normally instead
    of being masked by a fallback attempt that isn't relevant to it.
    """
    if not _FACE_RECOGNITION_AVAILABLE:
        raise RuntimeError("face_recognition is not installed.")

    if not known_face_locations:
        return []

    try:
        return face_recognition.face_encodings(
            face_image,
            known_face_locations=known_face_locations,
            num_jitters=num_jitters
        )

    except TypeError as exc:
        if not _typeerror_originated_in_compute_face_descriptor(exc):
            raise

    logger.info("Using dlib compatibility fallback shim.")

    api = _get_fallback_api()

    face_image = np.ascontiguousarray(face_image, dtype=np.uint8)

    landmarks = _raw_landmarks(face_image, known_face_locations)

    return [
        np.array(
            _try_call_patterns(
                api.face_encoder,
                face_image,
                landmark,
                num_jitters
            )
        )
        for landmark in landmarks
    ]