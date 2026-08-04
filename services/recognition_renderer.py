"""
services/recognition_renderer.py
-----------------------------------
Draws recognition results (boxes + labels) onto a frame for the live
preview. Deliberately has zero dependency on face_recognition/dlib - it
only consumes the plain dicts that FaceRecognitionEngine.recognize_frame()
produces, so this module is fully unit-testable without dlib installed.
"""

from __future__ import annotations

import cv2
import numpy as np

import config


def draw_recognition_overlay(
    frame: np.ndarray,
    results: list[dict],
    name_lookup: dict[str, str] | None = None,
) -> np.ndarray:
    """Draws a green box + name + confidence for each recognized face,
    and a red box + "Unknown" for each unrecognized one. Returns a new
    annotated frame (does not mutate the input).

    `results` is the list of dicts produced by
    FaceRecognitionEngine.recognize_frame(): each has "location"
    (top, right, bottom, left), "employee_id" (str or None), and
    "confidence" (float 0-100).

    `name_lookup` optionally maps employee_id -> display name; if omitted
    or missing an id, the employee_id itself is shown.
    """
    annotated = frame.copy()
    name_lookup = name_lookup or {}

    green = _hex_to_bgr(config.COLOR_SUCCESS_GREEN)
    red = _hex_to_bgr(config.COLOR_DANGER_RED)

    for result in results:
        top, right, bottom, left = result["location"]
        employee_id = result.get("employee_id")
        confidence = result.get("confidence", 0.0)

        if employee_id is not None:
            color = green
            display_name = name_lookup.get(employee_id, employee_id)
            label = f"{display_name} ({confidence:.1f}%)"
        else:
            color = red
            label = "Unknown"

        cv2.rectangle(annotated, (left, top), (right, bottom), color, 2)

        # Filled label background for readability, drawn just below the box.
        label_height = 28
        cv2.rectangle(
            annotated, (left, bottom), (right, bottom + label_height), color, cv2.FILLED
        )
        cv2.putText(
            annotated, label, (left + 6, bottom + label_height - 8),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA,
        )

    return annotated


def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    """Converts a '#RRGGBB' string (as used throughout config.py's UI
    palette) to an OpenCV-style BGR tuple.
    """
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)
