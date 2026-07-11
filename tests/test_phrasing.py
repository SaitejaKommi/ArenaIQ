"""Phrasing tests — cover every EN/FR branch of the templated answer generator."""

from __future__ import annotations

from app.services.phrasing import (
    PhrasingContext,
    alternatives_note,
    render_answer,
    step_instruction,
    type_label,
    urgency_note,
)


def _ctx(**overrides) -> PhrasingContext:
    base = {
        "language": "en",
        "facility_name": "North-East Accessible Restroom",
        "facility_type": "accessible_restroom",
        "facility_landmark": "beside the elevator",
        "crowd_level": "low",
        "accessibility_mode": "standard",
        "landmark_based": False,
        "hurry": False,
        "alternative_type": None,
        "total_distance": 100,
        "step_count": 2,
    }
    base.update(overrides)
    return PhrasingContext(**base)


def test_render_en_with_all_flags():
    out = render_answer(
        _ctx(
            landmark_based=True,
            accessibility_mode="captioned",
            hurry=True,
            alternative_type="restroom",
        )
    )
    assert "screen readers" in out
    assert "Sensory Room" in out
    assert "please head there quickly" in out
    assert "quieter" in out


def test_render_en_already_at_location():
    out = render_answer(_ctx(step_count=0, facility_landmark=None))
    assert "already at this location" in out


def test_render_fr_with_all_flags():
    out = render_answer(
        _ctx(
            language="fr",
            step_count=0,
            landmark_based=True,
            accessibility_mode="captioned",
            hurry=True,
            alternative_type="restroom",
        )
    )
    assert "Vous y êtes déjà" in out
    assert "lecteurs d'écran" in out
    assert "salle sensorielle" in out
    assert "imminent" in out


def test_urgency_note_localized():
    assert "dépêchez-vous" in urgency_note("fr")
    assert "hurry" in urgency_note("en")


def test_alternatives_note_localized():
    assert "plus calme" in alternatives_note("concession", "fr")
    assert "quieter" in alternatives_note("concession", "en")


def test_step_instruction_fr_variants():
    final = step_instruction(
        "elevator", "Upper Concourse", "near the lobby", is_final=True,
        facility_name="Restroom", language="fr",
    )
    mid = step_instruction(
        "walk", "Lower Concourse", None, is_final=False, facility_name="Restroom", language="fr",
    )
    assert "ascenseur" in final.lower()
    assert "se trouve" in final
    assert mid.startswith("Marchez")
    assert "jusqu'à" in mid


def test_render_es_with_all_flags():
    out = render_answer(
        _ctx(
            language="es",
            step_count=0,
            landmark_based=True,
            accessibility_mode="captioned",
            hurry=True,
            alternative_type="restroom",
        )
    )
    assert "Su destino" in out
    assert "Ya se encuentra" in out
    assert "lectores de pantalla" in out
    assert "sala sensorial" in out
    assert "diríjase allí" in out


def test_spanish_helpers():
    assert "dese prisa" in urgency_note("es")
    assert "más tranquila" in alternatives_note("concession", "es")
    step = step_instruction(
        "elevator", "Vestíbulo superior", "junto al ascensor", is_final=True,
        facility_name="Aseo", language="es",
    )
    assert step.startswith("Tome el ascensor")
    assert "donde encontrará" in step


def test_type_label_localized():
    assert type_label("restroom", "es") == "aseo"
    assert type_label("restroom", "fr") == "toilettes"
    assert type_label("mystery_type", "en") == "mystery type"
