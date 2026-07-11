"""
ArenaIQ — Privacy-preserving structured logging configuration.

Security requirement: secrets and raw PII must *never* reach the log stream.
Application code logs only non-identifying signals: zone IDs, destination
intents, crowd levels, and boolean outcomes. The raw free-text ``question``
and the Gemini API key are explicitly excluded from all log calls.

The module uses a ``_CONFIGURED`` guard to make ``configure_logging``
idempotent — safe to call multiple times (e.g. from tests and from the
application factory) without duplicating handlers or changing the level.

Typical usage::

    from app.logging_conf import get_logger
    logger = get_logger(__name__)
    logger.info("assist location=%s intent=%s", zone_id, intent)
"""

from __future__ import annotations

import logging

_CONFIGURED: bool = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger once, idempotently.

    Sets up a ``basicConfig`` handler that writes timestamped, levelled
    log records to stderr. Subsequent calls are no-ops, so it is safe to
    call from both the application factory and test fixtures.

    Args:
        level: The minimum severity level to emit, expressed as a
            ``logging`` integer constant (e.g. ``logging.DEBUG``,
            ``logging.INFO``). Defaults to ``logging.INFO``.

    Returns:
        None

    Raises:
        TypeError: If ``level`` is not an integer.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, ensuring root logging is configured first.

    Calls ``configure_logging`` (idempotent) before returning the logger,
    guaranteeing that the first log record is never lost due to the root
    handler not yet being attached.

    Args:
        name: The logger namespace, typically ``__name__`` of the calling
            module (e.g. ``"app.services.llm"``).

    Returns:
        A ``logging.Logger`` instance scoped to ``name``.

    Raises:
        TypeError: If ``name`` is not a string.
    """
    configure_logging()
    return logging.getLogger(name)
