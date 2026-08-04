"""
services/face_recognition_engine.py
--------------------------------------
Wraps face_recognition/dlib. Along with services/dlib_compat.py (which
it delegates encoding calls to for version-compatibility handling),
these are the only two modules in the project that import
face_recognition/dlib directly - everything else goes through here, so
the dlib dependency is isolated to these two files.

This phase implements the REGISTRATION half: turning captured photos
into encodings and storing them via EncodingCache. The RECOGNITION half
(matching a live frame against the cache) is built in Phase 5 on top of
the same class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

try:
    import face_recognition
    _FACE_RECOGNITION_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when dlib is missing
    face_recognition = None  # type: ignore[assignment]
    _FACE_RECOGNITION_AVAILABLE = False

import config
from services.dlib_compat import safe_face_encodings
from services.encoding_cache import EncodingCache
from utils.exceptions import FaceEncodingError
from utils.logger import get_logger

logger = get_logger(__name__)


class FaceRecognitionEngine:
    def __init__(self, cache: Optional[EncodingCache] = None) -> None:
        if not _FACE_RECOGNITION_AVAILABLE:
            logger.warning(
                "face_recognition/dlib is not installed. FaceRecognitionEngine "
                "will raise FaceEncodingError on any encoding attempt until it "
                "is installed. See PHASE0_SETUP.md."
            )
        self.cache = cache or EncodingCache()

    @staticmethod
    def _require_face_recognition() -> None:
        if not _FACE_RECOGNITION_AVAILABLE:
            raise FaceEncodingError(
                "face_recognition/dlib is not installed in this environment. "
                "Follow PHASE0_SETUP.md to install it before using this feature."
            )

    # ------------------------------------------------------------------
    # Single-image encoding
    # ------------------------------------------------------------------
    def encode_image(self, image: np.ndarray) -> np.ndarray:
        """Detects exactly one face in `image` (RGB or BGR-converted-to-RGB
        numpy array) and returns its 128-d encoding.

        Raises FaceEncodingError if zero or more than one face is found -
        registration photos must contain exactly one, clearly visible face.
        """
        self._require_face_recognition()

        # face_recognition expects RGB; OpenCV frames are BGR.
        if image.ndim == 3 and image.shape[2] == 3:
            rgb_image = image[:, :, ::-1]
        else:
            rgb_image = image

        locations = face_recognition.face_locations(rgb_image, model=config.FACE_DETECTION_MODEL)

        if len(locations) == 0:
            raise FaceEncodingError("No face detected in the captured image. Please retake.")
        if len(locations) > 1:
            raise FaceEncodingError(
                f"Multiple faces ({len(locations)}) detected in the captured image. "
                "Only one person should be in frame during registration."
            )

        encodings = safe_face_encodings(
            rgb_image, known_face_locations=locations, num_jitters=config.FACE_ENCODING_JITTERS
        )
        if not encodings:
            raise FaceEncodingError("Face was detected but encoding failed. Please retake.")

        return encodings[0]

    def encode_image_file(self, image_path: Path) -> np.ndarray:
        self._require_face_recognition()
        image = face_recognition.load_image_file(str(image_path))
        # load_image_file already returns RGB, so bypass the BGR conversion
        # in encode_image by calling the detection steps directly.
        locations = face_recognition.face_locations(image, model=config.FACE_DETECTION_MODEL)
        if len(locations) == 0:
            raise FaceEncodingError(f"No face detected in {image_path.name}.")
        if len(locations) > 1:
            raise FaceEncodingError(f"Multiple faces detected in {image_path.name}.")
        encodings = safe_face_encodings(
            image, known_face_locations=locations, num_jitters=config.FACE_ENCODING_JITTERS
        )
        if not encodings:
            raise FaceEncodingError(f"Encoding failed for {image_path.name}.")
        return encodings[0]

    # ------------------------------------------------------------------
    # Registration: build encodings for a whole employee photo folder
    # ------------------------------------------------------------------
    def enroll_employee_from_photos(self, employee_id: str, photo_dir: Path) -> int:
        """Encodes every image in `photo_dir`, skipping (and logging) any
        that fail rather than aborting the whole enrollment, then saves
        all successful encodings to the cache.

        Returns the number of successfully encoded photos. Raises
        FaceEncodingError if NONE of the photos could be encoded.
        """
        self._require_face_recognition()

        image_paths = sorted(
            p for p in photo_dir.glob("*")
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        if not image_paths:
            raise FaceEncodingError(f"No photos found in {photo_dir} for employee {employee_id}.")

        encodings: list[np.ndarray] = []
        for path in image_paths:
            try:
                encodings.append(self.encode_image_file(path))
            except FaceEncodingError as exc:
                logger.warning("Skipping %s during enrollment: %s", path.name, exc)

        if not encodings:
            raise FaceEncodingError(
                f"None of the {len(image_paths)} photo(s) for {employee_id} "
                "could be encoded. Please recapture."
            )

        self.cache.set_encodings(employee_id, encodings)
        logger.info(
            "Enrolled %s: %d/%d photos encoded successfully.",
            employee_id, len(encodings), len(image_paths),
        )
        return len(encodings)

    def remove_employee_encodings(self, employee_id: str) -> None:
        self.cache.remove_employee(employee_id)

    # ------------------------------------------------------------------
    # Recognition (Phase 5): match live faces against the cache
    # ------------------------------------------------------------------
    def detect_and_encode_frame(
        self, frame: np.ndarray
    ) -> list[tuple[tuple[int, int, int, int], np.ndarray]]:
        """Detects all faces in a live BGR camera frame and returns a list
        of (location, encoding) pairs. location is (top, right, bottom,
        left) in ORIGINAL frame coordinates, already scaled back up from
        the internal detection resolution.

        Unlike encode_image(), this does NOT raise on zero/multiple faces
        - a live frame legitimately has 0-N people in it at any moment.
        """
        self._require_face_recognition()

        # Downscale for detection speed, matching config.RECOGNITION_FRAME_RESIZE_SCALE.
        scale = config.RECOGNITION_FRAME_RESIZE_SCALE
        small_frame = frame
        if scale != 1.0:
            import cv2  # local import: keeps cv2 optional for pure-encoding use cases
            small_frame = cv2.resize(frame, (0, 0), fx=scale, fy=scale)

        rgb_small = small_frame[:, :, ::-1]
        locations_small = face_recognition.face_locations(rgb_small, model=config.FACE_DETECTION_MODEL)

        if not locations_small:
            return []

        encodings = safe_face_encodings(
            rgb_small, known_face_locations=locations_small, num_jitters=config.FACE_ENCODING_JITTERS
        )

        # Scale locations back up to the original frame's coordinate space.
        inv_scale = 1.0 / scale if scale != 0 else 1.0
        scaled_locations = [
            (
                int(top * inv_scale),
                int(right * inv_scale),
                int(bottom * inv_scale),
                int(left * inv_scale),
            )
            for (top, right, bottom, left) in locations_small
        ]

        return list(zip(scaled_locations, encodings))

    def match_encoding(self, encoding: np.ndarray) -> tuple[Optional[str], float]:
        """Compares one face encoding against every cached encoding and
        returns (best_matching_employee_id, confidence_percent).

        Returns (None, 0.0) if the cache is empty. Returns (None,
        confidence) if the best match's confidence is below
        config.MIN_CONFIDENCE_PERCENT - callers should treat that as
        "Unknown" even though a nearest neighbor technically exists.
        """
        self._require_face_recognition()

        known_encodings, known_ids = self.cache.flattened()
        if not known_encodings:
            return None, 0.0

        distances = face_recognition.face_distance(known_encodings, encoding)
        best_index = int(np.argmin(distances))
        best_distance = float(distances[best_index])

        # face_recognition distances are roughly 0 (identical) to ~1
        # (very different) for this model; convert to an intuitive
        # confidence percentage, clamped to [0, 100].
        confidence = max(0.0, min(100.0, (1.0 - best_distance) * 100.0))

        if best_distance > config.FACE_RECOGNITION_TOLERANCE or confidence < config.MIN_CONFIDENCE_PERCENT:
            return None, confidence

        return known_ids[best_index], confidence

    def recognize_frame(self, frame: np.ndarray) -> list[dict]:
        """High-level, one-call recognition for a live frame. Returns a
        list of dicts, one per detected face:
            {
                "location": (top, right, bottom, left),
                "employee_id": str | None,   # None = Unknown
                "confidence": float,         # 0-100
            }
        """
        results = []
        for location, encoding in self.detect_and_encode_frame(frame):
            employee_id, confidence = self.match_encoding(encoding)
            results.append({
                "location": location,
                "employee_id": employee_id,
                "confidence": confidence,
            })
        return results
