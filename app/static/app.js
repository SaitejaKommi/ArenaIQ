"use strict";

/**
 * @fileoverview ArenaIQ — client-side application logic.
 *
 * Handles all DOM interactions, API calls, localization switching, and
 * dynamic result rendering for the ArenaIQ stadium assistant single-page
 * application. No framework dependencies — plain ES2021 vanilla JS.
 *
 * Architecture:
 *   - On DOMContentLoaded, `init()` applies language strings and fetches
 *     stadium metadata from the backend to populate the location/intent dropdowns.
 *   - Form submission calls `onSubmit()`, which POSTs to `/api/assist` and
 *     passes the JSON response to `renderResult()`.
 *   - All API calls are prefixed with `API_BASE_URL` which resolves to the
 *     Render backend URL in production or an empty string when running locally.
 *
 * @module app
 */

/**
 * Base URL for all API requests.
 * Resolves to an empty string (relative paths) when running on localhost or
 * 127.0.0.1, so that the local uvicorn server is hit directly. In any other
 * environment (Vercel, CI preview) it points to the Render backend.
 *
 * @constant {string}
 */
const API_BASE_URL =
  window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? ""
    : "https://arenaiq-e22w.onrender.com";

// ---------------------------------------------------------------------------
// Localization tables (EN / ES / FR)
// UI chrome elements use [data-i18n] attributes; dynamic strings use STR[].
// ---------------------------------------------------------------------------

/**
 * Static UI string table for all three supported languages.
 * Keys match the `data-i18n` attribute values used in `index.html`.
 *
 * @type {Object.<string, Object.<string, string>>}
 */
const I18N = {
  en: {
    language: "Language",
    highVisibility: "High Contrast",
    yourContext: "Your context",
    whereNow: "Where are you now?",
    whereGo: "Where do you want to go?",
    accessNeeds: "Accessibility needs",
    needWheelchair: "♿ Wheelchair / step-free",
    needVisual: "👁️ Low vision / screen reader",
    needHearing: "👂 Deaf / hard of hearing",
    ticketSection: "Ticket section",
    minutesToKickoff: "Mins to kick-off",
    question: "Ask a question",
    questionHint: "Free text is treated as data only and never as instructions.",
    getHelp: "Get Directions →",
    assistance: "Assistance",
    placeholder: "Enter your details and select \"Get Directions\". Your answer appears here.",
    grounding:
      "Answers are grounded in verified stadium data — the assistant never invents facilities.",
  },
  es: {
    language: "Idioma",
    highVisibility: "Alto Contraste",
    yourContext: "Su contexto",
    whereNow: "¿Dónde se encuentra ahora?",
    whereGo: "¿A dónde quiere ir?",
    accessNeeds: "Necesidades de accesibilidad",
    needWheelchair: "♿ Silla de ruedas / sin escalones",
    needVisual: "👁️ Baja visión / lector de pantalla",
    needHearing: "👂 Sordo / con dificultad auditiva",
    ticketSection: "Sección del billete",
    minutesToKickoff: "Minutos para el inicio",
    question: "Haga una pregunta",
    questionHint: "El texto libre se trata solo como datos, nunca como instrucciones.",
    getHelp: "Obtener Direcciones →",
    assistance: "Asistencia",
    placeholder: "Complete su contexto y seleccione «Obtener Direcciones». Su respuesta aparecerá aquí.",
    grounding:
      "Las respuestas se basan en datos verificados del estadio: el asistente nunca inventa instalaciones.",
  },
  fr: {
    language: "Langue",
    highVisibility: "Contraste élevé",
    yourContext: "Votre contexte",
    whereNow: "Où êtes-vous actuellement ?",
    whereGo: "Où souhaitez-vous aller ?",
    accessNeeds: "Besoins d'accessibilité",
    needWheelchair: "♿ Fauteuil roulant / sans marches",
    needVisual: "👁️ Basse vision / lecteur d'écran",
    needHearing: "👂 Sourd / malentendant",
    ticketSection: "Section du billet",
    minutesToKickoff: "Minutes avant le coup d'envoi",
    question: "Posez une question",
    questionHint: "Le texte libre est traité comme des données, jamais comme des instructions.",
    getHelp: "Obtenir des Directions →",
    assistance: "Assistance",
    placeholder:
      "Renseignez votre contexte et choisissez « Obtenir des Directions ». Votre réponse apparaîtra ici.",
    grounding:
      "Les réponses s'appuient sur des données vérifiées — l'assistant n'invente aucune installation.",
  },
};

/**
 * Localized display labels for each destination intent value.
 * Populated into the `destination_intent` dropdown by `refreshIntentOptions`.
 *
 * @type {Object.<string, Object.<string, string>>}
 */
const INTENT_LABELS = {
  en: {
    restroom: "🚻 Restroom", gate: "🚪 Entry gate", seat: "💺 My seat", exit: "🚶 Exit",
    first_aid: "🏥 First aid", concession: "🍔 Food & drink", guest_services: "🎫 Guest services",
    water: "💧 Water refill", sensory_room: "🤫 Sensory room",
  },
  es: {
    restroom: "🚻 Aseos", gate: "🚪 Puerta de entrada", seat: "💺 Mi asiento", exit: "🚶 Salida",
    first_aid: "🏥 Primeros auxilios", concession: "🍔 Comida y bebida", guest_services: "🎫 Atención al aficionado",
    water: "💧 Fuente de agua", sensory_room: "🤫 Sala sensorial",
  },
  fr: {
    restroom: "🚻 Toilettes", gate: "🚪 Porte d'entrée", seat: "💺 Ma place", exit: "🚶 Sortie",
    first_aid: "🏥 Premiers secours", concession: "🍔 Restauration", guest_services: "🎫 Accueil",
    water: "💧 Point d'eau", sensory_room: "🤫 Salle sensorielle",
  },
};

/**
 * Localized dynamic strings used in result rendering (crowd labels, error messages, etc.).
 *
 * @type {Object.<string, Object.<string, string>>}
 */
const STR = {
  en: {
    crowd: "Crowd", accessible: "Step-free / accessible", route: "Route", mode: "Mode",
    low: "Low", medium: "Moderate", high: "High",
    standard: "Standard", screen_reader: "Screen-reader optimized", captioned: "Visual signage",
    reqFailed: "Sorry, something went wrong. Please try again.",
    invalid: "Please check your inputs and try again.",
    rateLimited: "Too many requests — please wait a moment and try again.",
    stepFree: "♿ Step-free",
    crowdAt: "Crowd at destination",
    findingRoute: "Finding your route…",
  },
  es: {
    crowd: "Afluencia", accessible: "Sin escalones / accesible", route: "Ruta", mode: "Modo",
    low: "Baja", medium: "Moderada", high: "Alta",
    standard: "Estándar", screen_reader: "Optimizado para lector de pantalla", captioned: "Señalización visual",
    reqFailed: "Lo sentimos, algo salió mal. Inténtelo de nuevo.",
    invalid: "Compruebe sus datos e inténtelo de nuevo.",
    rateLimited: "Demasiadas solicitudes: espere un momento e inténtelo de nuevo.",
    stepFree: "♿ Sin escalones",
    crowdAt: "Afluencia en el destino",
    findingRoute: "Buscando su ruta…",
  },
  fr: {
    crowd: "Affluence", accessible: "Sans marches / accessible", route: "Itinéraire", mode: "Mode",
    low: "Faible", medium: "Modérée", high: "Élevée",
    standard: "Standard", screen_reader: "Optimisé lecteur d'écran", captioned: "Signalétique visuelle",
    reqFailed: "Désolé, une erreur est survenue. Réessayez.",
    invalid: "Veuillez vérifier vos saisies et réessayer.",
    rateLimited: "Trop de requêtes — patientez un instant puis réessayez.",
    stepFree: "♿ Sans marches",
    crowdAt: "Affluence à destination",
    findingRoute: "Recherche de votre itinéraire…",
  },
};

/**
 * Shape-based crowd dot indicators (never rely on colour alone — accessibility).
 * Used alongside colour-coded badges so colour-blind users can distinguish levels.
 *
 * @type {Object.<string, string>}
 */
const DOTS = { low: "●○○", medium: "●●○", high: "●●●" };

/**
 * Emoji indicators for crowd level used in the crowd panel display.
 *
 * @type {Object.<string, string>}
 */
const CROWD_EMOJI = { low: "🟢", medium: "🟡", high: "🔴" };

/**
 * Emoji map for each transit means used in route step rendering.
 * Avoids hard-coding the same literals inside the forEach loop.
 *
 * @type {Object.<string, string>}
 */
const MEANS_EMOJI = { walk: "🚶", ramp: "♿", elevator: "🛗", stairs: "🪜" };

/**
 * Stagger delay in milliseconds added per route step entry animation.
 * Each step's CSS animation is delayed by its index times this value.
 *
 * @type {number}
 */
const STEP_ANIMATION_DELAY_MS = 80;

/**
 * Border colour for the step-free/accessible facility badge.
 * Defined as a constant to avoid a bare hex literal inside renderResult.
 *
 * @type {string}
 */
const COLOR_ACCESSIBLE_BORDER = "#A7F3D0";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** @type {string} Currently selected language code ('en', 'es', or 'fr'). */
let currentLang = "en";

/**
 * Shorthand helper to retrieve a DOM element by ID.
 *
 * @param {string} id - The element's `id` attribute value.
 * @returns {HTMLElement|null} The matching element, or null if not found.
 *
 * @example
 * const btn = $("submit-btn");
 * if (btn) btn.disabled = true;
 */
const $ = (id) => document.getElementById(id);

/**
 * Retrieve the localized string table for the current language, with English fallback.
 *
 * @template T
 * @param {Object.<string, T>} dict - A language-keyed object to look up.
 * @returns {T} The entry for the current language, or the English entry as fallback.
 * @throws {void} Does not throw; returns English fallback for unknown language codes.
 *
 * @example
 * const crowdText = t(STR).crowd; // Returns "Afluencia" if currentLang is "es"
 */
function t(dict) {
  return dict[currentLang] || dict.en;
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

/**
 * Application entry point — called once when the DOM is fully loaded.
 *
 * Applies the default language (English) to all `data-i18n` elements,
 * binds all interactive event listeners, and fetches stadium metadata
 * from the backend to populate the location and destination dropdowns.
 *
 * @async
 * @returns {Promise<void>} Resolves when stadium data has been fetched and
 *   the dropdowns have been populated (or an error state has been shown).
 *
 * @example
 * // Triggered automatically on DOM load:
 * document.addEventListener("DOMContentLoaded", init);
 */
async function init() {
  applyLanguage("en");
  bindEvents();
  await loadStadium();
}

/**
 * Bind all interactive event listeners to their respective DOM elements.
 *
 * Handles: language selector change, high-contrast toggle, form submission,
 * textarea character counter, and the +/− minute stepper buttons.
 *
 * @returns {void}
 *
 * @example
 * // Called during initialization:
 * bindEvents();
 */
function bindEvents() {
  $("language").addEventListener("change", (e) => applyLanguage(e.target.value));
  $("contrast-toggle").addEventListener("click", toggleContrast);
  $("assist-form").addEventListener("submit", onSubmit);

  // Update the character counter below the textarea on each keystroke.
  const q = $("question");
  const counter = $("char-count");
  if (q && counter) {
    q.addEventListener("input", () => { counter.textContent = q.value.length; });
  }

  // Wire up the +/− stepper buttons for the minutes-to-kickoff field.
  const mInput = $("minutes_to_kickoff");
  const btnMinus = $("minutes-minus");
  const btnPlus = $("minutes-plus");
  if (mInput && btnMinus && btnPlus) {
    btnMinus.addEventListener("click", () => {
      const val = parseInt(mInput.value, 10);
      if (!isNaN(val) && val > parseInt(mInput.min, 10)) {
        mInput.value = val - 1;
      }
    });
    btnPlus.addEventListener("click", () => {
      const val = parseInt(mInput.value, 10);
      if (!isNaN(val) && val < parseInt(mInput.max, 10)) {
        mInput.value = val + 1;
      }
    });
  }
}

/**
 * Fetch stadium metadata from the backend and populate the UI dropdowns.
 *
 * Makes a GET request to `{API_BASE_URL}/api/stadium`. On success, stores
 * the response on `window.__stadium` for re-use during language switching,
 * then calls `renderLocationOptions` and `refreshIntentOptions` to populate
 * the two `<select>` elements. Updates the stadium name badge in the header.
 *
 * @async
 * @returns {Promise<void>} Resolves when the dropdowns are populated.
 * @throws {Error} Caught internally; shows an error message in the result
 *   panel and clears the stadium badge if the request fails.
 *
 * @example
 * // Called during init to fetch static metadata:
 * await loadStadium();
 */
async function loadStadium() {
  try {
    const res = await fetch(API_BASE_URL + "/api/stadium");
    if (!res.ok) throw new Error("stadium metadata unavailable");
    const data = await res.json();
    window.__stadium = data;    // cache for re-localization on language change
    window.__intents = data.intents;
    renderLocationOptions();
    refreshIntentOptions(data.intents);
    const s = data.stadium;
    const metaEl = $("stadium-meta");
    if (metaEl) metaEl.textContent = `${s.name}`;
  } catch (err) {
    const metaEl = $("stadium-meta");
    if (metaEl) metaEl.textContent = "";
    renderError(t(STR).reqFailed);
  }
}

/**
 * Populate a `<select>` element with option elements from a list of value/label pairs.
 *
 * Clears all existing options before inserting the new ones so this function
 * is safe to call repeatedly during language switches.
 *
 * @param {HTMLSelectElement} select - The `<select>` element to populate.
 * @param {Array.<{value: string, label: string}>} pairs - Array of `{value, label}` objects
 *   where `value` is the option's `value` attribute and `label` is the
 *   visible text content.
 * @returns {void}
 * @throws {void} Does not throw.
 *
 * @example
 * const select = $("destination_intent");
 * populateSelect(select, [{value: "restroom", label: "Restroom"}, {value: "gate", label: "Entry Gate"}]);
 */
function populateSelect(select, pairs) {
  select.innerHTML = "";
  for (const [value, label] of pairs) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    select.appendChild(opt);
  }
}

/**
 * Re-render the destination intent `<select>` options for the current language.
 *
 * Preserves the user's previously selected value after re-populating so that
 * switching languages does not reset the selection.
 *
 * @param {string[]} intents - Array of intent key strings as returned by
 *   the `/api/stadium` endpoint (e.g. `["restroom", "gate", "seat", ...]`).
 * @returns {void}
 *
 * @example
 * refreshIntentOptions(["restroom", "gate", "seat"]);
 */
function refreshIntentOptions(intents) {
  const labels = INTENT_LABELS[currentLang] || INTENT_LABELS.en;
  const select = $("destination_intent");
  const previous = select.value;
  populateSelect(select, intents.map((i) => [i, labels[i] || i]));
  if (previous) select.value = previous;
}

/**
 * Re-render the current location `<select>` options for the current language.
 *
 * Uses the cached `window.__stadium.zones` array (set by `loadStadium`).
 * Preserves the user's previously selected value after re-populating.
 *
 * @returns {void}
 *
 * @example
 * renderLocationOptions();
 */
function renderLocationOptions() {
  const data = window.__stadium;
  if (!data) return;
  const select = $("current_location");
  const previous = select.value;
  populateSelect(
    select,
    data.zones.map((z) => [z.id, (z.name && (z.name[currentLang] || z.name.en)) || z.id])
  );
  if (previous) select.value = previous;
}

// ---------------------------------------------------------------------------
// Language + accessibility theme
// ---------------------------------------------------------------------------

/**
 * Switch the UI to the specified language and re-render all dynamic content.
 *
 * Updates the `lang` attribute on `<html>` for screen-reader compatibility,
 * replaces all `[data-i18n]` element text content with the new language
 * strings, and re-renders the location and intent dropdowns with localized
 * option labels.
 *
 * @param {string} lang - ISO 639-1 language code to switch to
 *   (`'en'`, `'es'`, or `'fr'`). Falls back to `'en'` for unknown codes.
 * @returns {void}
 *
 * @example
 * applyLanguage("es"); // Switches the entire UI to Spanish
 */
function applyLanguage(lang) {
  currentLang = lang in I18N ? lang : "en";
  document.documentElement.lang = currentLang;  // update <html lang> for a11y
  $("language").value = currentLang;
  const dict = I18N[currentLang];
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (dict[key]) el.textContent = dict[key];
  });
  if (window.__intents) refreshIntentOptions(window.__intents);
  renderLocationOptions();
}

/**
 * Toggle the high-contrast accessibility theme on the `<body>` element.
 *
 * Flips the `aria-pressed` state on the toggle button and adds/removes the
 * `hi-vis` CSS class from `<body>`. Also synchronizes the `visual`
 * accessibility checkbox to match the high-contrast state, so the backend
 * receives the correct accessibility mode when the form is submitted.
 *
 * @returns {void}
 *
 * @example
 * // Bound to the contrast toggle button click event:
 * toggleContrast();
 */
function toggleContrast() {
  const btn = $("contrast-toggle");
  const on = btn.getAttribute("aria-pressed") !== "true";
  btn.setAttribute("aria-pressed", String(on));
  document.body.classList.toggle("hi-vis", on);
  // Mirror the visual accessibility checkbox so the backend sees the correct mode.
  const visual = document.querySelector('input[name="need"][value="visual"]');
  if (visual) visual.checked = on;
}

// ---------------------------------------------------------------------------
// Submit state management
// ---------------------------------------------------------------------------

/**
 * Set or clear the loading state on the submit button.
 *
 * Disables the button, hides the icon, and shows the spinner animation
 * during an in-flight API request. Restores all elements to their resting
 * state when `isLoading` is `false`.
 *
 * @param {boolean} isLoading - `true` to enter the loading state; `false`
 *   to restore the button to its default interactive state.
 * @returns {void}
 *
 * @example
 * setLoading(true); // Spinners active, button disabled
 * await fetch("/api/assist", ...);
 * setLoading(false); // Restored
 */
function setLoading(isLoading) {
  const btn     = $("submit-btn");
  const icon    = $("btn-icon");
  const text    = $("btn-text");
  const spinner = $("btn-spinner");

  if (isLoading) {
    btn.disabled = true;
    btn.classList.add("loading");
    if (icon)    icon.hidden    = true;
    if (spinner) spinner.hidden = false;
    if (text)    text.textContent = t(STR).findingRoute;
  } else {
    btn.disabled = false;
    btn.classList.remove("loading");
    if (icon)    icon.hidden    = false;
    if (spinner) spinner.hidden = true;
    if (text) {
      const dict = I18N[currentLang] || I18N.en;
      text.textContent = dict.getHelp;
    }
  }
}

// ---------------------------------------------------------------------------
// Data collection
// ---------------------------------------------------------------------------

/**
 * Collect all current form field values into the request payload object.
 *
 * Reads the current location, destination intent, checked accessibility
 * needs, ticket section, minutes to kickoff, and optional question from
 * the form DOM elements. Omits optional fields when empty.
 *
 * @returns {{
 *   language: string,
 *   current_location: string,
 *   destination_intent: string,
 *   accessibility_needs: string[],
 *   minutes_to_kickoff: number,
 *   ticket_section?: string,
 *   question?: string
 * }} The JSON-serializable payload ready to POST to `/api/assist`.
 * @throws {void} Does not throw.
 *
 * @example
 * const payload = collectContext();
 * console.log(payload.language); // "en"
 */
function collectContext() {
  const needs = Array.from(document.querySelectorAll('input[name="need"]:checked')).map(
    (el) => el.value
  );
  const ticket = $("ticket_section").value.trim();
  const question = $("question").value.trim();
  const payload = {
    language: $("language").value,
    current_location: $("current_location").value,
    destination_intent: $("destination_intent").value,
    accessibility_needs: needs.length ? needs : ["none"],
    minutes_to_kickoff: parseInt($("minutes_to_kickoff").value, 10),
  };
  if (ticket) payload.ticket_section = ticket;
  if (question) payload.question = question;
  return payload;
}

// ---------------------------------------------------------------------------
// Form submission
// ---------------------------------------------------------------------------

/**
 * Handle form submission: POST the context to the backend and render the result.
 *
 * Prevents the default browser form submission, sets the ARIA busy state and
 * loading UI, then POSTs the collected context to `{API_BASE_URL}/api/assist`.
 * Handles HTTP 422 (invalid input), 429 (rate limited), and other error
 * statuses with localized error messages. On success, passes the response
 * JSON to `renderResult`.
 *
 * @async
 * @param {SubmitEvent} event - The form submit event to prevent default on.
 * @returns {Promise<void>} Resolves when the result or error has been rendered.
 *
 * @example
 * // Bound to the form submit event:
 * form.addEventListener("submit", onSubmit);
 */
async function onSubmit(event) {
  event.preventDefault();
  const result = $("result");
  result.setAttribute("aria-busy", "true");
  setLoading(true);
  // Hide the empty-state placeholder on first submission.
  const emptyState = $("empty-state");
  if (emptyState) emptyState.hidden = true;

  try {
    const res = await fetch(API_BASE_URL + "/api/assist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectContext()),
    });
    if (res.status === 422) return renderError(t(STR).invalid);
    if (res.status === 429) return renderError(t(STR).rateLimited);
    if (!res.ok) return renderError(t(STR).reqFailed);
    renderResult(await res.json());
  } catch (err) {
    renderError(t(STR).reqFailed);
  } finally {
    result.setAttribute("aria-busy", "false");
    setLoading(false);
  }
}

// ---------------------------------------------------------------------------
// Result rendering
// ---------------------------------------------------------------------------

/**
 * Render the full API response into the result panel.
 *
 * Builds and inserts DOM elements for: the AI answer paragraph, facility and
 * crowd metadata badges, the crowd level panel with pulsing dot indicator,
 * urgency and alternatives notices, and the numbered route steps list.
 * All elements are appended to a container with a CSS entry animation.
 *
 * @param {{
 *   answer: string,
 *   facility: {name: string, accessible: boolean},
 *   crowd_level: 'low'|'medium'|'high',
 *   accessibility_mode: string,
 *   urgency: string|null,
 *   alternatives_note: string|null,
 *   route_steps: Array.<{
 *     order: number,
 *     means: string,
 *     step_free: boolean,
 *     instruction: string
 *   }>
 * }} data - The deserialized JSON response from `POST /api/assist`.
 * @returns {void}
 *
/**
 * Build and return the facility, crowd, and accessibility metadata badge grid.
 *
 * Creates a `<div class="meta-grid">` containing three or four badge elements:
 * facility name, crowd level (with shape dots for colour-blind users), an
 * optional step-free badge, and the accessibility mode badge.
 *
 * @param {{
 *   facility: {name: string, accessible: boolean},
 *   crowd_level: 'low'|'medium'|'high',
 *   accessibility_mode: string
 * }} data - Subset of the API response used by this helper.
 * @param {Object.<string, string>} s - Localized string table for the current language.
 * @returns {HTMLDivElement} The populated `<div class="meta-grid">` element.
 * @throws {void} Does not throw.
 *
 * @example
 * const grid = _buildMetaBadges(data, t(STR));
 * wrap.appendChild(grid);
 */
function _buildMetaBadges(data, s) {
  const grid = document.createElement("div");
  grid.className = "meta-grid";

  const facilityBadge = document.createElement("span");
  facilityBadge.className = "badge";
  facilityBadge.textContent = data.facility.name;
  grid.appendChild(facilityBadge);

  const crowdBadge = document.createElement("span");
  crowdBadge.className = `badge crowd-${data.crowd_level}`;
  const dots = document.createElement("span");
  dots.className = "dots";
  dots.setAttribute("aria-hidden", "true");
  dots.textContent = DOTS[data.crowd_level] || "";
  crowdBadge.appendChild(dots);
  const crowdText = document.createElement("span");
  crowdText.textContent = ` ${s.crowd}: ${s[data.crowd_level]}`;
  crowdBadge.appendChild(crowdText);
  grid.appendChild(crowdBadge);

  if (data.facility.accessible) {
    const accBadge = document.createElement("span");
    accBadge.className = "badge";
    accBadge.style.color = "var(--crowd-low)";
    accBadge.style.background = "var(--crowd-low-bg)";
    accBadge.style.borderColor = COLOR_ACCESSIBLE_BORDER;
    accBadge.textContent = "♿ " + s.accessible;
    grid.appendChild(accBadge);
  }

  const modeBadge = document.createElement("span");
  modeBadge.className = "badge";
  modeBadge.textContent = `${s.mode}: ${s[data.accessibility_mode] || data.accessibility_mode}`;
  grid.appendChild(modeBadge);

  return grid;
}

/**
 * Build and return the animated crowd-level status panel.
 *
 * Creates a `<div class="crowd-panel {level}">` containing a pulsing dot
 * indicator, a label, and shape-based dot text for colour-blind accessibility.
 *
 * @param {{
 *   crowd_level: 'low'|'medium'|'high'
 * }} data - Subset of the API response containing the crowd level.
 * @param {Object.<string, string>} s - Localized string table for the current language.
 * @returns {HTMLDivElement} The populated crowd panel `<div>` element.
 * @throws {void} Does not throw.
 *
 * @example
 * const panel = _buildCrowdPanel(data, t(STR));
 * wrap.appendChild(panel);
 */
function _buildCrowdPanel(data, s) {
  const crowdPanel = document.createElement("div");
  crowdPanel.className = `crowd-panel ${data.crowd_level}`;

  const crowdDot = document.createElement("span");
  crowdDot.className = "crowd-dot";
  crowdDot.setAttribute("aria-hidden", "true");
  crowdPanel.appendChild(crowdDot);

  const crowdLabelEl = document.createElement("span");
  crowdLabelEl.className = "crowd-label";
  crowdLabelEl.textContent = `${s.crowdAt}: ${s[data.crowd_level]}`;
  crowdPanel.appendChild(crowdLabelEl);

  const crowdDotsText = document.createElement("span");
  crowdDotsText.className = "crowd-dots-text";
  crowdDotsText.setAttribute("aria-hidden", "true");
  crowdDotsText.textContent = DOTS[data.crowd_level] || "";
  crowdPanel.appendChild(crowdDotsText);

  return crowdPanel;
}

/**
 * Build and return the numbered route steps ordered list with staggered animations.
 *
 * Creates an `<ol class="route-steps">` element with one `<li>` per step.
 * Each list item contains the step number, instruction text, transit means
 * emoji, and an optional step-free badge. Returns null if there are no steps.
 *
 * @param {{
 *   route_steps: Array.<{
 *     order: number,
 *     means: string,
 *     step_free: boolean,
 *     instruction: string
 *   }>
 * }} data - Subset of the API response containing the route steps array.
 * @param {Object.<string, string>} s - Localized string table for the current language.
 * @returns {HTMLElement|null} A `<div>` containing the heading and `<ol>`, or
 *   `null` if `route_steps` is empty or absent.
 * @throws {void} Does not throw.
 *
 * @example
 * const stepsEl = _buildRouteStepsList(data, t(STR));
 * if (stepsEl) wrap.appendChild(stepsEl);
 */
function _buildRouteStepsList(data, s) {
  if (!data.route_steps || !data.route_steps.length) return null;

  const container = document.createElement("div");

  const heading = document.createElement("p");
  heading.className = "route-heading";
  heading.textContent = s.route;
  container.appendChild(heading);

  const ol = document.createElement("ol");
  ol.className = "route-steps";

  data.route_steps.forEach((step, idx) => {
    const li = document.createElement("li");
    li.style.animationDelay = `${idx * STEP_ANIMATION_DELAY_MS}ms`;

    const numEl = document.createElement("span");
    numEl.className = "step-num";
    numEl.setAttribute("aria-hidden", "true");
    numEl.textContent = step.order || (idx + 1);
    li.appendChild(numEl);

    const body = document.createElement("div");
    body.className = "step-body";

    const instr = document.createElement("p");
    instr.className = "step-instruction";
    instr.textContent = step.instruction;
    body.appendChild(instr);

    const meta = document.createElement("div");
    meta.style.display = "flex";
    meta.style.alignItems = "center";
    meta.style.flexWrap = "wrap";
    meta.style.gap = "0.4rem";
    meta.style.marginTop = "0.2rem";

    const meansEl = document.createElement("span");
    meansEl.className = "step-means";
    meansEl.textContent = (MEANS_EMOJI[step.means] || "➡️") + " " + step.means;
    meta.appendChild(meansEl);

    if (step.step_free) {
      const sfEl = document.createElement("span");
      sfEl.className = "step-sf";
      sfEl.textContent = s.stepFree;
      meta.appendChild(sfEl);
    }

    body.appendChild(meta);
    li.appendChild(body);
    ol.appendChild(li);
  });

  container.appendChild(ol);
  return container;
}

/**
 * Render the full API response into the result panel.
 *
 * Clears the result panel, then delegates construction of each section to
 * the three helper functions: `_buildMetaBadges`, `_buildCrowdPanel`, and
 * `_buildRouteStepsList`. Appends urgency and alternatives notices inline.
 *
 * @param {{
 *   answer: string,
 *   facility: {name: string, accessible: boolean},
 *   crowd_level: 'low'|'medium'|'high',
 *   accessibility_mode: string,
 *   urgency: string|null,
 *   alternatives_note: string|null,
 *   route_steps: Array.<{order: number, means: string, step_free: boolean, instruction: string}>
 * }} data - The deserialized JSON response from `POST /api/assist`.
 * @returns {void}
 * @throws {void} Does not throw.
 *
 * @example
 * renderResult({
 *   answer: "Walk to Gate A.", facility: { name: "Gate A", accessible: true },
 *   crowd_level: "low", accessibility_mode: "standard", route_steps: []
 * });
 */
function renderResult(data) {
  const s = STR[currentLang] || STR.en;
  const result = $("result");
  result.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.className = "result-enter";
  result.appendChild(wrap);

  const answer = document.createElement("p");
  answer.className = "answer";
  answer.textContent = data.answer;
  wrap.appendChild(answer);

  wrap.appendChild(_buildMetaBadges(data, s));
  wrap.appendChild(_buildCrowdPanel(data, s));

  if (data.urgency) wrap.appendChild(notice("⚡ " + data.urgency, true));
  if (data.alternatives_note) wrap.appendChild(notice("ℹ️ " + data.alternatives_note, false));

  const stepsEl = _buildRouteStepsList(data, s);
  if (stepsEl) wrap.appendChild(stepsEl);
}

// ---------------------------------------------------------------------------
// Notice helper
// ---------------------------------------------------------------------------

/**
 * Create a styled notice element for urgency or alternatives information.
 *
 * Returns a `<div>` with the appropriate CSS class for either an urgent
 * banner (yellow, bold) or an informational note (blue, normal weight).
 *
 * @param {string} text - The localized message text to display.
 * @param {boolean} urgent - If `true`, applies the `urgent` CSS class for
 *   the high-visibility warning style; otherwise uses the default info style.
 * @returns {HTMLDivElement} The configured notice `<div>` element.
 *
 * @example
 * const urgentNotice = notice("Kickoff is approaching!", true);
 * container.appendChild(urgentNotice);
 */
function notice(text, urgent) {
  const div = document.createElement("div");
  div.className = "notice" + (urgent ? " urgent" : "");
  div.textContent = text;
  return div;
}

// ---------------------------------------------------------------------------
// Error display
// ---------------------------------------------------------------------------

/**
 * Render a localized error message in the result panel.
 *
 * Clears any previous result content and inserts a single `<p>` element
 * with `role="alert"` so screen readers announce the error immediately.
 *
 * @param {string} message - The localized error string to display. A ⚠️
 *   emoji is prepended automatically.
 * @returns {void}
 *
 * @example
 * renderError("Network disconnected. Please try again.");
 */
function renderError(message) {
  const result = $("result");
  result.innerHTML = "";
  const p = document.createElement("p");
  p.className = "error";
  p.setAttribute("role", "alert");
  p.textContent = "⚠️ " + message;
  result.appendChild(p);
}

// ---------------------------------------------------------------------------
// Bootstrap on DOMContentLoaded
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", init);
