"""
services/camera_source.py
-----------------------------
Abstracts WHERE frames come from, so CameraManager's public interface
(open/read_frame/release) never has to change when moving from a
Windows/Linux webcam to a Raspberry Pi Camera v2. This is the Phase 13
migration seam mentioned since Phase 4/5 - CameraManager already only
ever called through this abstraction's shape, so this phase formalizes
it into its own module instead of CameraManager hardcoding cv2 directly.

Backend selection (see `create_camera_source()`):
    - Raspberry Pi detected (config.is_raspberry_pi()) AND picamera2
      is installed -> PiCameraSource
    - Otherwise -> OpenCVWebcamSource (works on Windows, regular Linux,
      and even on a Pi with a USB webcam instead of the ribbon-cable
      camera module)

This selection can also be forced explicitly via the `backend` param,
which is what the test suite uses to exercise PiCameraSource's logic
without actual Pi hardware.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

import config
from utils.exceptions import CameraError
from utils.logger import get_logger

logger = get_logger(__name__)

try:
    import cv2
except ImportError:  # pragma: no cover - opencv-python is a core requirement; this only
    cv2 = None          # guards against partial/broken installs during early setup.

try:
    from picamera2 import Picamera2
    _PICAMERA2_AVAILABLE = True
except ImportError:
    Picamera2 = None  # type: ignore[assignment]
    _PICAMERA2_AVAILABLE = False


class CameraSource(ABC):
    """Every backend implements these three methods identically, so
    CameraManager (and everything built on top of it - take_photos.py,
    preview_recognition.py, gui/dashboard.py) never needs to know which
    backend is active.
    """

    @abstractmethod
    def open(self, width: int, height: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def read_frame(self) -> np.ndarray:
        """Returns a BGR numpy array (matching OpenCV's convention,
        since that's what face_recognition_engine.py and
        recognition_renderer.py already expect throughout the project).
        """
        raise NotImplementedError

    @abstractmethod
    def release(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_open(self) -> bool:
        raise NotImplementedError


class OpenCVWebcamSource(CameraSource):
    """The original Windows/Linux webcam backend (unchanged behavior
    from Phases 4-11) - just moved into this abstraction.
    """

    def __init__(self, source_index: int = config.CAMERA_SOURCE) -> None:
        if cv2 is None:
            raise CameraError("opencv-python is not installed.")
        self.source_index = source_index
        self._cap: Optional["cv2.VideoCapture"] = None

    def open(self, width: int, height: int) -> None:
        if self._cap is not None and self._cap.isOpened():
            return
        cap = cv2.VideoCapture(self.source_index)
        if not cap.isOpened():
            raise CameraError(
                f"Could not open camera at source index {self.source_index}. "
                "Check that it's not in use by another application and that "
                "camera permissions are granted."
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap = cap

    def read_frame(self) -> np.ndarray:
        if self._cap is None or not self._cap.isOpened():
            raise CameraError("Camera is not open. Call open() first.")
        ret, frame = self._cap.read()
        if not ret or frame is None:
            raise CameraError("Failed to read frame from camera (device disconnected?).")
        return frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()


class PiCameraSource(CameraSource):
    """Raspberry Pi Camera v2 backend via picamera2 (the modern,
    libcamera-based successor to the old `picamera` package - required
    on Raspberry Pi OS Bullseye and later, which is what Pi 5 ships).

    picamera2 natively returns RGB frames; this backend converts to BGR
    before returning, so downstream code (face_recognition_engine,
    recognition_renderer) never needs an is-this-Pi branch - the BGR
    contract from CameraSource.read_frame() holds for every backend.
    """

    def __init__(self) -> None:
        if not _PICAMERA2_AVAILABLE:
            raise CameraError(
                "picamera2 is not installed. This is expected on Windows/regular "
                "Linux - PiCameraSource is only usable on a Raspberry Pi with "
                "picamera2 installed (`sudo apt install python3-picamera2`)."
            )
        self._picam: Optional["Picamera2"] = None

    def open(self, width: int, height: int) -> None:
        if self._picam is not None:
            return
        try:
            picam = Picamera2()
            camera_config = picam.create_video_configuration(
                main={"size": (width, height), "format": "RGB888"}
            )
            picam.configure(camera_config)
            picam.start()
            self._picam = picam
        except Exception as exc:  # noqa: BLE001 - picamera2 raises its own exception types
            raise CameraError(f"Could not open Raspberry Pi Camera: {exc}") from exc

    def read_frame(self) -> np.ndarray:
        if self._picam is None:
            raise CameraError("Pi Camera is not open. Call open() first.")
        try:
            rgb_frame = self._picam.capture_array()
        except Exception as exc:  # noqa: BLE001
            raise CameraError(f"Failed to capture frame from Pi Camera: {exc}") from exc
        # Convert RGB (picamera2's native format) to BGR (this project's
        # convention, matching OpenCV) so callers never branch on backend.
        return rgb_frame[:, :, ::-1]

    def release(self) -> None:
        if self._picam is not None:
            try:
                self._picam.stop()
                self._picam.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup, never raise on shutdown
                logger.exception("Error while releasing Pi Camera - continuing shutdown anyway.")
            self._picam = None

    def is_open(self) -> bool:
        return self._picam is not None


def create_camera_source(force_backend: Optional[str] = None) -> CameraSource:
    """Selects the appropriate CameraSource for the current platform.

    force_backend: "opencv" or "picamera2" to bypass auto-detection
    (used by tests, and by anyone who wants a USB webcam on a Pi instead
    of the ribbon-cable camera module).
    """
    if force_backend == "opencv":
        return OpenCVWebcamSource()
    if force_backend == "picamera2":
        return PiCameraSource()

    if config.is_raspberry_pi() and _PICAMERA2_AVAILABLE:
        logger.info("Raspberry Pi detected with picamera2 available - using PiCameraSource.")
        return PiCameraSource()

    return OpenCVWebcamSource()
