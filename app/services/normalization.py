"""
Normalization pipeline: turns a raw TelemetryIngestPayload reading into a
NormalizedHealthRecord that the rest of the system can rely on.

Responsibilities:
  - timestamp alignment: default to "now" (UTC) if the device didn't send one
  - missing-feature handling: record which fields were absent (imputed_fields)
    so the ML layer / frontend can be honest about confidence
"""

from datetime import datetime, timezone

from app.schemas import NormalizedHealthRecord, TelemetryReading, TelemetrySource

_TRACKED_FIELDS = [
    "heart_rate_bpm",
    "spo2_percent",
    "body_temp_c",
    "systolic_bp",
    "diastolic_bp",
    "respiratory_rate",
    "steps",
    "sleep_hours",
    "weight_kg",
]


def normalize_reading(
    user_id: int,
    reading: TelemetryReading,
    source: TelemetrySource,
) -> NormalizedHealthRecord:
    recorded_at = reading.timestamp or datetime.now(timezone.utc)
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)

    imputed: list[str] = []
    values: dict[str, float | int | None] = {}
    for field in _TRACKED_FIELDS:
        value = getattr(reading, field)
        if value is None:
            imputed.append(field)
        values[field] = value

    return NormalizedHealthRecord(
        user_id=user_id,
        recorded_at=recorded_at,
        source=source,
        imputed_fields=imputed,
        **values,
    )
