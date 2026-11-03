"""Real Redpanda: producer -> topic -> consumer service -> PostgreSQL, DLQ topic and restart safety."""

import threading
import time
from datetime import UTC, datetime

import pytest
from confluent_kafka import Consumer
from sqlalchemy import text

from aegis.streaming.consumer import ConsumerService
from aegis.streaming.defects import DefectRates, inject_defects
from aegis.streaming.kafka import ensure_topics, make_producer
from aegis.streaming.producer import publish

from .helpers import recent_events

pytestmark = pytest.mark.integration


def run_consumer_until(settings, predicate, timeout=60.0) -> None:
    svc = ConsumerService(settings)
    svc._dq_loop = lambda: None  # type: ignore[method-assign]
    import aegis.streaming.consumer as mod

    mod.start_http_server = lambda *_a, **_k: None  # metrics port may already be bound
    t = threading.Thread(target=svc.run, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline and not predicate():
            time.sleep(0.5)
    finally:
        svc.stop()
        t.join(15)
    assert predicate(), "consumer did not reach the expected state in time"


def counts(engine) -> tuple[int, int, int]:
    with engine.connect() as conn:
        return tuple(
            conn.execute(
                text(  # type: ignore[return-value]
                    "SELECT (SELECT count(*) FROM transactions), (SELECT count(*) FROM risk_predictions), "
                    "(SELECT count(*) FROM dead_letter_events)"
                )
            ).one()
        )


def test_kafka_pipeline_end_to_end_with_dlq_and_restart(clean, settings):
    ensure_topics(settings)
    events = recent_events(300, seed=21)
    msgs = list(
        inject_defects(
            events,
            DefectRates(duplicate=0.05, out_of_order=0.05, stale=0.0, invalid=0.03),
            seed=21,
            clock=lambda: datetime.now(UTC),
        )
    )
    expected_accept = sum(1 for m in msgs if m.expected == "accept")
    expected_dlq = sum(1 for m in msgs if m.expected.startswith("dead_letter"))
    assert expected_dlq > 0 and any(m.expected == "duplicate" for m in msgs)
    summary = publish(make_producer(settings), settings.kafka_transactions_topic, msgs)
    assert summary.sent == len(msgs)

    run_consumer_until(settings, lambda: counts(clean)[0] + counts(clean)[2] >= expected_accept + expected_dlq)
    txns, preds, dlq = counts(clean)
    assert txns == expected_accept and preds == expected_accept and dlq == expected_dlq

    # Quarantined events were also published to the DLQ topic with their reason.
    c = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": f"dlq-reader-{time.time()}",
            "auto.offset.reset": "earliest",
        }
    )
    c.subscribe([settings.kafka_dlq_topic])
    seen = []
    deadline = time.monotonic() + 20
    while len(seen) < expected_dlq and time.monotonic() < deadline:
        m = c.poll(1.0)
        if m is not None and not m.error():
            seen.append(dict(m.headers() or [])["reason"].decode())
    c.close()
    assert len(seen) == expected_dlq

    # Restart with the same consumer group: committed offsets mean nothing is reprocessed.
    with clean.connect() as conn:
        stats_before = conn.execute(text("SELECT coalesce(sum(consumed), 0) FROM pipeline_stats")).scalar_one()
    run_consumer_until(settings, lambda: True, timeout=8)
    time.sleep(6)
    assert counts(clean) == (txns, preds, dlq)
    with clean.connect() as conn:
        stats_after = conn.execute(text("SELECT coalesce(sum(consumed), 0) FROM pipeline_stats")).scalar_one()
    assert stats_after == stats_before  # no messages re-consumed after restart
