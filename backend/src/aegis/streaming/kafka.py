"""Thin, typed wrappers around confluent-kafka (librdkafka) for Redpanda."""

from __future__ import annotations

import time

from confluent_kafka import Consumer, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from aegis.config import Settings, get_settings
from aegis.observability.logging import get_logger

log = get_logger(__name__)


def make_producer(settings: Settings | None = None, client_id: str = "aegis-producer") -> Producer:
    s = settings or get_settings()
    return Producer(
        {
            "bootstrap.servers": s.kafka_bootstrap_servers,
            "client.id": client_id,
            # Idempotent producer: broker de-duplicates retried sends within a session.
            "enable.idempotence": True,
            "acks": "all",
            "linger.ms": 20,
            "compression.type": "lz4",
            "message.timeout.ms": 30_000,
        }
    )


def make_consumer(settings: Settings | None = None, group_id: str | None = None) -> Consumer:
    s = settings or get_settings()
    return Consumer(
        {
            "bootstrap.servers": s.kafka_bootstrap_servers,
            "group.id": group_id or s.kafka_consumer_group,
            "client.id": "aegis-consumer",
            # Offsets are committed manually, only after the batch is durably persisted.
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "enable.partition.eof": False,
            "max.poll.interval.ms": 300_000,
            "session.timeout.ms": 30_000,
            "isolation.level": "read_committed",
        }
    )


def ensure_topics(settings: Settings | None = None, retries: int = 30) -> None:
    """Create the transaction and dead-letter topics if missing (idempotent)."""
    s = settings or get_settings()
    admin = AdminClient({"bootstrap.servers": s.kafka_bootstrap_servers})
    wanted = {
        s.kafka_transactions_topic: NewTopic(
            s.kafka_transactions_topic, num_partitions=s.kafka_partitions, replication_factor=1
        ),
        s.kafka_dlq_topic: NewTopic(s.kafka_dlq_topic, num_partitions=1, replication_factor=1),
    }
    for attempt in range(1, retries + 1):
        try:
            existing = set(admin.list_topics(timeout=5).topics)
            missing = [t for name, t in wanted.items() if name not in existing]
            if missing:
                for name, fut in admin.create_topics(missing).items():
                    try:
                        fut.result()
                        log.info("topic_created", topic=name)
                    except KafkaException as exc:
                        if "TOPIC_ALREADY_EXISTS" not in str(exc):
                            raise
            return
        except Exception as exc:
            log.warning("kafka_not_ready", attempt=attempt, error=str(exc))
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"Kafka at {s.kafka_bootstrap_servers} unavailable after {retries} attempts")


def delivery_report(err: object, msg: object) -> None:
    if err is not None:
        log.error("kafka_delivery_failed", error=str(err))
