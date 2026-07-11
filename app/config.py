"""
ArenaIQ — Application configuration via Pydantic-settings.

Settings are loaded from environment variables (and an optional ``.env``
file) through ``pydantic-settings``. Secrets are **never** hard-coded —
the Gemini API key is read exclusively from the environment and may be
absent, in which case the application falls back to the offline
:class:`~app.services.llm.MockLLM` gracefully.

Environment variables:
    ``GEMINI_API_KEY``: Google Gemini API key (optional). Absence triggers
        the MockLLM fallback so the app runs fully offline.
    ``GEMINI_MODEL``: Model identifier string (default: ``"gemini-1.5-flash"``).
    ``GEMINI_MAX_OUTPUT_TOKENS``: Token cap per Gemini response (default: 256).
    ``RATE_LIMIT_CAPACITY``: Token-bucket size per IP (default: 30).
    ``RATE_LIMIT_REFILL_PER_SEC``: Token refill rate per second (default: 0.5).

Typical usage::

    from app.config import get_settings
    settings = get_settings()          # cached singleton
    if settings.gemini_enabled:
        print(f"Using model: {settings.gemini_model}")
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated application settings loaded from the environment.

    Every field can be overridden by an environment variable of the same
    upper-cased name, e.g. ``GEMINI_API_KEY`` or ``RATE_LIMIT_CAPACITY``.
    A ``.env`` file in the working directory is automatically read if present.

    Attributes:
        app_name: Display name for the application.
        gemini_api_key: Google Gemini API key. If ``None`` or empty, the
            application runs in offline mode with :class:`~app.services.llm.MockLLM`.
        gemini_model: Gemini model identifier used for response generation.
        gemini_max_output_tokens: Maximum number of tokens in a single
            Gemini response. Bounded to ``[16, 2048]``.
        allowed_origins: Explicit CORS origin allow-list for local development.
            Production Vercel origins are handled by ``allow_origin_regex``
            in the middleware configuration.
        rate_limit_capacity: Maximum token-bucket size per client IP.
            Also the starting token count for each new IP. Must be >= 1.
        rate_limit_refill_per_sec: Rate at which tokens are added to each
            IP bucket per second. Zero disables token refilling.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ArenaIQ"

    # --- Gemini (optional; absence triggers the MockLLM fallback) ---
    gemini_api_key: str | None = Field(default=None, description="Google Gemini API key.")
    gemini_model: str = Field(default="gemini-1.5-flash")
    gemini_max_output_tokens: int = Field(default=256, ge=16, le=2048)

    allowed_origins: list[str] = Field(
        default=[
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000",
            "http://localhost:5501",
        ],
        description="Explicit CORS allow-list. Same-origin localhost by default.",
    )

    # --- Rate limiting (token bucket, per client IP) ---
    rate_limit_capacity: int = Field(default=30, ge=1)
    rate_limit_refill_per_sec: float = Field(default=0.5, ge=0.0)

    @property
    def gemini_enabled(self) -> bool:
        """Return ``True`` when a non-empty Gemini API key is configured.

        Used by :func:`~app.services.llm.get_llm_client` to decide whether
        to construct a :class:`~app.services.llm.GeminiClient` or fall back
        to :class:`~app.services.llm.MockLLM`.

        Returns:
            ``True`` if ``gemini_api_key`` is set and non-empty after
            stripping whitespace, ``False`` otherwise.
        """
        return bool(self.gemini_api_key and self.gemini_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` singleton.

    Uses ``lru_cache(maxsize=1)`` to ensure the environment and ``.env``
    file are parsed exactly once per process. The returned instance is
    shared across all callers (FastAPI dependency injection, test fixtures,
    and the module-level ``app = create_app()`` call).

    Returns:
        The singleton :class:`Settings` instance populated from environment
        variables and the ``.env`` file if present.
    """
    return Settings()
