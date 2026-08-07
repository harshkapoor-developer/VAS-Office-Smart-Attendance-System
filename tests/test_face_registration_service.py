"""
tests/test_face_registration_service.py
--------------------------------------------
Real tests for FaceRegistrationSession's non-camera logic (progress
tracking, angle labels, save/discard bookkeeping), plus mocked-camera
tests for the open/read/finish lifecycle - same honest mocking pattern
as the rest of the project's face_recognition/dlib-boundary tests.

Run with: python tests/test_face_registration_service.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import config
from services.database_manager import DatabaseManager
from services.employee_manager import EmployeeManager
from services.face_registration_service import FaceRegistrationSession, angle_labels
from utils.exceptions import CameraError


class TestAngleLabels(unittest.TestCase):
    def test_returns_exact_count(self) -> None:
        self.assertEqual(len(angle_labels(5)), 5)
        self.assertEqual(len(angle_labels(18)), 18)

    def test_more_than_base_repeats_neutral(self) -> None:
        labels = angle_labels(30)
        self.assertEqual(len(labels), 30)
        self.assertEqual(labels[-1], "Neutral, relaxed expression")


class TestFaceRegistrationSession(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self._orig_images_dir = config.EMPLOYEE_IMAGES_DIR
        self._orig_encodings_file = config.ENCODINGS_FILE
        config.EMPLOYEE_IMAGES_DIR = tmp_root / "employee_images"
        config.ENCODINGS_FILE = tmp_root / "encodings.pkl"

        self.db = DatabaseManager(db_path=tmp_root / "test.db")
        self.emp_mgr = EmployeeManager(db=self.db)
        self.emp_mgr.register_employee(
            employee_id="EMP001", name="Harsh Kapoor", department="Eng",
            designation="Dev", mobile="9999999999", email="harsh@example.com",
        )

    def tearDown(self) -> None:
        config.EMPLOYEE_IMAGES_DIR = self._orig_images_dir
        config.ENCODINGS_FILE = self._orig_encodings_file
        self._tmpdir.cleanup()

    def test_open_camera_unknown_employee_raises(self) -> None:
        session = FaceRegistrationSession("GHOST", target_count=3, emp_mgr=self.emp_mgr)
        with self.assertRaises(ValueError):
            session.open_camera()

    def test_progress_and_completion_tracking(self) -> None:
        session = FaceRegistrationSession("EMP001", target_count=3, emp_mgr=self.emp_mgr)
        session._photo_dir = self.emp_mgr.employee_photo_dir("EMP001")  # bypass real camera.open()
        self.assertFalse(session.is_complete)
        self.assertEqual(session.progress_text, "0/3 images captured")

        frame = np.zeros((10, 10, 3), dtype="uint8")
        session.save_frame(frame)
        self.assertEqual(session.progress_text, "1/3 images captured")
        self.assertFalse(session.is_complete)

        session.save_frame(frame)
        session.save_frame(frame)
        self.assertTrue(session.is_complete)

    def test_save_frame_after_complete_raises(self) -> None:
        session = FaceRegistrationSession("EMP001", target_count=1, emp_mgr=self.emp_mgr)
        session._photo_dir = self.emp_mgr.employee_photo_dir("EMP001")
        frame = np.zeros((10, 10, 3), dtype="uint8")
        session.save_frame(frame)
        with self.assertRaises(ValueError):
            session.save_frame(frame)

    def test_saved_photos_actually_written_to_disk(self) -> None:
        session = FaceRegistrationSession("EMP001", target_count=2, emp_mgr=self.emp_mgr)
        photo_dir = self.emp_mgr.employee_photo_dir("EMP001")
        session._photo_dir = photo_dir
        frame = (np.random.rand(20, 20, 3) * 255).astype("uint8")
        path1 = session.save_frame(frame)
        path2 = session.save_frame(frame)
        self.assertTrue(path1.exists())
        self.assertTrue(path2.exists())
        self.assertEqual(len(list(photo_dir.glob("*.jpg"))), 2)

    def test_discard_removes_captured_photos_and_resets_count(self) -> None:
        session = FaceRegistrationSession("EMP001", target_count=2, emp_mgr=self.emp_mgr)
        photo_dir = self.emp_mgr.employee_photo_dir("EMP001")
        session._photo_dir = photo_dir
        frame = np.zeros((10, 10, 3), dtype="uint8")
        session.save_frame(frame)
        self.assertEqual(len(list(photo_dir.glob("*.jpg"))), 1)

        session.discard_captured_photos()
        self.assertEqual(len(list(photo_dir.glob("*.jpg"))), 0)
        self.assertEqual(session.captured_count, 0)

    def test_current_label_matches_progress(self) -> None:
        session = FaceRegistrationSession("EMP001", target_count=3, emp_mgr=self.emp_mgr)
        session._photo_dir = self.emp_mgr.employee_photo_dir("EMP001")
        self.assertEqual(session.current_label, angle_labels(3)[0])
        session.save_frame(np.zeros((10, 10, 3), dtype="uint8"))
        self.assertEqual(session.current_label, angle_labels(3)[1])

    def test_open_camera_wraps_camera_error(self) -> None:
        session = FaceRegistrationSession("EMP001", target_count=2, emp_mgr=self.emp_mgr)
        fake_camera_cls = MagicMock()
        fake_camera_cls.return_value.open.side_effect = CameraError("no camera")
        with patch("services.face_registration_service.CameraManager", fake_camera_cls):
            with self.assertRaises(CameraError):
                session.open_camera()

    def test_read_frame_before_open_raises(self) -> None:
        session = FaceRegistrationSession("EMP001", target_count=2, emp_mgr=self.emp_mgr)
        with self.assertRaises(CameraError):
            session.read_frame()

    def test_close_is_idempotent(self) -> None:
        session = FaceRegistrationSession("EMP001", target_count=2, emp_mgr=self.emp_mgr)
        session.close()
        session.close()  # must not raise on a session that was never opened


if __name__ == "__main__":
    unittest.main(verbosity=2)
