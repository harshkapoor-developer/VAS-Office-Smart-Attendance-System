"""
utils/logger.py
----------------
Centralized logging setup. Every module in the project should obtain its
logger via `get_logger(__name__)` rather than configuring logging itself,
so log output is consistent and all handlers are attached exactly once.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import config

_CONFIGURED: bool = False


def _configure_root_logger() -> None:
    """Attaches a rotating file handler and a console handler to the root
    logger. Safe to call multiple times - only configures once per process.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(config.LOG_LEVEL)

    formatter = logging.Formatter(config.LOG_FORMAT)

    file_handler = RotatingFileHandler(
        filename=str(config.LOG_FILE),
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Returns a module-scoped logger, configuring the root logger's
    handlers on first use.

    Usage:
        from utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Employee registered: %s", employee_id)
    """
    _configure_root_logger()
    return logging.getLogger(name)
