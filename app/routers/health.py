"""
Pillar 2 + trends: ML risk evaluation and historical trend queries.

- POST /api/v1/health/evaluate   run the ML engine (+ safeguards) on a
                                  reading, or on the user's latest stored entry
- GET  /api/v1/health/trends     7-day / 30-day moving averages + baseline
                                  deviation, for the frontend's trend charts
"""

from __future__ import annotations

import logging
import pickle
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_auth_user, get_current_user
from app.models import HealthEntry, RiskEvaluation, User
from app.schemas import (
    MetricTrend,
    NormalizedHealthRecord,
    RiskLevel,
    RiskPredictionResponse,
    TelemetryReading,
    TelemetrySource,
    TrendsResponse,
    TrendWindow,
)
from app.services import baseline as baseline_service
from app.services.ml_engine import evaluate as ml_evaluate
from app.services.normalization import normalize_reading
from app.services.safeguards import evaluate_safeguards

logger = logging.getLogger("health_companion.health_router")

router = APIRouter(prefix="/api/v1/health", tags=["health"])

# --- Trained model for POST /evaluate ---------------------------------------
# train_model.py writes model.pkl to the project root. We load it once at
# import time and use it for /evaluate in place of the heuristic fallback in
# app/ml/predict.py. If the file is missing or fails to load / infer, we fall
# back to the shared ml_engine (heuristic) so the endpoint never 500s.
_EVALUATE_MODEL_PATH = Path(__file__).resolve().parents[2] / "model.pkl"
# Feature order is fixed by train_model.py and must not change.
_EVALUATE_MODEL_FEATURES = ["heart_rate_bpm", "spo2_percent", "body_temp_c", "sleep_hours"]
_EVALUATE_MODEL_VERSION = "model-pkl-v1"
_RISK_ORDER = {RiskLevel.low: 0, RiskLevel.elevated: 1, RiskLevel.high_attention: 2}


def _load_evaluate_model():
    try:
        with _EVALUATE_MODEL_PATH.open("rb") as fh:
            return pickle.load(fh)
    except FileNotFoundError:
        logger.info("%s not found; /evaluate will use the heuristic fallback", _EVALUATE_MODEL_PATH)
    except Exception:
        logger.exception("Failed to load %s; /evaluate will use the heuristic fallback", _EVALUATE_MODEL_PATH)
    return None


_EVALUATE_MODEL = _load_evaluate_model()


def _evaluate_with_model(
    record: NormalizedHealthRecord, baseline: dict[str, float]
) -> RiskPredictionResponse | None:
    """
    Run model.pkl on a normalized reading and combine it with the deterministic
    safeguards exactly the way app/services/ml_engine.evaluate does (a safeguard
    can only push the risk level UP). Returns None when the model is unavailable
    or errors, so the caller falls back to the shared heuristic engine.
    """
    if _EVALUATE_MODEL is None:
        return None

    start = time.perf_counter()
    try:
        row = [[float(getattr(record, f) or 0) for f in _EVALUATE_MODEL_FEATURES]]
        proba = _EVALUATE_MODEL.predict_proba(row)[0]
        classes = list(_EVALUATE_MODEL.classes_)
        probabilities = {str(cls): round(float(p), 3) for cls, p in zip(classes, proba)}
        ml_level = RiskLevel(max(probabilities, key=probabilities.get))
        ml_score = probabilities.get(RiskLevel.high_attention.value, max(probabilities.values()))
    except Exception:
        logger.exception("model.pkl inference failed; /evaluate falling back to heuristic engine")
        return None

    safeguard_level, safeguard_triggered, explanations = evaluate_safeguards(record)
    final_level = (
        ml_level if _RISK_ORDER[ml_level] >= _RISK_ORDER[safeguard_level] else safeguard_level
    )

    return RiskPredictionResponse(
        risk_level=final_level,
        risk_score=max(float(ml_score), _RISK_ORDER[safeguard_level] / 2),
        probabilities=probabilities,
        explanations=explanations,
        ml_available=True,
        model_version=_EVALUATE_MODEL_VERSION,
        safeguard_triggered=safeguard_triggered,
        latency_ms=(time.perf_counter() - start) * 1000,
    )

_TRACKED_METRICS = {
    "heart_rate_bpm": "avg_hr",
    "spo2_percent": "avg_spo2",
    "body_temp_c": "avg_temp",
    "sleep_hours": "avg_sleep",
    "steps": "avg_steps",
}


@router.post("/evaluate", response_model=RiskPredictionResponse)
def evaluate_health(
    reading: TelemetryReading | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_auth_user),
):
    """
    Requires a valid `Authorization: Bearer <token>` (see POST
    /api/v1/auth/login).

    If `reading` is provided in the request body AND has at least one
    vital set, evaluates it directly (useful for "what-if" checks from the
    frontend). Otherwise evaluates the user's most recently stored health
    entry. (An empty body `{}` is treated the same as no body at all -
    every field on TelemetryReading is optional, so `{}` is technically a
    "valid but empty" reading rather than a missing one.)
    """
    has_data = reading is not None and any(
        getattr(reading, f) is not None for f in reading.model_fields if f != "timestamp"
    )
    if has_data:
        normalized = normalize_reading(user.id, reading, TelemetrySource.manual)
        source_entry_id = None
    else:
        latest = (
            db.query(HealthEntry)
            .filter(HealthEntry.user_id == user.id)
            .order_by(HealthEntry.recorded_at.desc())
            .first()
        )
        if latest is None:
            raise HTTPException(status_code=404, detail="No health entries yet for this user")
        normalized = NormalizedHealthRecord(
            user_id=user.id,
            recorded_at=latest.recorded_at,
            source=latest.source,
            heart_rate_bpm=latest.heart_rate_bpm,
            spo2_percent=latest.spo2_percent,
            body_temp_c=latest.body_temp_c,
            systolic_bp=latest.systolic_bp,
            diastolic_bp=latest.diastolic_bp,
            respiratory_rate=latest.respiratory_rate,
            steps=latest.steps,
            sleep_hours=latest.sleep_hours,
            weight_kg=latest.weight_kg,
        )
        source_entry_id = latest.id

    baseline = baseline_service.get_baseline(db, user.id)
    result = _evaluate_with_model(normalized, baseline) or ml_evaluate(normalized, baseline)

    db.add(
        RiskEvaluation(
            user_id=user.id,
            source_entry_id=source_entry_id,
            risk_level=result.risk_level.value,
            risk_score=result.risk_score,
            probabilities=result.probabilities,
            ml_available=result.ml_available,
            ml_model_version=result.model_version,
            safeguard_triggered=result.safeguard_triggered,
            explanations=[e.model_dump() for e in result.explanations],
            baseline_snapshot=baseline,
        )
    )
    db.commit()

    return result


@router.get("/trends", response_model=TrendsResponse)
def get_trends(
    window: TrendWindow = TrendWindow.seven_day,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    days = 7 if window == TrendWindow.seven_day else 30
    since = datetime.now(timezone.utc) - timedelta(days=days)
    baseline = baseline_service.get_baseline(db, user.id, window_days=days)

    latest = (
        db.query(HealthEntry)
        .filter(HealthEntry.user_id == user.id)
        .order_by(HealthEntry.recorded_at.desc())
        .first()
    )

    metrics: list[MetricTrend] = []
    for column_name, baseline_key in _TRACKED_METRICS.items():
        column = getattr(HealthEntry, column_name)
        avg_value, sample_count = (
            db.query(func.avg(column), func.count(column))
            .filter(HealthEntry.user_id == user.id, HealthEntry.recorded_at >= since, column.isnot(None))
            .one()
        )
        avg_value = round(float(avg_value), 2) if avg_value is not None else None
        latest_value = getattr(latest, column_name, None) if latest else None

        deviation = None
        baseline_avg = baseline.get(baseline_key)
        if avg_value is not None and baseline_avg:
            deviation = round((avg_value - baseline_avg) / baseline_avg * 100, 2)

        metrics.append(
            MetricTrend(
                metric=column_name,
                moving_average=avg_value,
                baseline_deviation_percent=deviation,
                latest_value=latest_value,
                samples=sample_count or 0,
            )
        )

    return TrendsResponse(
        user_id=user.id,
        window=window,
        generated_at=datetime.now(timezone.utc),
        metrics=metrics,
    )
