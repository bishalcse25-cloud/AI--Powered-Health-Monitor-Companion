"""
ML prediction module.

Design goal: the rest of the backend calls `predict(features)` and never
needs to know whether a real trained model is present. Two modes:

  1. TRAINED MODEL - if app/ml/model.joblib exists, load it once (module
     import time) and use it. Intended for a scikit-learn RandomForest /
     XGBoost classifier trained on health features, saved with joblib.

  2. HEURISTIC FALLBACK - if no model file exists (or loading fails), use a
     simple, transparent, weighted-scoring function instead. This keeps
     /api/v1/health/evaluate working from day one, before any model has
     been trained, and keeps working if the model file goes missing later.

Either way this function must be fast (<10ms) - it's a resource
comparison / a handful of arithmetic ops, not a network call.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

MODEL_PATH = Path(__file__).parent / "model.joblib"
MODEL_VERSION_HEURISTIC = "heuristic-v1"

_model = None
_model_load_attempted = False


def _try_load_model():
    """Lazily load a trained model if one has been placed at MODEL_PATH."""
    global _model, _model_load_attempted
    if _model_load_attempted:
        return _model
    _model_load_attempted = True

    if not MODEL_PATH.exists():
        return None

    try:
        import joblib  # optional dependency; only required if a model is present

        _model = joblib.load(MODEL_PATH)
    except Exception:
        # Any failure (missing package, corrupt file, version mismatch) ->
        # fall back to the heuristic. We never let a bad model file crash
        # the API.
        _model = None
    return _model


def _heuristic_score(features: dict[str, Any], baseline: dict[str, float]) -> tuple[float, dict[str, float]]:
    """
    A transparent, explainable weighted score in [0, 1].
    Each vital contributes points the further it drifts from a normal
    resting range and from the user's own baseline. This is intentionally
    simple - it is a safety net, not a diagnostic tool.
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

    return score, probabilities, level  # type: ignore[return-value]


def predict(features: dict[str, Any], baseline: dict[str, float] | None = None) -> dict[str, Any]:
    """
    Main entry point used by app/services/ml_engine.py.

    Args:
        features: normalized health features (see schemas.NormalizedHealthRecord)
        baseline: rolling baseline averages for this user, e.g. {"avg_hr": 72.0}

    Returns a dict shaped like schemas.RiskPredictionResponse (minus the
    safeguard/explanation fields, which the caller merges in separately).
    """
    baseline = baseline or {}
    start = time.perf_counter()

    model = _try_load_model()

    if model is not None:
        try:
            # Expected contract for a real model: predict_proba on a single
            # row, class order ["LOW", "ELEVATED", "HIGH_ATTENTION"].
            row = [[
                features.get("heart_rate_bpm") or 0,
                features.get("spo2_percent") or 0,
                features.get("body_temp_c") or 0,
                features.get("sleep_hours") or 0,
            ]]
            proba = model.predict_proba(row)[0]
            classes = list(model.classes_)
            probabilities = {cls: round(float(p), 3) for cls, p in zip(classes, proba)}
            level = max(probabilities, key=probabilities.get)
            score = probabilities.get("HIGH_ATTENTION", max(probabilities.values()))
            latency_ms = (time.perf_counter() - start) * 1000
            return {
                "risk_level": level,
                "risk_score": float(score),
                "probabilities": probabilities,
                "ml_available": True,
                "model_version": "trained-model-v1",
                "latency_ms": latency_ms,
            }
        except Exception:
            # Model exists but failed at inference time (bad input shape,
            # corrupted state, etc). Fall through to the heuristic so the
            # endpoint still returns a usable answer instead of a 500.
            pass

    score, probabilities, level = _heuristic_score(features, baseline)
    latency_ms = (time.perf_counter() - start) * 1000
    return {
        "risk_level": level,
        "risk_score": float(score),
        "probabilities": probabilities,
        "ml_available": False,  # this result came from the heuristic fallback, not a trained model
        "model_version": MODEL_VERSION_HEURISTIC,
        "latency_ms": latency_ms,
    }
