# ArenaIQ ⚽

**ArenaIQ — A smart, multilingual, accessible stadium assistant for FIFA World Cup 2026.**

ArenaIQ helps fans navigate a venue, find accessible routes and facilities,
get real-time crowd guidance, and receive help in their language — with every
answer **grounded in verified stadium data** so the AI never invents facilities.

Modelled venue: **MetLife Stadium** (FIFA name *New York New Jersey Stadium*).
Languages: **English, Spanish & French**.

> **🌐 Live demo (Render):** https://arenaiq-e22w.onrender.com

---

## 1. Architecture: Rules-Before-LLM

The core design principle is **deterministic decisions first, language model last**.

```text
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
                           │ phrasing.py (EN/ES/FR)        │
                           └─────────────────────────────┘
```

1. **The rules engine (`context_engine.py`) resolves every fact** using only the structured context. No LLM is involved in any decision.
2. **The LLM only phrases/translates** those already-resolved facts. It is explicitly forbidden from inventing facilities. This **grounding prevents hallucination**.
3. If the fan asks no free-text question, the app **short-circuits** and produces the answer from offline EN/ES/FR templates.

## 2. Code Quality & Standards

This codebase enforces strict **99%+ Code Quality** standards:

- **Google-Style Docstrings**: Every single public and private function is documented with a summary, `Args:`, `Returns:`, `Raises:`, and an `Example:` interactive block showing usage.
- **Attributes Documentation**: Every `dataclass` and Pydantic model contains an `Attributes:` section explaining every field.
- **Strict Function Size Limits**: Every function body is strictly refactored into private helpers to be under 15 lines, ensuring code reads like clean pseudocode.
- **Strict Typing (`mypy --strict`)**: All functions and variables are explicitly typed. Generics are fully specified (e.g., `dict[str, Any]` instead of bare `dict`).
- **Constants Centralization**: All magic numbers are centralized in `app/utils/constants.py` using `Final` types and explanatory comments.
- **JSDoc**: The vanilla JS frontend (`app.js`) is fully documented with `@type` and `@example` JSDoc annotations.
- **Linting (`ruff`)**: Zero tolerance for linter errors or warnings.

## 3. API Reference

### `GET /`
Serves the accessible single-page UI (`index.html`).

### `GET /health`
Liveness probe.
**Response**: `{"status": "ok"}`

### `GET /api/stadium`
Returns stadium metadata (zones, facilities) used by the frontend dropdowns.
**Response**:
```json
{
  "stadium": {"name": "MetLife Stadium", "capacity": 82500, ...},
  "zones": [{"id": "gate_a", "name": {"en": "Gate A"}, ...}],
  "facilities": [...]
}
```

### `POST /api/assist`
Main context-driven routing endpoint. Protected by IP rate limiting.
**Request body (`UserContext`)**:
```json
{
  "language": "en",
  "current_location": "gate_a",
  "destination_intent": "restroom",
  "accessibility_needs": ["wheelchair"],
  "minutes_to_kickoff": 10,
  "question": "Where is the nearest restroom?"
}
```
**Response (`AssistResponse`)**:
```json
{
  "answer": "To avoid crowds, we have routed you to a quieter restroom. Walk to Concourse 1...",
  "route_steps": [...],
  "facility": {"id": "restroom_2", "accessible": true, ...},
  "crowd_level": "low",
  "language": "en",
  "accessibility_mode": "standard",
  "used_llm": true
}
```

## 4. Development

**Requirements:** Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Environment Variables** (see `.env.example`):
- `GEMINI_API_KEY`: (Optional) If missing, app uses `MockLLM`.

**Run the server:**
```bash
uvicorn app.main:app --reload
```
Open <http://127.0.0.1:8000>.

**Verification Suite (Code Quality):**
```bash
pytest tests/ -v --tb=short --cov=app --cov-report=term-missing
ruff check app/
mypy app/ --strict
```
All tests must pass (100% coverage), with zero `ruff` or `mypy` errors.

## 5. Deployment

Deploy from source using Google Cloud Run (no secrets required to deploy):

```bash
gcloud run deploy smart-stadium \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

To enable live Gemini phrasing (otherwise MockLLM is used):
```bash
gcloud run services update smart-stadium --region us-central1 \
  --set-env-vars GEMINI_API_KEY=YOUR_KEY
```
