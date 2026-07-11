"""Deterministic, offline natural-language phrasing in English, Spanish and French.

This module turns the rules engine's structured facts into localized prose. It is
the short-circuit answer generator (no LLM needed) and is also what
:class:`~app.services.llm.MockLLM` returns. All localized strings live in per-language
tables here (and localized *facility/zone names* live in the JSON fixtures), so the
whole response — prose, route steps and place names — is translated even offline.

Because output is a pure function of the (hashable) :class:`PhrasingContext`, results
are memoized with ``lru_cache`` (efficiency) and are fully deterministic (testable).

The LLM (when a real key is configured) only rephrases/translates these same grounded
facts; it never introduces new ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

_DEFAULT_LANG = "en"

# Movement verb per travel means (imperative, lower-cased; capitalized on use).
_MEANS: dict[str, dict[str, str]] = {
    "en": {"walk": "walk", "ramp": "take the ramp", "elevator": "take the elevator",
           "stairs": "take the stairs"},
    "es": {"walk": "camine", "ramp": "tome la rampa", "elevator": "tome el ascensor",
           "stairs": "suba por las escaleras"},
    "fr": {"walk": "marchez", "ramp": "empruntez la rampe", "elevator": "prenez l'ascenseur",
           "stairs": "prenez les escaliers"},
}

_CROWD_WORD: dict[str, dict[str, str]] = {
    "en": {"low": "low", "medium": "moderate", "high": "high"},
    "es": {"low": "baja", "medium": "moderada", "high": "alta"},
    "fr": {"low": "faible", "medium": "modérée", "high": "élevée"},
}

_TYPE_LABEL: dict[str, dict[str, str]] = {
    "en": {"restroom": "restroom", "accessible_restroom": "accessible restroom",
           "first_aid": "first aid station", "concession": "concession",
           "guest_services": "guest services desk", "water": "water refill point",
           "sensory_room": "sensory room", "exit": "exit", "gate": "gate",
           "seat": "seat", "elevator": "elevator"},
    "es": {"restroom": "aseo", "accessible_restroom": "aseo accesible",
           "first_aid": "puesto de primeros auxilios", "concession": "puesto de comida",
           "guest_services": "punto de atención", "water": "fuente de agua",
           "sensory_room": "sala sensorial", "exit": "salida", "gate": "puerta",
           "seat": "asiento", "elevator": "ascensor"},
    "fr": {"restroom": "toilettes", "accessible_restroom": "toilettes accessibles",
           "first_aid": "poste de premiers secours", "concession": "point de restauration",
           "guest_services": "comptoir d'accueil", "water": "point d'eau",
           "sensory_room": "salle sensorielle", "exit": "sortie", "gate": "porte",
           "seat": "place", "elevator": "ascenseur"},
}

# Route-step templates: {verb} {to} {name} {lm} are filled in.
_STEP: dict[str, dict[str, str]] = {
    "en": {"final": "{verb} to {to}, where you'll find {name}{lm}.", "mid": "{verb} to {to}."},
    "es": {"final": "{verb} hasta {to}, donde encontrará {name}{lm}.", "mid": "{verb} hasta {to}."},
    "fr": {"final": "{verb} jusqu'à {to}, où se trouve {name}{lm}.", "mid": "{verb} jusqu'à {to}."},
}

_ALT_NOTE: dict[str, str] = {
    "en": "A closer {label} was crowded, so a quieter one is suggested.",
    "es": "Un {label} más cercano estaba muy concurrido; se sugiere una opción más tranquila.",
    "fr": "Un(e) {label} plus proche était bondé(e) : une option plus calme est proposée.",
}

_URGENCY: dict[str, str] = {
    "en": "Kickoff in under 15 minutes — please hurry.",
    "es": "El partido comienza en menos de 15 minutos: dese prisa.",
    "fr": "Coup d'envoi dans moins de 15 minutes — dépêchez-vous.",
}

# Sentence fragments composed into the full answer paragraph.
_ANSWER: dict[str, dict[str, str]] = {
    "en": {
        "dest": "Your destination is {name}{lm}.",
        "here": "You're already at this location.",
        "route": "Follow the {n}-step route below (about {d} m).",
        "crowd": "Crowd level there is currently {c}.",
        "landmark": "These directions use landmarks and are optimized for screen readers.",
        "captioned": "Look for visual signage on the way; a quiet Sensory Room is available if you need it.",
        "hurry": "Kickoff is very soon — please head there quickly.",
    },
    "es": {
        "dest": "Su destino es {name}{lm}.",
        "here": "Ya se encuentra en este lugar.",
        "route": "Siga la ruta de abajo en {n} paso(s) (unos {d} m).",
        "crowd": "La afluencia allí es actualmente {c}.",
        "landmark": "Estas indicaciones se basan en puntos de referencia y están optimizadas para lectores de pantalla.",
        "captioned": "Busque la señalización visual por el camino; hay una sala sensorial tranquila disponible si la necesita.",
        "hurry": "El partido está a punto de comenzar: diríjase allí rápidamente.",
    },
    "fr": {
        "dest": "Votre destination est {name}{lm}.",
        "here": "Vous y êtes déjà.",
        "route": "Suivez l'itinéraire ci-dessous en {n} étape(s) (environ {d} m).",
        "crowd": "L'affluence sur place est actuellement {c}.",
        "landmark": "Ces indications s'appuient sur des points de repère et sont optimisées pour les lecteurs d'écran.",
        "captioned": "Repérez la signalétique visuelle en chemin ; une salle sensorielle calme est disponible au besoin.",
        "hurry": "Le coup d'envoi est imminent — rendez-vous-y rapidement.",
    },
}


def _lang(language: str) -> str:
    """Return a supported language key, defaulting to English."""
    return language if language in _MEANS else _DEFAULT_LANG


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def type_label(facility_type: str, language: str) -> str:
    lang = _lang(language)
    return _TYPE_LABEL[lang].get(facility_type, facility_type.replace("_", " "))


def step_instruction(
    means: str,
    to_name: str,
    landmark: str | None,
    *,
    is_final: bool,
    facility_name: str,
    language: str,
) -> str:
    """Build one localized route-step instruction."""
    lang = _lang(language)
    verb = _cap(_MEANS[lang].get(means, _MEANS[lang]["walk"]))
    lm = f" ({landmark})" if (is_final and landmark) else ""
    template = _STEP[lang]["final" if is_final else "mid"]
    return template.format(verb=verb, to=to_name, name=facility_name, lm=lm)


def alternatives_note(facility_type: str, language: str) -> str:
    """Short localized note explaining a crowd-avoidance facility swap."""
    lang = _lang(language)
    return _ALT_NOTE[lang].format(label=type_label(facility_type, lang))


def urgency_note(language: str) -> str:
    """Short localized urgency note for imminent kickoff."""
    return _URGENCY[_lang(language)]


@dataclass(frozen=True)
class PhrasingContext:
    """Hashable snapshot of everything needed to phrase the final answer."""

    language: str
    facility_name: str
    facility_type: str
    facility_landmark: str | None
    crowd_level: str
    accessibility_mode: str
    landmark_based: bool
    hurry: bool
    alternative_type: str | None
    total_distance: int
    step_count: int


@lru_cache(maxsize=256)
def render_answer(ctx: PhrasingContext) -> str:
    """Compose the full localized answer paragraph (memoized)."""
    lang = _lang(ctx.language)
    a = _ANSWER[lang]
    crowd = _CROWD_WORD[lang][ctx.crowd_level]
    dest_lm = f" ({ctx.facility_landmark})" if ctx.facility_landmark else ""

    parts = [a["dest"].format(name=ctx.facility_name, lm=dest_lm)]
    if ctx.step_count == 0:
        parts.append(a["here"])
    else:
        parts.append(a["route"].format(n=ctx.step_count, d=ctx.total_distance))
    parts.append(a["crowd"].format(c=crowd))
    if ctx.alternative_type:
        parts.append(alternatives_note(ctx.alternative_type, lang))
    if ctx.landmark_based:
        parts.append(a["landmark"])
    if ctx.accessibility_mode == "captioned":
        parts.append(a["captioned"])
    if ctx.hurry:
        parts.append(a["hurry"])
    return " ".join(parts)
