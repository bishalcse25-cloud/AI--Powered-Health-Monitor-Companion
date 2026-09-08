from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.routers import auth, companion, health, telemetry

settings = get_settings()

# The schema is owned by Alembic. Run `alembic upgrade head` to create or
# update tables (see alembic/README). Nothing is created implicitly at
# startup, so the running code and the migration history can't drift apart.

app = FastAPI(title="Health Companion API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this once a real frontend origin exists
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(telemetry.router)
app.include_router(health.router)
app.include_router(companion.router)


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "health-companion",
        "simulator_mode": settings.simulator_mode,
        "ml_enabled": settings.ml_enabled,
        "llm_enabled": settings.llm_enabled and bool(settings.anthropic_api_key),
    }


@app.get("/health/db")
def health_db():
    """Check that the API can talk to the database."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"database": "ok"}


# Serve the single-file frontend. Mounted last so it never shadows an API
# route. `html=True` makes "/app/" resolve to index.html. Visit /app/.
_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/app", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
