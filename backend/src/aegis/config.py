"""Centralised, typed runtime configuration.

Every value can be overridden with an ``AEGIS_``-prefixed environment variable.
Defaults target the local Docker Compose stack and are NOT suitable for production.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Marker used in defaults so nobody mistakes them for real secrets.
_NONPROD = "nonprod-local-dev-only"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEGIS_", env_file=".env", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"
    log_json: bool = True

    # --- storage -----------------------------------------------------------------
    database_url: str = "postgresql+psycopg://aegis:aegis@localhost:55432/aegis"
    redis_url: str = "redis://localhost:56379/0"

    # --- streaming ---------------------------------------------------------------
    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_transactions_topic: str = "transactions.v1"
    kafka_dlq_topic: str = "transactions.dlq"
    kafka_consumer_group: str = "aegis-risk-scorer"
    kafka_partitions: int = 3
    consumer_batch_size: int = 200
    consumer_poll_timeout_s: float = 1.0
    # Events older than the tenant watermark by more than this are flagged late...
    late_event_tolerance_s: int = 300
    # ...and beyond this they are quarantined as stale (cannot be scored meaningfully).
    max_event_lateness_s: int = 86_400 * 2
    consumer_metrics_port: int = 9108
    data_quality_interval_s: int = 60

    # --- ML ------------------------------------------------------------------------
    model_dir: str = "./artifacts/models"
    mlflow_tracking_uri: str = "http://localhost:5050"
    mlflow_experiment: str = "aegis-fraud-risk"

    # --- auth ----------------------------------------------------------------------
    jwt_secret: str = Field(default=f"{_NONPROD}-change-me-jwt-secret-0123456789")
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 480
    demo_user_password: str = Field(default="AegisDemo!2026")

    # --- investigation / optional local LLM ------------------------------------------
    ollama_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_s: float = 60.0

    # --- simulator -------------------------------------------------------------------
    simulator_seed: int = 42

    # --- misc ------------------------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    consumer_metrics_url: str = "http://localhost:9108/metrics"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production and _NONPROD in settings.jwt_secret:
        raise RuntimeError("Refusing to start in production with the development JWT secret.")
    return settings
