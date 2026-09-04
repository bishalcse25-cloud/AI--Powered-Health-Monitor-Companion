"""
Historical Aggregation & Baseline Manager.

Computes each user's rolling N-day baseline (avg heart rate, avg sleep,
etc.) from `health_entries` in Postgres, and caches the result in memory
for a short TTL so the ML engine / trends endpoint aren't re-querying the
database on every request.

Why in-memory instead of Redis: this project runs as a single process
today, so a plain dict with a TTL gives the same practical benefit with
zero extra infrastructure. If this backend is ever scaled to multiple
processes, swap `_cache` for a Redis client behind the same two functions
(get_baseline / invalidate) - nothing else in the codebase would change.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import HealthEntry

settings = get_settings()

# user_id -> (computed_at_epoch_seconds, baseline_dict)
_cache: dict[int, tuple[float, dict[str, float]]] = {}


def invalidate(user_id: int) -> None:
    """Call this after inserting a new health_entry for a user."""
    _cache.pop(user_id, None)


def _compute_baseline(db: Session, user_id: int, window_days: int) -> dict[str, float]:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)

    row = (
        db.query(
            func.avg(HealthEntry.heart_rate_bpm).label("avg_hr"),
            func.stddev_samp(HealthEntry.heart_rate_bpm).label("hr_stddev"),
            func.avg(HealthEntry.spo2_percent).label("avg_spo2"),
            func.avg(HealthEntry.body_temp_c).label("avg_temp"),
            func.avg(HealthEntry.sleep_hours).label("avg_sleep"),
            func.avg(HealthEntry.steps).label("avg_steps"),
            func.count(HealthEntry.id).label("sample_count"),
        )
        .filter(HealthEntry.user_id == user_id, HealthEntry.recorded_at >= since)
        .one()
    )

    def rnd(value):
        return round(float(value), 2) if value is not None else None

    return {
        "avg_hr": rnd(row.avg_hr),
        "hr_stddev": rnd(row.hr_stddev),
        "avg_spo2": rnd(row.avg_spo2),
        "avg_temp": rnd(row.avg_temp),
        "avg_sleep": rnd(row.avg_sleep),
        "avg_steps": rnd(row.avg_steps),
        "sample_count": row.sample_count or 0,
        "window_days": window_days,
    }


def get_baseline(db: Session, user_id: int, window_days: int | None = None) -> dict[str, float]:
    """
    Returns the cached baseline if fresh enough, otherwise recomputes it
    from the database and refreshes the cache.
    """
    window_days = window_days or settings.baseline_window_days
    cached = _cache.get(user_id)
    now = time.time()

    if cached is not None:
        computed_at, baseline = cached
        if now - computed_at < settings.baseline_cache_ttl_seconds:
            return baseline

    baseline = _compute_baseline(db, user_id, window_days)
    _cache[user_id] = (now, baseline)
    return baseline


def hr_deviation(current_hr: float | None, baseline: dict[str, float]) -> float | None:
    """How far (in stddevs, or % if stddev unavailable) current HR is from baseline."""
    if current_hr is None or baseline.get("avg_hr") is None:
        return None
    avg = baseline["avg_hr"]
    stddev = baseline.get("hr_stddev")
    if stddev:
        return round((current_hr - avg) / stddev, 2)
    if avg:
        return round((current_hr - avg) / avg * 100, 2)  # percent deviation
    return None
