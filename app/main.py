from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import Base, engine
from app import models  # noqa: F401 - import registers all tables on Base
from app.routers import auth, companion, health, telemetry

settings = get_settings()

# Creates any tables that don't exist yet. Safe to run every startup - it
# never touches tables that already exist. (A later phase replaces this
# with proper Alembic migrations for real schema changes.)
Base.metadata.create_all(bind=engine)

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
