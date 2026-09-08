"""
API tests.

Everything runs against an in-memory SQLite database, never Postgres:

  * the ``get_db`` FastAPI dependency is replaced with ``override_get_db``
  * ``app.database.engine`` / ``app.database.SessionLocal`` are monkeypatched
    (the telemetry background task builds its own session from ``SessionLocal``,
    and ``GET /health/db`` uses ``app.main.engine`` directly)

Run:

    pytest -q                       # from the project root
    venv\\Scripts\\python -m pytest -q   # if pytest isn't on PATH (Windows)
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database_module
import app.main as main_module
from app.database import Base, get_db
from app.main import app
from app.models import DeviceReading, HealthEntry, User
from app.security import create_access_token, hash_password

# --- In-memory database -----------------------------------------------------
# StaticPool + check_same_thread=False => a single shared connection that the
# request thread and the background-task threadpool can both use.
test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


def override_get_db():
    """Test replacement for app.database.get_db."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Fixtures -------------------------------------------------------------


@pytest.fixture
def anyio_backend():
    """Run the async tests on asyncio only (not trio)."""
    return "asyncio"


@pytest.fixture(autouse=True)
def db_setup(monkeypatch):
    """Fresh schema per test; redirect every DB entry point at the test engine."""
    monkeypatch.setattr(database_module, "engine", test_engine)
    monkeypatch.setattr(database_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(main_module, "engine", test_engine)

    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
async def client(db_setup):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def auth(db_setup):
    """Create a user directly in the DB and return (user_id, bearer_token)."""
    db = TestingSessionLocal()
    try:
        user = User(
            email="alice@example.com",
            full_name="Alice",
            hashed_password=hash_password("password123"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
    finally:
        db.close()
    return user_id, create_access_token(user_id)


# --- GET /health/db --------------------------------------------------------


@pytest.mark.anyio
async def test_health_db_ok(client):
    resp = await client.get("/health/db")
    assert resp.status_code == 200
    assert resp.json() == {"database": "ok"}


# --- Unauthorized access on telemetry endpoints --------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path, json_body",
    [
        ("/api/v1/telemetry/ingest", {"readings": [{"heart_rate_bpm": 72}]}),
        ("/api/v1/telemetry/simulate", None),
        ("/api/v1/devices/register?name=wristband", None),
    ],
)
async def test_telemetry_endpoints_reject_anonymous(client, path, json_body):
    resp = await client.post(path, json=json_body)
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_ingest_rejects_bad_token(client):
    resp = await client.post(
        "/api/v1/telemetry/ingest",
        headers={"Authorization": "Bearer not-a-real-jwt"},
        json={"readings": [{"heart_rate_bpm": 72}]},
    )
    assert resp.status_code == 401


# --- POST /api/v1/telemetry/ingest with a valid JWT --------------------


@pytest.mark.anyio
async def test_ingest_telemetry_with_valid_jwt(client, auth):
    user_id, token = auth

    resp = await client.post(
        "/api/v1/telemetry/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "user_id": 9999,  # must be ignored in favour of the token's user
            "readings": [
                {
                    "heart_rate_bpm": 78,
                    "spo2_percent": 97,
                    "body_temp_c": 36.7,
                    "sleep_hours": 7.0,
                }
            ],
        },
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 1
    assert body["status"] == "queued_for_processing"

    # ASGITransport awaits BackgroundTasks, so the write path has completed.
    db = TestingSessionLocal()
    try:
        assert db.query(DeviceReading).filter_by(user_id=user_id).count() == 1
        assert db.query(DeviceReading).filter_by(user_id=9999).count() == 0
        assert db.query(HealthEntry).filter_by(user_id=user_id).count() == 1
    finally:
        db.close()
