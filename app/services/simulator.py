"""
Mock / Simulator Mode.

When hardware isn't available yet (or the team is doing integration
testing), this generates realistic-looking synthetic IoT readings so every
other layer (normalization, ML, trends, companion) can be exercised
end-to-end without a real ESP32.

Turned on by setting SIMULATOR_MODE=true in .env. It never runs on its own -
routers call `generate_reading()` explicitly (see routers/telemetry.py's
POST /api/v1/telemetry/simulate endpoint), so it's opt-in.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from app.schemas import TelemetryReading

# Realistic resting baselines to jitter around.
_BASE_HR = 72.0
_BASE_SPO2 = 97.5
_BASE_TEMP = 36.8


def generate_reading(anomaly: bool = False) -> TelemetryReading:
    """
    Produces one synthetic reading.

    anomaly=True intentionally produces an out-of-range reading, useful for
    testing that the safeguard rules and alerts actually fire.
    """
    if anomaly:
        scenario = random.choice(["low_spo2", "high_hr", "fever"])
        hr = random.uniform(175, 195) if scenario == "high_hr" else random.uniform(65, 85)
        spo2 = random.uniform(78, 84) if scenario == "low_spo2" else random.uniform(95, 99)
        temp = random.uniform(39.6, 40.5) if scenario == "fever" else random.uniform(36.5, 37.2)
    else:
        hr = random.gauss(_BASE_HR, 5)
        spo2 = min(100.0, random.gauss(_BASE_SPO2, 0.8))
        temp = random.gauss(_BASE_TEMP, 0.2)

    return TelemetryReading(
        timestamp=datetime.now(timezone.utc),
        heart_rate_bpm=round(hr, 1),
        spo2_percent=round(spo2, 1),
        body_temp_c=round(temp, 2),
        respiratory_rate=round(random.gauss(16, 2), 1),
        steps=random.randint(0, 40),
    )
