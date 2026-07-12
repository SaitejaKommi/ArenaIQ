"""
ArenaIQ — Application configuration via Pydantic-settings.

Settings are loaded from environment variables (and an optional ``.env``
file) through ``pydantic-settings``. Secrets are **never** hard-coded —
the Gemini API key is read exclusively from the environment and may be
absent, in which case the application falls back to the offline
:class:`~app.services.llm.MockLLM` gracefully.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated application settings loaded from the environment.

    Attributes:
        app_name: Display name for the application.
        gemini_api_key: Google Gemini API key. If ``None`` or empty, the
            application runs in offline mode with MockLLM.
        gemini_model: Gemini model identifier used for response generation.
        gemini_max_output_tokens: Maximum number of tokens in a single
            Gemini response. Bounded to ``[16, 2048]``.
        allowed_origins: Explicit CORS origin allow-list for local dev.
        rate_limit_capacity: Maximum token-bucket size per client IP.
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
        description="Explicit CORS allow-list.",
    )

    rate_limit_capacity: int = Field(default=30, ge=1)
    rate_limit_refill_per_sec: float = Field(default=0.5, ge=0.0)

    @property
    def gemini_enabled(self) -> bool:
        """Return True when a non-empty Gemini API key is configured.

        Args:
            None

        Returns:
            True if configured, False otherwise.

        Raises:
            None

        Example:
            >>> s = Settings(gemini_api_key="123")
            >>> s.gemini_enabled
            True
        """
        return bool(self.gemini_api_key and self.gemini_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached Settings singleton.

    Args:
        None

    Returns:
        The cached Settings instance.

    Raises:
        None

    Example:
        >>> s = get_settings()
    """
    return Settings()
