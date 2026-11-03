"""Batch processing core of the streaming consumer, independent of Kafka for testability.

For each batch of raw messages:

1. **Validate** - JSON + versioned schema, then tenant / customer / merchant integrity.
2. **Time** - advance the per-(tenant, partition) event-time watermark; flag late events, quarantine
   stale or future-dated ones.
3. **Deduplicate** - an id already persisted (or seen earlier in the batch) with the same
   content hash is an idempotent replay and is skipped; the same id with *different* content
   is a conflict and is quarantined.
4. **Featurise + score** - point-in-time features, then one batched model call with
   occlusion explanations.
5. **Persist atomically** - transactions, predictions, alerts, labels and dead letters in a
   single database transaction. Only after this commits may the caller commit Kafka offsets.

Labels from the simulation block go straight to ``simulation_labels``; they never enter
feature computation or scoring.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Engine

from aegis.config import Settings
from aegis.events.schema import EventRejected, TransactionEnvelope, parse_envelope, payload_hash
from aegis.features.compute import CustomerReference, FeatureEngine
from aegis.features.store import FeatureStore
from aegis.ml.model import RiskModelBundle
from aegis.observability import metrics as m
from aegis.observability.logging import get_logger
from aegis.repositories import pipeline as repo

log = get_logger(__name__)


@dataclass(frozen=True)
class RawMessage:
    value: bytes
    topic: str
    partition: int | None
    offset: int | None
    key: bytes | None = None


@dataclass
class BatchResult:
    consumed: int = 0
    persisted: int = 0
    duplicates: int = 0
    late: int = 0
    alerts: int = 0
    dead_letters: list[dict[str, Any]] = field(default_factory=list)
    processing_ms: float = 0.0

    @property
    def dead_lettered(self) -> int:
        return len(self.dead_letters)

    def reasons(self) -> dict[str, int]:
        return dict(Counter(d["reason"] for d in self.dead_letters))


class ReferenceCache:
    """Tenant reference data cached in memory (refreshed on miss, rate-limited)."""

    def __init__(self, engine: Engine, refresh_after_s: float = 60.0) -> None:
        self.engine = engine
        self.refresh_after_s = refresh_after_s
        self._tenants: set[str] = set()
        self._customers: dict[str, dict[str, CustomerReference]] = {}
        self._merchants: dict[str, dict[str, str]] = {}
        self._loaded_at: dict[str, float] = {}

    def _load(self, tenant_id: str | None = None) -> None:
        with self.engine.connect() as conn:
            self._tenants = repo.tenant_ids(conn)
            for t in [tenant_id] if tenant_id else self._tenants:
                if t in self._tenants:
                    self._customers[t] = repo.load_customer_references(conn, t)
                    self._merchants[t] = repo.load_merchant_categories(conn, t)
                    self._loaded_at[t] = time.monotonic()

    def _maybe_refresh(self, tenant_id: str) -> None:
        if time.monotonic() - self._loaded_at.get(tenant_id, -1e9) > self.refresh_after_s:
            self._load(tenant_id)

    def has_tenant(self, tenant_id: str) -> bool:
        if tenant_id not in self._tenants:
            self._maybe_refresh(tenant_id)
        return tenant_id in self._tenants

    def customer(self, tenant_id: str, customer_id: str) -> CustomerReference | None:
        ref = self._customers.get(tenant_id, {}).get(customer_id)
        if ref is None:
            self._maybe_refresh(tenant_id)
            ref = self._customers.get(tenant_id, {}).get(customer_id)
        return ref

    def merchant_category(self, tenant_id: str, merchant_id: str) -> str | None:
        cat = self._merchants.get(tenant_id, {}).get(merchant_id)
        if cat is None:
            self._maybe_refresh(tenant_id)
            cat = self._merchants.get(tenant_id, {}).get(merchant_id)
        return cat


class ModelProvider:
    """Loads the active model from the registry and hot-swaps when a new version is activated."""

    def __init__(self, engine: Engine, check_every_s: float = 30.0) -> None:
        self.engine = engine
        self.check_every_s = check_every_s
        self.bundle: RiskModelBundle | None = None
        self.model_version_id: int | None = None
        self._checked = -1e9

    def get(self) -> tuple[RiskModelBundle, int]:
        if self.bundle is None or time.monotonic() - self._checked > self.check_every_s:
            self._checked = time.monotonic()
            with self.engine.connect() as conn:
                row = repo.active_model(conn)
            if row is None:
                if self.bundle is None:
                    raise RuntimeError("No active model registered. Run `make train` (or `make up`).")
            elif row.model_version_id != self.model_version_id:
                self.bundle = RiskModelBundle.load(Path(row.artifact_path))
                self.model_version_id = int(row.model_version_id)
                log.info("model_loaded", version=row.version, model_version_id=row.model_version_id)
        assert self.bundle is not None and self.model_version_id is not None
        return self.bundle, self.model_version_id


class TransactionProcessor:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        store: FeatureStore,
        references: ReferenceCache | None = None,
        models: ModelProvider | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.store = store
        self.features = FeatureEngine(store)
        self.references = references or ReferenceCache(engine)
        self.models = models or ModelProvider(engine)
        self.clock = clock

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _dead_letter(msg: RawMessage, reason: str, detail: str, tenant_id: str | None) -> dict[str, Any]:
        # PostgreSQL text cannot hold NUL bytes; escape them so hostile payloads are still quarantined.
        raw = msg.value.decode("utf-8", errors="replace").replace("\x00", "\\u0000")
        return {
            "tenant_id": tenant_id,
            "reason": reason,
            "error_detail": detail[:2000].replace("\x00", ""),
            "raw_payload": raw[:20_000],
            "source_topic": msg.topic,
            "source_partition": msg.partition,
            "source_offset": msg.offset,
        }

    def _validate(self, msg: RawMessage) -> TransactionEnvelope:
        env = parse_envelope(msg.value)
        p = env.payload
        if not self.references.has_tenant(p.tenant_id):
            raise EventRejected("unknown_tenant", f"tenant {p.tenant_id!r} is not registered", None)
        if self.references.customer(p.tenant_id, p.customer_id) is None:
            raise EventRejected("unknown_customer", f"customer {p.customer_id!r} not in reference data", p.tenant_id)
        category = self.references.merchant_category(p.tenant_id, p.merchant_id)
        if category is None:
            raise EventRejected("unknown_merchant", f"merchant {p.merchant_id!r} not in reference data", p.tenant_id)
        if category != p.merchant_category.value:
            raise EventRejected(
                "merchant_category_mismatch",
                f"event says {p.merchant_category.value!r}, reference says {category!r}",
                p.tenant_id,
            )
        return env

    # ------------------------------------------------------------------ main entry point
    def process_batch(self, messages: list[RawMessage]) -> BatchResult:
        started = time.perf_counter()
        result = BatchResult(consumed=len(messages))
        now = self.clock()
        accepted: list[tuple[RawMessage, TransactionEnvelope, str, bool]] = []

        for msg in messages:
            try:
                env = self._validate(msg)
            except EventRejected as rej:
                m.VALIDATION_FAILURES.labels(rej.reason).inc()
                result.dead_letters.append(self._dead_letter(msg, rej.reason, rej.detail, rej.tenant_id))
                continue
            p = env.payload
            if p.event_timestamp > now + timedelta(minutes=5):
                result.dead_letters.append(
                    self._dead_letter(
                        msg,
                        "future_timestamp",
                        f"event_timestamp {p.event_timestamp.isoformat()} is in the future",
                        p.tenant_id,
                    )
                )
                continue
            # Kafka only orders events within a partition, so lateness is judged per partition.
            age = (now - p.event_timestamp).total_seconds()
            if age > self.settings.max_event_lateness_s:
                # Processing-time bound: an old event cannot set (or hide behind) a fresh watermark.
                result.dead_letters.append(
                    self._dead_letter(
                        msg, "stale_event", f"event is {age:.0f}s older than processing time", p.tenant_id
                    )
                )
                continue
            watermark = self.store.advance_watermark(f"{p.tenant_id}:p{msg.partition}", p.event_timestamp)
            lag = (watermark - p.event_timestamp).total_seconds()
            if lag > self.settings.max_event_lateness_s:
                result.dead_letters.append(
                    self._dead_letter(
                        msg, "stale_event", f"event is {lag:.0f}s behind the partition watermark", p.tenant_id
                    )
                )
                continue
            accepted.append((msg, env, payload_hash(p), lag > self.settings.late_event_tolerance_s))

        # ---- deduplicate against the database and within the batch
        with self.engine.connect() as conn:
            known = repo.existing_hashes(conn, [e.payload.transaction_id for _, e, _, _ in accepted])
        fresh: list[tuple[RawMessage, TransactionEnvelope, str, bool]] = []
        seen: dict[UUID, str] = {}
        for item in accepted:
            msg, env, h, late = item
            tid = env.payload.transaction_id
            prior = known.get(tid) or seen.get(tid)
            if prior is None:
                seen[tid] = h
                fresh.append(item)
            elif prior == h:
                result.duplicates += 1
            else:
                result.dead_letters.append(
                    self._dead_letter(
                        msg,
                        "conflicting_duplicate",
                        f"transaction_id {tid} re-used with different content",
                        env.payload.tenant_id,
                    )
                )

        # ---- features + scoring
        bundle, model_version_id = self.models.get() if fresh else (None, None)
        scored = []
        per_event_ms = 0.0
        if fresh and bundle is not None:
            feats = []
            for _, env, _, _ in fresh:
                p = env.payload
                ref = self.references.customer(p.tenant_id, p.customer_id)
                assert ref is not None
                feats.append((self.features.process(p, ref), p.merchant_category.value))
            t0 = time.perf_counter()
            scored = bundle.score_batch(feats)
            per_event_ms = (time.perf_counter() - t0) * 1000 / len(fresh)
            for _ in fresh:
                m.SCORING_SECONDS.observe(per_event_ms / 1000)

        # ---- persist atomically
        txn_rows, label_rows, pred_rows = [], [], []
        for (msg, env, h, late), s in zip(fresh, scored, strict=True):
            p = env.payload
            txn_rows.append(
                {
                    "transaction_id": p.transaction_id,
                    "tenant_id": p.tenant_id,
                    "event_id": env.event_id,
                    "schema_version": env.schema_version,
                    "event_timestamp": p.event_timestamp,
                    "customer_id": p.customer_id,
                    "merchant_id": p.merchant_id,
                    "merchant_category": p.merchant_category.value,
                    "amount": p.transaction_amount,
                    "currency": p.currency,
                    "country": p.transaction_country,
                    "device_id": p.device_id,
                    "payment_channel": p.payment_channel.value,
                    "status": p.transaction_status.value,
                    "is_late": late,
                    "payload_hash": h,
                    "kafka_partition": msg.partition,
                    "kafka_offset": msg.offset,
                }
            )
            if env.simulation is not None:
                label_rows.append(
                    {
                        "transaction_id": p.transaction_id,
                        "tenant_id": p.tenant_id,
                        "is_fraud": bool(env.simulation.ground_truth_label),
                        "scenario": env.simulation.scenario,
                    }
                )
            pred_rows.append(
                {
                    "transaction_id": p.transaction_id,
                    "tenant_id": p.tenant_id,
                    "model_version_id": model_version_id,
                    "risk_score": s.risk_score,
                    "probability": s.probability,
                    "risk_category": s.risk_category,
                    "features": s.features,
                    "explanation": s.explanation,
                    "scoring_latency_ms": round(per_event_ms, 3),
                }
            )

        with self.engine.begin() as conn:
            inserted = repo.insert_transactions(conn, txn_rows)
            # A concurrent writer may have won the race for some ids: treat those as duplicates.
            result.duplicates += len(txn_rows) - len(inserted)
            repo.insert_labels(conn, [r for r in label_rows if r["transaction_id"] in inserted])
            pred_ids = repo.insert_predictions(conn, [r for r in pred_rows if r["transaction_id"] in inserted])
            alert_rows = []
            for row, s in zip(pred_rows, scored, strict=True):
                pred_txn = row["transaction_id"]
                if s.is_alert and isinstance(pred_txn, UUID) and pred_txn in pred_ids:
                    severity = s.risk_category if s.risk_category in ("high", "critical") else "medium"
                    alert_rows.append(
                        {
                            "tenant_id": row["tenant_id"],
                            "transaction_id": pred_txn,
                            "prediction_id": pred_ids[pred_txn],
                            "severity": severity,
                        }
                    )
                    m.ALERTS_CREATED.labels(severity).inc()
            result.alerts = repo.insert_alerts(conn, alert_rows)
            repo.insert_dead_letters(conn, result.dead_letters)

        result.persisted = len(inserted)
        result.late = sum(1 for (_, env, _, late) in fresh if late and env.payload.transaction_id in inserted)
        result.processing_ms = (time.perf_counter() - started) * 1000

        # ---- metrics
        m.EVENTS_CONSUMED.inc(result.consumed)
        m.EVENTS_PERSISTED.inc(result.persisted)
        m.EVENTS_DUPLICATE.inc(result.duplicates)
        m.EVENTS_LATE.inc(result.late)
        for reason, n in result.reasons().items():
            m.EVENTS_DEAD_LETTERED.labels(reason).inc(n)
        for _, env, _, _ in fresh:
            m.END_TO_END_SECONDS.observe(max((datetime.now(UTC) - env.produced_at).total_seconds(), 0))
        for s in scored:
            m.RISK_SCORE.observe(s.risk_score)
        m.BATCH_SECONDS.observe(result.processing_ms / 1000)
        return result
