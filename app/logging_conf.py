"""Privacy-preserving logging setup.

Security requirement: never log secrets or raw PII. Application code logs only
non-identifying signals such as zone ids, destination intents and outcomes — it
must never pass the API key or the raw free-text ``question`` to the logger.
"""

from __future__ import annotations

import logging

_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging once, idempotently."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, ensuring logging is configured first."""
    configure_logging()
    return logging.getLogger(name)
