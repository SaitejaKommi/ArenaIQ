"""Application configuration.

Settings are loaded from environment variables (and an optional ``.env`` file)
via ``pydantic-settings``. Secrets are **never** hard-coded here — the Gemini API
key is read from the environment and may be absent, in which case the app falls
back to the offline :class:`~app.services.llm.MockLLM`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated application settings.

    Every field can be overridden by an environment variable of the same
    (upper-cased) name, e.g. ``GEMINI_API_KEY`` or ``RATE_LIMIT_CAPACITY``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "StadiumMate"

    # --- Gemini (optional; absence triggers the MockLLM fallback) ---
    gemini_api_key: str | None = Field(default=None, description="Google Gemini API key.")
    gemini_model: str = Field(default="gemini-1.5-flash")
    gemini_max_output_tokens: int = Field(default=256, ge=16, le=2048)

    # --- HTTP security ---
    allowed_origins: list[str] = Field(
        default=["http://localhost:8000", "http://127.0.0.1:8000"],
        description="Explicit CORS allow-list. Same-origin localhost by default.",
    )

    # --- Rate limiting (token bucket, per client IP) ---
    rate_limit_capacity: int = Field(default=30, ge=1)
    rate_limit_refill_per_sec: float = Field(default=0.5, ge=0.0)

    @property
    def gemini_enabled(self) -> bool:
        """True when a non-empty Gemini API key is configured."""
        return bool(self.gemini_api_key and self.gemini_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance."""
    return Settings()
