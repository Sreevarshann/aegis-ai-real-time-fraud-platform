"""Streaming processor against real PostgreSQL + Redis: persistence, idempotency, DLQ, lateness."""

import json
from datetime import timedelta

import pytest
import redis
from sqlalchemy import text

from aegis.features.store import RedisFeatureStore
from aegis.streaming.processor import RawMessage, TransactionProcessor

from .helpers import recent_events, to_messages

pytestmark = pytest.mark.integration


def make_processor(engine, settings) -> TransactionProcessor:
    return TransactionProcessor(settings, engine, RedisFeatureStore(redis.Redis.from_url(settings.redis_url)))


def count(engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())  # noqa: S608 - fixed names


def test_events_are_persisted_with_predictions_and_separate_labels(clean, settings):
    events = recent_events(120)
    result = make_processor(clean, settings).process_batch(to_messages(events))
    assert result.persisted == 120 and result.duplicates == 0 and not result.dead_letters
    assert count(clean, "transactions") == 120
    assert count(clean, "risk_predictions") == 120
    assert count(clean, "simulation_labels") == 120
    with clean.connect() as conn:
        bad = conn.execute(
            text(
                "SELECT count(*) FROM risk_predictions WHERE risk_score NOT BETWEEN 0 AND 100 "
                "OR jsonb_typeof(explanation) <> 'array'"
            )
        ).scalar_one()
        stored_features = conn.execute(text("SELECT features FROM risk_predictions LIMIT 1")).scalar_one()
        alerts = conn.execute(
            text(
                "SELECT count(*) FROM risk_alerts a JOIN risk_predictions p USING (prediction_id) "
                "JOIN model_versions m USING (model_version_id) "
                "WHERE p.probability < m.decision_threshold"
            )
        ).scalar_one()
    assert bad == 0 and alerts == 0
    assert "ground_truth_label" not in stored_features and "label" not in stored_features


def test_replayed_events_never_create_duplicate_transactions(clean, settings):
    proc = make_processor(clean, settings)
    msgs = to_messages(recent_events(80, seed=12))
    first = proc.process_batch(msgs)
    with clean.connect() as conn:
        scores_before = dict(conn.execute(text("SELECT transaction_id, probability FROM risk_predictions")).all())
    replay = proc.process_batch(msgs)  # e.g. consumer crashed before committing offsets
    assert first.persisted == 80
    assert replay.persisted == 0 and replay.duplicates == 80 and not replay.dead_letters
    assert count(clean, "transactions") == 80 and count(clean, "risk_predictions") == 80
    # Within-batch duplicates are caught too.
    dup_batch = proc.process_batch(msgs[:5] + msgs[:5])
    assert dup_batch.duplicates == 10 and dup_batch.persisted == 0
    with clean.connect() as conn:
        assert (
            dict(conn.execute(text("SELECT transaction_id, probability FROM risk_predictions")).all()) == scores_before
        )


def test_conflicting_reuse_of_an_id_is_quarantined(clean, settings):
    proc = make_processor(clean, settings)
    [msg] = to_messages(recent_events(1, seed=13))
    proc.process_batch([msg])
    doc = json.loads(msg.value)
    doc["payload"]["transaction_amount"] = "99999.99"
    result = proc.process_batch([RawMessage(json.dumps(doc).encode(), "t", 0, 1)])
    assert result.reasons() == {"conflicting_duplicate": 1}
    with clean.connect() as conn:
        amount = conn.execute(text("SELECT amount FROM transactions")).scalar_one()
    assert float(amount) != 99999.99


def test_invalid_events_go_to_dead_letter_table(clean, settings):
    from aegis.streaming.defects import INVALID_KINDS, corrupt, encode

    events = recent_events(len(INVALID_KINDS) + 2, seed=14)
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    raw = [
        RawMessage(corrupt(encode(e, now), k), "t", 0, i)
        for i, (e, k) in enumerate(zip(events, INVALID_KINDS, strict=False))
    ]
    raw.append(RawMessage(b"\x00\xff binary garbage with NUL", "t", 0, 100))
    stale = encode(events[-1], now)
    stale["payload"]["event_timestamp"] = (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    raw.append(RawMessage(json.dumps(stale).encode(), "t", 0, 101))
    result = make_processor(clean, settings).process_batch(raw)
    assert result.persisted == 0
    assert result.reasons() == {
        "schema_validation_failed": 5,
        "malformed_json": 2,
        "unsupported_schema_version": 1,
        "unknown_customer": 1,
        "stale_event": 1,
    }
    assert count(clean, "dead_letter_events") == len(raw)
    # Re-delivering the same poison messages must not double-quarantine them.
    make_processor(clean, settings).process_batch(raw)
    assert count(clean, "dead_letter_events") == len(raw)


def test_out_of_order_events_are_flagged_late(clean, settings):
    strict = settings.model_copy(update={"late_event_tolerance_s": 1})
    proc = make_processor(clean, strict)
    events = recent_events(40, seed=15)
    msgs = to_messages(events)
    assert (events[-1].payload.event_timestamp - events[0].payload.event_timestamp).total_seconds() > 1
    proc.process_batch(msgs[1:])  # newer events advance partition 0's watermark
    result = proc.process_batch([RawMessage(msgs[0].value, "t", 0, 999)])  # the oldest arrives last
    assert result.persisted == 1 and result.late == 1
    with clean.connect() as conn:
        late = conn.execute(
            text("SELECT is_late FROM transactions WHERE transaction_id = :t"), {"t": events[0].payload.transaction_id}
        ).scalar_one()
    assert late is True
