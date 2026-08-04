"""
services/camera_manager.py
----------------------------
Owns the camera device lifecycle and mirror-flip behavior. As of Phase
13, the actual frame source (webcam vs Raspberry Pi Camera v2) is
delegated to services/camera_source.py's CameraSource abstraction -
CameraManager itself no longer knows or cares which backend is active.

Everything built on top of CameraManager since Phase 4 (take_photos.py,
preview_recognition.py, gui/dashboard.py) keeps working unchanged: this
class's public interface (open/read_frame/release/is_open, context
manager support) is identical to before this refactor.
"""

from __future__ import annotations

from types import TracebackType
from typing import Optional

import numpy as np

import config
from services.camera_source import CameraSource, create_camera_source
from utils.exceptions import CameraError
from utils.logger import get_logger

logger = get_logger(__name__)

try:
    import cv2
except ImportError:  # pragma: no cover - opencv-python is a core requirement
    cv2 = None


class CameraManager:
    """Thin, testable wrapper that owns mirror-flip and delegates actual
    frame capture to a CameraSource backend.

    Usage:
        with CameraManager() as cam:
            frame = cam.read_frame()
    """

    def __init__(
        self,
        source: int = config.CAMERA_SOURCE,
        width: int = config.CAMERA_FRAME_WIDTH,
        height: int = config.CAMERA_FRAME_HEIGHT,
        mirror: bool = config.CAMERA_MIRROR,
        camera_source: Optional[CameraSource] = None,
        force_backend: Optional[str] = None,
    ) -> None:
        """
        camera_source: inject a specific CameraSource instance directly
            (used by tests to exercise PiCameraSource's logic without
            real Pi hardware, and by anyone building alternate backends).
        force_backend: "opencv" or "picamera2" - passed through to
            create_camera_source() when camera_source isn't given
            directly. Leave both None for normal auto-detection.
        """
        self.source = source
        self.width = width
        self.height = height
        self.mirror = mirror
        self._backend: CameraSource = camera_source or create_camera_source(force_backend=force_backend)

        # OpenCVWebcamSource specifically respects a chosen device index;
        # other backends (Pi Camera) don't have a concept of "index".
        if hasattr(self._backend, "source_index"):
            self._backend.source_index = source  # type: ignore[attr-defined]

    def open(self) -> None:
        self._backend.open(self.width, self.height)
        logger.info("Camera opened (backend=%s, %sx%s)", type(self._backend).__name__, self.width, self.height)

    def read_frame(self) -> np.ndarray:
        """Reads a single frame. Raises CameraError on failure rather than
        returning None, so callers never need a None-check - just try/except.
        """
        frame = self._backend.read_frame()
        if self.mirror:
            if cv2 is not None:
                frame = cv2.flip(frame, 1)
            else:  # pragma: no cover - opencv-python is a core requirement
                frame = frame[:, ::-1, :]
        return frame

    def release(self) -> None:
        self._backend.release()
        logger.info("Camera released.")

    def is_open(self) -> bool:
        return self._backend.is_open()

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------
    def __enter__(self) -> "CameraManager":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.release()
