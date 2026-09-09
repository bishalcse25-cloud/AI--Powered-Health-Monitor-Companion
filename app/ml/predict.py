"""
ML prediction module.

Design goal: the rest of the backend calls ``predict(features)`` and never
needs to know whether a real trained model is present. Two modes:

  1. TRAINED MODEL - if ``app/ml/model.joblib`` exists, it is loaded once at
     import time with :mod:`joblib` and used for every prediction. It is
     expected to be a scikit-learn classifier (e.g. RandomForest) trained on
     the four features in ``FEATURE_ORDER`` and saved with ``joblib.dump``.

  2. HEURISTIC FALLBACK - if the model file is missing, cannot be loaded, or
     raises at inference time, a transparent weighted-scoring function is used
     instead. This keeps the risk endpoints working from day one, before any
     model has been trained, and keeps them working if the model file later
     goes missing or a joblib/scikit-learn version mismatch breaks loading.

Either way ``predict`` is fast (<10ms) and never raises: a bad model can only
downgrade the service to the heuristic, never 500 the API.

To produce ``model.joblib`` run ``python train_model.py`` from the project
root - it writes the artifact straight to ``app/ml/model.joblib``. The feature
order below is the contract between training and serving and must not change.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("health_companion.ml.predict")

# Contract with train_model.py - order matters, do not reorder.
FEATURE_ORDER = ["heart_rate_bpm", "spo2_percent", "body_temp_c", "sleep_hours"]
RISK_CLASSES = ["LOW", "ELEVATED", "HIGH_ATTENTION"]

MODEL_PATH = Path(__file__).parent / "model.joblib"
MODEL_VERSION_TRAINED = "model-joblib-v1"
MODEL_VERSION_HEURISTIC = "heuristic-v1"


def _load_model() -> Any | None:
    """
    Load the trained model from ``MODEL_PATH`` with joblib.

    Returns ``None`` (and logs why) on any failure - a missing file, joblib
    not installed, a corrupt artifact, or a scikit-learn version mismatch -
    so the caller transparently falls back to the heuristic.
    """
    if not MODEL_PATH.exists():
        logger.info("No trained model at %s; using heuristic fallback", MODEL_PATH)
        return None

    try:
        import joblib

        model = joblib.load(MODEL_PATH)
    except Exception:
        logger.exception("Failed to load %s; using heuristic fallback", MODEL_PATH)
        return None

    logger.info("Loaded trained model from %s", MODEL_PATH)
    return model


# Loaded once at import time. Kept module-global so a process handles the disk
# read exactly once, not per request.
_MODEL = _load_model()


def model_is_loaded() -> bool:
    """True if a trained joblib model is active (useful for /health probes)."""
    return _MODEL is not None


def _feature_row(features: dict[str, Any]) -> list[list[float]]:
    """Single-row 2D input in the fixed FEATURE_ORDER; missing vitals -> 0.0."""
    return [[float(features.get(name) or 0.0) for name in FEATURE_ORDER]]


def _predict_with_model(features: dict[str, Any]) -> dict[str, Any] | None:
    """
    Run the trained model. Returns ``None`` on any inference error so the
    caller can fall back to the heuristic instead of surfacing a 500.
    """
    if _MODEL is None:
        return None

    try:
        proba = _MODEL.predict_proba(_feature_row(features))[0]
        classes = [str(c) for c in _MODEL.classes_]
        probabilities = {cls: round(float(p), 3) for cls, p in zip(classes, proba)}
        level = max(probabilities, key=probabilities.get)
        score = probabilities.get("HIGH_ATTENTION", max(probabilities.values()))
        return {
            "risk_level": level,
            "risk_score": float(score),
            "probabilities": probabilities,
            "ml_available": True,
            "model_version": MODEL_VERSION_TRAINED,
        }
    except Exception:
        logger.exception("Trained model inference failed; using heuristic fallback")
        return None


def _heuristic_score(
    features: dict[str, Any], baseline: dict[str, float]
) -> tuple[float, dict[str, float], str]:
    """
    Transparent, explainable weighted score in [0, 1]. Each vital adds points
    the further it drifts from a normal resting range and from the user's own
    baseline. Intentionally simple - a safety net, not a diagnostic tool.
    """
    score = 0.0

    hr = features.get("heart_rate_bpm")
    if hr is not None:
        if hr > 100 or hr < 50:
            score += min(abs(hr - 75) / 100, 0.3)
        avg_hr = baseline.get("avg_hr")
        if avg_hr:
            score += min(abs(hr - avg_hr) / avg_hr, 0.2)

    spo2 = features.get("spo2_percent")
    if spo2 is not None and spo2 < 95:
        score += min((95 - spo2) / 15, 0.3)

    temp = features.get("body_temp_c")
    if temp is not None and (temp > 37.8 or temp < 36.0):
        score += min(abs(temp - 37.0) / 5, 0.2)

    sleep = features.get("sleep_hours")
    if sleep is not None and sleep < 5:
        score += min((5 - sleep) / 10, 0.1)

    score = max(0.0, min(1.0, score))

    if score < 0.3:
        level = "LOW"
    elif score < 0.65:
        level = "ELEVATED"
    else:
        level = "HIGH_ATTENTION"

    probabilities = {
        "LOW": round(max(0.0, 1 - score - 0.1), 3),
        "ELEVATED": round(max(0.0, 1 - abs(score - 0.5)), 3),
        "HIGH_ATTENTION": round(score, 3),
    }
    # Normalize so probabilities sum to ~1 (kept simple, not a real softmax).
    total = sum(probabilities.values()) or 1.0
    probabilities = {k: round(v / total, 3) for k, v in probabilities.items()}

    return score, probabilities, level


def predict(features: dict[str, Any], baseline: dict[str, float] | None = None) -> dict[str, Any]:
    """
    Main entry point used by ``app/services/ml_engine.py``.

    Args:
        features: normalized health features (see schemas.NormalizedHealthRecord)
        baseline: rolling baseline averages for this user, e.g. {"avg_hr": 72.0}

    Returns a dict shaped like schemas.RiskPredictionResponse (minus the
    safeguard/explanation fields, which the caller merges in separately)::

        {
          "risk_level": "LOW" | "ELEVATED" | "HIGH_ATTENTION",
          "risk_score": float,             # 0.0 - 1.0
          "probabilities": {class: prob},
          "ml_available": bool,            # True only for a trained-model result
          "model_version": str,
          "latency_ms": float,
        }
    """
    baseline = baseline or {}
    start = time.perf_counter()

    result = _predict_with_model(features)
    if result is None:
        score, probabilities, level = _heuristic_score(features, baseline)
        result = {
            "risk_level": level,
            "risk_score": float(score),
            "probabilities": probabilities,
            "ml_available": False,  # heuristic fallback, not a trained model
            "model_version": MODEL_VERSION_HEURISTIC,
        }

    result["latency_ms"] = (time.perf_counter() - start) * 1000
    return result
