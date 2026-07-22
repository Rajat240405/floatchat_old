"""Structured logging configuration for FloatChat."""

import logging
import sys

from floatchat.config import settings


def configure_logging() -> None:
    """Configure root logger with a consistent format.

    Modules should obtain their own logger via ``logging.getLogger(__name__)``.
    """
    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(log_format))

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level.upper())
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
