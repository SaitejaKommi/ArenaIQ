"""API contract tests using the offline TestClient (MockLLM)."""

from __future__ import annotations

_REQUIRED_KEYS = {
    "answer",
    "route_steps",
    "facility",
    "crowd_level",
    "language",
    "accessibility_mode",
    "used_llm",
}


def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_assist_happy_path_returns_required_keys(client, base_payload):
    res = client.post("/api/assist", json=base_payload)
    assert res.status_code == 200
    body = res.json()
    assert _REQUIRED_KEYS.issubset(body)
    assert body["language"] == "en"
    assert isinstance(body["route_steps"], list)


def test_assist_short_circuits_without_question(client, base_payload):
    res = client.post("/api/assist", json=base_payload)
    assert res.json()["used_llm"] is False


def test_assist_offline_with_question_still_not_live(client, base_payload):
    payload = dict(base_payload, question="Where is the nearest restroom?")
    res = client.post("/api/assist", json=payload)
    assert res.status_code == 200
    # MockLLM is not a live model, so used_llm stays False even with a question.
    assert res.json()["used_llm"] is False


def test_assist_french_language(client, base_payload):
    payload = dict(base_payload, language="fr")
    body = client.post("/api/assist", json=payload).json()
    assert body["language"] == "fr"
    # French answer should not contain the English destination lead-in.
    assert "Your destination" not in body["answer"]
    assert "Votre destination" in body["answer"]


def test_assist_spanish_localizes_answer_and_place_names(client, base_payload):
    payload = dict(
        base_payload, language="es",
        current_location="concourse_lower_sw", accessibility_needs=["wheelchair"],
    )
    body = client.post("/api/assist", json=payload).json()
    assert body["language"] == "es"
    assert "Su destino" in body["answer"]
    # Facility name is localized to Spanish, not the English fixture value.
    assert body["facility"]["name"] == "Aseo accesible noreste"
    # Route-step place names are localized too.
    assert any("Vestíbulo" in step["instruction"] for step in body["route_steps"])


def test_malformed_body_returns_422(client):
    res = client.post("/api/assist", json={"language": "en"})  # missing required fields
    assert res.status_code == 422


def test_unknown_zone_via_api_returns_422(client, base_payload):
    payload = dict(base_payload, current_location="atlantis")
    res = client.post("/api/assist", json=payload)
    assert res.status_code == 422


def test_index_page_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_route_not_found_returns_404(client, base_payload, monkeypatch):
    import app.main as main_mod
    from app.services.context_engine import RouteNotFound

    async def _raise(*args, **kwargs):
        raise RouteNotFound("boom")

    monkeypatch.setattr(main_mod, "run_assist", _raise)
    res = client.post("/api/assist", json=base_payload)
    assert res.status_code == 404
    assert res.json()["detail"] == "boom"


def test_stadium_metadata(client):
    body = client.get("/api/stadium").json()
    zone_ids = {z["id"] for z in body["zones"]}
    assert {"gate_a", "concourse_lower_sw", "seating_upper"}.issubset(zone_ids)
    assert body["languages"] == ["en", "es", "fr"]
    assert "restroom" in body["intents"]
    assert body["stadium"]["name"] == "MetLife Stadium"
    # Zone names are localized maps (en/es/fr) for the UI language switcher.
    gate_a = next(z for z in body["zones"] if z["id"] == "gate_a")
    assert set(gate_a["name"]) == {"en", "es", "fr"}
