"""
ML engine facade: the ONE function the rest of the app calls to get a risk
evaluation. It always returns a usable result, even if the ML model is
completely offline - that is the "graceful failover" requirement.

Order of operations:
  1. Run the deterministic safeguard rules (never fails, no external deps).
  2. Try the ML model (app/ml/predict.py). If it raises for any reason,
     log it and continue with an ml_available=False result instead of
     propagating a 500 to the caller.
  3. Combine: final risk level = the HIGHER of (safeguard level, ML level).
     A safeguard can only push risk UP, never mask a real ML alert down.
"""

from __future__ import annotations

import logging

from app.ml.predict import predict as ml_predict
from app.schemas import NormalizedHealthRecord, RiskLevel, RiskPredictionResponse
from app.services.safeguards import evaluate_safeguards

logger = logging.getLogger("health_companion.ml_engine")

_RISK_ORDER = {RiskLevel.low: 0, RiskLevel.elevated: 1, RiskLevel.high_attention: 2}


def evaluate(record: NormalizedHealthRecord, baseline: dict[str, float]) -> RiskPredictionResponse:
    safeguard_level, safeguard_triggered, explanations = evaluate_safeguards(record)

    try:
        ml_result = ml_predict(record.model_dump(), baseline)
    except Exception:
        logger.exception("ML prediction failed; falling back to safeguard-only result")
        ml_result = {
            "risk_level": RiskLevel.low.value,
            "risk_score": 0.0,
            "probabilities": {},
            "ml_available": False,
            "model_version": None,
            "latency_ms": None,
        }

    ml_level = RiskLevel(ml_result["risk_level"])
    final_level = ml_level if _RISK_ORDER[ml_level] >= _RISK_ORDER[safeguard_level] else safeguard_level

    return RiskPredictionResponse(
        risk_level=final_level,
        risk_score=max(ml_result["risk_score"], _RISK_ORDER[safeguard_level] / 2),
        probabilities=ml_result.get("probabilities", {}),
        explanations=explanations,
        ml_available=ml_result.get("ml_available", False),
        model_version=ml_result.get("model_version"),
        safeguard_triggered=safeguard_triggered,
        latency_ms=ml_result.get("latency_ms"),
    )
