"""Operational data quality checks over the live pipeline's output.

Each check is one parameterised SQL query that returns an observed value; the check then
compares it with a threshold and records a pass / warn / fail row in
``data_quality_results``. Checks cover the classic dimensions: completeness, uniqueness,
validity, timeliness and consistency. dbt tests (see ``dbt/``) cover the analytical layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, text

from aegis.db.tables import data_quality_results
from aegis.observability import metrics as m
from aegis.observability.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Check:
    name: str
    dimension: str
    description: str
    sql: str
    # (observed) -> status; thresholds are stated so the UI can show them.
    warn_above: float | None = None
    fail_above: float | None = None
    fail_below: float | None = None

    def evaluate(self, observed: float | None) -> str:
        if observed is None:
            return "pass"
        if self.fail_above is not None and observed > self.fail_above:
            return "fail"
        if self.fail_below is not None and observed < self.fail_below:
            return "fail"
        if self.warn_above is not None and observed > self.warn_above:
            return "warn"
        return "pass"

    @property
    def threshold(self) -> float | None:
        return self.fail_above if self.fail_above is not None else self.fail_below


CHECKS: tuple[Check, ...] = (
    Check(
        "prediction_coverage_pct",
        "completeness",
        "Share of transactions in the last 24h that have a stored risk prediction",
        """SELECT 100.0 * count(p.prediction_id) / NULLIF(count(*), 0)
             FROM transactions t LEFT JOIN risk_predictions p USING (transaction_id)
             WHERE t.ingested_at > now() - interval '24 hours'""",
        fail_below=99.9,
    ),
    Check(
        "duplicate_event_ids",
        "uniqueness",
        "Event ids persisted more than once (should be impossible)",
        """SELECT count(*) FROM (SELECT event_id FROM transactions
             GROUP BY event_id HAVING count(*) > 1) d""",
        fail_above=0,
    ),
    Check(
        "dead_letter_rate_pct_1h",
        "validity",
        "Quarantined messages as a share of all messages in the last hour",
        """SELECT 100.0 * dl / NULLIF(dl + ok, 0) FROM
             (SELECT count(*) dl FROM dead_letter_events WHERE received_at > now() - interval '1 hour') a,
             (SELECT count(*) ok FROM transactions WHERE ingested_at > now() - interval '1 hour') b""",
        warn_above=2.0,
        fail_above=10.0,
    ),
    Check(
        "late_event_rate_pct_1h",
        "timeliness",
        "Accepted events flagged as arriving out of order in the last hour",
        """SELECT 100.0 * count(*) FILTER (WHERE is_late) / NULLIF(count(*), 0)
             FROM transactions WHERE ingested_at > now() - interval '1 hour'""",
        warn_above=5.0,
        fail_above=20.0,
    ),
    Check(
        "seconds_since_last_event",
        "timeliness",
        "Freshness: seconds since the most recent transaction was ingested",
        "SELECT EXTRACT(EPOCH FROM now() - max(ingested_at)) FROM transactions",
        warn_above=120,
        fail_above=900,
    ),
    Check(
        "alert_rate_pct_24h",
        "consistency",
        "Alerts as a share of scored transactions (guards against a broken or drifting model)",
        """SELECT 100.0 * count(a.alert_id) / NULLIF(count(*), 0) FROM risk_predictions p
             LEFT JOIN risk_alerts a USING (transaction_id) WHERE p.scored_at > now() - interval '24 hours'""",
        warn_above=10.0,
        fail_above=25.0,
    ),
    Check(
        "large_amount_outliers_24h",
        "validity",
        "Transactions above 50,000 (any currency) in the last 24h - plausible but worth eyeballing",
        """SELECT count(*) FROM transactions WHERE amount > 50000
             AND ingested_at > now() - interval '24 hours'""",
        warn_above=5,
    ),
    Check(
        "cross_tenant_reference_violations",
        "consistency",
        "Predictions or alerts whose tenant differs from their transaction's tenant",
        """SELECT (SELECT count(*) FROM risk_predictions p JOIN transactions t USING (transaction_id)
                     WHERE p.tenant_id <> t.tenant_id)
                  + (SELECT count(*) FROM risk_alerts a JOIN transactions t USING (transaction_id)
                     WHERE a.tenant_id <> t.tenant_id)""",
        fail_above=0,
    ),
    Check(
        "future_dated_transactions",
        "validity",
        "Persisted transactions with an event time more than 5 minutes in the future",
        "SELECT count(*) FROM transactions WHERE event_timestamp > now() + interval '5 minutes'",
        fail_above=0,
    ),
    Check(
        "failed_dbt_tests_latest_run",
        "consistency",
        "dbt tests that failed or errored in the most recent dbt invocation",
        """SELECT count(*) FROM transformation_runs WHERE resource_type = 'test'
             AND status IN ('fail', 'error') AND invocation_id = (
               SELECT invocation_id FROM transformation_runs ORDER BY completed_at DESC LIMIT 1)""",
        fail_above=0,
    ),
)


def run_data_quality(
    engine: Engine, checks: tuple[Check, ...] = CHECKS, on_result: Callable[[dict[str, Any]], None] | None = None
) -> list[dict[str, Any]]:
    run_id = uuid.uuid4()
    results: list[dict[str, Any]] = []
    with engine.begin() as conn:
        for check in checks:
            observed = _observe(conn, check)
            status = check.evaluate(observed)
            row = {
                "run_id": run_id,
                "tenant_id": None,
                "check_name": check.name,
                "dimension": check.dimension,
                "status": status,
                "observed_value": observed,
                "threshold": check.threshold,
                "details": {"description": check.description, "warn_above": check.warn_above},
            }
            results.append(row)
            m.DQ_CHECKS.labels(check.name, status).inc()
            if on_result:
                on_result(row)
        conn.execute(data_quality_results.insert(), results)
    failing = [r["check_name"] for r in results if r["status"] == "fail"]
    log.info(
        "data_quality_run", run_id=str(run_id), failing=failing, passed=sum(r["status"] == "pass" for r in results)
    )
    return results


def _observe(conn: Connection, check: Check) -> float | None:
    value = conn.execute(text(check.sql)).scalar()
    return None if value is None else round(float(value), 4)
