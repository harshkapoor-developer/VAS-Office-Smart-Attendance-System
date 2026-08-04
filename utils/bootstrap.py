"""
utils/bootstrap.py
-------------------
Ensures every directory the application depends on exists before any
service tries to read or write into it. This must be the first thing
that runs on application startup (see main.py in a later phase).

Deliberately has zero dependencies on other project modules besides
config + logger, so it can never fail due to an import cycle.
"""

from __future__ import annotations

import config
from utils.exceptions import SmartAttendanceError
from utils.logger import get_logger

logger = get_logger(__name__)


def ensure_directories() -> None:
    """Creates every directory in config.REQUIRED_DIRECTORIES if missing.

    Idempotent - safe to call on every startup. Each creation is logged
    so a fresh checkout's first run is fully traceable in system.log.

    Raises SmartAttendanceError with a clear, actionable message if a
    directory can't be created due to a permissions problem - this is
    the very first thing that runs on startup, so a raw PermissionError
    traceback here would be the worst possible first impression.
    """
    failures: list[str] = []
    for directory in config.REQUIRED_DIRECTORIES:
        if directory.exists():
            continue
        try:
            directory.mkdir(parents=True, exist_ok=True)
            logger.info("Created missing directory: %s", directory)
        except PermissionError as exc:
            logger.error("Permission denied creating directory %s: %s", directory, exc)
            failures.append(str(directory))
        except OSError as exc:
            logger.error("Could not create directory %s: %s", directory, exc)
            failures.append(str(directory))

    if failures:
        raise SmartAttendanceError(
            "Could not create required folder(s):\n"
            + "\n".join(f"  - {f}" for f in failures)
            + "\n\nCheck that the application has write permission to this "
            "project's parent folder, then restart."
        )

    logger.info("Directory bootstrap complete. %d directories verified.", len(config.REQUIRED_DIRECTORIES))


if __name__ == "__main__":
    # Allows running `python -m utils.bootstrap` standalone to pre-create
    # folders without starting the full application.
    ensure_directories()
    print("All required directories are present.")
