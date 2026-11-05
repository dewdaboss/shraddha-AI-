"""Logging that can never take the assistant down.

A desktop app that crashes because it cannot write a log file is a broken app. Every
filesystem failure here degrades to console logging instead of raising.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "shraddha"
_DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MARKER = "_shraddha_configured"

# Rotating logs keep disk use bounded — relevant on a low-storage Windows 10 machine.
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    console: bool = True,
) -> logging.Logger:
    """Configure the ``shraddha`` logger and return it.

    Safe to call more than once: handlers are installed only the first time, so a
    re-invocation never duplicates log lines.
    """
    logger = logging.getLogger(LOGGER_NAME)
    log_level = _coerce_level(level)

    if getattr(logger, _MARKER, False):
        logger.setLevel(log_level)
        return logger

    logger.setLevel(log_level)
    logger.propagate = False
    formatter = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DATE_FORMAT)

    if console:
        stream = logging.StreamHandler(stream=sys.stderr)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    if log_file is not None:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
                delay=True,
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:  # read-only profile, locked file, full disk...
            logger.warning("file logging disabled (%s); continuing with console only", exc)

    setattr(logger, _MARKER, True)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger of the application logger."""
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")


def _coerce_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(str(level).upper())
    return resolved if isinstance(resolved, int) else logging.INFO
