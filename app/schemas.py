"""
Pydantic schemas - the "data contracts" between the four pillars:

  IoT hardware  --(TelemetryIngestPayload)-->  Backend
  Backend       --(NormalizedHealthRecord)-->  ML engine
  ML engine     --(RiskPredictionResponse)-->  Backend / Frontend
  Backend       --(CompanionContext)-->        LLM
  Backend       --(TrendsResponse)-->          Frontend dashboard
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 1. Ingestion payload (IoT device or manual user log)
# ---------------------------------------------------------------------------

class TelemetrySource(str, Enum):
    device = "device"
    manual = "manual"
    simulator = "simulator"


class TelemetryReading(BaseModel):
    """One sample. All vitals are optional - a real sensor may only report a subset."""

    timestamp: datetime | None = Field(
        default=None, description="When the reading was taken. Server time is used if omitted."
    )
    heart_rate_bpm: float | None = Field(default=None, ge=0, le=300)
    spo2_percent: float | None = Field(default=None, ge=0, le=100)
    body_temp_c: float | None = Field(default=None, ge=25, le=45)
    systolic_bp: int | None = Field(default=None, ge=0, le=300)
    diastolic_bp: int | None = Field(default=None, ge=0, le=200)
    respiratory_rate: float | None = Field(default=None, ge=0, le=100)
    steps: int | None = Field(default=None, ge=0)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    weight_kg: float | None = Field(default=None, ge=0, le=500)
    mood: str | None = None
    notes: str | None = None


class TelemetryIngestPayload(BaseModel):
    """Body of POST /api/v1/telemetry/ingest. Supports single or batched readings."""

    # Ignored for JWT-authenticated callers (the user is taken from the token);
    # for a device caller the owner is resolved from the device_token. Kept as
    # an optional field only for backwards compatibility with older clients.
    user_id: int | None = None
    device_token: str | None = Field(
        default=None, description="Required when source='device'; identifies + authenticates the hardware."
    )
    source: TelemetrySource = TelemetrySource.manual
    readings: list[TelemetryReading] = Field(min_length=1)


# ---------------------------------------------------------------------------
# 2. Normalization pipeline output
# ---------------------------------------------------------------------------

class NormalizedHealthRecord(BaseModel):
    """
    Output of the normalization pipeline: timestamps aligned to UTC-minute
    resolution, missing features explicitly marked, ready for the ML engine.
    """

    user_id: int
    recorded_at: datetime
    source: TelemetrySource

    heart_rate_bpm: float | None = None
    spo2_percent: float | None = None
    body_temp_c: float | None = None
    systolic_bp: int | None = None
    diastolic_bp: int | None = None
    respiratory_rate: float | None = None
    steps: int | None = None
    sleep_hours: float | None = None
    weight_kg: float | None = None

    # Which fields were missing in the raw payload and therefore
    # back-filled (e.g. from baseline) rather than measured directly.
    imputed_fields: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3. ML prediction request / response
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    low = "LOW"
    elevated = "ELEVATED"
    high_attention = "HIGH_ATTENTION"


class RiskPredictionRequest(BaseModel):
    """What the backend sends into the ML engine (predict.py)."""

    user_id: int
    features: NormalizedHealthRecord
    baseline: dict[str, Any] = Field(
        default_factory=dict, description="Rolling baseline averages, e.g. {'avg_hr': 72.0}"
    )


class RuleExplanation(BaseModel):
    rule: str
    triggered: bool
    detail: str


class RiskPredictionResponse(BaseModel):
    """What the ML engine (or the safeguard fallback) returns."""

    risk_level: RiskLevel
    risk_score: float = Field(ge=0.0, le=1.0)
    probabilities: dict[str, float] = Field(default_factory=dict)
    explanations: list[RuleExplanation] = Field(default_factory=list)

    ml_available: bool = True
    model_version: str | None = None
    safeguard_triggered: bool = False
    latency_ms: float | None = None


# ---------------------------------------------------------------------------
# 4. LLM context payload (companion chat)
# ---------------------------------------------------------------------------

class ChatRole(str, Enum):
    user = "user"
    assistant = "assistant"


class ChatHistoryMessage(BaseModel):
    role: ChatRole
    content: str


class CompanionContext(BaseModel):
    """
    Everything the LLM needs to answer well: who the user is, their current
    risk assessment, their recent trend, and the recent back-and-forth.
    This is what CompanionContextBuilder.build() produces.
    """

    user_id: int
    current_risk: RiskPredictionResponse | None = None
    baseline: dict[str, Any] = Field(default_factory=dict)
    recent_trend_summary: str | None = None
    history: list[ChatHistoryMessage] = Field(default_factory=list)


class CompanionChatRequest(BaseModel):
    user_id: int
    conversation_id: int | None = None
    message: str = Field(min_length=1, max_length=4000)


# ---------------------------------------------------------------------------
# 4b. Auth (JWT)
# ---------------------------------------------------------------------------

class UserRegister(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserPublic(BaseModel):
    id: int
    email: str
    full_name: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


# ---------------------------------------------------------------------------
# 5. Trends
# ---------------------------------------------------------------------------

class TrendWindow(str, Enum):
    seven_day = "7d"
    thirty_day = "30d"


class MetricTrend(BaseModel):
    metric: str
    moving_average: float | None
    baseline_deviation_percent: float | None
    latest_value: float | None
    samples: int


class TrendsResponse(BaseModel):
    user_id: int
    window: TrendWindow
    generated_at: datetime
    metrics: list[MetricTrend]
