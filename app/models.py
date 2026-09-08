"""
SQLAlchemy ORM models - the database tables.

Table map:
  users              accounts
  devices            registered IoT hardware (e.g. an ESP32 sensor board)
  device_readings    raw payloads received from a device, before processing
  health_entries     the normalized, unified health record (manual or device)
  risk_evaluations   output of the ML engine + safeguard rules for one moment
  medications        a medication a user takes
  medication_logs    "taken" / "skipped" events for a medication
  ai_conversations   one chat thread with the AI companion
  ai_messages        one message inside a conversation
  ai_insights        AI-generated summary of a user's trends over a period
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=True)  # filled in the auth phase
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")
    health_entries = relationship("HealthEntry", back_populates="user", cascade="all, delete-orphan")
    medications = relationship("Medication", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("AIConversation", back_populates="user", cascade="all, delete-orphan")


class Device(Base):
    """A piece of registered hardware, e.g. an ESP32 with HR/SpO2/temp sensors."""

    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    device_type = Column(String(50), default="esp32")
    # The device sends this token on every ingest request to prove who it is.
    secret_token = Column(String(64), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="devices")
    readings = relationship("DeviceReading", back_populates="device", cascade="all, delete-orphan")


class DeviceReading(Base):
    """Raw ingested payload, kept as-received for audit/debugging, before normalization."""

    __tablename__ = "device_readings"

    # A user's readings are always queried newest-first, so index the pair.
    # (user_id alone is covered by this composite's leading column.)
    __table_args__ = (
        Index("ix_device_readings_user_received", "user_id", "received_at"),
    )

    id = Column(Integer, primary_key=True)
    # Nullable: only readings that came from a real registered device have one;
    # manual entries and simulator-generated readings leave this empty.
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    raw_payload = Column(JSON, nullable=False)
    processed = Column(Boolean, default=False)
    health_entry_id = Column(Integer, ForeignKey("health_entries.id"), nullable=True)

    device = relationship("Device", back_populates="readings")


class HealthEntry(Base):
    """
    One normalized health record for a user at a point in time.
    Populated either by a user typing it in manually, or by the
    normalization pipeline after a device reading comes in.
    """

    __tablename__ = "health_entries"

    # The hot path everywhere in the app: "this user's entries, newest first"
    # (baseline window, trends, latest reading). A btree on (user_id,
    # recorded_at) serves those and also any filter on user_id alone, so no
    # separate user_id index is needed.
    #
    # The CHECK constraints are the last line of defence against a bad vital
    # reaching the ML engine / charts - they hold even if a bug bypasses the
    # Pydantic layer or someone writes to the table directly. NULL is allowed
    # (a partial reading), only out-of-range numbers are rejected.
    __table_args__ = (
        Index("ix_health_entries_user_recorded", "user_id", "recorded_at"),
        CheckConstraint(
            "spo2_percent IS NULL OR (spo2_percent >= 0 AND spo2_percent <= 100)",
            name="ck_health_entries_spo2_percent_range",
        ),
        CheckConstraint(
            "heart_rate_bpm IS NULL OR (heart_rate_bpm >= 0 AND heart_rate_bpm <= 300)",
            name="ck_health_entries_heart_rate_bpm_range",
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False, index=True)
    source = Column(String(20), default="manual")  # "manual" | "device" | "simulator"
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)

    heart_rate_bpm = Column(Float, nullable=True)
    spo2_percent = Column(Float, nullable=True)
    body_temp_c = Column(Float, nullable=True)
    systolic_bp = Column(Integer, nullable=True)
    diastolic_bp = Column(Integer, nullable=True)
    respiratory_rate = Column(Float, nullable=True)
    steps = Column(Integer, nullable=True)
    sleep_hours = Column(Float, nullable=True)
    weight_kg = Column(Float, nullable=True)
    mood = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="health_entries")


class RiskEvaluation(Base):
    """Result of running the ML engine + deterministic safeguards for one moment."""

    __tablename__ = "risk_evaluations"

    # Read as "this user's evaluations, newest first" (history + latest badge).
    __table_args__ = (
        Index("ix_risk_evaluations_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    source_entry_id = Column(Integer, ForeignKey("health_entries.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    risk_level = Column(String(20), nullable=False)  # LOW | ELEVATED | HIGH_ATTENTION
    risk_score = Column(Float, nullable=False)  # 0.0 - 1.0
    probabilities = Column(JSON, nullable=True)  # per-class ML probabilities

    ml_available = Column(Boolean, default=True)  # False if the model was offline
    ml_model_version = Column(String(50), nullable=True)

    safeguard_triggered = Column(Boolean, default=False)
    explanations = Column(JSON, nullable=True)  # list of human-readable reasons
    baseline_snapshot = Column(JSON, nullable=True)  # baseline used for this evaluation


class Medication(Base):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    dosage = Column(String(100), nullable=True)
    schedule_text = Column(String(255), nullable=True)  # e.g. "08:00, 20:00 daily"
    active = Column(Boolean, default=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="medications")
    logs = relationship("MedicationLog", back_populates="medication", cascade="all, delete-orphan")


class MedicationLog(Base):
    __tablename__ = "medication_logs"

    # Adherence stats scan one user's logs over a time window.
    __table_args__ = (
        Index("ix_medication_logs_user_logged", "user_id", "logged_at"),
    )

    id = Column(Integer, primary_key=True)
    medication_id = Column(Integer, ForeignKey("medications.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), nullable=False)  # "taken" | "skipped" | "missed"
    logged_at = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text, nullable=True)

    medication = relationship("Medication", back_populates="logs")


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    # Conversation list for a user, most-recently-updated first.
    __table_args__ = (
        Index("ix_ai_conversations_user_updated", "user_id", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), default="New conversation")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="conversations")
    messages = relationship("AIMessage", back_populates="conversation", cascade="all, delete-orphan")


class AIMessage(Base):
    __tablename__ = "ai_messages"

    # Messages are always fetched per-conversation in chronological order.
    __table_args__ = (
        Index("ix_ai_messages_conversation_created", "conversation_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("ai_conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" | "assistant" | "system"
    content = Column(Text, nullable=False)
    context_snapshot = Column(JSON, nullable=True)  # the health context sent to the LLM, for audit
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("AIConversation", back_populates="messages")


class AIInsight(Base):
    __tablename__ = "ai_insights"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    summary = Column(Text, nullable=False)
    highlights = Column(JSON, nullable=True)
    risk_level = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
