import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.database import engine
from app.rate_limit import limiter
from app.routers import auth, companion, health, telemetry

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("health_companion")

# The schema is owned by Alembic. Run `alembic upgrade head` to create or
# update tables (see alembic/README). Nothing is created implicitly at
# startup, so the running code and the migration history can't drift apart.

app = FastAPI(title="Health Companion API", version="0.2.0")

# --- Rate limiting (SlowAPI) --------------------------------------------------
# The limiter is created in app/rate_limit.py and applied per-endpoint with
# @limiter.limit(...) in the routers. It only needs to be reachable via
# app.state, plus a handler that turns a breach into a clean 429.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --- Request-ID middleware --------------------------------------------------
async def _request_id_dispatch(request: Request, call_next):
    """
    Give every request an id: reuse an inbound X-Request-ID if the caller
    (or an upstream proxy) set one, otherwise mint a short uuid. It is stored
    on request.state for handlers/loggers and echoed back on the response so
    a client can quote it in a bug report.
    """
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Added before CORS so CORS ends up as the OUTERMOST middleware and its
# headers are applied to everything that passes back through the stack.
app.add_middleware(BaseHTTPMiddleware, dispatch=_request_id_dispatch)

# --- CORS: locked to known frontend origins --------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,  # e.g. http://localhost:5173
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)


# --- Global exception handler ---------------------------------------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Last-resort catch for anything not already turned into a response
    (HTTPException, request validation, and rate-limit errors have their own
    handlers). Logs the full traceback server-side; the client only gets an
    opaque message plus the request id to quote.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled error [request_id=%s] %s %s", request_id, request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
        headers={"X-Request-ID": request_id or ""},
    )


# --- Routers --------------------------------------------------------------
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
