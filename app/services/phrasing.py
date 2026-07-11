"""
ArenaIQ — Deterministic, offline natural-language response generation.

Turns the rules engine's structured decision facts into localized prose in
English, Spanish, and French without any LLM or network call. This module
serves two roles simultaneously:

1. **Short-circuit answer path**: When the fan provides no free-text question,
   :func:`render_answer` is called directly and the LLM is bypassed entirely.
2. **MockLLM fallback**: :class:`~app.services.llm.MockLLM` delegates to
   :func:`render_answer`, making the application fully functional offline
   and making the test suite deterministic and network-free.

All localized strings for UI chrome live in per-language lookup tables in
this module. Facility names, zone names, and landmark descriptions are
localized in the JSON fixtures (``facilities.json``, ``stadium.json``) and
resolved by :func:`~app.services.stadium_data.localized`.

Performance:
    :func:`render_answer` is decorated with ``lru_cache(maxsize=256)``
    because :class:`PhrasingContext` is a frozen dataclass (hashable).
    Repeated requests with the same context — common during peak load —
    hit the cache and return without any string formatting work.

Typical usage::

    from app.services.phrasing import render_answer, PhrasingContext
    ctx = PhrasingContext(
        language="en",
        facility_name="North-East Accessible Restroom",
        facility_type="accessible_restroom",
        facility_landmark="beside the North-East elevator",
        crowd_level="low",
        accessibility_mode="screen_reader",
        landmark_based=True,
        hurry=False,
        alternative_type=None,
        total_distance=120,
        step_count=3,
    )
    answer = render_answer(ctx)
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.utils.constants import DEFAULT_LANGUAGE

# ---------------------------------------------------------------------------
# Localization tables
# ---------------------------------------------------------------------------

# Movement verb per travel means (imperative, lower-cased; capitalized on use).
_MEANS: dict[str, dict[str, str]] = {
    "en": {
        "walk": "walk",
        "ramp": "take the ramp",
        "elevator": "take the elevator",
        "stairs": "take the stairs",
    },
    "es": {
        "walk": "camine",
        "ramp": "tome la rampa",
        "elevator": "tome el ascensor",
        "stairs": "suba por las escaleras",
    },
    "fr": {
        "walk": "marchez",
        "ramp": "empruntez la rampe",
        "elevator": "prenez l'ascenseur",
        "stairs": "prenez les escaliers",
    },
}

_CROWD_WORD: dict[str, dict[str, str]] = {
    "en": {"low": "low", "medium": "moderate", "high": "high"},
    "es": {"low": "baja", "medium": "moderada", "high": "alta"},
    "fr": {"low": "faible", "medium": "modérée", "high": "élevée"},
}

_TYPE_LABEL: dict[str, dict[str, str]] = {
    "en": {
        "restroom": "restroom",
        "accessible_restroom": "accessible restroom",
        "first_aid": "first aid station",
        "concession": "concession",
        "guest_services": "guest services desk",
        "water": "water refill point",
        "sensory_room": "sensory room",
        "exit": "exit",
        "gate": "gate",
        "seat": "seat",
        "elevator": "elevator",
    },
    "es": {
        "restroom": "aseo",
        "accessible_restroom": "aseo accesible",
        "first_aid": "puesto de primeros auxilios",
        "concession": "puesto de comida",
        "guest_services": "punto de atención",
        "water": "fuente de agua",
        "sensory_room": "sala sensorial",
        "exit": "salida",
        "gate": "puerta",
        "seat": "asiento",
        "elevator": "ascensor",
    },
    "fr": {
        "restroom": "toilettes",
        "accessible_restroom": "toilettes accessibles",
        "first_aid": "poste de premiers secours",
        "concession": "point de restauration",
        "guest_services": "comptoir d'accueil",
        "water": "point d'eau",
        "sensory_room": "salle sensorielle",
        "exit": "sortie",
        "gate": "porte",
        "seat": "place",
        "elevator": "ascenseur",
    },
}

# Route-step sentence templates; {verb}, {to}, {name}, {lm} are substituted at render time.
_STEP: dict[str, dict[str, str]] = {
    "en": {
        "final": "{verb} to {to}, where you'll find {name}{lm}.",
        "mid": "{verb} to {to}.",
    },
    "es": {
        "final": "{verb} hasta {to}, donde encontrará {name}{lm}.",
        "mid": "{verb} hasta {to}.",
    },
    "fr": {
        "final": "{verb} jusqu'à {to}, où se trouve {name}{lm}.",
        "mid": "{verb} jusqu'à {to}.",
    },
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

# Sentence fragments composed into the full answer paragraph by render_answer.
_ANSWER: dict[str, dict[str, str]] = {
    "en": {
        "dest": "Your destination is {name}{lm}.",
        "here": "You're already at this location.",
        "route": "Follow the {n}-step route below (about {d} m).",
        "crowd": "Crowd level there is currently {c}.",
        "landmark": "These directions use landmarks and are optimized for screen readers.",
        "captioned": (
            "Look for visual signage on the way; "
            "a quiet Sensory Room is available if you need it."
        ),
        "hurry": "Kickoff is very soon — please head there quickly.",
    },
    "es": {
        "dest": "Su destino es {name}{lm}.",
        "here": "Ya se encuentra en este lugar.",
        "route": "Siga la ruta de abajo en {n} paso(s) (unos {d} m).",
        "crowd": "La afluencia allí es actualmente {c}.",
        "landmark": (
            "Estas indicaciones se basan en puntos de referencia "
            "y están optimizadas para lectores de pantalla."
        ),
        "captioned": (
            "Busque la señalización visual por el camino; "
            "hay una sala sensorial tranquila disponible si la necesita."
        ),
        "hurry": "El partido está a punto de comenzar: diríjase allí rápidamente.",
    },
    "fr": {
        "dest": "Votre destination est {name}{lm}.",
        "here": "Vous y êtes déjà.",
        "route": "Suivez l'itinéraire ci-dessous en {n} étape(s) (environ {d} m).",
        "crowd": "L'affluence sur place est actuellement {c}.",
        "landmark": (
            "Ces indications s'appuient sur des points de repère "
            "et sont optimisées pour les lecteurs d'écran."
        ),
        "captioned": (
            "Repérez la signalétique visuelle en chemin ; "
            "une salle sensorielle calme est disponible au besoin."
        ),
        "hurry": "Le coup d'envoi est imminent — rendez-vous-y rapidement.",
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _lang(language: str) -> str:
    """Return a supported language key, falling back to the default language.

    Args:
        language: ISO 639-1 language code requested by the caller.

    Returns:
        The ``language`` string if it exists in the localization tables,
        otherwise :data:`~app.utils.constants.DEFAULT_LANGUAGE` (``"en"``).
    """
    return language if language in _MEANS else DEFAULT_LANGUAGE


def _cap(text: str) -> str:
    """Capitalize the first character of a string, leaving the rest unchanged.

    Used to capitalize movement verbs at the start of route-step sentences
    while preserving the casing of multi-word phrases (e.g. ``"take the ramp"``
    → ``"Take the ramp"``).

    Args:
        text: The string to capitalize.

    Returns:
        The input string with its first character upper-cased, or the
        original string if it is empty.
    """
    return text[:1].upper() + text[1:] if text else text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def type_label(facility_type: str, language: str) -> str:
    """Return the localized display label for a facility type string.

    Args:
        facility_type: Internal facility type key (e.g. ``"accessible_restroom"``).
        language: ISO 639-1 language code for the desired translation.

    Returns:
        Localized label string (e.g. ``"accessible restroom"`` in English).
        Falls back to the type string with underscores replaced by spaces
        if the type is not in the localization table.
    """
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
    """Build one localized route-step instruction sentence.

    Selects the appropriate sentence template (``"final"`` for the last step,
    ``"mid"`` for intermediate steps) and substitutes the travel verb,
    destination name, facility name, and optional landmark.

    Args:
        means: Travel means key (``"walk"``, ``"ramp"``, ``"elevator"``,
            ``"stairs"``). Unknown means default to ``"walk"``.
        to_name: Localized name of the destination zone for this step.
        landmark: Localized landmark description shown on the final step,
            or ``None`` if no landmark is defined for the facility.
        is_final: ``True`` if this is the last step in the route, which
            triggers the longer template that names the facility and landmark.
        facility_name: Localized name of the target facility, injected into
            the final-step template only.
        language: ISO 639-1 language code for the localization lookup.

    Returns:
        A complete, capitalized instruction sentence for this route step.
    """
    lang = _lang(language)
    verb = _cap(_MEANS[lang].get(means, _MEANS[lang]["walk"]))
    lm = f" ({landmark})" if (is_final and landmark) else ""
    template = _STEP[lang]["final" if is_final else "mid"]
    return template.format(verb=verb, to=to_name, name=facility_name, lm=lm)


def alternatives_note(facility_type: str, language: str) -> str:
    """Return a localized note explaining a crowd-avoidance facility swap.

    Called when the nearest facility for an intent was at high crowd level
    and the engine selected a quieter alternative instead.

    Args:
        facility_type: The type of the alternative facility selected
            (e.g. ``"restroom"``), used to insert the localized type label.
        language: ISO 639-1 language code for the localization lookup.

    Returns:
        A complete localized sentence explaining that a quieter alternative
        was suggested due to crowd congestion at the nearest facility.
    """
    lang = _lang(language)
    return _ALT_NOTE[lang].format(label=type_label(facility_type, lang))


def urgency_note(language: str) -> str:
    """Return a localized urgency banner string for imminent kickoff.

    Displayed when ``minutes_to_kickoff < KICKOFF_URGENCY_MINUTES`` and
    the fan's destination intent is time-sensitive (gate or seat).

    Args:
        language: ISO 639-1 language code for the localization lookup.

    Returns:
        A short localized urgency sentence advising the fan to hurry.
    """
    return _URGENCY[_lang(language)]


@dataclass(frozen=True)
class PhrasingContext:
    """Hashable snapshot of all facts needed to compose the final answer.

    Being a frozen dataclass makes instances hashable, enabling
    :func:`render_answer` to be memoized with ``lru_cache``. All fields
    are derived from :class:`~app.models.schemas.DecisionResult` and must
    be primitive types or immutable values to preserve hashability.

    Attributes:
        language: ISO 639-1 language code for the response.
        facility_name: Localized name of the resolved target facility.
        facility_type: Type key of the resolved facility.
        facility_landmark: Localized landmark description, or ``None``.
        crowd_level: Simulated crowd level string (``"low"``/``"medium"``/``"high"``).
        accessibility_mode: Presentation mode string from the rules engine.
        landmark_based: ``True`` when landmark-based instructions are active.
        hurry: ``True`` when kickoff is imminent and the intent is time-sensitive.
        alternative_type: Facility type of the crowd-avoidance swap, or ``None``.
        total_distance: Sum of all route step distances in metres.
        step_count: Number of route steps in the path.
    """

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
    """Compose the full localized answer paragraph from a phrasing context.

    Assembles a natural-language paragraph by joining selected sentence
    fragments from the ``_ANSWER`` tables based on the flags and values in
    ``ctx``. The result is memoized: identical :class:`PhrasingContext`
    instances (same frozen field values) return the cached string without
    re-executing any formatting logic.

    This function is the core of the short-circuit path (no LLM) and also
    the fallback used by :class:`~app.services.llm.MockLLM`.

    Args:
        ctx: A frozen :class:`PhrasingContext` snapshot containing all
            facts needed to phrase the response.

    Returns:
        A localized answer paragraph as a single space-joined string of
        all applicable sentence fragments.
    """
    lang = _lang(ctx.language)
    a = _ANSWER[lang]
    crowd = _CROWD_WORD[lang][ctx.crowd_level]
    dest_lm = f" ({ctx.facility_landmark})" if ctx.facility_landmark else ""

    parts = [a["dest"].format(name=ctx.facility_name, lm=dest_lm)]
    if ctx.step_count == 0:
        # Fan is already at the destination — no navigation needed.
        parts.append(a["here"])
    else:
        parts.append(a["route"].format(n=ctx.step_count, d=ctx.total_distance))
    parts.append(a["crowd"].format(c=crowd))
    if ctx.alternative_type:
        # A quieter alternative was selected — explain why.
        parts.append(alternatives_note(ctx.alternative_type, lang))
    if ctx.landmark_based:
        # Visual accessibility mode — note that landmark instructions are used.
        parts.append(a["landmark"])
    if ctx.accessibility_mode == "captioned":
        # Hearing accessibility mode — point to visual signage and sensory room.
        parts.append(a["captioned"])
    if ctx.hurry:
        # Kickoff is imminent — add urgency encouragement.
        parts.append(a["hurry"])
    return " ".join(parts)
