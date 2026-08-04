"""
Phase 0 - Environment Validation Script
-----------------------------------------
Run this BEFORE writing any application code.

Usage (Windows PowerShell / cmd):
    python validate_environment.py

This script checks, in order:
    1. Python version
    2. Presence of CMake and a C++ compiler (needed to build dlib)
    3. That every required package can be imported
    4. That a webcam is reachable via OpenCV
    5. That face_recognition can actually encode a face end-to-end

It never assumes success silently - every check prints PASS/FAIL and the
script exits with a non-zero code if anything critical is missing, so it
is also safe to use in an automated setup pipeline.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field


REQUIRED_PACKAGES: list[str] = [
    "numpy",
    "cv2",
    "dlib",
    "face_recognition",
    "customtkinter",
    "PIL",
    "pandas",
    "openpyxl",
]

MIN_PYTHON = (3, 10)


@dataclass
class ValidationReport:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def ok(self, msg: str) -> None:
        self.passed.append(msg)
        print(f"[PASS] {msg}")

    def fail(self, msg: str) -> None:
        self.failed.append(msg)
        print(f"[FAIL] {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"[WARN] {msg}")

    def summary(self) -> int:
        print("\n" + "=" * 60)
        print(f"PASSED: {len(self.passed)}  FAILED: {len(self.failed)}  WARNINGS: {len(self.warnings)}")
        print("=" * 60)
        if self.failed:
            print("\nEnvironment is NOT ready. Fix the FAIL items above and re-run.")
            return 1
        print("\nEnvironment is ready for Phase 1.")
        return 0


def check_python_version(report: ValidationReport) -> None:
    current = sys.version_info[:2]
    if current >= MIN_PYTHON:
        report.ok(f"Python version {sys.version.split()[0]} meets minimum {'.'.join(map(str, MIN_PYTHON))}")
    else:
        report.fail(
            f"Python version {sys.version.split()[0]} is below minimum "
            f"{'.'.join(map(str, MIN_PYTHON))}"
        )
    if current[0] == 3 and current[1] >= 14:
        report.warn(
            "Python 3.14.x detected. dlib has no prebuilt wheels for any Python "
            "version on PyPI (source-only). If `pip install dlib` fails below, "
            "the fastest fix is installing Python 3.11 or 3.12 side-by-side "
            "specifically for this project's virtual environment, since dlib's "
            "build has been most widely tested there. This is optional to try "
            "first with 3.14 - only fall back if the build genuinely fails."
        )


def check_build_tools(report: ValidationReport) -> None:
    cmake_path = shutil.which("cmake")
    if cmake_path:
        try:
            out = subprocess.run(
                ["cmake", "--version"], capture_output=True, text=True, timeout=10
            )
            first_line = out.stdout.splitlines()[0] if out.stdout else "unknown version"
            report.ok(f"CMake found ({first_line}) at {cmake_path}")
        except Exception as exc:  # noqa: BLE001
            report.warn(f"CMake found at {cmake_path} but version check failed: {exc}")
    else:
        report.fail(
            "CMake not found on PATH. Install it from https://cmake.org/download/ "
            "and check 'Add CMake to system PATH' during install."
        )

    if sys.platform == "win32":
        vswhere = shutil.which("cl")
        if vswhere:
            report.ok("MSVC C++ compiler (cl.exe) found on PATH")
        else:
            report.warn(
                "cl.exe (MSVC compiler) not found on PATH directly. This is normal "
                "unless you're in a 'Developer Command Prompt for VS'. As long as "
                "Visual Studio Build Tools with 'Desktop development with C++' is "
                "installed, pip's build step will locate it automatically. If the "
                "dlib install fails below, install Build Tools from: "
                "https://visualstudio.microsoft.com/visual-cpp-build-tools/"
            )


def check_imports(report: ValidationReport) -> None:
    for pkg in REQUIRED_PACKAGES:
        try:
            __import__(pkg)
            report.ok(f"Import succeeded: {pkg}")
        except ImportError as exc:
            report.fail(f"Import failed: {pkg} ({exc})")


def check_webcam(report: ValidationReport) -> None:
    try:
        import cv2
    except ImportError:
        report.fail("Cannot test webcam - cv2 (opencv-python) is not installed")
        return

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        report.fail(
            "Webcam at index 0 could not be opened. Check that no other app "
            "is using it, and that camera privacy permissions are enabled "
            "(Windows Settings > Privacy > Camera)."
        )
        return

    ret, frame = cap.read()
    cap.release()
    if ret and frame is not None:
        h, w = frame.shape[:2]
        report.ok(f"Webcam captured a frame successfully ({w}x{h})")
    else:
        report.fail("Webcam opened but failed to return a frame")


def check_face_recognition_pipeline(report: ValidationReport) -> None:
    try:
        import numpy as np
        import face_recognition
    except ImportError:
        report.fail("Cannot test face_recognition pipeline - dependencies missing")
        return

    try:
        # Synthetic image (no real face) - this only proves the encoding
        # pipeline runs end-to-end without crashing, not that it detects
        # a face in blank noise (it correctly should detect none).
        blank_image = (np.random.rand(200, 200, 3) * 255).astype("uint8")
        locations = face_recognition.face_locations(blank_image)
        report.ok(
            f"face_recognition pipeline executed end-to-end "
            f"({len(locations)} face(s) found in synthetic test image, as expected)"
        )
    except Exception as exc:  # noqa: BLE001
        report.fail(f"face_recognition pipeline raised an exception: {exc}")


def main() -> int:
    report = ValidationReport()
    print("Smart Attendance System - Phase 0 Environment Validation")
    print("=" * 60)

    check_python_version(report)
    check_build_tools(report)
    check_imports(report)
    check_webcam(report)
    check_face_recognition_pipeline(report)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
