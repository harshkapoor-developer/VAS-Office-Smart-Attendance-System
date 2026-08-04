"""
tests/test_face_recognition_engine.py
----------------------------------------
face_recognition/dlib is not installed in this dev sandbox (see
PHASE0_SETUP.md - no prebuilt wheels exist for it). To still verify
FaceRecognitionEngine's ORCHESTRATION logic (skip-bad-photos, error
propagation, cache writes) without dlib, this test injects a fake
`face_recognition` module into sys.modules before importing the engine.

This proves the Python logic is correct. It does NOT prove real face
detection accuracy - that can only be verified on a machine with dlib
installed and a real camera/photos, which is why Phase 0 has you run
validate_environment.py separately with the real library.

Run with:
    python tests/test_face_recognition_engine.py
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np


def _install_fake_face_recognition() -> "types.ModuleType":
    """Builds a minimal stand-in for the face_recognition module whose
    behavior we control from the test, then registers it in sys.modules
    so `import face_recognition` inside the engine picks it up.
    """
    fake = types.ModuleType("face_recognition")

    # Configuration the test can adjust per-case.
    fake._face_count_by_path = {}  # type: ignore[attr-defined]
    fake._default_face_count = 1  # type: ignore[attr-defined]

    def load_image_file(path: str) -> np.ndarray:
        return np.zeros((10, 10, 3), dtype="uint8")

    def face_locations(image: np.ndarray, model: str = "hog"):
        count = getattr(fake, "_next_face_count", None)
        if count is None:
            count = fake._default_face_count  # type: ignore[attr-defined]
        return [(0, 10, 10, 0)] * count

    def face_encodings(image, known_face_locations=None, num_jitters=1):
        n = len(known_face_locations) if known_face_locations else 1
        forced = getattr(fake, "_next_encoding", None)
        if forced is not None:
            return [forced for _ in range(n)]
        return [np.ones(128) * i for i in range(n)]

    def face_distance(known_encodings, encoding_to_check):
        return np.array([
            np.linalg.norm(np.asarray(k) - np.asarray(encoding_to_check))
            for k in known_encodings
        ])

    fake.load_image_file = load_image_file  # type: ignore[attr-defined]
    fake.face_locations = face_locations  # type: ignore[attr-defined]
    fake.face_encodings = face_encodings  # type: ignore[attr-defined]
    fake.face_distance = face_distance  # type: ignore[attr-defined]

    sys.modules["face_recognition"] = fake
    return fake


_fake_fr = _install_fake_face_recognition()

# Import AFTER the fake module is registered, and force a fresh import so
# the engine module's `import face_recognition` binds to our fake.
sys.modules.pop("services.face_recognition_engine", None)
from services.face_recognition_engine import FaceRecognitionEngine  # noqa: E402
from services.encoding_cache import EncodingCache  # noqa: E402
from utils.exceptions import FaceEncodingError  # noqa: E402


class TestFaceRecognitionEngine(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        cache_path = Path(self._tmpdir.name) / "encodings.pkl"
        self.cache = EncodingCache(cache_path=cache_path)
        self.engine = FaceRecognitionEngine(cache=self.cache)
        _fake_fr._next_face_count = 1  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _make_photo_dir(self, n_photos: int) -> Path:
        photo_dir = Path(self._tmpdir.name) / "photos"
        photo_dir.mkdir(exist_ok=True)
        for i in range(n_photos):
            (photo_dir / f"angle_{i}.jpg").write_bytes(b"fake image bytes")
        return photo_dir

    def test_encode_image_file_single_face_succeeds(self) -> None:
        photo_dir = self._make_photo_dir(1)
        path = next(photo_dir.glob("*.jpg"))
        _fake_fr._next_face_count = 1  # type: ignore[attr-defined]
        encoding = self.engine.encode_image_file(path)
        self.assertEqual(encoding.shape, (128,))

    def test_encode_image_file_zero_faces_raises(self) -> None:
        photo_dir = self._make_photo_dir(1)
        path = next(photo_dir.glob("*.jpg"))
        _fake_fr._next_face_count = 0  # type: ignore[attr-defined]
        with self.assertRaises(FaceEncodingError):
            self.engine.encode_image_file(path)

    def test_encode_image_file_multiple_faces_raises(self) -> None:
        photo_dir = self._make_photo_dir(1)
        path = next(photo_dir.glob("*.jpg"))
        _fake_fr._next_face_count = 2  # type: ignore[attr-defined]
        with self.assertRaises(FaceEncodingError):
            self.engine.encode_image_file(path)

    def test_enroll_employee_from_photos_success(self) -> None:
        photo_dir = self._make_photo_dir(5)
        _fake_fr._next_face_count = 1  # type: ignore[attr-defined]
        count = self.engine.enroll_employee_from_photos("EMP001", photo_dir)
        self.assertEqual(count, 5)
        self.assertTrue(self.cache.has_encodings("EMP001"))
        self.assertEqual(len(self.cache.get_encodings("EMP001")), 5)

    def test_enroll_skips_bad_photos_but_succeeds_with_rest(self) -> None:
        photo_dir = self._make_photo_dir(3)
        paths = sorted(photo_dir.glob("*.jpg"))

        # Make the engine fail detection specifically by patching
        # face_locations to vary per call: first photo has 0 faces
        # (bad), rest have 1 (good).
        call_state = {"n": 0}

        def flaky_face_locations(image, model="hog"):
            call_state["n"] += 1
            return [] if call_state["n"] == 1 else [(0, 10, 10, 0)]

        _fake_fr.face_locations = flaky_face_locations  # type: ignore[attr-defined]

        count = self.engine.enroll_employee_from_photos("EMP002", photo_dir)
        self.assertEqual(count, 2)  # 1 skipped, 2 succeeded

    def test_enroll_raises_when_all_photos_fail(self) -> None:
        photo_dir = self._make_photo_dir(2)
        _fake_fr.face_locations = lambda image, model="hog": []  # type: ignore[attr-defined]
        with self.assertRaises(FaceEncodingError):
            self.engine.enroll_employee_from_photos("EMP003", photo_dir)

    def test_enroll_raises_on_empty_folder(self) -> None:
        empty_dir = Path(self._tmpdir.name) / "empty"
        empty_dir.mkdir()
        with self.assertRaises(FaceEncodingError):
            self.engine.enroll_employee_from_photos("EMP004", empty_dir)

    def test_remove_employee_encodings(self) -> None:
        photo_dir = self._make_photo_dir(2)
        self.engine.enroll_employee_from_photos("EMP005", photo_dir)
        self.assertTrue(self.cache.has_encodings("EMP005"))
        self.engine.remove_employee_encodings("EMP005")
        self.assertFalse(self.cache.has_encodings("EMP005"))

    # ------------------------------------------------------------------
    # Recognition (Phase 5)
    # ------------------------------------------------------------------
    def test_match_encoding_empty_cache_returns_none(self) -> None:
        unknown_encoding = np.ones(128) * 5
        employee_id, confidence = self.engine.match_encoding(unknown_encoding)
        self.assertIsNone(employee_id)
        self.assertEqual(confidence, 0.0)

    def test_match_encoding_exact_match_high_confidence(self) -> None:
        known = np.ones(128) * 3
        self.cache.set_encodings("EMP010", [known])
        employee_id, confidence = self.engine.match_encoding(known)
        self.assertEqual(employee_id, "EMP010")
        self.assertGreater(confidence, 99.0)

    def test_match_encoding_far_vector_returns_unknown(self) -> None:
        known = np.zeros(128)
        self.cache.set_encodings("EMP011", [known])
        far_away = np.ones(128) * 100
        employee_id, confidence = self.engine.match_encoding(far_away)
        self.assertIsNone(employee_id)

    def test_match_encoding_picks_closest_of_multiple(self) -> None:
        self.cache.set_encodings("EMP_A", [np.ones(128) * 1])
        self.cache.set_encodings("EMP_B", [np.ones(128) * 3])
        query = np.ones(128) * 1.01  # small delta -> distance stays within tolerance
        employee_id, _ = self.engine.match_encoding(query)
        self.assertEqual(employee_id, "EMP_A")

    def test_detect_and_encode_frame_no_faces(self) -> None:
        _fake_fr._next_face_count = 0  # type: ignore[attr-defined]
        frame = np.zeros((100, 100, 3), dtype="uint8")
        results = self.engine.detect_and_encode_frame(frame)
        self.assertEqual(results, [])

    def test_detect_and_encode_frame_scales_locations_back_up(self) -> None:
        _fake_fr._next_face_count = 1  # type: ignore[attr-defined]
        frame = np.zeros((400, 400, 3), dtype="uint8")
        results = self.engine.detect_and_encode_frame(frame)
        self.assertEqual(len(results), 1)
        location, encoding = results[0]
        top, right, bottom, left = location
        self.assertGreater(right, 10)
        self.assertEqual(encoding.shape, (128,))

    def test_recognize_frame_end_to_end(self) -> None:
        known = np.ones(128) * 7
        self.cache.set_encodings("EMP020", [known])
        _fake_fr._next_face_count = 1  # type: ignore[attr-defined]
        _fake_fr._next_encoding = known  # type: ignore[attr-defined]

        frame = np.zeros((200, 200, 3), dtype="uint8")
        results = self.engine.recognize_frame(frame)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["employee_id"], "EMP020")
        self.assertGreater(results[0]["confidence"], 99.0)

        _fake_fr._next_encoding = None  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main(verbosity=2)
