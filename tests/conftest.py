"""Shared pytest fixtures.

Every fixture forces the offline configuration: no Gemini key (so the app uses
:class:`~app.services.llm.MockLLM`) and a generous rate limit so functional tests
are never throttled. Individual tests override these as needed.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from starlette.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _settings(**overrides) -> Settings:
    params = {
        "gemini_api_key": None,  # highest-priority override → always offline MockLLM
        "rate_limit_capacity": 1000,
        "rate_limit_refill_per_sec": 1000.0,
        "allowed_origins": ["http://testserver"],
    }
    params.update(overrides)
    return Settings(**params)


@pytest.fixture
def settings() -> Settings:
    return _settings()


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def make_client() -> Callable[..., TestClient]:
    """Factory to build a TestClient with custom settings (e.g. low rate limit)."""

    def _make(**overrides) -> TestClient:
        return TestClient(create_app(_settings(**overrides)))

    return _make


@pytest.fixture
def base_payload() -> dict:
    """A minimal valid ``/api/assist`` request body."""
    return {
        "language": "en",
        "current_location": "concourse_lower_sw",
        "destination_intent": "restroom",
        "accessibility_needs": ["none"],
        "minutes_to_kickoff": 20,
    }
