"""
ArenaIQ — Static template localization and text generation.

This module is the OFFLINE rendering path for the ArenaIQ assistant.
It provides templated natural-language responses in English, Spanish, and
French for all routing and accessibility scenarios, operating entirely
without any network calls or LLM dependency.

Relation to the LLM strategy pattern
--------------------------------------
The codebase uses a ``Rules-Before-LLM`` architecture:
1. ``context_engine.py`` resolves all facts deterministically.
2. Those facts are packaged into a :class:`PhrasingContext`.
3. If the user supplied a free-text question, the context is passed to
   ``llm.phrase()`` (Gemini or MockLLM).
4. If no question was asked — or if Gemini fails — ``render_answer()``
   (this module) is called directly to produce a fully grounded, offline,
   template-based answer.

``render_answer`` is also the fallback used by :class:`~app.services.llm.MockLLM`,
which simply delegates to it instead of calling any external API.

Typical usage
-------------
::

    from app.services.phrasing import PhrasingContext, render_answer

    ctx = PhrasingContext(
        language="en", facility_name="Gate A", facility_type="gate",
        facility_landmark="beside the escalator", crowd_level="medium",
        accessibility_mode="standard", landmark_based=False, hurry=False,
        alternative_type=None, total_distance=120, step_count=3,
    )
    answer = render_answer(ctx)
    # "Your route to Gate A is 120m long and takes 3 steps. ..."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.utils.constants import DEFAULT_LANGUAGE


@dataclass(frozen=True)
class PhrasingContext:
    """Read-only container for all resolved routing facts.

    Attributes:
        language: ISO 639-1 language code.
        facility_name: Localized name of the target facility.
        facility_type: Category of the target facility.
        facility_landmark: Optional localized landmark description.
        crowd_level: Resolved crowd index ('low', 'medium', 'high').
        accessibility_mode: Selected display mode (standard, captioned, etc).
        landmark_based: True if route instructions should emphasize landmarks.
        hurry: True if the user is rushing to a time-sensitive destination.
        alternative_type: Facility type of the alternative if a crowd-swap occurred.
        total_distance: Total journey distance in metres.
        step_count: Number of edges in the route.
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


def _lang(strings: dict[str, Any], lang: str) -> Any:
    """Retrieve the value for a language code, falling back to DEFAULT_LANGUAGE.

    Looks up ``lang`` in ``strings``. If not present, falls back to the
    value stored under ``DEFAULT_LANGUAGE`` (English). Returns an empty
    string if neither key exists.

    Args:
        strings: A dict mapping ISO 639-1 language codes to translated values.
        lang: The requested ISO 639-1 language code (e.g. ``'en'``, ``'fr'``).

    Returns:
        The translated value for ``lang``, the DEFAULT_LANGUAGE fallback, or
        an empty string when neither key is present.

    Raises:
        None

    Example:
        >>> _lang({"en": "Walk to {}", "fr": "Marchez vers {}"}, "fr")
        'Marchez vers {}'
        >>> _lang({"en": "Walk to {}"}, "es")
        'Walk to {}'
    """
    return strings.get(lang, strings.get(DEFAULT_LANGUAGE, ""))


def _cap(text: str) -> str:
    """Capitalise the first letter of a string, leaving the rest unchanged.

    Args:
        text: The string whose first character should be uppercased.

    Returns:
        The input string with its first character converted to uppercase.
        Returns the original string unchanged if it is empty.

    Raises:
        None

    Example:
        >>> _cap("walk to gate a")
        'Walk to gate a'
        >>> _cap("")
        ''
    """
    return text[:1].upper() + text[1:] if text else text


def type_label(facility_type: str, language: str) -> str:
    """Return the localized display label for a given facility type string.

    Performs a dictionary lookup for common facility types. For unknown types,
    replaces underscores with spaces and returns the result in English.

    Args:
        facility_type: The internal facility type key (e.g. ``'restroom'``,
            ``'first_aid'``, ``'gate'``).
        language: ISO 639-1 language code for the desired output language.

    Returns:
        A human-readable localized string for the facility type (e.g.
        ``'toilettes'`` for ``('restroom', 'fr')``).

    Raises:
        None

    Example:
        >>> type_label("restroom", "fr")
        'toilettes'
        >>> type_label("restroom", "es")
        'aseo'
        >>> type_label("mystery_facility", "en")
        'mystery facility'
    """
    labels: dict[str, dict[str, str]] = {
        "restroom": {"en": "restroom", "es": "aseo", "fr": "toilettes"},
        "gate": {"en": "gate", "es": "puerta", "fr": "porte"},
        "first_aid": {"en": "first aid", "es": "primeros auxilios", "fr": "premiers secours"},
    }
    return _lang(labels.get(facility_type, {"en": facility_type.replace("_", " ")}), language)  # type: ignore[no-any-return]


def _build_base_instruction(means: str, zone_name: str, language: str) -> str:
    """Build the base movement instruction sentence without landmark or arrival text.

    Selects the appropriate verb phrase template for the given transit means
    and formats it with the destination zone name.

    Args:
        means: The mode of transit (``'walk'``, ``'ramp'``, ``'elevator'``,
            ``'stairs'``). Falls back to the ``'walk'`` template for unknown values.
        zone_name: The localized display name of the destination zone.
        language: ISO 639-1 language code for the output.

    Returns:
        A single formatted instruction sentence without landmark or arrival
        suffix (e.g. ``'Walk to Lower Concourse'``).

    Raises:
        None

    Example:
        >>> _build_base_instruction("elevator", "Upper Concourse", "en")
        'Take the elevator to Upper Concourse'
        >>> _build_base_instruction("walk", "Puerta Norte", "es")
        'Camine hacia Puerta Norte'
    """
    templates: dict[str, dict[str, str]] = {
        "walk": {"en": "Walk to {}", "es": "Camine hacia {}", "fr": "Marchez jusqu'à {}"},
        "ramp": {"en": "Take the ramp to {}", "es": "Tome la rampa hacia {}", "fr": "Prenez la rampe vers {}"},
        "elevator": {"en": "Take the elevator to {}", "es": "Tome el ascensor a {}", "fr": "Prenez l'ascenseur vers {}"},
        "stairs": {"en": "Take the stairs to {}", "es": "Tome las escaleras a {}", "fr": "Prenez les escaliers vers {}"},
    }
    base = _lang(templates.get(means, templates["walk"]), language)
    return str(base).format(zone_name)


def _append_landmark(base: str, landmark: str | None, language: str) -> str:
    """Append a localized landmark hint to a base instruction string if one is present.

    If ``landmark`` is ``None`` or empty, the original ``base`` string is
    returned unchanged.

    Args:
        base: The base instruction string already containing the movement verb
            and destination (e.g. ``'Walk to Lower Concourse'``).
        landmark: Optional landmark description string. If falsy, this function
            is a no-op.
        language: ISO 639-1 language code used to select the correct template.

    Returns:
        The ``base`` string with the landmark parenthetical appended, e.g.
        ``'Walk to Lower Concourse (look for: beside the elevator)'``.
        Returns ``base`` unchanged when ``landmark`` is falsy.

    Raises:
        None

    Example:
        >>> _append_landmark("Walk to Gate A", "beside the escalator", "en")
        'Walk to Gate A (look for: beside the escalator)'
        >>> _append_landmark("Walk to Gate A", None, "en")
        'Walk to Gate A'
    """
    if not landmark:
        return base
    templates: dict[str, str] = {
        "en": "{} (look for: {})",
        "es": "{} (busque: {})",
        "fr": "{} (cherchez : {})",
    }
    return str(_lang(templates, language)).format(base, landmark)


def _append_arrival(base: str, is_final: bool, facility_name: str, language: str) -> str:
    """Append a localized arrival confirmation to the instruction for the final step.

    For intermediate steps, simply appends a period. For the final step,
    appends an arrival clause naming the target facility.

    Args:
        base: The assembled base instruction (possibly with landmark).
        is_final: If ``True``, appends the arrival clause; otherwise appends
            just a period to terminate the sentence.
        facility_name: The localized display name of the target facility,
            used only when ``is_final=True``.
        language: ISO 639-1 language code for the arrival clause template.

    Returns:
        The completed step instruction string. For final steps this ends with
        the facility name (e.g. ``'… to arrive at Gate A.'``); for intermediate
        steps it ends with a period.

    Raises:
        None

    Example:
        >>> _append_arrival("Take the elevator to Upper Concourse", True, "Gate A", "en")
        'Take the elevator to Upper Concourse to arrive at Gate A.'
        >>> _append_arrival("Walk to Lower Concourse", False, "Gate A", "en")
        'Walk to Lower Concourse.'
    """
    if not is_final:
        return base + "."
    arr: dict[str, str] = {
        "en": " to arrive at {}.",
        "es": " donde encontrará {}.",
        "fr": " où se trouve {}.",
    }
    return base + str(_lang(arr, language)).format(facility_name)


def step_instruction(
    means: str,
    zone_name: str,
    landmark: str | None,
    *,
    is_final: bool,
    facility_name: str,
    language: str,
) -> str:
    """Format a complete, localized, step-by-step route instruction.

    Composes the three sub-components — movement verb, optional landmark
    hint, and arrival clause — into a single instruction sentence.

    Args:
        means: Transit mode string (``'walk'``, ``'ramp'``, ``'elevator'``,
            ``'stairs'``).
        zone_name: Localized display name of the destination zone for this step.
        landmark: Optional localized landmark string shown parenthetically.
        is_final: If ``True``, appends an arrival confirmation at the destination.
        facility_name: Name of the ultimate target facility (used only on
            the final step for the arrival clause).
        language: ISO 639-1 language code for all output strings.

    Returns:
        A single complete, localized instruction sentence for this route step,
        e.g. ``'Take the elevator to Upper West (look for: beside the lobby) to arrive at Gate A.'``

    Raises:
        None

    Example:
        >>> step_instruction("elevator", "Upper Concourse", "near the lobby",
        ...                  is_final=True, facility_name="Restroom", language="fr")
        "Prenez l'ascenseur vers Upper Concourse (cherchez : near the lobby) où se trouve Restroom."
    """
    base = _build_base_instruction(means, zone_name, language)
    with_lm = _append_landmark(base, landmark, language)
    return _append_arrival(with_lm, is_final, facility_name, language)


def alternatives_note(alternative_type: str, language: str) -> str:
    """Format a localized notice explaining that a quieter alternative facility was selected.

    Used when the primary facility is at high crowd level and the engine
    has swapped to a less congested alternative.

    Args:
        alternative_type: The internal type key of the alternative facility
            (e.g. ``'restroom'``, ``'concession'``).
        language: ISO 639-1 language code for the output message.

    Returns:
        A full localized sentence explaining the crowd-based rerouting, e.g.
        ``'To avoid crowds, we have routed you to a quieter restroom.'``

    Raises:
        None

    Example:
        >>> alternatives_note("restroom", "en")
        'To avoid crowds, we have routed you to a quieter restroom.'
        >>> alternatives_note("concession", "fr")
        'Pour éviter la foule, nous vous avons dirigé vers un restauration plus calme.'
    """
    label: str = type_label(alternative_type, language)
    templates: dict[str, str] = {
        "en": f"To avoid crowds, we have routed you to a quieter {label}.",
        "es": f"Para evitar aglomeraciones, le hemos dirigido a un {label} más tranquila.",
        "fr": f"Pour éviter la foule, nous vous avons dirigé vers un {label} plus calme.",
    }
    return str(_lang(templates, language))


def urgency_note(language: str) -> str:
    """Format a localized urgency warning when kickoff is imminent.

    Called when ``minutes_to_kickoff`` is within the threshold defined by
    ``KICKOFF_URGENCY_MINUTES`` and the destination is a gate or seat.

    Args:
        language: ISO 639-1 language code for the output message.

    Returns:
        A localized urgency warning string encouraging the fan to hurry to
        their gate or seat before the match starts.

    Raises:
        None

    Example:
        >>> urgency_note("en")
        'Kickoff is approaching — hurry, please head there quickly.'
        >>> urgency_note("fr")
        "Le coup d'envoi est imminent — dépêchez-vous."
    """
    templates: dict[str, str] = {
        "en": "Kickoff is approaching — hurry, please head there quickly.",
        "es": "El inicio se acerca: dese prisa y diríjase allí.",
        "fr": "Le coup d'envoi est imminent — dépêchez-vous.",
    }
    return str(_lang(templates, language))


def _build_answer_intro(ctx: PhrasingContext) -> str:
    """Build the opening introduction sentence for the templated answer.

    Produces either an "already here" message (when ``step_count == 0``) or
    a route summary sentence stating the distance and number of steps.

    Args:
        ctx: The frozen :class:`PhrasingContext` containing all resolved facts.

    Returns:
        A single localized sentence — either confirming the fan is already
        at the destination, or summarising the route length and step count.

    Raises:
        None

    Example:
        >>> ctx = PhrasingContext(language="en", facility_name="Gate A",
        ...     facility_type="gate", facility_landmark=None, crowd_level="low",
        ...     accessibility_mode="standard", landmark_based=False, hurry=False,
        ...     alternative_type=None, total_distance=0, step_count=0)
        >>> _build_answer_intro(ctx)
        'You are already at this location.'
    """
    if ctx.step_count == 0:
        templates_zero = {
            "en": "You are already at this location.",
            "es": "Ya se encuentra en Su destino.",
            "fr": "Vous y êtes déjà.",
        }
        return str(_lang(templates_zero, ctx.language))

    templates = {
        "en": "Your route to {name} is {dist}m long and takes {steps} steps.",
        "es": "Su destino {name} está a {dist}m y {steps} pasos.",
        "fr": "Votre destination {name} est à {dist}m en {steps} étapes.",
    }
    intro = str(_lang(templates, ctx.language))
    return intro.format(name=ctx.facility_name, dist=ctx.total_distance, steps=ctx.step_count)


def _build_answer_crowd(ctx: PhrasingContext) -> str:
    """Build the crowd-level context sentence for the templated answer.

    Appends a localized description of the current crowd level at the
    destination zone to help the fan plan accordingly.

    Args:
        ctx: The frozen :class:`PhrasingContext` containing all resolved facts.

    Returns:
        A single localized sentence about current crowd density at the
        destination, e.g. ``' Current crowd level at destination is moderate.'``

    Raises:
        None

    Example:
        >>> ctx = PhrasingContext(language="en", facility_name="Restroom",
        ...     facility_type="restroom", facility_landmark=None, crowd_level="medium",
        ...     accessibility_mode="standard", landmark_based=False, hurry=False,
        ...     alternative_type=None, total_distance=50, step_count=1)
        >>> _build_answer_crowd(ctx)
        ' Current crowd level at destination is moderate.'
    """
    templates: dict[str, str] = {
        "en": " Current crowd level at destination is {crowd}.",
        "es": " La afluencia actual en el destino es {crowd}.",
        "fr": " L'affluence actuelle à destination est {crowd}.",
    }
    crowds: dict[str, dict[str, str]] = {
        "low": {"en": "low", "es": "baja", "fr": "faible"},
        "medium": {"en": "moderate", "es": "moderada", "fr": "modérée"},
        "high": {"en": "high", "es": "alta", "fr": "élevée"},
    }
    crowd_str = str(_lang(crowds.get(ctx.crowd_level, crowds["low"]), ctx.language))
    return str(_lang(templates, ctx.language)).format(crowd=crowd_str)


def _build_answer_lm(ctx: PhrasingContext) -> str:
    """Build the landmark lookup sentence for the templated answer, if applicable.

    Returns a non-empty string only when ``landmark_based=True`` and a
    ``facility_landmark`` is available in the context.

    Args:
        ctx: The frozen :class:`PhrasingContext` containing all resolved facts.

    Returns:
        A localized sentence directing the fan to look for the landmark
        (e.g. ``' Look for: beside the elevator.'``), or an empty string
        when landmarks are not applicable.

    Raises:
        None

    Example:
        >>> ctx = PhrasingContext(language="en", facility_name="Restroom",
        ...     facility_type="restroom", facility_landmark="beside the elevator",
        ...     crowd_level="low", accessibility_mode="screen_reader",
        ...     landmark_based=True, hurry=False, alternative_type=None,
        ...     total_distance=80, step_count=2)
        >>> _build_answer_lm(ctx)
        ' Look for: beside the elevator.'
    """
    if not ctx.landmark_based or not ctx.facility_landmark:
        return ""
    templates: dict[str, str] = {
        "en": " Look for: {lm}.",
        "es": " Busque: {lm}.",
        "fr": " Cherchez : {lm}.",
    }
    return str(_lang(templates, ctx.language)).format(lm=ctx.facility_landmark)


def _build_answer_mode(ctx: PhrasingContext) -> str:
    """Build the accessibility mode notification suffix for the templated answer.

    Returns an empty string in standard mode. For ``screen_reader`` mode
    or when ``landmark_based=True``, appends a screen-reader optimisation
    notice. For ``captioned`` mode, additionally appends a sensory room notice.

    Args:
        ctx: The frozen :class:`PhrasingContext` containing all resolved facts.

    Returns:
        Zero, one, or two localized accessbility mode suffix sentences
        concatenated together, e.g.
        ``' Optimized for screen readers. Signage mode (Sensory Room available).'``
        Returns an empty string for standard mode with no landmarks.

    Raises:
        None

    Example:
        >>> ctx = PhrasingContext(language="en", facility_name="Restroom",
        ...     facility_type="restroom", facility_landmark=None, crowd_level="low",
        ...     accessibility_mode="screen_reader", landmark_based=True, hurry=False,
        ...     alternative_type=None, total_distance=50, step_count=1)
        >>> _build_answer_mode(ctx)
        ' Optimized for screen readers.'
    """
    res: list[str] = []
    if ctx.accessibility_mode == "screen_reader" or ctx.landmark_based:
        templates = {
            "en": " Optimized for screen readers.",
            "es": " Optimizado para lectores de pantalla.",
            "fr": " Optimisé pour lecteurs d'écran.",
        }
        res.append(str(_lang(templates, ctx.language)))
    if ctx.accessibility_mode == "captioned":
        templates_cap = {
            "en": " Signage mode (Sensory Room available).",
            "es": " Modo señalización (sala sensorial disponible).",
            "fr": " Mode signalétique (salle sensorielle disponible).",
        }
        res.append(str(_lang(templates_cap, ctx.language)))
    return "".join(res)


def render_answer(ctx: PhrasingContext) -> str:
    """Compose the full templated offline answer from all sub-components.

    This is the primary offline answer generator and the fallback used by
    :class:`~app.services.llm.MockLLM`. It assembles the introduction,
    optional alternatives and urgency notes, crowd status, landmark hint,
    and accessibility mode suffix into a single coherent response.

    Args:
        ctx: The frozen :class:`PhrasingContext` containing all resolved facts
            from the rules engine.

    Returns:
        A stripped, localized string containing the complete answer ready to
        be returned in the ``AssistResponse.answer`` field.

    Raises:
        None

    Example:
        >>> from app.services.phrasing import PhrasingContext, render_answer
        >>> ctx = PhrasingContext(
        ...     language="en", facility_name="Gate A", facility_type="gate",
        ...     facility_landmark=None, crowd_level="low",
        ...     accessibility_mode="standard", landmark_based=False, hurry=False,
        ...     alternative_type=None, total_distance=120, step_count=3,
        ... )
        >>> render_answer(ctx)
        'Your route to Gate A is 120m long and takes 3 steps. Current crowd level at destination is low.'
    """
    parts: list[str] = [_build_answer_intro(ctx)]
    if ctx.alternative_type:
        parts.append(" " + alternatives_note(ctx.alternative_type, ctx.language))
    if ctx.hurry:
        parts.append(" " + urgency_note(ctx.language))
    parts.extend([
        _build_answer_crowd(ctx),
        _build_answer_lm(ctx),
        _build_answer_mode(ctx),
    ])
    return "".join(parts).strip()
