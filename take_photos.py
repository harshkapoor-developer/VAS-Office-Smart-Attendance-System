"""
take_photos.py
---------------
Interactive CLI face-capture tool. Kept for scripted/headless use and
for updating an existing employee's face without opening the full GUI -
all the actual capture/save/encode logic now lives in
services/face_registration_service.py (shared with the in-app Register
Employee -> Capture Face flow), so this file is just a thin terminal
front-end over that shared session object.

    python take_photos.py
"""

from __future__ import annotations

import sys
import time

import cv2

from services.face_registration_service import FaceRegistrationSession
from utils.bootstrap import ensure_directories
from utils.exceptions import CameraError, FaceEncodingError
from utils.logger import get_logger

logger = get_logger(__name__)

WINDOW_NAME = "Face Registration - press SPACE to capture, ESC to cancel"


def _countdown_capture(session: FaceRegistrationSession) -> None:
    """Shows a live preview with an on-screen prompt, waits for SPACE to
    capture the current angle (saving it via the session), or ESC to abort.
    """
    label = session.current_label
    print(f"\n>> Position yourself: {label}")
    print(f"   ({session.progress_text}) Press SPACE to capture, ESC to cancel.")

    while True:
        frame = session.read_frame()
        display = frame.copy()
        cv2.putText(display, f"Angle: {label}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
        cv2.putText(display, session.progress_text, (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(display, "SPACE = capture   ESC = cancel", (20, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imshow(WINDOW_NAME, display)

        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            raise KeyboardInterrupt("Registration cancelled by user.")
        if key == 32:  # SPACE
            session.save_frame(frame)
            return


def main() -> int:
    ensure_directories()

    print("=" * 60)
    print("Smart Attendance System - Face Registration")
    print("=" * 60)

    employee_id = input("Enter Employee ID to register/update face for: ").strip()
    if not employee_id:
        print("No Employee ID entered. Exiting.")
        return 1

    session = FaceRegistrationSession(employee_id)

    try:
        session.open_camera()
        cv2.namedWindow(WINDOW_NAME)
        try:
            while not session.is_complete:
                _countdown_capture(session)
                print(f"   Saved. ({session.progress_text})")
                time.sleep(0.3)  # brief pause so the next prompt isn't jarring
        finally:
            cv2.destroyWindow(WINDOW_NAME)
    except KeyboardInterrupt as exc:
        session.discard_captured_photos()
        session.close()
        print(f"\nCancelled: {exc}")
        return 1
    except (ValueError, CameraError) as exc:
        session.close()
        print(f"\nError: {exc}")
        return 1

    print(f"\nCaptured {session.captured_count} photo(s). Generating face encodings...")

    try:
        encoded_count = session.finish()
    except FaceEncodingError as exc:
        print(f"\nEncoding failed: {exc}")
        print("Try running this script again with better lighting / a clearer view of your face.")
        return 1

    print(f"\nSuccess: {encoded_count} encoding(s) saved for employee '{employee_id}'.")
    print("This employee can now be recognized by the attendance system.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
