"""
main.py
---------
The single entrypoint for the Smart Attendance System desktop app.

Run with:
    python main.py

Startup sequence:
    1. Bootstrap required directories (utils.bootstrap.ensure_directories)
    2. Show the login window (creates the admin account on first run)
    3. On successful login, hand off to the main dashboard

Any failure during step 1 (e.g. permission denied creating a folder) is
shown in a plain Tk messagebox and logged, since the full GUI theme
isn't guaranteed to be usable yet at that point - startup errors need
to be visible even in a degraded state.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

from services.auth_manager import AuthManager
from utils.bootstrap import ensure_directories
from utils.exceptions import SmartAttendanceError
from utils.logger import get_logger

logger = get_logger(__name__)


def main() -> int:
    logger.info("Smart Attendance System starting up.")

    try:
        ensure_directories()
    except SmartAttendanceError as exc:
        logger.critical("Startup failed during directory bootstrap: %s", exc)
        _show_fatal_startup_error(str(exc))
        return 1

    from gui.dashboard import DashboardApp
    from gui.login_window import LoginWindow

    auth = AuthManager()

    def on_login_success() -> None:
        try:
            app = DashboardApp(auth=auth)
            app.mainloop()
        except Exception:  # noqa: BLE001 - last-resort net so a crash is logged, not silent
            logger.exception("Unhandled exception in DashboardApp - application exiting.")
            raise

    login_window = LoginWindow(auth=auth, on_success=on_login_success)
    login_window.mainloop()

    logger.info("Smart Attendance System shut down normally.")
    return 0


def _show_fatal_startup_error(message: str) -> None:
    """Shows a startup error using a bare Tk messagebox - deliberately
    not using customtkinter here, since the failure that got us here
    (can't create required folders) might mean the app isn't in a
    reliable enough state to trust its own themed widgets yet.
    """
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Smart Attendance System - Startup Error", message)
        root.destroy()
    except Exception:  # noqa: BLE001 - if even this fails, fall back to stderr
        print(f"FATAL STARTUP ERROR: {message}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
