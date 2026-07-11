"""Schema validation tests — the first line of input defense."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.schemas import AccessibilityNeed, Language, UserContext


def _ctx(**overrides) -> dict:
    base = {
        "language": "en",
        "current_location": "concourse_lower_sw",
        "destination_intent": "restroom",
        "minutes_to_kickoff": 20,
    }
    base.update(overrides)
    return base


def test_valid_context_parses():
    ctx = UserContext(**_ctx())
    assert ctx.language is Language.en
    assert ctx.accessibility_needs == [AccessibilityNeed.none]


@pytest.mark.parametrize("lang", ["en", "es", "fr"])
def test_supported_languages_accepted(lang):
    assert UserContext(**_ctx(language=lang)).language.value == lang


def test_unsupported_language_rejected():
    # German is out of scope; only the three host-nation languages are supported.
    with pytest.raises(ValidationError):
        UserContext(**_ctx(language="de"))


def test_invalid_accessibility_need_rejected():
    with pytest.raises(ValidationError):
        UserContext(**_ctx(accessibility_needs=["teleport"]))


def test_invalid_intent_rejected():
    with pytest.raises(ValidationError):
        UserContext(**_ctx(destination_intent="teleport"))


def test_unknown_zone_rejected():
    with pytest.raises(ValidationError):
        UserContext(**_ctx(current_location="mars_base"))


def test_oversized_ticket_section_rejected():
    with pytest.raises(ValidationError):
        UserContext(**_ctx(ticket_section="TOO-LONG-SECTION"))


def test_oversized_question_rejected():
    with pytest.raises(ValidationError):
        UserContext(**_ctx(question="x" * 281))


@pytest.mark.parametrize("minutes", [-121, 1441])
def test_minutes_out_of_range_rejected(minutes):
    with pytest.raises(ValidationError):
        UserContext(**_ctx(minutes_to_kickoff=minutes))


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        UserContext(**_ctx(is_admin=True))


def test_needs_are_normalized():
    # "none" alongside a real need is dropped; duplicates collapse.
    ctx = UserContext(**_ctx(accessibility_needs=["none", "wheelchair", "wheelchair"]))
    assert ctx.accessibility_needs == [AccessibilityNeed.wheelchair]


def test_question_is_sanitized():
    ctx = UserContext(**_ctx(question="Hello\x00\x07   world\n\n"))
    assert ctx.question == "Hello world"


def test_empty_needs_defaults_to_none():
    ctx = UserContext(**_ctx(accessibility_needs=[]))
    assert ctx.accessibility_needs == [AccessibilityNeed.none]


def test_explicit_none_question_stays_none():
    ctx = UserContext(**_ctx(question=None))
    assert ctx.question is None
