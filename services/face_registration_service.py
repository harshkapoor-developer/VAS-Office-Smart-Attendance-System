"""
services/face_registration_service.py
------------------------------------------
Single source of truth for the "capture N face angles -> save images ->
generate encodings" workflow. Both take_photos.py (CLI) and
gui/widgets/face_capture_dialog.py (in-app modal) call THIS - neither
duplicates the capture/save/encode logic itself.

Deliberately has zero GUI dependency (no cv2.imshow/customtkinter here)
so it works identically whether driven by a terminal loop or a Tk
.after() polling loop: the caller owns the display and calls
capture_next_frame()/save_current_frame() as its own event loop ticks.

Camera abstraction is inherited from CameraManager -> camera_source.py,
so this already works on both a Windows/Linux webcam and a Raspberry
Pi Camera Module 3 without any branching here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

import config
from services.camera_manager import CameraManager
from services.employee_manager import EmployeeManager
from services.encoding_cache import EncodingCache
from services.face_recognition_engine import FaceRecognitionEngine
from utils.exceptions import CameraError, FaceEncodingError
from utils.logger import get_logger

logger = get_logger(__name__)

ANGLE_LABELS_BASE: list[str] = [
    "Look straight ahead", "Turn slightly left", "Turn slightly right",
    "Tilt slightly up", "Tilt slightly down", "Rotate head slightly left",
    "Rotate head slightly right", "Look slightly up-left", "Look slightly up-right",
    "Look slightly down-left", "Look slightly down-right", "Neutral, relaxed expression",
]


def angle_labels(n: int) -> list[str]:
    if n <= len(ANGLE_LABELS_BASE):
        return ANGLE_LABELS_BASE[:n]
    # More angles requested than canned labels - repeat "Neutral" for the
    # extras rather than crashing on an index error.
    return ANGLE_LABELS_BASE + ["Neutral, relaxed expression"] * (n - len(ANGLE_LABELS_BASE))


class FaceRegistrationSession:
    """One registration run for one employee. Owns the camera and the
    in-progress capture count; the caller (CLI or GUI) drives the loop
    and calls save_frame()/finish() at its own pace.

    Usage:
        session = FaceRegistrationSession(employee_id)
        session.open_camera()
        while not session.is_complete:
            frame = session.read_frame()
            # ...display it, wait for a capture trigger...
            session.save_frame(frame)
        count = session.finish()   # encodes + saves to cache, releases camera
        session.close()            # always safe to call, idempotent
    """

    def __init__(
        self,
        employee_id: str,
        target_count: int = config.CAPTURE_ANGLES_PER_EMPLOYEE,
        emp_mgr: Optional[EmployeeManager] = None,
        engine: Optional[FaceRecognitionEngine] = None,
    ) -> None:
        self.employee_id = employee_id
        self.target_count = target_count
        self.emp_mgr = emp_mgr or EmployeeManager()
        self.engine = engine or FaceRecognitionEngine(cache=EncodingCache())
        self.labels = angle_labels(target_count)

        self.captured_count = 0
        self._camera: Optional[CameraManager] = None
        self._photo_dir: Optional[Path] = None
        self._saved_paths: list[Path] = []

    @property
    def is_complete(self) -> bool:
        return self.captured_count >= self.target_count

    @property
    def current_label(self) -> str:
        idx = min(self.captured_count, self.target_count - 1)
        return self.labels[idx]

    @property
    def progress_text(self) -> str:
        return f"{self.captured_count}/{self.target_count} images captured"

    # ------------------------------------------------------------------
    # Camera lifecycle
    # ------------------------------------------------------------------
    def open_camera(self) -> None:
        employee = self.emp_mgr.get_employee(self.employee_id)
        if employee is None:
            raise ValueError(
                f"Employee ID '{self.employee_id}' is not registered yet. "
                "Save the employee's details first, then capture their face."
            )
        self._photo_dir = self.emp_mgr.employee_photo_dir(self.employee_id)

        self._camera = CameraManager()
        self._camera.open()  # raises CameraError on failure - works for webcam or Pi Camera 3
        logger.info("Face registration camera opened for %s.", self.employee_id)

    def read_frame(self) -> np.ndarray:
        if self._camera is None:
            raise CameraError("Camera is not open. Call open_camera() first.")
        return self._camera.read_frame()

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------
    def save_frame(self, frame: np.ndarray) -> Path:
        """Saves the given frame as the next angle's photo. Returns the
        saved file path. Raises ValueError if already complete - callers
        should check is_complete before calling this.
        """
        if self.is_complete:
            raise ValueError("Capture already complete - no more angles to save.")
        if self._photo_dir is None:
            raise ValueError("Camera/session not opened yet.")

        import cv2  # local import: keeps this module importable even if cv2 isn't (mirrors project convention)

        index = self.captured_count + 1
        filename = self._photo_dir / f"{self.employee_id}_{index:02d}.jpg"
        cv2.imwrite(str(filename), frame)
        self._saved_paths.append(filename)
        self.captured_count += 1
        logger.info("Saved capture %d/%d for %s: %s", self.captured_count, self.target_count, self.employee_id, filename.name)
        return filename

    # ------------------------------------------------------------------
    # Finish: encode + cache, then release camera
    # ------------------------------------------------------------------
    def finish(self) -> int:
        """Generates and saves face encodings from every captured photo,
        then releases the camera. Returns the number of photos that
        successfully encoded. Raises FaceEncodingError if none did.
        """
        self.close()
        if self._photo_dir is None:
            raise ValueError("Nothing was captured - session was never opened.")
        return self.engine.enroll_employee_from_photos(self.employee_id, self._photo_dir)

    def close(self) -> None:
        """Releases the camera. Safe to call multiple times (idempotent)
        and safe to call on cancel/error paths, not just success.
        """
        if self._camera is not None:
            self._camera.release()
            self._camera = None
            logger.info("Face registration camera released for %s.", self.employee_id)

    def discard_captured_photos(self) -> None:
        """Deletes any photos saved so far in THIS session (cancel path)
        without touching encodings.pkl or any previously-enrolled photos
        from an earlier successful session.
        """
        for path in self._saved_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove discarded capture: %s", path)
        self._saved_paths.clear()
        self.captured_count = 0
