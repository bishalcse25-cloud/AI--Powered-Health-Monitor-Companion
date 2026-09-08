"""
Central configuration.

All settings are read from environment variables (and the .env file).
Nothing secret is hard-coded here. Access settings via `get_settings()`.
"""

import warnings
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_JWT_DEFAULT = "dev-insecure-change-me"


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

    # --- Database connection pool ---
    # QueuePool keeps `db_pool_size` connections open and opens up to
    # `db_max_overflow` more under load; `db_pool_recycle` drops connections
    # older than N seconds so a server-side idle timeout never hands us a
    # dead socket.
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

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

    # --- JWT authentication ---
    # Override JWT_SECRET in .env for any non-local deployment. The default
    # is a throwaway dev value and is NOT safe for production.
    jwt_secret: str = _INSECURE_JWT_DEFAULT
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24

    @model_validator(mode="after")
    def _warn_on_insecure_secret(self) -> "Settings":
        if self.jwt_secret == _INSECURE_JWT_DEFAULT:
            warnings.warn(
                "JWT_SECRET is unset - using the insecure dev default. Set a real "
                "JWT_SECRET in .env before deploying (see .env.example).",
                stacklevel=2,
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed only once per process."""
    return Settings()
