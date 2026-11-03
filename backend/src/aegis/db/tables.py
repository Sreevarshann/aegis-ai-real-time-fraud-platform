"""SQLAlchemy Core table definitions.

The authoritative DDL lives in Alembic migrations (``backend/alembic/versions``); these
definitions mirror it so repositories can build parameterised queries without raw strings.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

tenants = Table(
    "tenants",
    metadata,
    Column("tenant_id", String(32), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", String(32), ForeignKey("tenants.tenant_id"), nullable=False),
    Column("email", String(254), nullable=False, unique=True),
    Column("full_name", String(120), nullable=False),
    Column("password_hash", String(100), nullable=False),
    Column("role", String(16), nullable=False),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

customers = Table(
    "customers",
    metadata,
    Column("tenant_id", String(32), ForeignKey("tenants.tenant_id"), primary_key=True),
    Column("customer_id", String(32), primary_key=True),
    Column("home_country", String(2), nullable=False),
    Column("registered_devices", JSONB, nullable=False),
    Column("account_opened_at", DateTime(timezone=True), nullable=False),
    Column("avg_ticket_usd", Numeric(12, 2), nullable=False),
)

merchants = Table(
    "merchants",
    metadata,
    Column("tenant_id", String(32), ForeignKey("tenants.tenant_id"), primary_key=True),
    Column("merchant_id", String(32), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("category", String(32), nullable=False),
    Column("country", String(2), nullable=False),
)

model_versions = Table(
    "model_versions",
    metadata,
    Column("model_version_id", Integer, Identity(), primary_key=True),
    Column("version", String(64), nullable=False, unique=True),
    Column("algorithm", String(64), nullable=False),
    Column("artifact_path", Text, nullable=False),
    Column("feature_names", JSONB, nullable=False),
    Column("metrics", JSONB, nullable=False),
    Column("training_summary", JSONB, nullable=False),
    Column("decision_threshold", Float, nullable=False),
    Column("mlflow_run_id", String(64)),
    Column("is_active", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

transactions = Table(
    "transactions",
    metadata,
    Column("transaction_id", UUID(as_uuid=True), primary_key=True),
    Column("seq", BigInteger, Identity(), nullable=False, unique=True),
    Column("tenant_id", String(32), ForeignKey("tenants.tenant_id"), nullable=False),
    Column("event_id", UUID(as_uuid=True), nullable=False),
    Column("schema_version", String(8), nullable=False),
    Column("event_timestamp", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("customer_id", String(32), nullable=False),
    Column("merchant_id", String(32), nullable=False),
    Column("merchant_category", String(32), nullable=False),
    Column("amount", Numeric(14, 2), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("country", String(2), nullable=False),
    Column("device_id", String(64), nullable=False),
    Column("payment_channel", String(24), nullable=False),
    Column("status", String(16), nullable=False),
    Column("is_late", Boolean, nullable=False, server_default="false"),
    Column("payload_hash", String(64), nullable=False),
    Column("kafka_partition", Integer),
    Column("kafka_offset", BigInteger),
)

simulation_labels = Table(
    "simulation_labels",
    metadata,
    Column("transaction_id", UUID(as_uuid=True), ForeignKey("transactions.transaction_id"), primary_key=True),
    Column("tenant_id", String(32), ForeignKey("tenants.tenant_id"), nullable=False),
    Column("is_fraud", Boolean, nullable=False),
    Column("scenario", String(32), nullable=False),
)

risk_predictions = Table(
    "risk_predictions",
    metadata,
    Column("prediction_id", BigInteger, Identity(), primary_key=True),
    Column(
        "transaction_id", UUID(as_uuid=True), ForeignKey("transactions.transaction_id"), nullable=False, unique=True
    ),
    Column("tenant_id", String(32), ForeignKey("tenants.tenant_id"), nullable=False),
    Column("model_version_id", Integer, ForeignKey("model_versions.model_version_id"), nullable=False),
    Column("risk_score", Integer, nullable=False),
    Column("probability", Float, nullable=False),
    Column("risk_category", String(16), nullable=False),
    Column("features", JSONB, nullable=False),
    Column("explanation", JSONB, nullable=False),
    Column("scoring_latency_ms", Float, nullable=False),
    Column("scored_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

risk_alerts = Table(
    "risk_alerts",
    metadata,
    Column("alert_id", BigInteger, Identity(), primary_key=True),
    Column("tenant_id", String(32), ForeignKey("tenants.tenant_id"), nullable=False),
    Column(
        "transaction_id", UUID(as_uuid=True), ForeignKey("transactions.transaction_id"), nullable=False, unique=True
    ),
    Column("prediction_id", BigInteger, ForeignKey("risk_predictions.prediction_id"), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("status", String(24), nullable=False, server_default="open"),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

investigations = Table(
    "investigations",
    metadata,
    Column("investigation_id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", String(32), ForeignKey("tenants.tenant_id"), nullable=False),
    Column("alert_id", BigInteger, ForeignKey("risk_alerts.alert_id")),
    Column("transaction_id", UUID(as_uuid=True), ForeignKey("transactions.transaction_id"), nullable=False),
    Column("created_by", UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False),
    Column("engine", String(16), nullable=False),
    Column("llm_model", String(64)),
    Column("priority", String(8), nullable=False),
    Column("report", JSONB, nullable=False),
    Column("review_status", String(24), nullable=False, server_default="pending_review"),
    Column("reviewer_notes", Text),
    Column("duration_ms", Float, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

dead_letter_events = Table(
    "dead_letter_events",
    metadata,
    Column("dead_letter_id", BigInteger, Identity(), primary_key=True),
    Column("tenant_id", String(32)),  # may be unknown/invalid, so deliberately no FK
    Column("reason", String(48), nullable=False),
    Column("error_detail", Text, nullable=False),
    Column("raw_payload", Text, nullable=False),
    Column("source_topic", String(128), nullable=False),
    Column("source_partition", Integer),
    Column("source_offset", BigInteger),
    Column("received_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

data_quality_results = Table(
    "data_quality_results",
    metadata,
    Column("result_id", BigInteger, Identity(), primary_key=True),
    Column("run_id", UUID(as_uuid=True), nullable=False),
    Column("tenant_id", String(32), ForeignKey("tenants.tenant_id")),
    Column("check_name", String(64), nullable=False),
    Column("dimension", String(24), nullable=False),
    Column("status", String(8), nullable=False),
    Column("observed_value", Float),
    Column("threshold", Float),
    Column("details", JSONB, nullable=False),
    Column("checked_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

pipeline_stats = Table(
    "pipeline_stats",
    metadata,
    Column("stat_id", BigInteger, Identity(), primary_key=True),
    Column("component", String(48), nullable=False),
    Column("instance_id", String(64), nullable=False),
    Column("window_started_at", DateTime(timezone=True), nullable=False),
    Column("window_ended_at", DateTime(timezone=True), nullable=False),
    Column("consumed", Integer, nullable=False),
    Column("persisted", Integer, nullable=False),
    Column("duplicates", Integer, nullable=False),
    Column("dead_lettered", Integer, nullable=False),
    Column("late", Integer, nullable=False),
    Column("errors", Integer, nullable=False),
    Column("consumer_lag", BigInteger),
    Column("avg_processing_ms", Float),
)

transformation_runs = Table(
    "transformation_runs",
    metadata,
    Column("run_row_id", BigInteger, Identity(), primary_key=True),
    Column("invocation_id", String(64), nullable=False),
    Column("node_id", String(256), nullable=False),
    Column("resource_type", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("execution_time_s", Float),
    Column("rows_affected", BigInteger),
    Column("message", Text),
    Column("completed_at", DateTime(timezone=True), nullable=False),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("audit_id", BigInteger, Identity(), primary_key=True),
    Column("tenant_id", String(32), ForeignKey("tenants.tenant_id")),
    Column("actor_user_id", UUID(as_uuid=True), ForeignKey("users.user_id")),
    Column("action", String(64), nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("entity_id", String(64)),
    Column("details", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
