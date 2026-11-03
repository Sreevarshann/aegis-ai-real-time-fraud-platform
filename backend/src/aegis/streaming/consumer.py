"""Kafka consumer service: poll -> process batch -> persist -> publish DLQ -> commit offsets.

Delivery semantics: at-least-once from Kafka, made effectively-once for persisted state by
the idempotent processor (primary-key dedup + idempotent feature-store writes). Offsets are
committed synchronously and only after the database transaction succeeds, so a crash at any
point causes redelivery, never loss.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import threading
import time
from datetime import UTC, datetime

import redis
from confluent_kafka import KafkaError, TopicPartition
from prometheus_client import start_http_server
from sqlalchemy.exc import OperationalError

from aegis.config import Settings, get_settings
from aegis.db.engine import get_engine
from aegis.features.store import RedisFeatureStore
from aegis.observability import metrics as m
from aegis.observability.logging import configure_logging, get_logger
from aegis.quality.checks import run_data_quality
from aegis.repositories import pipeline as repo
from aegis.streaming.kafka import ensure_topics, make_consumer, make_producer
from aegis.streaming.processor import BatchResult, RawMessage, TransactionProcessor

log = get_logger(__name__)
MAX_RETRIES = 5


class StatsWindow:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.started = datetime.now(UTC)
        self.consumed = self.persisted = self.duplicates = self.dead = self.late = self.errors = 0
        self.ms_total = 0.0
        self.batches = 0

    def add(self, r: BatchResult) -> None:
        self.consumed += r.consumed
        self.persisted += r.persisted
        self.duplicates += r.duplicates
        self.dead += r.dead_lettered
        self.late += r.late
        self.ms_total += r.processing_ms
        self.batches += 1


class ConsumerService:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.engine = get_engine()
        self.redis = redis.Redis.from_url(settings.redis_url)
        self.processor = TransactionProcessor(settings, self.engine, RedisFeatureStore(self.redis))
        self.consumer = make_consumer(settings)
        self.dlq_producer = make_producer(settings, "aegis-dlq-producer")
        self.running = True
        self.instance_id = f"{socket.gethostname()}-{os.getpid()}"
        self.window = StatsWindow()

    def stop(self, *_: object) -> None:
        log.info("shutdown_requested")
        self.running = False

    def _publish_dlq(self, result: BatchResult) -> None:
        for d in result.dead_letters:
            self.dlq_producer.produce(
                self.s.kafka_dlq_topic, value=json.dumps(d, default=str).encode(), headers={"reason": d["reason"]}
            )
        if result.dead_letters and self.dlq_producer.flush(15):
            raise RuntimeError("DLQ publish did not complete; refusing to commit offsets")

    def _lag(self) -> int | None:
        try:
            total = 0
            for tp in self.consumer.assignment():
                _, high = self.consumer.get_watermark_offsets(tp, timeout=2, cached=False)
                pos = self.consumer.position([tp])[0].offset
                total += max(high - pos, 0) if pos >= 0 else high
            return total
        except Exception:
            return None

    def _flush_stats(self) -> None:
        w = self.window
        lag = self._lag()
        if lag is not None:
            m.CONSUMER_LAG.set(lag)
        try:
            with self.engine.begin() as conn:
                repo.insert_pipeline_stats(
                    conn,
                    {
                        "component": "risk-scoring-consumer",
                        "instance_id": self.instance_id,
                        "window_started_at": w.started,
                        "window_ended_at": datetime.now(UTC),
                        "consumed": w.consumed,
                        "persisted": w.persisted,
                        "duplicates": w.duplicates,
                        "dead_lettered": w.dead,
                        "late": w.late,
                        "errors": w.errors,
                        "consumer_lag": lag,
                        "avg_processing_ms": (w.ms_total / w.batches) if w.batches else None,
                    },
                )
        except Exception as exc:
            log.warning("stats_flush_failed", error=str(exc))
        w.reset()

    def _process_with_retry(self, batch: list[RawMessage]) -> BatchResult:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self.processor.process_batch(batch)
            except (OperationalError, redis.ConnectionError, redis.TimeoutError) as exc:
                m.PROCESSING_ERRORS.labels("infrastructure").inc()
                self.window.errors += 1
                log.warning("batch_retry", attempt=attempt, error=str(exc)[:300])
                time.sleep(min(2**attempt, 30))
        raise RuntimeError("batch failed after retries; exiting without committing so it is redelivered")

    def _dq_loop(self) -> None:
        while self.running:
            time.sleep(self.s.data_quality_interval_s)
            try:
                run_data_quality(self.engine)
            except Exception as exc:
                log.warning("data_quality_run_failed", error=str(exc))

    def run(self) -> None:
        ensure_topics(self.s)
        start_http_server(self.s.consumer_metrics_port)
        self.consumer.subscribe(
            [self.s.kafka_transactions_topic],
            on_assign=lambda c, parts: log.info("partitions_assigned", partitions=[p.partition for p in parts]),
            on_revoke=lambda c, parts: log.info("partitions_revoked", partitions=[p.partition for p in parts]),
        )
        threading.Thread(target=self._dq_loop, daemon=True, name="dq").start()
        log.info("consumer_started", topic=self.s.kafka_transactions_topic, group=self.s.kafka_consumer_group)
        last_flush = time.monotonic()
        try:
            while self.running:
                msgs = self.consumer.consume(self.s.consumer_batch_size, self.s.consumer_poll_timeout_s)
                batch: list[RawMessage] = []
                for msg in msgs:
                    err = msg.error()
                    if err is not None:
                        if err.code() != KafkaError._PARTITION_EOF:
                            m.PROCESSING_ERRORS.labels("kafka").inc()
                            log.error("kafka_error", error=str(err))
                        continue
                    batch.append(
                        RawMessage(msg.value() or b"", msg.topic() or "", msg.partition(), msg.offset(), msg.key())
                    )
                if batch:
                    result = self._process_with_retry(batch)
                    self._publish_dlq(result)
                    # Commit the next offset per partition, synchronously, after persistence.
                    offsets: dict[int, int] = {}
                    for b in batch:
                        offsets[b.partition or 0] = max(offsets.get(b.partition or 0, -1), (b.offset or 0) + 1)
                    self.consumer.commit(
                        offsets=[TopicPartition(self.s.kafka_transactions_topic, p, o) for p, o in offsets.items()],
                        asynchronous=False,
                    )
                    self.window.add(result)
                    if result.dead_lettered or result.duplicates:
                        log.info(
                            "batch_processed",
                            consumed=result.consumed,
                            persisted=result.persisted,
                            duplicates=result.duplicates,
                            dead_letters=result.reasons(),
                            late=result.late,
                            alerts=result.alerts,
                            ms=round(result.processing_ms, 1),
                        )
                if time.monotonic() - last_flush >= 10:
                    self._flush_stats()
                    last_flush = time.monotonic()
        finally:
            self._flush_stats()
            self.consumer.close()
            log.info("consumer_stopped")


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    svc = ConsumerService(s)
    signal.signal(signal.SIGTERM, svc.stop)
    signal.signal(signal.SIGINT, svc.stop)
    svc.run()


if __name__ == "__main__":
    main()
