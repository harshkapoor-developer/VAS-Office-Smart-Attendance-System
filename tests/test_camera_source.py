"""
tests/test_camera_source.py
-------------------------------
Tests the CameraSource abstraction and backend selection logic using
mocked cv2.VideoCapture / a fake picamera2 module - same honest pattern
as test_face_recognition_engine.py's fake face_recognition module (see
tests/README.md's "what's genuinely tested vs mocked" section).

This proves the OPEN/READ/RELEASE/ERROR-HANDLING LOGIC is correct for
both backends. It does NOT prove real camera hardware works - that
still needs a physical webcam (OpenCVWebcamSource) or physical Pi
Camera v2 + picamera2 installed (PiCameraSource) to verify for real.

Run with:
    python tests/test_camera_source.py
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import config
from utils.exceptions import CameraError


class TestOpenCVWebcamSource(unittest.TestCase):
    def setUp(self) -> None:
        from services.camera_source import OpenCVWebcamSource
        self.OpenCVWebcamSource = OpenCVWebcamSource

    def test_open_success(self) -> None:
        fake_cap = MagicMock()
        fake_cap.isOpened.return_value = True
        with patch("services.camera_source.cv2.VideoCapture", return_value=fake_cap):
            source = self.OpenCVWebcamSource(source_index=0)
            source.open(640, 480)
        self.assertTrue(source.is_open())
        fake_cap.set.assert_any_call(3, 640)  # cv2.CAP_PROP_FRAME_WIDTH == 3 in real cv2, but
        # we don't assert the exact constant value here - just that set() was called twice.
        self.assertEqual(fake_cap.set.call_count, 2)

    def test_open_failure_raises_camera_error(self) -> None:
        fake_cap = MagicMock()
        fake_cap.isOpened.return_value = False
        with patch("services.camera_source.cv2.VideoCapture", return_value=fake_cap):
            source = self.OpenCVWebcamSource(source_index=5)
            with self.assertRaises(CameraError):
                source.open(640, 480)

    def test_open_is_idempotent(self) -> None:
        fake_cap = MagicMock()
        fake_cap.isOpened.return_value = True
        with patch("services.camera_source.cv2.VideoCapture", return_value=fake_cap) as mock_ctor:
            source = self.OpenCVWebcamSource(source_index=0)
            source.open(640, 480)
            source.open(640, 480)  # second call should be a no-op
        mock_ctor.assert_called_once()

    def test_read_frame_success(self) -> None:
        fake_frame = np.zeros((480, 640, 3), dtype="uint8")
        fake_cap = MagicMock()
        fake_cap.isOpened.return_value = True
        fake_cap.read.return_value = (True, fake_frame)
        with patch("services.camera_source.cv2.VideoCapture", return_value=fake_cap):
            source = self.OpenCVWebcamSource()
            source.open(640, 480)
            frame = source.read_frame()
        np.testing.assert_array_equal(frame, fake_frame)

    def test_read_frame_before_open_raises(self) -> None:
        source = self.OpenCVWebcamSource()
        with self.assertRaises(CameraError):
            source.read_frame()

    def test_read_frame_device_disconnected_raises(self) -> None:
        fake_cap = MagicMock()
        fake_cap.isOpened.return_value = True
        fake_cap.read.return_value = (False, None)  # simulates a disconnected device
        with patch("services.camera_source.cv2.VideoCapture", return_value=fake_cap):
            source = self.OpenCVWebcamSource()
            source.open(640, 480)
            with self.assertRaises(CameraError):
                source.read_frame()

    def test_release_resets_state(self) -> None:
        fake_cap = MagicMock()
        fake_cap.isOpened.return_value = True
        with patch("services.camera_source.cv2.VideoCapture", return_value=fake_cap):
            source = self.OpenCVWebcamSource()
            source.open(640, 480)
            source.release()
        fake_cap.release.assert_called_once()
        self.assertFalse(source.is_open())

    def test_is_open_false_before_open(self) -> None:
        source = self.OpenCVWebcamSource()
        self.assertFalse(source.is_open())


def _install_fake_picamera2() -> types.ModuleType:
    """Injects a fake picamera2 module into sys.modules so PiCameraSource
    can be imported and exercised without real Pi hardware/libcamera.
    """
    fake_module = types.ModuleType("picamera2")

    class FakePicamera2:
        instances: list["FakePicamera2"] = []

        def __init__(self, fail_on_start: bool = False):
            self.started = False
            self.closed = False
            self.fail_on_start = fail_on_start
            self.next_frame = np.zeros((480, 640, 3), dtype="uint8")
            FakePicamera2.instances.append(self)

        def create_video_configuration(self, main=None):
            return {"main": main}

        def configure(self, cfg):
            self.config = cfg

        def start(self):
            if self.fail_on_start:
                raise RuntimeError("Simulated camera init failure")
            self.started = True

        def capture_array(self):
            if not self.started:
                raise RuntimeError("capture_array called before start()")
            return self.next_frame

        def stop(self):
            self.started = False

        def close(self):
            self.closed = True

    fake_module.Picamera2 = FakePicamera2  # type: ignore[attr-defined]
    sys.modules["picamera2"] = fake_module
    return fake_module


class TestPiCameraSource(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_module = _install_fake_picamera2()
        # Force a fresh import of camera_source so its module-level
        # `from picamera2 import Picamera2` picks up our fake module.
        sys.modules.pop("services.camera_source", None)
        from services.camera_source import PiCameraSource
        self.PiCameraSource = PiCameraSource
        self.fake_module.Picamera2.instances.clear()

    def tearDown(self) -> None:
        sys.modules.pop("picamera2", None)
        sys.modules.pop("services.camera_source", None)

    def test_open_starts_camera(self) -> None:
        source = self.PiCameraSource()
        source.open(1280, 720)
        self.assertTrue(source.is_open())
        self.assertTrue(self.fake_module.Picamera2.instances[0].started)

    def test_open_failure_raises_camera_error(self) -> None:
        # Patch the fake class to fail on start for this one test.
        original_init = self.fake_module.Picamera2.__init__

        def failing_init(self_inner):
            original_init(self_inner, fail_on_start=True)

        self.fake_module.Picamera2.__init__ = failing_init
        try:
            source = self.PiCameraSource()
            with self.assertRaises(CameraError):
                source.open(1280, 720)
        finally:
            self.fake_module.Picamera2.__init__ = original_init

    def test_read_frame_returns_bgr_converted_from_rgb(self) -> None:
        source = self.PiCameraSource()
        source.open(1280, 720)

        # Set a distinguishable RGB frame: red-heavy in channel 0.
        instance = self.fake_module.Picamera2.instances[0]
        rgb_frame = np.zeros((10, 10, 3), dtype="uint8")
        rgb_frame[:, :, 0] = 200  # R channel high
        instance.next_frame = rgb_frame

        bgr_frame = source.read_frame()
        # After RGB->BGR conversion, the "high" value should have moved
        # from channel 0 (R) to channel 2 (B).
        self.assertEqual(bgr_frame[0, 0, 2], 200)
        self.assertEqual(bgr_frame[0, 0, 0], 0)

    def test_read_frame_before_open_raises(self) -> None:
        source = self.PiCameraSource()
        with self.assertRaises(CameraError):
            source.read_frame()

    def test_release_stops_and_closes(self) -> None:
        source = self.PiCameraSource()
        source.open(1280, 720)
        instance = self.fake_module.Picamera2.instances[0]
        source.release()
        self.assertTrue(instance.closed)
        self.assertFalse(source.is_open())


class TestBackendSelection(unittest.TestCase):
    def test_force_opencv_backend(self) -> None:
        from services.camera_source import create_camera_source, OpenCVWebcamSource
        source = create_camera_source(force_backend="opencv")
        self.assertIsInstance(source, OpenCVWebcamSource)

    def test_force_picamera2_backend_without_hardware_raises_clear_error(self) -> None:
        # Ensure the REAL (unmocked) module state is in effect - picamera2
        # genuinely isn't installed in this environment, which is exactly
        # what we want to verify degrades gracefully.
        sys.modules.pop("picamera2", None)
        sys.modules.pop("services.camera_source", None)
        from services.camera_source import create_camera_source
        with self.assertRaises(CameraError) as ctx:
            create_camera_source(force_backend="picamera2")
        self.assertIn("picamera2 is not installed", str(ctx.exception))

    def test_defaults_to_opencv_when_not_on_raspberry_pi(self) -> None:
        sys.modules.pop("services.camera_source", None)
        from services.camera_source import create_camera_source, OpenCVWebcamSource
        with patch("config.is_raspberry_pi", return_value=False):
            source = create_camera_source()
        self.assertIsInstance(source, OpenCVWebcamSource)

    def test_uses_picamera_when_on_pi_and_available(self) -> None:
        fake_module = _install_fake_picamera2()
        sys.modules.pop("services.camera_source", None)
        try:
            from services.camera_source import create_camera_source, PiCameraSource
            with patch("config.is_raspberry_pi", return_value=True):
                source = create_camera_source()
            self.assertIsInstance(source, PiCameraSource)
        finally:
            sys.modules.pop("picamera2", None)
            sys.modules.pop("services.camera_source", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
