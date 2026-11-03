"""Model registry, data-quality, pipeline, dead-letter and dbt-mart reads."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text


def model_versions(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        SELECT model_version_id, version, algorithm, decision_threshold, is_active, created_at, mlflow_run_id,
               metrics - 'reference' - 'feature_importance' AS metrics
        FROM model_versions ORDER BY created_at DESC""")
    )
    return [dict(r) for r in rows.mappings()]


def active_model_detail(conn: Connection) -> dict[str, Any] | None:
    row = conn.execute(text("SELECT * FROM model_versions WHERE is_active")).mappings().first()
    return dict(row) if row else None


def recent_score_histogram(conn: Connection, model_version_id: int, tenant_id: str | None, limit: int) -> list[float]:
    tenant_clause = "AND tenant_id = :t" if tenant_id else ""
    rows = conn.execute(
        text(f"""
        SELECT probability FROM risk_predictions WHERE model_version_id = :mv {tenant_clause}
        ORDER BY prediction_id DESC LIMIT :limit"""),  # noqa: S608 - clause is a constant
        {"mv": model_version_id, "t": tenant_id, "limit": limit},
    )
    return [float(r[0]) for r in rows]


def recent_feature_values(conn: Connection, model_version_id: int, feature: str, limit: int) -> list[float | None]:
    rows = conn.execute(
        text("""
        SELECT (features->>:f)::float FROM risk_predictions WHERE model_version_id = :mv
        ORDER BY prediction_id DESC LIMIT :limit"""),
        {"f": feature, "mv": model_version_id, "limit": limit},
    )
    return [r[0] for r in rows]


def latest_dq_results(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        SELECT result_id, run_id, check_name, dimension, status, observed_value, threshold, details, checked_at
        FROM data_quality_results
        WHERE run_id = (SELECT run_id FROM data_quality_results ORDER BY checked_at DESC LIMIT 1)
        ORDER BY dimension, check_name""")
    )
    return [dict(r) for r in rows.mappings()]


def dq_history(conn: Connection, hours: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        SELECT run_id, min(checked_at) AS checked_at,
               count(*) FILTER (WHERE status = 'pass') AS passed,
               count(*) FILTER (WHERE status = 'warn') AS warned,
               count(*) FILTER (WHERE status = 'fail') AS failed
        FROM data_quality_results WHERE checked_at > now() - make_interval(hours => :h)
        GROUP BY run_id ORDER BY 2 DESC LIMIT 120"""),
        {"h": hours},
    )
    return list(reversed([dict(r) for r in rows.mappings()]))


def dead_letters(conn: Connection, tenant_id: str, include_unattributed: bool, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        SELECT dead_letter_id, tenant_id, reason, error_detail, left(raw_payload, 600) AS raw_payload,
               source_topic, source_partition, source_offset, received_at
        FROM dead_letter_events
        WHERE tenant_id = :t OR (:unattributed AND tenant_id IS NULL)
        ORDER BY received_at DESC, dead_letter_id DESC LIMIT :limit"""),
        {"t": tenant_id, "unattributed": include_unattributed, "limit": limit},
    )
    return [dict(r) for r in rows.mappings()]


def dead_letter_reasons(conn: Connection, tenant_id: str, include_unattributed: bool) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        SELECT reason, count(*) AS count, max(received_at) AS last_seen FROM dead_letter_events
        WHERE tenant_id = :t OR (:unattributed AND tenant_id IS NULL)
        GROUP BY reason ORDER BY count DESC"""),
        {"t": tenant_id, "unattributed": include_unattributed},
    )
    return [dict(r) for r in rows.mappings()]


def pipeline_windows(conn: Connection, minutes: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        SELECT window_started_at, window_ended_at, consumed, persisted, duplicates, dead_lettered, late, errors,
               consumer_lag, avg_processing_ms, instance_id
        FROM pipeline_stats WHERE window_ended_at > now() - make_interval(mins => :m)
        ORDER BY window_ended_at"""),
        {"m": minutes},
    )
    return [dict(r) for r in rows.mappings()]


def pipeline_totals(conn: Connection) -> dict[str, Any]:
    row = (
        conn.execute(
            text("""
        SELECT coalesce(sum(consumed), 0) AS consumed, coalesce(sum(persisted), 0) AS persisted,
               coalesce(sum(duplicates), 0) AS duplicates, coalesce(sum(dead_lettered), 0) AS dead_lettered,
               coalesce(sum(late), 0) AS late, coalesce(sum(errors), 0) AS errors,
               max(window_ended_at) AS last_heartbeat,
               (SELECT consumer_lag FROM pipeline_stats ORDER BY window_ended_at DESC LIMIT 1) AS consumer_lag
        FROM pipeline_stats""")
        )
        .mappings()
        .one()
    )
    return dict(row)


def transformation_runs(conn: Connection, limit_invocations: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        WITH inv AS (
          SELECT invocation_id, max(completed_at) AS completed_at FROM transformation_runs
          GROUP BY invocation_id ORDER BY 2 DESC LIMIT :n)
        SELECT r.invocation_id, inv.completed_at AS invocation_completed_at, r.node_id, r.resource_type, r.status,
               r.execution_time_s, r.rows_affected, r.message
        FROM transformation_runs r JOIN inv USING (invocation_id)
        ORDER BY inv.completed_at DESC, r.resource_type, r.node_id"""),
        {"n": limit_invocations},
    )
    return [dict(r) for r in rows.mappings()]


def mart_exists(conn: Connection, name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"analytics.{name}"}).scalar())


# dbt marts are tenant-keyed; every query below filters on tenant_id.
MART_QUERIES: dict[str, str] = {
    "hourly_volume": """SELECT hour, transactions, total_amount_usd, alerts, avg_risk_score
                        FROM analytics.fct_hourly_volume WHERE tenant_id = :t ORDER BY hour DESC LIMIT 48""",
    "fraud_rate_trend": """SELECT day, transactions, labelled_fraud, alerts, true_positives,
                                  simulated_fraud_rate, alert_rate, alert_precision
                           FROM analytics.fct_fraud_rate_daily WHERE tenant_id = :t ORDER BY day DESC LIMIT 30""",
    "risk_by_category": """SELECT merchant_category, transactions, avg_risk_score, high_risk_share, alerts,
                                  total_amount_usd FROM analytics.fct_risk_by_category WHERE tenant_id = :t
                           ORDER BY avg_risk_score DESC""",
    "risk_distribution": """SELECT score_band, transactions, share FROM analytics.fct_risk_distribution
                            WHERE tenant_id = :t ORDER BY band_floor""",
    "daily_summary": """SELECT day, transactions, customers, merchants, total_amount_usd, declined_share,
                               late_share, alerts FROM analytics.fct_daily_summary WHERE tenant_id = :t
                        ORDER BY day DESC LIMIT 14""",
    "top_customers": """SELECT customer_id, transactions, total_amount_usd, avg_amount_usd, distinct_devices,
                               distinct_countries, max_risk_score, alerts
                        FROM analytics.dim_customer_behavior WHERE tenant_id = :t
                        ORDER BY max_risk_score DESC, transactions DESC LIMIT 15""",
    "completeness": """SELECT check_name, total_rows, failing_rows, pass_rate FROM analytics.dq_completeness
                       WHERE tenant_id = :t ORDER BY check_name""",
}


def mart(conn: Connection, tenant_id: str, name: str) -> list[dict[str, Any]] | None:
    sql = MART_QUERIES[name]
    table = sql.split("FROM analytics.")[1].split()[0]
    if not mart_exists(conn, table):
        return None
    return [dict(r) for r in conn.execute(text(sql), {"t": tenant_id}).mappings()]
