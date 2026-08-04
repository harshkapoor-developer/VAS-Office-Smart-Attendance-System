"""
take_photos.py
---------------
Interactive CLI: captures multiple face angles for an employee via
webcam, saves them to employee_images/{id}/, then encodes and caches
them via FaceRecognitionEngine.

Requires face_recognition/dlib to be installed (see PHASE0_SETUP.md).
This script is meant to be run directly on the machine with the camera:

    python take_photos.py

It will prompt for an employee ID that must already be registered
(via EmployeeManager / the GUI in a later phase) - this script only
handles the photo capture + encoding step, not employee record creation,
so re-running it to update a face doesn't touch employee metadata.
"""

from __future__ import annotations

import sys
import time

import cv2

import config
from services.camera_manager import CameraManager
from services.database_manager import DatabaseManager
from services.employee_manager import EmployeeManager
from services.encoding_cache import EncodingCache
from services.face_recognition_engine import FaceRecognitionEngine
from utils.bootstrap import ensure_directories
from utils.exceptions import CameraError, FaceEncodingError
from utils.logger import get_logger

logger = get_logger(__name__)

WINDOW_NAME = "Face Registration - press SPACE to capture, ESC to cancel"


def _countdown_capture(cam: CameraManager, angle_label: str) -> "cv2.typing.MatLike":
    """Shows a live preview with an on-screen prompt and waits for the
    user to press SPACE to capture, or ESC to abort. Returns the
    captured frame.
    """
    print(f"\n>> Position yourself: {angle_label}")
    print("   Press SPACE to capture this angle, or ESC to cancel registration.")

    while True:
        frame = cam.read_frame()
        display = frame.copy()
        cv2.putText(
            display, f"Angle: {angle_label}", (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2,
        )
        cv2.putText(
            display, "SPACE = capture   ESC = cancel", (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
        )
        cv2.imshow(WINDOW_NAME, display)

        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            raise KeyboardInterrupt("Registration cancelled by user.")
        if key == 32:  # SPACE
            return frame


def capture_employee_photos(employee_id: str) -> int:
    """Captures config.CAPTURE_ANGLES_PER_EMPLOYEE photos for the given
    employee, saves them, and returns the number saved.
    """
    emp_mgr = EmployeeManager()
    employee = emp_mgr.get_employee(employee_id)
    if employee is None:
        raise ValueError(
            f"Employee ID '{employee_id}' is not registered yet. "
            "Register the employee's details first, then run this script."
        )

    photo_dir = emp_mgr.employee_photo_dir(employee_id)
    angle_labels = _angle_labels(config.CAPTURE_ANGLES_PER_EMPLOYEE)

    saved_count = 0
    with CameraManager() as cam:
        cv2.namedWindow(WINDOW_NAME)
        try:
            for i, label in enumerate(angle_labels, start=1):
                frame = _countdown_capture(cam, label)
                filename = photo_dir / f"{employee_id}_{i:02d}.jpg"
                cv2.imwrite(str(filename), frame)
                saved_count += 1
                print(f"   Saved: {filename.name}")
                time.sleep(0.3)  # brief pause so the next prompt isn't jarring
        finally:
            cv2.destroyWindow(WINDOW_NAME)

    return saved_count


def _angle_labels(n: int) -> list[str]:
    base = ["Look straight ahead", "Turn slightly left", "Turn slightly right",
            "Tilt slightly up", "Tilt slightly down", "Neutral, relaxed expression"]
    if n <= len(base):
        return base[:n]
    # If more angles are requested than we have canned labels for, repeat
    # "Neutral" for the extras rather than crashing on an index error.
    return base + ["Neutral, relaxed expression"] * (n - len(base))


def main() -> int:
    ensure_directories()

    print("=" * 60)
    print("Smart Attendance System - Face Registration")
    print("=" * 60)

    employee_id = input("Enter Employee ID to register/update face for: ").strip()
    if not employee_id:
        print("No Employee ID entered. Exiting.")
        return 1

    try:
        saved = capture_employee_photos(employee_id)
    except KeyboardInterrupt as exc:
        print(f"\nCancelled: {exc}")
        return 1
    except (ValueError, CameraError) as exc:
        print(f"\nError: {exc}")
        return 1

    print(f"\nCaptured {saved} photo(s). Generating face encodings...")

    try:
        engine = FaceRecognitionEngine(cache=EncodingCache())
        emp_mgr = EmployeeManager()
        photo_dir = emp_mgr.employee_photo_dir(employee_id)
        encoded_count = engine.enroll_employee_from_photos(employee_id, photo_dir)
    except FaceEncodingError as exc:
        print(f"\nEncoding failed: {exc}")
        print("Try running this script again with better lighting / a clearer view of your face.")
        return 1

    print(f"\nSuccess: {encoded_count} encoding(s) saved for employee '{employee_id}'.")
    print("This employee can now be recognized by the attendance system.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
