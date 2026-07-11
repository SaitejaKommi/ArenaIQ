"""Unit tests for fixture loading and the localized() helper."""

from __future__ import annotations

from app.services.stadium_data import get_stadium, localized


def test_localized_fallback_chain():
    assert localized(None, "en") is None
    assert localized({}, "es") is None
    assert localized({"es": "Hola"}, "es") == "Hola"
    assert localized({"en": "Hello"}, "es") == "Hello"  # falls back to English
    assert localized({"fr": "Bonjour"}, "es") == "Bonjour"  # then to any available value


def test_zone_name_localized_and_defaults():
    stadium = get_stadium()
    assert stadium.zone_name("gate_a", "es") == "Puerta A (suroeste)"
    assert stadium.zone_name("gate_a", "fr") == "Porte A (sud-ouest)"
    # Unknown zone id falls back to the id itself.
    assert stadium.zone_name("nope", "en") == "nope"
