"""
tests/conftest.py
---------------------
Shared pytest configuration:

1. Ensures the project root is on sys.path even under pytest's own
   import mechanism (each test file also does this itself via
   sys.path.insert, which is what lets `python tests/test_x.py` work
   standalone - this is just the pytest-idiomatic equivalent).

2. Auto-skips gui tests (tests/test_gui_dashboard.py) when no display
   is available, so `pytest` runs clean in a plain CI container without
   Xvfb, rather than failing with a wall of "couldn't connect to
   display" errors that look like real bugs. Set up a virtual display
   (Xvfb on Linux) and these tests run for real, as they did throughout
   Phase 8-11 development.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _display_available() -> bool:
    """Tries to actually open a Tk root window - the only reliable way
    to know a display will work, since DISPLAY can be set but stale/dead.
    """
    try:
        import tkinter as tk
        root = tk.Tk()
        root.destroy()
        return True
    except Exception:
        return False


_GUI_TEST_FILENAME = "test_gui_dashboard.py"


def pytest_collection_modifyitems(config, items) -> None:
    if _display_available():
        return  # real or virtual display works - run GUI tests normally

    skip_marker = pytest.mark.skip(
        reason="No display available (tkinter couldn't open a window). "
        "Start Xvfb (Linux) or run on a machine with a real display to "
        "execute GUI tests."
    )
    for item in items:
        if _GUI_TEST_FILENAME in str(item.fspath):
            item.add_marker(skip_marker)
