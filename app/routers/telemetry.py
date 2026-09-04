"""
Pillar 1: IoT Hardware.

- POST /api/v1/devices/register   register a device, get back a secret token
- POST /api/v1/telemetry/ingest   high-throughput, non-blocking ingestion
- POST /api/v1/telemetry/simulate generate + ingest synthetic readings (mock mode)
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import authenticate_device, get_current_user
from app.models import Device, DeviceReading, HealthEntry, User
from app.schemas import TelemetryIngestPayload, TelemetryReading, TelemetrySource
from app.services import baseline
from app.services.normalization import normalize_reading
from app.services.simulator import generate_reading

router = APIRouter(prefix="/api/v1", tags=["telemetry"])
settings = get_settings()


# ---------------------------------------------------------------------------
# Device registration
# ---------------------------------------------------------------------------

@router.post("/devices/register", status_code=status.HTTP_201_CREATED)
def register_device(
    name: str,
    device_type: str = "esp32",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    token = secrets.token_hex(16)
    device = Device(user_id=user.id, name=name, device_type=device_type, secret_token=token)
    db.add(device)
    db.commit()
    db.refresh(device)
    return {"device_id": device.id, "name": device.name, "device_token": token}


# ---------------------------------------------------------------------------
# Ingestion (the non-blocking path)
# ---------------------------------------------------------------------------

def _process_readings_in_background(
    readings: list[TelemetryReading],
    user_id: int,
    source: TelemetrySource,
    device_id: int | None,
    reading_id_map: list[int],
) -> None:
    """
    Runs AFTER the HTTP response has already been sent (FastAPI BackgroundTasks).
    Owns its own short-lived DB session since the request's session is closed
    by the time this runs.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        for reading, device_reading_id in zip(readings, reading_id_map):
            normalized = normalize_reading(user_id, reading, source)
            entry = HealthEntry(
                user_id=user_id,
                recorded_at=normalized.recorded_at,
                source=source.value,
                device_id=device_id,
                heart_rate_bpm=normalized.heart_rate_bpm,
                spo2_percent=normalized.spo2_percent,
                body_temp_c=normalized.body_temp_c,
                systolic_bp=normalized.systolic_bp,
                diastolic_bp=normalized.diastolic_bp,
                respiratory_rate=normalized.respiratory_rate,
                steps=normalized.steps,
                sleep_hours=normalized.sleep_hours,
                weight_kg=normalized.weight_kg,
            )
            db.add(entry)
            db.flush()  # get entry.id without a full commit yet

            device_reading = db.get(DeviceReading, device_reading_id)
            if device_reading is not None:
                device_reading.processed = True
                device_reading.health_entry_id = entry.id

        db.commit()
        baseline.invalidate(user_id)
    finally:
        db.close()


@router.post("/telemetry/ingest", status_code=status.HTTP_202_ACCEPTED)
def ingest_telemetry(
    payload: TelemetryIngestPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Accepts one or many readings, stores the raw payload immediately (fast,
    synchronous - this is the durability guarantee), then does the heavier
    normalization + risk-relevant DB writes in a background task so the
    HTTP response returns immediately. This is what keeps the endpoint
    non-blocking under a high-frequency sensor stream.
    """
    device_id = None
    if payload.source == TelemetrySource.device:
        if not payload.device_token:
            raise HTTPException(status_code=400, detail="device_token is required when source='device'")
        device = authenticate_device(db, payload.device_token)
        if device.user_id != payload.user_id:
            raise HTTPException(status_code=403, detail="Device does not belong to this user")
        device_id = device.id
        device.last_seen_at = datetime.now(timezone.utc)

    reading_id_map: list[int] = []
    for reading in payload.readings:
        device_reading = DeviceReading(
            device_id=device_id,
            user_id=payload.user_id,
            raw_payload=reading.model_dump(mode="json"),
        )
        db.add(device_reading)
        db.flush()
        reading_id_map.append(device_reading.id)
    db.commit()

    background_tasks.add_task(
        _process_readings_in_background,
        payload.readings,
        payload.user_id,
        payload.source,
        device_id,
        reading_id_map,
    )

    return {"accepted": len(payload.readings), "status": "queued_for_processing"}


@router.post("/telemetry/simulate")
def simulate_telemetry(
    background_tasks: BackgroundTasks,
    count: int = 1,
    anomaly: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generates synthetic readings and pushes them through the same ingest path."""
    if not settings.simulator_mode:
        raise HTTPException(status_code=403, detail="Simulator mode is disabled (set SIMULATOR_MODE=true in .env)")

    readings = [generate_reading(anomaly=anomaly) for _ in range(max(1, count))]
    payload = TelemetryIngestPayload(user_id=user.id, source=TelemetrySource.simulator, readings=readings)
    return ingest_telemetry(payload, background_tasks, db)
