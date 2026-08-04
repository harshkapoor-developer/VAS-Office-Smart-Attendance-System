"""
config.py
---------
Single source of truth for every path, constant, and tunable setting in the
Smart Attendance System. Nothing outside this file should hard-code a path,
a color, a threshold, or a filename pattern - import from here instead.

Swapping platforms (Windows dev -> Raspberry Pi 5) should only ever require
changing values in this file (CAMERA_SOURCE, DISPLAY_SIZE, SMS_BACKEND),
never touching business logic elsewhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

# --------------------------------------------------------------------------
# BASE PATHS
# --------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent

DATABASE_DIR: Path = BASE_DIR / "database"
EMPLOYEE_IMAGES_DIR: Path = BASE_DIR / "employee_images"
ATTENDANCE_RECORDS_DIR: Path = BASE_DIR / "attendance"  # year/month/day-file archive
LOGS_DIR: Path = BASE_DIR / "logs"
EXPORTS_DIR: Path = BASE_DIR / "exports"
ASSETS_DIR: Path = BASE_DIR / "assets"

# Every directory the application depends on. utils/bootstrap.py iterates
# this list on every startup and creates anything missing - the app must
# never crash because a folder was deleted or this is a fresh checkout.
REQUIRED_DIRECTORIES: list[Path] = [
    DATABASE_DIR,
    EMPLOYEE_IMAGES_DIR,
    ATTENDANCE_RECORDS_DIR,
    LOGS_DIR,
    EXPORTS_DIR,
    ASSETS_DIR,
]

# --------------------------------------------------------------------------
# DATABASE FILES
# --------------------------------------------------------------------------
DATABASE_FILE: Path = DATABASE_DIR / "employee_data.db"
ENCODINGS_FILE: Path = DATABASE_DIR / "encodings.pkl"

# --------------------------------------------------------------------------
# ATTENDANCE / CSV
# --------------------------------------------------------------------------
# One file per calendar day, archived under attendance/{year}/{MonthName}/.
# SD-card safe: plain files, no DB server, works unchanged in hardware mode.
ATTENDANCE_FILENAME_PATTERN: str = "{date}_attendance.csv"  # date = YYYY-MM-DD
ATTENDANCE_CSV_COLUMNS: list[str] = [
    "Date", "Employee Name", "Employee ID", "In-Time", "Out-Time", "Status",
]
ATTENDANCE_STATUS_PRESENT: str = "Present"
ATTENDANCE_STATUS_ABSENT: str = "Absent"
ATTENDANCE_DATE_DISPLAY_FORMAT: str = "%d-%m-%Y"   # e.g. 03-08-2026
ATTENDANCE_TIME_DISPLAY_FORMAT: str = "%I:%M:%S %p"  # e.g. 09:12:35 AM

# --------------------------------------------------------------------------
# FACE RECOGNITION
# --------------------------------------------------------------------------
FACE_RECOGNITION_TOLERANCE: float = 0.5  # lower = stricter match
FACE_DETECTION_MODEL: str = "hog"  # "hog" (CPU, fast) or "cnn" (GPU, slower on Pi)
FACE_ENCODING_JITTERS: int = 1  # re-samples per encoding; raise for accuracy, costs speed
MIN_CONFIDENCE_PERCENT: float = 55.0  # below this, treat as Unknown even if matched
CAPTURE_ANGLES_PER_EMPLOYEE: int = 5  # photos taken during registration
RECOGNITION_FRAME_RESIZE_SCALE: float = 0.25  # downscale factor for speed

# --------------------------------------------------------------------------
# CAMERA
# --------------------------------------------------------------------------
# On Windows this is an integer device index. On Raspberry Pi with the
# Pi Camera v2, Phase 13 swaps this for a Picamera2-based source behind
# the same CameraManager interface - nothing above that layer changes.
CAMERA_SOURCE: int = 0
CAMERA_MIRROR: bool = True
CAMERA_FRAME_WIDTH: int = 1280
CAMERA_FRAME_HEIGHT: int = 720
CAMERA_TARGET_FPS: int = 30

# --------------------------------------------------------------------------
# UI / THEME
# --------------------------------------------------------------------------
APP_NAME: str = "Smart Attendance System"
APP_VERSION: str = "1.0.0"

# CustomTkinter appearance
UI_APPEARANCE_MODE: str = "dark"
UI_COLOR_THEME: str = "blue"

COLOR_PRIMARY_BLUE: str = "#2563EB"
COLOR_WHITE: str = "#F5F7FA"
COLOR_DARK_GRAY: str = "#1E1E24"
COLOR_PANEL_GRAY: str = "#2A2A33"
COLOR_SUCCESS_GREEN: str = "#22C55E"
COLOR_DANGER_RED: str = "#EF4444"
COLOR_WARNING_AMBER: str = "#F59E0B"

# Display target: 10.5" HDMI touchscreen is 1920x1280; dev window defaults
# smaller for a laptop screen. Phase 13 can override this for the Pi build.
DISPLAY_SIZE_DEV: tuple[int, int] = (1400, 860)
DISPLAY_SIZE_PI: tuple[int, int] = (1920, 1280)

# --------------------------------------------------------------------------
# KEYBOARD SHORTCUTS
# --------------------------------------------------------------------------
SHORTCUT_QUIT: str = "q"
SHORTCUT_REGISTER: str = "r"
SHORTCUT_TODAY_ATTENDANCE: str = "a"
SHORTCUT_NOTIFICATIONS: str = "s"
SHORTCUT_EMPLOYEE_LIST: str = "l"

# --------------------------------------------------------------------------
# ADMIN / SECURITY
# --------------------------------------------------------------------------
PBKDF2_ITERATIONS: int = 260_000
MIN_PASSWORD_LENGTH: int = 8

# --------------------------------------------------------------------------
# SMS MODULE
# --------------------------------------------------------------------------
# "simulator" now; Phase 13 introduces "sim800l" as a real backend behind
# the same interface (see services/sms_simulator.py).
SMS_BACKEND: str = "simulator"

# --------------------------------------------------------------------------
# LOGGING
# --------------------------------------------------------------------------
LOG_FILE: Path = LOGS_DIR / "system.log"
LOG_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB per file
LOG_BACKUP_COUNT: int = 5
LOG_LEVEL: str = "INFO"
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# --------------------------------------------------------------------------
# PLATFORM DETECTION
# --------------------------------------------------------------------------
IS_WINDOWS: bool = sys.platform == "win32"
IS_LINUX: bool = sys.platform.startswith("linux")


def is_raspberry_pi() -> bool:
    """
    Detects whether the app is currently running on a Raspberry Pi, by
    checking the device tree model string. Returns False on Windows/other
    Linux without raising - this is a runtime check, never an assumption.
    """
    model_path = Path("/proc/device-tree/model")
    if not model_path.exists():
        return False
    try:
        return "raspberry pi" in model_path.read_text(errors="ignore").lower()
    except OSError:
        return False


# --------------------------------------------------------------------------
# TOUCHSCREEN-AWARE UI SCALING (Raspberry Pi 10.5" display)
# --------------------------------------------------------------------------
# A 10.5" touchscreen at 1920x1280 has a much higher pixel density than a
# laptop's 14" 1400x860 dev window - UI elements sized for mouse+laptop
# precision render too small to reliably tap with a finger at that DPI.
# get_ui_scale() is applied via customtkinter's set_widget_scaling() /
# set_window_scaling() at DashboardApp startup (gui/dashboard.py) to
# enlarge buttons, fonts, and touch targets uniformly, rather than
# hand-tuning every widget's explicit pixel size for two form factors.
UI_SCALE_DEV: float = 1.0
UI_SCALE_PI_TOUCHSCREEN: float = 1.35


def get_ui_scale() -> float:
    return UI_SCALE_PI_TOUCHSCREEN if is_raspberry_pi() else UI_SCALE_DEV


def get_display_size() -> tuple[int, int]:
    return DISPLAY_SIZE_PI if is_raspberry_pi() else DISPLAY_SIZE_DEV
