"""dbt transformations run against the integration database (skipped if dbt is not installed)."""

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest
import redis
from sqlalchemy import text

from aegis.features.store import RedisFeatureStore
from aegis.streaming.processor import TransactionProcessor

from .helpers import recent_events, to_messages

pytestmark = pytest.mark.integration
DBT_DIR = Path(__file__).resolve().parents[3] / "dbt"


def dbt_binary() -> str | None:
    local = DBT_DIR / ".venv" / "bin" / "dbt"
    return os.environ.get("DBT_BIN") or (str(local) if local.exists() else shutil.which("dbt"))


def test_dbt_models_and_tests_pass_and_reconcile(clean, settings):
    dbt = dbt_binary()
    if dbt is None:
        pytest.skip("dbt is not installed (pip install -r dbt/requirements.txt)")
    proc = TransactionProcessor(settings, clean, RedisFeatureStore(redis.Redis.from_url(settings.redis_url)))
    proc.process_batch(to_messages(recent_events(200, seed=41)))
    url = urlparse(settings.database_url.replace("postgresql+psycopg", "postgresql"))
    env = os.environ | {
        "DBT_HOST": url.hostname or "localhost",
        "DBT_PORT": str(url.port or 5432),
        "DBT_USER": url.username or "aegis",
        "DBT_PASSWORD": url.password or "",
        "DBT_DBNAME": url.path.lstrip("/"),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
    }
    run = subprocess.run(
        [dbt, "build", "--profiles-dir", "."],
        cwd=DBT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 0, run.stdout[-3000:]
    assert "ERROR=0" in run.stdout
    with clean.connect() as conn:
        staged = conn.execute(text("SELECT count(*) FROM transactions")).scalar_one()
        hourly = conn.execute(text("SELECT sum(transactions) FROM analytics.fct_hourly_volume")).scalar_one()
        bands = conn.execute(text("SELECT count(*) FROM analytics.fct_risk_distribution")).scalar_one()
        tenants = conn.execute(text("SELECT count(DISTINCT tenant_id) FROM analytics.fct_daily_summary")).scalar_one()
    assert hourly == staged == 200
    assert bands == 10 * tenants
