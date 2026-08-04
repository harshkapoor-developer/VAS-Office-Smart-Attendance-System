"""
tests/test_dlib_compat.py
-----------------------------
Verifies the compatibility shim's cascading call-pattern logic using a
fake dlib/face_recognition module pair - same honest mocking pattern as
test_face_recognition_engine.py. This proves the FALLBACK LOGIC is
correct (tries multiple call shapes, remembers the working one, raises
clearly if none work). It cannot prove real dlib 20.0.1's actual break
matches one of the patterns tried here, since dlib isn't installed in
this sandbox either (see PHASE0_SETUP.md) - if a real dlib 20.0.1
install still fails after this shim, the RuntimeError it raises tells
you exactly that, rather than a cryptic TypeError.

Run with:
    python tests/test_dlib_compat.py
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np


def _install_fake_dlib_and_face_recognition(compute_face_descriptor_impl, face_encodings_override=None):
    """Builds fake `dlib` and `face_recognition`/`face_recognition.api`
    modules. `compute_face_descriptor_impl` is the encoder function the
    test controls, simulating whichever dlib version's signature is
    under test. `face_encodings_override`, if given, replaces the fast
    path's face_encodings() entirely (set at module-construction time,
    not mutated afterward - a post-hoc attribute override can race with
    pytest's assertion-rewriting import hook, which re-imports modules
    differently than plain unittest).
    """
    fake_dlib = types.ModuleType("dlib")

    class FakeEncoder:
        def compute_face_descriptor(self, *args, **kwargs):
            return compute_face_descriptor_impl(*args, **kwargs)

    fake_dlib.face_recognition_model_v1 = lambda path: FakeEncoder()  # type: ignore[attr-defined]

    fake_fr = types.ModuleType("face_recognition")
    fake_fr_api = types.ModuleType("face_recognition.api")

    fake_fr_api.pose_predictor_68_point = lambda image, rect: f"landmark_for_{rect}"  # type: ignore[attr-defined]
    fake_fr_api._css_to_rect = lambda loc: loc  # type: ignore[attr-defined]
    fake_fr_api.face_encoder = FakeEncoder()  # type: ignore[attr-defined]

    def fake_face_encodings(face_image, known_face_locations=None, num_jitters=1):
        # Simulates face_recognition's real face_encodings() calling
        # compute_face_descriptor with the OLD (pre-20.0.0) signature -
        # this is what raises the TypeError the shim needs to catch.
        landmarks = [
            fake_fr_api.pose_predictor_68_point(face_image, loc) for loc in known_face_locations
        ]
        return [
            np.array(fake_fr_api.face_encoder.compute_face_descriptor(face_image, lm, num_jitters))
            for lm in landmarks
        ]

    fake_fr.face_encodings = face_encodings_override or fake_face_encodings  # type: ignore[attr-defined]
    fake_fr.api = fake_fr_api  # type: ignore[attr-defined]

    sys.modules["dlib"] = fake_dlib
    sys.modules["face_recognition"] = fake_fr
    sys.modules["face_recognition.api"] = fake_fr_api
    sys.modules.pop("services.dlib_compat", None)

    return fake_dlib, fake_fr, fake_fr_api


class TestDlibCompatShimFastPath(unittest.TestCase):
    """When the installed dlib/face_recognition versions are actually
    compatible (the normal case after this project's requirements.txt
    pin), the shim should add zero behavior change - just pass through.
    """

    def tearDown(self) -> None:
        for mod in ("dlib", "face_recognition", "face_recognition.api", "services.dlib_compat"):
            sys.modules.pop(mod, None)

    def test_compatible_dlib_uses_fast_path_unchanged(self) -> None:
        def old_style_compute(face_image, landmark, num_jitters):
            return [0.1] * 128  # the "correct", pre-break call signature

        _install_fake_dlib_and_face_recognition(old_style_compute)
        from services.dlib_compat import safe_face_encodings

        result = safe_face_encodings(
            np.zeros((10, 10, 3), dtype="uint8"), known_face_locations=[(0, 10, 10, 0)], num_jitters=1
        )
        self.assertEqual(len(result), 1)
        np.testing.assert_array_almost_equal(result[0], [0.1] * 128)

    def test_empty_locations_returns_empty_without_calling_dlib(self) -> None:
        calls = {"count": 0}

        def counting_compute(face_image, landmark, num_jitters):
            calls["count"] += 1
            return [0.1] * 128

        _install_fake_dlib_and_face_recognition(counting_compute)
        from services.dlib_compat import safe_face_encodings

        result = safe_face_encodings(np.zeros((10, 10, 3), dtype="uint8"), known_face_locations=[])
        self.assertEqual(result, [])
        self.assertEqual(calls["count"], 0)


class TestDlibCompatShimFallback(unittest.TestCase):
    """Simulates the actual dlib 20.0.0+ break: face_recognition's normal
    face_encodings() call raises TypeError, and the shim must fall back
    to manually calling compute_face_descriptor with an adapted
    signature - trying each known pattern until one works.
    """

    def tearDown(self) -> None:
        for mod in ("dlib", "face_recognition", "face_recognition.api", "services.dlib_compat"):
            sys.modules.pop(mod, None)

    def test_falls_back_to_keyword_jitters_pattern(self) -> None:
        def new_style_compute(face_image, landmark, *, num_jitters=1):
            # keyword-only num_jitters: genuinely rejects the old
            # positional-3rd-argument call face_recognition 1.3.0 makes,
            # exactly the shape of a real breaking signature change.
            return [0.2] * 128

        _install_fake_dlib_and_face_recognition(new_style_compute)
        from services.dlib_compat import safe_face_encodings

        result = safe_face_encodings(
            np.zeros((10, 10, 3), dtype="uint8"), known_face_locations=[(0, 10, 10, 0)], num_jitters=1
        )
        self.assertEqual(len(result), 1)
        np.testing.assert_array_almost_equal(result[0], [0.2] * 128)

    def test_falls_back_to_keyword_padding_pattern(self) -> None:
        def strict_new_style_compute(face_image, landmark, *, num_jitters=1, padding):
            # padding is mandatory keyword-only - rejects both the old
            # positional call AND the plain "keyword_jitters" pattern,
            # forcing the shim to reach its third fallback pattern.
            return [0.3] * 128

        _install_fake_dlib_and_face_recognition(strict_new_style_compute)
        from services.dlib_compat import safe_face_encodings

        result = safe_face_encodings(
            np.zeros((10, 10, 3), dtype="uint8"), known_face_locations=[(0, 10, 10, 0)], num_jitters=1
        )
        self.assertEqual(len(result), 1)
        np.testing.assert_array_almost_equal(result[0], [0.3] * 128)

    def test_remembers_working_pattern_across_calls(self) -> None:
        """After the first successful fallback, subsequent calls should
        try the remembered pattern FIRST - this matters for the live
        recognition loop, which calls this once per frame and can't
        afford re-probing every time.
        """
        call_log = []

        def new_style_compute(face_image, landmark, *, num_jitters=1):
            call_log.append(num_jitters)
            return [0.4] * 128

        _install_fake_dlib_and_face_recognition(new_style_compute)
        from services.dlib_compat import safe_face_encodings
        import services.dlib_compat as compat_module

        compat_module._working_call_pattern = None  # ensure a clean slate for this test

        safe_face_encodings(
            np.zeros((10, 10, 3), dtype="uint8"), known_face_locations=[(0, 10, 10, 0)], num_jitters=1
        )
        self.assertIsNotNone(compat_module._working_call_pattern)
        remembered = compat_module._working_call_pattern

        safe_face_encodings(
            np.zeros((10, 10, 3), dtype="uint8"), known_face_locations=[(0, 10, 10, 0)], num_jitters=1
        )
        self.assertEqual(compat_module._working_call_pattern, remembered)

    def test_raises_clear_runtime_error_when_no_pattern_works(self) -> None:
        def always_incompatible(*args, **kwargs):
            raise TypeError("compute_face_descriptor(): completely unknown new signature")

        _install_fake_dlib_and_face_recognition(always_incompatible)
        from services.dlib_compat import safe_face_encodings

        with self.assertRaises(RuntimeError) as ctx:
            safe_face_encodings(
                np.zeros((10, 10, 3), dtype="uint8"), known_face_locations=[(0, 10, 10, 0)], num_jitters=1
            )
        self.assertIn("dlib<20.0.0", str(ctx.exception))

    def test_non_compute_face_descriptor_typeerror_is_not_swallowed(self) -> None:
        """A TypeError from a genuinely different bug (e.g. bad input
        shape) should propagate normally, not get masked by the
        fallback path meant only for the known compute_face_descriptor
        signature break.
        """
        def fake_face_encodings_bad_input(face_image, known_face_locations=None, num_jitters=1):
            raise TypeError("some_other_unrelated_bug(): bad argument")

        _install_fake_dlib_and_face_recognition(
            lambda *a, **k: [0.1] * 128,
            face_encodings_override=fake_face_encodings_bad_input,
        )

        from services.dlib_compat import safe_face_encodings
        with self.assertRaises(TypeError) as ctx:
            safe_face_encodings(
                np.zeros((10, 10, 3), dtype="uint8"), known_face_locations=[(0, 10, 10, 0)], num_jitters=1
            )
        self.assertIn("some_other_unrelated_bug", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
