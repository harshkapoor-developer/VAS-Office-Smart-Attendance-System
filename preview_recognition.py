"""
preview_recognition.py
-------------------------
Phase 5 standalone verification tool: opens the webcam, runs live face
recognition against everyone currently enrolled, and shows the annotated
preview window in real time. This does NOT mark attendance - that's
Phase 6. It exists purely so you can confirm recognition quality,
speed, and confidence numbers before attendance logic depends on it.

Requires face_recognition/dlib installed and at least one employee
enrolled via take_photos.py.

Run with:
    python preview_recognition.py

Press Q to quit.
"""

from __future__ import annotations

import sys
import time

import cv2

from services.camera_manager import CameraManager
from services.employee_manager import EmployeeManager
from services.encoding_cache import EncodingCache
from services.face_recognition_engine import FaceRecognitionEngine
from services.recognition_renderer import draw_recognition_overlay
from utils.bootstrap import ensure_directories
from utils.exceptions import CameraError, FaceEncodingError
from utils.logger import get_logger

logger = get_logger(__name__)

WINDOW_NAME = "Recognition Preview - press Q to quit"


def _build_name_lookup(emp_mgr: EmployeeManager) -> dict[str, str]:
    return {emp.employee_id: emp.name for emp in emp_mgr.list_all(active_only=False)}


def main() -> int:
    ensure_directories()

    cache = EncodingCache()
    if cache.total_encodings() == 0:
        print(
            "No enrolled faces found in encodings.pkl. Run take_photos.py "
            "for at least one employee first."
        )
        return 1

    engine = FaceRecognitionEngine(cache=cache)
    emp_mgr = EmployeeManager()
    name_lookup = _build_name_lookup(emp_mgr)

    print(f"Loaded {cache.total_encodings()} encoding(s) across {len(cache.all_employee_ids())} employee(s).")
    print("Starting live preview. Press Q to quit.")

    frame_times: list[float] = []

    try:
        with CameraManager() as cam:
            cv2.namedWindow(WINDOW_NAME)
            while True:
                start = time.perf_counter()

                frame = cam.read_frame()
                try:
                    results = engine.recognize_frame(frame)
                except FaceEncodingError as exc:
                    logger.error("Recognition error on this frame: %s", exc)
                    results = []

                annotated = draw_recognition_overlay(frame, results, name_lookup=name_lookup)

                elapsed = time.perf_counter() - start
                frame_times.append(elapsed)
                if len(frame_times) > 30:
                    frame_times.pop(0)
                avg_ms = (sum(frame_times) / len(frame_times)) * 1000

                cv2.putText(
                    annotated, f"Recognition: {avg_ms:.0f} ms/frame", (20, annotated.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
                )

                cv2.imshow(WINDOW_NAME, annotated)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except CameraError as exc:
        print(f"Camera error: {exc}")
        return 1
    finally:
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    sys.exit(main())
