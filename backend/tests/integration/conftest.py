"""Integration fixtures: real PostgreSQL, Redis and Redpanda (start them with `make up` or `make infra`).

Everything runs in isolation from demo data: the `aegis_test` database (recreated via Alembic),
Redis logical DB 15, and per-session Kafka topic names.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

TEST_DB = os.environ.get(
    "AEGIS_TEST_DATABASE_URL", "postgresql+psycopg://aegis:aegis-local-dev-password@localhost:55432/aegis_test"
)
RUN = uuid.uuid4().hex[:8]
os.environ.update(
    {
        "AEGIS_DATABASE_URL": TEST_DB,
        "AEGIS_REDIS_URL": os.environ.get("AEGIS_TEST_REDIS_URL", "redis://localhost:56379/15"),
        "AEGIS_KAFKA_BOOTSTRAP_SERVERS": os.environ.get("AEGIS_TEST_KAFKA", "localhost:19092"),
        "AEGIS_KAFKA_TRANSACTIONS_TOPIC": f"test.transactions.{RUN}",
        "AEGIS_KAFKA_DLQ_TOPIC": f"test.dlq.{RUN}",
        "AEGIS_KAFKA_CONSUMER_GROUP": f"test-group-{RUN}",
        "AEGIS_LOG_JSON": "false",
        "AEGIS_OLLAMA_ENABLED": "false",
        "AEGIS_MLFLOW_TRACKING_URI": "http://127.0.0.1:9",  # deliberately unreachable: training must not depend on it
        "AEGIS_CONSUMER_METRICS_URL": "http://127.0.0.1:9/metrics",
    }
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import Engine, text  # noqa: E402

from aegis.config import get_settings  # noqa: E402
from aegis.db.engine import get_engine  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]


def _infra_available() -> str | None:
    import redis
    from confluent_kafka.admin import AdminClient

    try:
        get_engine().connect().close()
    except Exception as exc:
        return f"PostgreSQL unavailable at {TEST_DB}: {exc.__class__.__name__}"
    try:
        redis.Redis.from_url(os.environ["AEGIS_REDIS_URL"], socket_timeout=2).ping()
    except Exception as exc:
        return f"Redis unavailable: {exc}"
    try:
        AdminClient({"bootstrap.servers": os.environ["AEGIS_KAFKA_BOOTSTRAP_SERVERS"]}).list_topics(timeout=5)
    except Exception as exc:
        return f"Kafka unavailable: {exc}"
    return None


@pytest.fixture(scope="session")
def engine(tmp_path_factory) -> Iterator[Engine]:
    get_settings.cache_clear()
    get_engine.cache_clear()
    problem = _infra_available()
    if problem:
        if os.environ.get("AEGIS_REQUIRE_INTEGRATION") == "1":
            pytest.fail(problem)
        pytest.skip(problem)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = get_engine()

    from aegis.ml.train import register, train
    from aegis.seed import seed

    seed(eng)
    bundle, path = train(seed=5, customers_per_tenant=800, days=3, out_dir=tmp_path_factory.mktemp("models"))
    register(bundle, path, None)
    yield eng
    eng.dispose()


@pytest.fixture
def clean(engine: Engine) -> Engine:
    """Empty the event tables (keeps tenants, users, reference data and the model)."""
    import redis

    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE transactions, dead_letter_events, pipeline_stats, data_quality_results, "
                "audit_events, transformation_runs CASCADE"
            )
        )
    redis.Redis.from_url(os.environ["AEGIS_REDIS_URL"]).flushdb()
    return engine


@pytest.fixture
def settings():
    return get_settings()
