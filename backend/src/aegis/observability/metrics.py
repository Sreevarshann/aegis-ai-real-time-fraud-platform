"""Prometheus metrics shared by the consumer and the API."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

EVENTS_CONSUMED = Counter("aegis_events_consumed_total", "Kafka messages consumed")
EVENTS_PERSISTED = Counter("aegis_events_persisted_total", "Transactions persisted and scored")
EVENTS_DUPLICATE = Counter("aegis_events_duplicate_total", "Exact replays skipped idempotently")
EVENTS_LATE = Counter("aegis_events_late_total", "Events accepted but flagged late (out of order)")
EVENTS_DEAD_LETTERED = Counter("aegis_events_dead_lettered_total", "Events quarantined", ["reason"])
VALIDATION_FAILURES = Counter("aegis_validation_failures_total", "Schema/referential validation failures", ["reason"])
PROCESSING_ERRORS = Counter("aegis_processing_errors_total", "Batch failures (retried)", ["stage"])
ALERTS_CREATED = Counter("aegis_alerts_created_total", "Risk alerts raised", ["severity"])
BATCH_SECONDS = Histogram(
    "aegis_batch_processing_seconds",
    "Wall time to process one batch",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
SCORING_SECONDS = Histogram(
    "aegis_scoring_seconds_per_event",
    "Model scoring + explanation per event",
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1),
)
END_TO_END_SECONDS = Histogram(
    "aegis_end_to_end_latency_seconds",
    "Producer timestamp to persisted",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
CONSUMER_LAG = Gauge("aegis_consumer_lag_messages", "High watermark minus committed offset (sum)")
RISK_SCORE = Histogram(
    "aegis_risk_score", "Distribution of assigned risk scores", buckets=(10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
)
DQ_CHECKS = Counter("aegis_data_quality_checks_total", "Data quality check outcomes", ["check", "status"])
API_LATENCY = Histogram("aegis_api_request_seconds", "API request latency", ["method", "route", "status"])
