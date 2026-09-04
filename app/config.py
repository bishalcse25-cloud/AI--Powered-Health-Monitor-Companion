"""
Central configuration.

All settings are read from environment variables (and the .env file).
Nothing secret is hard-coded here. Access settings via `get_settings()`.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Load variables from the .env file in the project root.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database (matches the DB_* keys already in your .env) ---
    db_user: str = "postgres"
    db_password: str = ""
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "health_companion"

    # --- LLM / AI companion ---
    # The API key is NEVER committed. Put it in .env only when you are ready.
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5"
    llm_max_tokens: int = 1024

    # --- Feature flags (the "mock / simulator mode" switches) ---
    # When True, telemetry can be produced without real hardware.
    simulator_mode: bool = False
    # When False (or the model file is missing), the ML engine uses a
    # transparent rule-based fallback instead of a trained model.
    ml_enabled: bool = True
    # When False (or no API key is set), the companion returns canned replies.
    llm_enabled: bool = True

    # --- Historical baseline manager ---
    baseline_window_days: int = 7
    baseline_cache_ttl_seconds: int = 300  # 5 minutes

    # --- Demo user (until real auth is added in a later phase) ---
    demo_user_email: str = "demo@healthcompanion.local"


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed only once per process."""
    return Settings()
