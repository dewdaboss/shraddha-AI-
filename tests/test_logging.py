"""Tests for logging: idempotency, rotating files, and graceful degradation."""

from __future__ import annotations

import logging
from pathlib import Path

from shraddha.logging_setup import LOGGER_NAME, get_logger, setup_logging


def _reset() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    if hasattr(logger, "_shraddha_configured"):
        delattr(logger, "_shraddha_configured")


def test_setup_is_idempotent(app_home: Path) -> None:
    _reset()
    setup_logging(level="INFO", log_file=app_home / "logs" / "a.log", console=False)
    first = len(logging.getLogger(LOGGER_NAME).handlers)
    setup_logging(level="INFO", log_file=app_home / "logs" / "a.log", console=False)
    assert len(logging.getLogger(LOGGER_NAME).handlers) == first
    _reset()


def test_messages_reach_the_file(app_home: Path) -> None:
    _reset()
    log_path = app_home / "logs" / "test.log"
    logger = setup_logging(level="DEBUG", log_file=log_path, console=False)
    logger.info("नमस्ते, श्रद्धा यहाँ है")
    for handler in logger.handlers:
        handler.flush()
    assert "नमस्ते" in log_path.read_text(encoding="utf-8")
    _reset()


def test_level_is_applied(app_home: Path) -> None:
    _reset()
    logger = setup_logging(level="WARNING", log_file=None, console=False)
    assert logger.level == logging.WARNING
    _reset()


def test_unknown_level_falls_back_to_info(app_home: Path) -> None:
    _reset()
    logger = setup_logging(level="LOUD", log_file=None, console=False)
    assert logger.level == logging.INFO
    _reset()


def test_unwritable_log_path_does_not_raise(app_home: Path) -> None:
    _reset()
    blocker = app_home / "blocked"
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("not a directory", encoding="utf-8")
    logger = setup_logging(level="INFO", log_file=blocker / "nested" / "x.log", console=False)
    assert logger is not None, "logging must degrade instead of crashing the app"
    _reset()


def test_child_logger_is_namespaced() -> None:
    assert get_logger("tts").name == "shraddha.tts"
    assert get_logger().name == LOGGER_NAME
