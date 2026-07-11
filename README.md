# ArenaIQ ⚽

**ArenaIQ — A smart, multilingual, accessible stadium assistant for FIFA World Cup 2026.**

ArenaIQ helps fans navigate a venue, find accessible routes and facilities,
get real-time crowd guidance, and receive help in their language — with every
answer **grounded in verified stadium data** so the AI never invents facilities.

Modelled venue: **MetLife Stadium** (FIFA name *New York New Jersey Stadium*),
host of the 2026 Final. Languages: **English, Spanish & French** (the three
FIFA WC 2026 host-nation languages) — the *entire* response is localized,
including facility and zone names.

> **🌐 Live demo (Google Cloud Run):** `https://<your-cloud-run-url>.a.run.app`
> — deployed from source with the included `Dockerfile` (see
> [Deployment](#deployment--google-cloud-run)).

---

## 1. Chosen vertical & persona

- **Persona:** Fan
- **Vertical:** Navigation + Accessibility + Multilingual Assistance
- **Product:** *ArenaIQ* — a conversational assistant that answers "how do I
  get to X, accessibly, in my language, given how busy it is and how long until
  kickoff?" Every response is a function of the fan's **context**:
  `language`, `current_location`, `destination_intent`, `accessibility_needs`,
  `ticket_section`, `minutes_to_kickoff`, and an optional free-text `question`.

## 2. Approach & logic — *rules before LLM*

The core design principle is **deterministic decisions first, language model
last**:

```
UserContext ─▶ Rules engine (deterministic) ─▶ resolved facts ─▶ LLM (phrasing only) ─▶ answer
              • pick facility        • route steps
              • find route           • crowd level
              • crowd simulation     • accessibility mode
              • urgency / swaps      • urgency / alternatives
```

1. **The rules engine (`context_engine.py`) resolves every fact** — the target
   facility, the route (BFS/Dijkstra over the zone graph), the simulated crowd
   level, the accessibility mode and any urgency/crowd-avoidance swaps — using
   **only the structured context**. No LLM is involved in any decision.
2. **The LLM only phrases/translates** those already-resolved facts into natural
   language in the requested language. It is explicitly forbidden (via a strict,
   delimited system prompt) from inventing facilities or following instructions
   embedded in user text. This **grounding prevents hallucination**.
3. If the fan asks no free-text question, the app **short-circuits** and produces
   the answer from offline EN/ES/FR templates — **no LLM call at all**.

Rules implemented (see `context_engine.py`):

| Rule | Behaviour |
|------|-----------|
| Wheelchair / visual need | Only **accessible** facilities + **step-free** routes (stairs excluded) |
| Visual need | Landmark-based, audio-friendly directions; `screen_reader` mode |
| Hearing need | Emphasises visual signage / sensory room; `captioned` mode |
| `minutes_to_kickoff < 15` (gate/seat) | Adds urgency ("hurry") guidance |
| Target facility crowd = high | Reroutes to the nearest **quieter** equivalent |
| Crowd simulation | Gates/concourses surge near kickoff, relax once in play |

## 3. How it works — setup & run

**Requirements:** Python 3.11+.

```bash
cd ArenaIQ
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

**Environment config** (all optional — copy `.env.example` → `.env`):

| Variable | Purpose | Default |
|----------|---------|---------|
| `GEMINI_API_KEY` | Enables live Gemini phrasing. **Absent → offline MockLLM.** | *(unset)* |
| `GEMINI_MODEL` | Gemini model id | `gemini-1.5-flash` |
| `GEMINI_MAX_OUTPUT_TOKENS` | Output cap (cost/efficiency) | `256` |
| `ALLOWED_ORIGINS` | CORS allow-list (JSON array) | localhost only |
| `RATE_LIMIT_CAPACITY` / `RATE_LIMIT_REFILL_PER_SEC` | Token-bucket limiter | `30` / `0.5` |

> 🔐 The app runs **fully offline without any key**: if `GEMINI_API_KEY` is unset,
> it transparently falls back to a deterministic `MockLLM`, so it never crashes.

**Using the UI:** pick your language, where you are, where you want to go, tick
any accessibility needs, set minutes-to-kickoff, optionally type a question, and
select **Get help**. Toggle **High-visibility / screen-reader mode** for a
high-contrast theme that also enables the visual (screen-reader) path.

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/` | Accessible single-page UI |
| `GET`  | `/health` | `{"status": "ok"}` |
| `POST` | `/api/assist` | Body = `UserContext`; returns answer, route, facility, crowd, mode |
| `GET`  | `/api/stadium` | Zone/facility metadata for the UI |

Interactive API docs are available at `/docs`.

### Deployment — Google Cloud Run

The repo ships a container `Dockerfile` (and `.dockerignore`). The image binds
uvicorn to Cloud Run's `$PORT` (8080) on `0.0.0.0`, and the app runs fully on the
offline `MockLLM` fallback, so **no secrets are required** to deploy.

Deploy straight from source (Cloud Build reads the `Dockerfile`):

```bash
# In Google Cloud Shell (or any authenticated gcloud), from the repo root:
gcloud run deploy smart-stadium \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

The command prints the public **Service URL** (e.g.
`https://Arena-Iq-XXXXXXXX-uc.a.run.app`). Verify with:

```bash
curl https://<service-url>/health      # -> {"status":"ok"}
```

Optional — enable live Gemini phrasing (otherwise MockLLM is used):

```bash
gcloud run services update smart-stadium --region us-central1 \
  --set-env-vars GEMINI_API_KEY=YOUR_KEY   # prefer Secret Manager in production
```

Because the UI is served same-origin from the Cloud Run URL, no CORS changes are
needed. To build/run the container locally instead:

```bash
docker build -t arenaiq . && docker run -p 8080:8080 arenaiq
```

## 4. Assumptions

- Stadium map, facilities and base crowd levels are **illustrative fixture data**
  (`app/data/*.json`), not official MetLife/FIFA data.
- Crowd levels are **simulated** from `minutes_to_kickoff`, not a live feed.
- A **single** stadium is modelled.
- Facility/zone names and landmarks are translated in the JSON fixtures (EN/ES/FR),
  so the whole response is localized even offline; with a real Gemini key the model
  rephrases these same grounded facts more naturally.
- The Gemini key is **optional**; the offline MockLLM covers development & tests.

## 5. Quality attributes

### 🔐 Security
- **No secrets in code.** The API key is read from the environment only;
  `.env` is git-ignored and only `.env.example` is committed. Missing key →
  graceful `MockLLM` fallback.
- **Strict input validation** (Pydantic v2): enums for language/needs/intent,
  bounded numbers, length/pattern-limited strings, **unknown zone ids rejected**,
  and unknown request fields forbidden.
- **Prompt-injection defense:** free text is sanitized (control chars stripped,
  length-capped), wrapped in a clearly delimited `<user_question>` block, and the
  model is instructed to treat it as data only. Crucially, **the decision is
  computed before and independently of the question**, so injection can never
  change routing or facts (proven by `test_security.py`).
- **Security headers** on every response: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and a restrictive CSP.
- **Restrictive CORS** (explicit allow-list) and an in-memory **per-IP
  token-bucket rate limiter** on `/api/assist` (`429` + `Retry-After`).
- **Privacy-safe logging:** only zone ids / intents / outcomes — never the API
  key or the raw free-text question.

### ⚡ Efficiency
- JSON fixtures are parsed **once** at startup (`lru_cache` singleton).
- **Short-circuit:** rule-only queries (and `/health`) skip the LLM entirely.
- Phrasing is memoized with `lru_cache` keyed on a hashable context.
- Endpoints are **async**; the (optional) blocking Gemini call runs in a thread.
- Gemini is capped with a low `max_output_tokens`.

### ♿ Accessibility — WCAG 2.1 AA
- Semantic landmarks (`header`/`nav`/`main`/`footer`), a single `<h1>`, logical
  headings, and a **skip-to-content** link.
- Every control has an associated `<label>`; checkbox groups use `fieldset`/
  `legend`; the assistant output uses `aria-live="polite"`.
- Full keyboard operability with visible `:focus-visible` outlines.
- Contrast ≥ 4.5:1; **crowd levels never rely on colour alone** (text + shape
  indicator `●●○`).
- `<html lang>` is set and **updated to match the selected language** (en/es/fr),
  and the form controls + dropdown option labels re-localize on language change.
- `prefers-reduced-motion` respected; no motion-only cues.
- A **High-visibility / screen-reader mode** toggle (high-contrast theme + the
  visual accessibility path).

**Automated audit:** an **axe-core 4.10.2** WCAG 2.0/2.1 A + AA scan of the live page
reported **0 violations / 21 checks passed**. The only "needs-review" item was
`color-contrast` on three overlapping elements, manually verified as passing
(white on `#0b5c3f` header = **8.0:1**; body text on white ≈ **15:1** — both above the
4.5:1 AA threshold). A `pytest` check (`tests/test_static.py`) also asserts the key
a11y markers (`lang`, single `<h1>`, `aria-live`, labels, skip link) stay present.

### 🧪 Testing
Run the full, **offline** suite (no network, no API key required):

```bash
pytest            # runs with coverage (see pytest.ini)
```

**78 tests, 100% statement coverage**, across:
- `test_schemas.py` — validation: bad language/need/intent/zone, oversized
  strings, out-of-range numbers, need normalization, question sanitization.
- `test_context_engine.py` — wheelchair → step-free + accessible; visual →
  landmark + screen-reader; hearing → captioned; imminent kickoff → urgency;
  high crowd → quieter alternative; seat resolved from ticket section; defensive
  route-not-found guards.
- `test_api.py` — `/health`, `/`, `/api/assist` happy path + required keys,
  short-circuit `used_llm=False`, French + Spanish localized answers/place names,
  `422` on malformed/unknown zone, `404` guard, `/api/stadium` contents.
- `test_security.py` — prompt injection can't change the decision, missing key →
  MockLLM, rate limit → `429`, rate-limiter internals + LRU eviction, sanitization, headers.
- `test_llm.py` — MockLLM grounding + injection-ignoring; fake-SDK GeminiClient
  success, empty-text/error fallback, factory selection.
- `test_crowd.py`, `test_routing.py`, `test_phrasing.py`, `test_stadium_data.py`,
  `test_static.py` — units for crowd simulation, step-free pathfinding, EN/ES/FR
  phrasing, localized name resolution, and static accessibility markers.

**Lint & types:** `ruff check` and `mypy` both pass clean (config in `pyproject.toml`):

```bash
ruff check app tests    # All checks passed!
mypy                    # Success: no issues found
```

## 6. Architecture

```
                         ┌─────────────────────────────┐
   Browser (a11y UI) ───▶│  FastAPI app (main.py)      │
   index.html/app.js     │  • CORS + security headers  │
                         │  • token-bucket rate limit  │
                         └──────────────┬──────────────┘
                                        │ POST /api/assist (UserContext)
                                        ▼
                         ┌─────────────────────────────┐
                         │  context_engine.py          │  ← deterministic RULES
                         │  ├─ stadium_data (fixtures)  │
                         │  ├─ routing (step-free BFS)  │
                         │  └─ crowd (time simulation)  │
                         └──────────────┬──────────────┘
                                        │ resolved facts (DecisionResult)
                                        ▼
                         ┌─────────────────────────────┐
                         │  llm.py  (phrasing only)     │
                         │  MockLLM (offline) │ Gemini  │───▶ grounded, localized answer
                         │ phrasing.py (EN/ES/FR templates)│
                         └─────────────────────────────┘
```

```
ArenaIQ/
├── app/
│   ├── __init__.py                    # package marker + version
│   ├── main.py                        # FastAPI factory, routes, middleware, static mount
│   ├── config.py                      # pydantic-settings (no committed secrets)
│   ├── logging_conf.py                # privacy-preserving logging
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py                 # Pydantic models, enums, validators
│   ├── services/
│   │   ├── __init__.py
│   │   ├── context_engine.py          # rules → DecisionResult (before any LLM)
│   │   ├── stadium_data.py            # loads JSON fixtures once; graph + lookups
│   │   ├── routing.py                 # Dijkstra with step-free constraint
│   │   ├── crowd.py                   # time-based crowd simulation
│   │   ├── phrasing.py                # EN/ES/FR templated phrasing (lru_cache)
│   │   ├── llm.py                     # LLMClient · MockLLM · GeminiClient · factory
│   │   └── security.py                # input sanitization + token-bucket rate limiter
│   ├── data/
│   │   ├── stadium.json               # zone graph, edges, stadium metadata
│   │   ├── facilities.json            # facilities with localized names & landmarks
│   │   └── crowd.json                 # base crowd levels + simulation config
│   └── static/
│       ├── index.html                 # accessible single-page UI (WCAG 2.1 AA)
│       ├── style.css                  # design tokens, animations, high-contrast mode
│       └── app.js                     # EN/ES/FR i18n, form logic, result rendering
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    # shared fixtures (TestClient, MockLLM, base payload)
│   ├── test_api.py                    # API contract tests (happy path, 422, 404, i18n)
│   ├── test_context_engine.py         # rules engine (wheelchair, visual, hearing, urgency, crowd)
│   ├── test_crowd.py                  # crowd simulation across kickoff windows
│   ├── test_llm.py                    # MockLLM + GeminiClient (fake SDK, fallback)
│   ├── test_phrasing.py               # EN/ES/FR templated answer generation
│   ├── test_routing.py                # Dijkstra: step-free, disconnected, unknown zones
│   ├── test_schemas.py                # Pydantic validation, sanitization, normalization
│   ├── test_security.py               # prompt injection, rate limit, headers, sanitize
│   ├── test_stadium_data.py           # fixture loading, localized() helper
│   └── test_static.py                 # WCAG HTML markers (lang, h1, aria-live, labels)
├── .env.example                       # config template (GEMINI_API_KEY left blank)
├── .gitignore                         # excludes .env, __pycache__, .venv, coverage
├── .dockerignore
├── Dockerfile                         # Google Cloud Run container image
├── pyproject.toml                     # ruff lint + mypy type-check config
├── pytest.ini                         # test paths + coverage flags
├── requirements.txt                   # runtime + dev/test dependencies
├── LICENSE                            # MIT
└── README.md
```

## License

MIT — see [LICENSE](LICENSE).
