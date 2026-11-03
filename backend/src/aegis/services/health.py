"""Dependency health checks for readiness and the System Operations page."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import redis
from confluent_kafka.admin import AdminClient
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import Engine, text

from aegis.config import Settings


def _timed(fn: Callable[[], str | None]) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        detail = fn()
        return {"status": "up", "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "detail": detail}
    except Exception as exc:
        return {
            "status": "down",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "detail": f"{exc.__class__.__name__}: {str(exc)[:160]}",
        }


def check_postgres(engine: Engine) -> dict[str, Any]:
    def run() -> str:
        with engine.connect() as conn:
            return str(conn.execute(text("SHOW server_version")).scalar())

    return _timed(run)


def check_redis(settings: Settings) -> dict[str, Any]:
    def run() -> str:
        r = redis.Redis.from_url(settings.redis_url, socket_timeout=2)
        r.ping()
        return f"{r.info('memory')['used_memory_human']} used"

    return _timed(run)


def check_kafka(settings: Settings) -> dict[str, Any]:
    def run() -> str:
        md = AdminClient({"bootstrap.servers": settings.kafka_bootstrap_servers}).list_topics(timeout=3)
        topics = [t for t in md.topics if not t.startswith("_")]
        return f"{len(md.brokers)} broker(s); topics: {', '.join(sorted(topics))}"

    return _timed(run)


def check_http(url: str) -> dict[str, Any]:
    def run() -> str:
        r = httpx.get(url, timeout=3)
        r.raise_for_status()
        return f"HTTP {r.status_code}"

    return _timed(run)


def consumer_metrics(settings: Settings) -> dict[str, Any]:
    """Scrape the consumer's Prometheus endpoint and return selected counters."""
    wanted = {
        "aegis_events_consumed_total",
        "aegis_events_persisted_total",
        "aegis_events_duplicate_total",
        "aegis_events_late_total",
        "aegis_events_dead_lettered_total",
        "aegis_consumer_lag_messages",
        "aegis_processing_errors_total",
        "aegis_alerts_created_total",
    }
    out: dict[str, Any] = {"available": False}
    try:
        body = httpx.get(settings.consumer_metrics_url, timeout=3).text
    except Exception as exc:
        out["error"] = str(exc)[:160]
        return out
    out["available"] = True
    latency: dict[str, float] = {}
    for fam in text_string_to_metric_families(body):
        for s in fam.samples:
            if s.name in wanted:
                label = ",".join(f"{v}" for v in s.labels.values())
                key = s.name + (f"[{label}]" if label else "")
                out[key] = s.value
            if fam.name in ("aegis_end_to_end_latency_seconds", "aegis_scoring_seconds_per_event") and s.name.endswith(
                ("_sum", "_count")
            ):
                latency[s.name] = s.value
    for base in ("aegis_end_to_end_latency_seconds", "aegis_scoring_seconds_per_event"):
        c = latency.get(f"{base}_count", 0)
        out[f"{base}_avg_ms"] = round(latency.get(f"{base}_sum", 0) / c * 1000, 2) if c else None
    return out


def system_health(engine: Engine, settings: Settings) -> dict[str, Any]:
    services = {
        "postgres": check_postgres(engine),
        "redis": check_redis(settings),
        "redpanda": check_kafka(settings),
        "mlflow": check_http(f"{settings.mlflow_tracking_uri.rstrip('/')}/health")
        if settings.mlflow_tracking_uri.startswith("http")
        else {"status": "n/a"},
        "consumer": check_http(settings.consumer_metrics_url),
    }
    if settings.ollama_enabled:
        services["ollama"] = check_http(f"{settings.ollama_base_url}/api/tags")
    with engine.connect() as conn:
        hb = conn.execute(text("SELECT max(window_ended_at) FROM pipeline_stats")).scalar()
        dbt_last = conn.execute(text("SELECT max(completed_at) FROM transformation_runs")).scalar()
    now = datetime.now(UTC)
    return {
        "checked_at": now,
        "services": services,
        "consumer_heartbeat_age_s": round((now - hb).total_seconds(), 1) if hb else None,
        "dbt_last_run_age_s": round((now - dbt_last).total_seconds(), 1) if dbt_last else None,
        "llm": {"enabled": settings.ollama_enabled, "model": settings.ollama_model},
    }
