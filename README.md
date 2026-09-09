# Health Companion

AI-assisted IoT health monitoring for elderly and physically challenged people.
A wearable (ESP32 + heart-rate / SpO₂ / temperature / accelerometer / GPS
sensors) streams vitals; the backend normalizes them, scores health risk with a
small ML model plus deterministic safety rules, and an LLM companion answers
questions with that context in view.

> **Not a medical device.** Everything here is informational support only. It
> does not diagnose, treat, or replace professional medical care.

---

## Architecture

| Pillar | What it does | Code |
| --- | --- | --- |
| 1. Ingestion | Non-blocking telemetry intake (device token or user JWT), raw payloads stored immediately, normalization done in the background | `app/routers/telemetry.py`, `app/services/normalization.py` |
| 2. Risk engine | Trained `RandomForest` (joblib) with a transparent rule-based fallback, merged with hard safeguard rules that can only push risk **up** | `app/ml/predict.py`, `app/services/ml_engine.py`, `app/services/safeguards.py` |
| 3. AI companion | SSE chat endpoint; injects current risk + baseline + recent trend into the system prompt | `app/routers/companion.py`, `app/services/llm.py` |
| 4. Trends | 7 / 30-day moving averages and baseline deviation for the dashboard | `app/routers/health.py`, `app/services/baseline.py` |

Cross-cutting: JWT auth (`app/security.py`, `app/deps.py`), per-IP rate
limiting, request IDs, locked-down CORS, Alembic-managed schema.

### Frontends

- **`web/`** — the primary frontend: a Vite + React + TypeScript app.
  - **Dashboard** — history charts, ML risk, AI companion chat. Talks to this backend.
  - **Live monitor** — real-time vitals, streaming chart, fall alerts, GPS map.
    Reads the live sensor feed straight from Firebase Realtime Database, and can
    push the current reading back into this backend's pipeline.
  - Installable PWA with an offline app shell.
  - See [`web/README.md`](web/README.md).
- **`frontend/index.html`** — a legacy single-file demo UI, served by the API at
  `/app/` with no build step. Kept for quick demos only.

---

## Prerequisites

- **Python 3.12+** (3.13 in Docker)
- **PostgreSQL 13+** running locally (or use Docker Compose, below)
- **Node.js 20+** — only needed to run `web/`

---

## Backend — local setup

```bash
python -m venv venv
venv\Scripts\activate            # Windows;  source venv/bin/activate on macOS/Linux
pip install -r requirements.txt

copy .env.example .env           # cp on macOS/Linux — then set DB_PASSWORD and JWT_SECRET
```

Generate a JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Create the database and apply migrations:

```bash
createdb health_companion       # or: psql -c "CREATE DATABASE health_companion;"
alembic upgrade head
```

Run the API:

```bash
uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- Legacy demo UI: http://127.0.0.1:8000/app/

### Train the ML model (optional)

The risk engine works out of the box using a transparent heuristic. To use a
trained model instead:

```bash
python train_model.py
```

This writes `app/ml/model.joblib` (synthetic data — not medically validated).
`app/ml/predict.py` loads it automatically on the next start; if the file is
missing or fails to load it silently falls back to the heuristic.

### Tests

```bash
pytest -q
```

In-memory SQLite, no Postgres needed.

---

## Frontend (`web/`) — local setup

```bash
cd web
npm install
npm run dev
```

Opens http://localhost:5173 and proxies `/api` to the backend on port 8000
(`web/vite.config.ts`). Register an account on first load.

---

## Docker (backend + database)

```bash
cp .env.example .env             # set DB_PASSWORD and JWT_SECRET
docker compose up --build
```

API on http://localhost:8000, Postgres on 5432, migrations run automatically on
container start. `web/` is not containerized — run it separately or `npm run
build` and serve `web/dist/` behind your own web server.

---

## Project layout

```
app/
  routers/        auth, telemetry, health (risk + trends), companion
  services/       normalization, baseline, ml_engine, safeguards, llm, simulator
  ml/             predict.py  +  model.joblib (generated)
  models.py       SQLAlchemy tables            schemas.py  Pydantic contracts
alembic/          migrations (schema source of truth)
tests/            API tests (SQLite)
train_model.py    standalone ML training script
web/              React + TS frontend (Dashboard + Live monitor, PWA)
frontend/         legacy single-file demo served at /app/
Dockerfile, docker-compose.yml
```

---

## Environment variables

See [`.env.example`](.env.example) for the full list. Only `DB_PASSWORD` and
`JWT_SECRET` strictly need a value; everything else has a working default.
`ANTHROPIC_API_KEY` is optional — without it the companion returns canned
replies so the app is fully testable offline.
