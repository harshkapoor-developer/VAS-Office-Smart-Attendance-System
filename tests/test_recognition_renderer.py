"""
tests/test_recognition_renderer.py
-------------------------------------
Run with:
    python tests/test_recognition_renderer.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import config
from services.recognition_renderer import draw_recognition_overlay, _hex_to_bgr

GREEN_BGR = _hex_to_bgr(config.COLOR_SUCCESS_GREEN)
RED_BGR = _hex_to_bgr(config.COLOR_DANGER_RED)


class TestRecognitionRenderer(unittest.TestCase):
    def _blank_frame(self) -> np.ndarray:
        return np.zeros((200, 200, 3), dtype="uint8")

    def test_hex_to_bgr_conversion(self) -> None:
        # Pure red #FF0000 -> BGR (0, 0, 255)
        self.assertEqual(_hex_to_bgr("#FF0000"), (0, 0, 255))
        # Pure green #00FF00 -> BGR (0, 255, 0)
        self.assertEqual(_hex_to_bgr("#00FF00"), (0, 255, 0))

    def test_does_not_mutate_input_frame(self) -> None:
        frame = self._blank_frame()
        original = frame.copy()
        results = [{"location": (10, 100, 100, 10), "employee_id": "EMP001", "confidence": 92.5}]
        draw_recognition_overlay(frame, results)
        np.testing.assert_array_equal(frame, original)

    def test_known_face_draws_green_box(self) -> None:
        frame = self._blank_frame()
        results = [{"location": (10, 100, 100, 10), "employee_id": "EMP001", "confidence": 92.5}]
        annotated = draw_recognition_overlay(frame, results)
        # The box border should now contain the config palette's green.
        green_pixel_present = np.any(
            np.all(annotated == GREEN_BGR, axis=-1)
        )
        self.assertTrue(green_pixel_present)

    def test_unknown_face_draws_red_box(self) -> None:
        frame = self._blank_frame()
        results = [{"location": (10, 100, 100, 10), "employee_id": None, "confidence": 0.0}]
        annotated = draw_recognition_overlay(frame, results)
        red_pixel_present = np.any(
            np.all(annotated == RED_BGR, axis=-1)
        )
        self.assertTrue(red_pixel_present)

    def test_empty_results_returns_unchanged_frame(self) -> None:
        frame = self._blank_frame()
        annotated = draw_recognition_overlay(frame, [])
        np.testing.assert_array_equal(annotated, frame)

    def test_name_lookup_used_when_provided(self) -> None:
        # We can't easily OCR the rendered text, but we can confirm the
        # function runs without error when a name_lookup dict is passed
        # and that it doesn't crash on a missing id (falls back to raw id).
        frame = self._blank_frame()
        results = [
            {"location": (10, 100, 100, 10), "employee_id": "EMP001", "confidence": 88.0},
            {"location": (110, 190, 190, 110), "employee_id": "EMP_NOT_IN_LOOKUP", "confidence": 60.0},
        ]
        annotated = draw_recognition_overlay(frame, results, name_lookup={"EMP001": "Harsh Kapoor"})
        self.assertEqual(annotated.shape, frame.shape)

    def test_multiple_faces_all_drawn(self) -> None:
        frame = self._blank_frame()
        results = [
            {"location": (10, 90, 90, 10), "employee_id": "EMP001", "confidence": 95.0},
            {"location": (100, 190, 190, 100), "employee_id": None, "confidence": 0.0},
        ]
        annotated = draw_recognition_overlay(frame, results)
        has_green = np.any(np.all(annotated == GREEN_BGR, axis=-1))
        has_red = np.any(np.all(annotated == RED_BGR, axis=-1))
        self.assertTrue(has_green)
        self.assertTrue(has_red)


if __name__ == "__main__":
    unittest.main(verbosity=2)
