"""
ArenaIQ — Standardised JSON logging configuration.

Provides structured JSON logging for all environments, ensuring
consistency between local development output and production log aggregators,
using only the Python standard library.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter using standard library json module."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a JSON string.

        Args:
            record: The log record to format.

        Returns:
            JSON string representation of the log.

        Raises:
            None
        """
        payload = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload)


def _get_handler() -> logging.StreamHandler:  # type: ignore[type-arg]
    """Create and configure the stdout stream handler.

    Args:
        None

    Returns:
        Configured StreamHandler.

    Raises:
        None
    """
    handler: logging.StreamHandler[Any] = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%SZ"))
    return handler


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with JSON formatting.

    Args:
        level: Minimum log level integer (e.g. logging.INFO).

    Returns:
        None

    Raises:
        None

    Example:
        >>> configure_logging(logging.DEBUG)
    """
    root: logging.Logger = logging.getLogger()
    root.setLevel(level)

    for h in list(root.handlers):
        root.removeHandler(h)

    root.addHandler(_get_handler())


def get_logger(name: str) -> logging.Logger:
    """Retrieve a configured child logger instance.

    Args:
        name: The name of the module or component.

    Returns:
        Configured Logger instance.

    Raises:
        None

    Example:
        >>> log = get_logger("app.main")
        >>> log.info("Server started.")
    """
    return logging.getLogger(name)
