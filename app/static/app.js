"use strict";

const API_BASE_URL = "RENDER_BACKEND_URL_HERE";

// ---------------------------------------------------------------------------
// Localization (EN/ES/FR). UI chrome uses [data-i18n]; dynamic strings use STR[].
// ---------------------------------------------------------------------------
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

// Shape-based crowd dots (never rely on colour alone — accessibility)
const DOTS = { low: "●○○", medium: "●●○", high: "●●●" };

// Crowd emojis for the panel
const CROWD_EMOJI = { low: "🟢", medium: "🟡", high: "🔴" };

// ---------------------------------------------------------------------------
// State + helpers
// ---------------------------------------------------------------------------
let currentLang = "en";
const $ = (id) => document.getElementById(id);

function t(dict) {
  return dict[currentLang] || dict.en;
}

// ---------------------------------------------------------------------------
// Bootstrapping
// ---------------------------------------------------------------------------
async function init() {
  applyLanguage("en");
  bindEvents();
  await loadStadium();
}

function bindEvents() {
  $("language").addEventListener("change", (e) => applyLanguage(e.target.value));
  $("contrast-toggle").addEventListener("click", toggleContrast);
  $("assist-form").addEventListener("submit", onSubmit);

  // Character counter for question textarea
  const q = $("question");
  const counter = $("char-count");
  if (q && counter) {
    q.addEventListener("input", () => { counter.textContent = q.value.length; });
  }

  // +/- buttons for minutes_to_kickoff
  const mInput = $("minutes_to_kickoff");
  const btnMinus = $("minutes-minus");
  const btnPlus  = $("minutes-plus");
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

async function loadStadium() {
  try {
    const res = await fetch(API_BASE_URL + "/api/stadium");
    if (!res.ok) throw new Error("stadium metadata unavailable");
    const data = await res.json();
    window.__stadium = data;   // keep zone/facility maps for re-localization
    window.__intents = data.intents;
    renderLocationOptions();
    refreshIntentOptions(data.intents);
    const s = data.stadium;
    // Update both header stadium-meta badge and footer
    const metaEl = $("stadium-meta");
    if (metaEl) metaEl.textContent = `${s.name}`;
  } catch (err) {
    const metaEl = $("stadium-meta");
    if (metaEl) metaEl.textContent = "";
    renderError(t(STR).reqFailed);
  }
}

function populateSelect(select, pairs) {
  select.innerHTML = "";
  for (const [value, label] of pairs) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    select.appendChild(opt);
  }
}

function refreshIntentOptions(intents) {
  const labels = INTENT_LABELS[currentLang] || INTENT_LABELS.en;
  const select = $("destination_intent");
  const previous = select.value;
  populateSelect(select, intents.map((i) => [i, labels[i] || i]));
  if (previous) select.value = previous;
}

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
// Language + theme
// ---------------------------------------------------------------------------
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

function toggleContrast() {
  const btn = $("contrast-toggle");
  const on = btn.getAttribute("aria-pressed") !== "true";
  btn.setAttribute("aria-pressed", String(on));
  document.body.classList.toggle("hi-vis", on);
  // High-visibility mode maps to the visual accessibility path server-side.
  const visual = document.querySelector('input[name="need"][value="visual"]');
  if (visual) visual.checked = on;
}

// ---------------------------------------------------------------------------
// Submit state helpers
// ---------------------------------------------------------------------------
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
// Submit handler
// ---------------------------------------------------------------------------
async function onSubmit(event) {
  event.preventDefault();
  const result = $("result");
  result.setAttribute("aria-busy", "true");
  setLoading(true);
  // Hide empty state on first submit
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
function renderResult(data) {
  const s = STR[currentLang] || STR.en;
  const result = $("result");
  result.innerHTML = "";

  // Wrap everything in an animated container
  const wrap = document.createElement("div");
  wrap.className = "result-enter";
  result.appendChild(wrap);

  // --- AI answer text ---
  const answer = document.createElement("p");
  answer.className = "answer";
  answer.textContent = data.answer;
  wrap.appendChild(answer);

  // --- Facility + crowd + accessibility badges ---
  const grid = document.createElement("div");
  grid.className = "meta-grid";

  // Facility name badge
  const facilityBadge = document.createElement("span");
  facilityBadge.className = "badge";
  facilityBadge.textContent = data.facility.name;
  grid.appendChild(facilityBadge);

  // Crowd badge with shape indicator
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

  // Accessibility badge
  if (data.facility.accessible) {
    const accBadge = document.createElement("span");
    accBadge.className = "badge";
    accBadge.style.color = "var(--crowd-low)";
    accBadge.style.background = "var(--crowd-low-bg)";
    accBadge.style.borderColor = "#A7F3D0";
    accBadge.textContent = "♿ " + s.accessible;
    grid.appendChild(accBadge);
  }

  // Mode badge
  const modeBadge = document.createElement("span");
  modeBadge.className = "badge";
  modeBadge.textContent = `${s.mode}: ${s[data.accessibility_mode] || data.accessibility_mode}`;
  grid.appendChild(modeBadge);

  wrap.appendChild(grid);

  // --- Crowd level panel ---
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
  wrap.appendChild(crowdPanel);

  // --- Urgency banner ---
  if (data.urgency) wrap.appendChild(notice("⚡ " + data.urgency, true));

  // --- Alternatives note ---
  if (data.alternatives_note) wrap.appendChild(notice("ℹ️ " + data.alternatives_note, false));

  // --- Route steps ---
  if (data.route_steps && data.route_steps.length) {
    const heading = document.createElement("p");
    heading.className = "route-heading";
    heading.textContent = s.route;
    wrap.appendChild(heading);

    const ol = document.createElement("ol");
    ol.className = "route-steps";

    data.route_steps.forEach((step, idx) => {
      const li = document.createElement("li");
      // Stagger animation
      li.style.animationDelay = `${idx * 80}ms`;

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
      // Map means to emoji
      const meansEmoji = {
        walk: "🚶", ramp: "♿", elevator: "🛗", stairs: "🪜"
      };
      meansEl.textContent = (meansEmoji[step.means] || "➡️") + " " + step.means;
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

    wrap.appendChild(ol);
  }
}

// ---------------------------------------------------------------------------
// Notice (urgency / alternatives)
// ---------------------------------------------------------------------------
function notice(text, urgent) {
  const div = document.createElement("div");
  div.className = "notice" + (urgent ? " urgent" : "");
  div.textContent = text;
  return div;
}

// ---------------------------------------------------------------------------
// Error display
// ---------------------------------------------------------------------------
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
