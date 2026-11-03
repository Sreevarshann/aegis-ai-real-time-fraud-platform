"""Tenant-scoped reads over transactions, predictions and alerts.

Every function takes ``tenant_id`` as a required argument and applies it in SQL; there is
no code path that reads business data without a tenant predicate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

_TXN_COLUMNS = """
    t.transaction_id, t.seq, t.event_timestamp, t.ingested_at, t.customer_id, t.merchant_id,
    m.name AS merchant_name, t.merchant_category, t.amount, t.currency, t.country, t.device_id,
    t.payment_channel, t.status, t.is_late, p.risk_score, p.risk_category, p.probability,
    p.scored_at, mv.version AS model_version, a.alert_id, a.status AS alert_status
"""
_TXN_FROM = """
    FROM transactions t
    JOIN merchants m ON m.tenant_id = t.tenant_id AND m.merchant_id = t.merchant_id
    LEFT JOIN risk_predictions p ON p.transaction_id = t.transaction_id
    LEFT JOIN model_versions mv ON mv.model_version_id = p.model_version_id
    LEFT JOIN risk_alerts a ON a.transaction_id = t.transaction_id
"""


def list_transactions(
    conn: Connection,
    tenant_id: str,
    *,
    limit: int,
    before_seq: int | None = None,
    after_seq: int | None = None,
    min_score: int | None = None,
    risk_category: str | None = None,
    search: str | None = None,
    channel: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["t.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": tenant_id, "limit": limit}
    if before_seq is not None:
        clauses.append("t.seq < :before_seq")
        params["before_seq"] = before_seq
    if after_seq is not None:
        clauses.append("t.seq > :after_seq")
        params["after_seq"] = after_seq
    if min_score is not None:
        clauses.append("p.risk_score >= :min_score")
        params["min_score"] = min_score
    if risk_category:
        clauses.append("p.risk_category = :cat")
        params["cat"] = risk_category
    if channel:
        clauses.append("t.payment_channel = :channel")
        params["channel"] = channel
    if status:
        clauses.append("t.status = :status")
        params["status"] = status
    if search:
        clauses.append(
            "(t.customer_id ILIKE :q OR t.merchant_id ILIKE :q OR m.name ILIKE :q "
            "OR t.device_id ILIKE :q OR t.transaction_id::text ILIKE :q)"
        )
        params["q"] = f"%{search}%"
    order = "ASC" if after_seq is not None else "DESC"
    sql = f"SELECT {_TXN_COLUMNS} {_TXN_FROM} WHERE {' AND '.join(clauses)} ORDER BY t.seq {order} LIMIT :limit"
    rows = [dict(r) for r in conn.execute(text(sql), params).mappings()]
    return rows if order == "DESC" else list(reversed(rows))


def get_transaction_detail(conn: Connection, tenant_id: str, transaction_id: UUID) -> dict[str, Any] | None:
    sql = f"""SELECT {_TXN_COLUMNS}, p.features, p.explanation, p.scoring_latency_ms,
                     mv.decision_threshold, t.kafka_partition, t.kafka_offset, t.payload_hash
              {_TXN_FROM} WHERE t.tenant_id = :tenant AND t.transaction_id = :tid"""
    row = conn.execute(text(sql), {"tenant": tenant_id, "tid": transaction_id}).mappings().first()
    return dict(row) if row else None


def list_alerts(
    conn: Connection, tenant_id: str, *, status: str | None, limit: int, offset: int
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"tenant": tenant_id, "limit": limit, "offset": offset}
    status_clause = ""
    if status:
        status_clause = "AND a.status = :status"
        params["status"] = status
    sql = f"""
        SELECT a.alert_id, a.status, a.severity, a.created_at, a.updated_at, t.transaction_id,
               t.event_timestamp, t.customer_id, t.merchant_id, m.name AS merchant_name, t.merchant_category,
               t.amount, t.currency, t.country, t.payment_channel, p.risk_score, p.risk_category,
               p.explanation,
               (SELECT i.investigation_id FROM investigations i WHERE i.tenant_id = a.tenant_id
                  AND i.transaction_id = a.transaction_id ORDER BY i.created_at DESC LIMIT 1) AS investigation_id,
               (SELECT i.priority FROM investigations i WHERE i.tenant_id = a.tenant_id
                  AND i.transaction_id = a.transaction_id ORDER BY i.created_at DESC LIMIT 1) AS investigation_priority
        FROM risk_alerts a
        JOIN transactions t ON t.transaction_id = a.transaction_id
        JOIN merchants m ON m.tenant_id = t.tenant_id AND m.merchant_id = t.merchant_id
        JOIN risk_predictions p ON p.prediction_id = a.prediction_id
        WHERE a.tenant_id = :tenant {status_clause}
        ORDER BY a.created_at DESC, a.alert_id DESC LIMIT :limit OFFSET :offset"""  # noqa: S608
    return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def alert_counts(conn: Connection, tenant_id: str) -> dict[str, int]:
    rows = conn.execute(
        text("SELECT status, count(*) FROM risk_alerts WHERE tenant_id = :tenant GROUP BY status"),
        {"tenant": tenant_id},
    )
    return {r[0]: int(r[1]) for r in rows}


def update_alert_status(conn: Connection, tenant_id: str, alert_id: int, status: str) -> bool:
    res = conn.execute(
        text("""UPDATE risk_alerts SET status = :status, updated_at = now()
                               WHERE tenant_id = :tenant AND alert_id = :aid"""),
        {"status": status, "tenant": tenant_id, "aid": alert_id},
    )
    return res.rowcount == 1


def alert_for_transaction(conn: Connection, tenant_id: str, transaction_id: UUID) -> int | None:
    return conn.execute(
        text("SELECT alert_id FROM risk_alerts WHERE tenant_id = :tenant AND transaction_id = :tid"),
        {"tenant": tenant_id, "tid": transaction_id},
    ).scalar()


def overview(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = (
        conn.execute(
            text("""
        SELECT
          (SELECT count(*) FROM transactions WHERE tenant_id = :t) AS total_transactions,
          (SELECT count(*) FROM transactions WHERE tenant_id = :t AND ingested_at > now() - interval '60 seconds')
              AS last_60s,
          (SELECT count(*) FROM transactions WHERE tenant_id = :t AND ingested_at > now() - interval '24 hours')
              AS last_24h,
          (SELECT coalesce(sum(amount), 0) FROM transactions WHERE tenant_id = :t
              AND ingested_at > now() - interval '24 hours') AS amount_24h,
          (SELECT count(*) FROM risk_alerts WHERE tenant_id = :t) AS total_alerts,
          (SELECT count(*) FROM risk_alerts WHERE tenant_id = :t AND status IN ('open', 'investigating', 'escalated'))
              AS open_alerts,
          (SELECT count(*) FROM risk_alerts WHERE tenant_id = :t AND created_at > now() - interval '24 hours')
              AS alerts_24h,
          (SELECT count(*) FROM investigations WHERE tenant_id = :t) AS investigations,
          (SELECT avg(risk_score) FROM risk_predictions WHERE tenant_id = :t
              AND scored_at > now() - interval '24 hours') AS avg_score_24h,
          (SELECT max(ingested_at) FROM transactions WHERE tenant_id = :t) AS last_ingested_at
    """),
            {"t": tenant_id},
        )
        .mappings()
        .one()
    )
    return dict(row)


def risk_distribution(conn: Connection, tenant_id: str, hours: int = 24) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        SELECT width_bucket(risk_score, 0, 101, 10) AS bucket, count(*) AS n
        FROM risk_predictions WHERE tenant_id = :t AND scored_at > now() - make_interval(hours => :h)
        GROUP BY 1 ORDER BY 1"""),
        {"t": tenant_id, "h": hours},
    ).mappings()
    counts = {int(r["bucket"]): int(r["n"]) for r in rows}
    return [
        {"range": f"{(b - 1) * 10}-{b * 10 - 1 if b < 10 else 100}", "count": counts.get(b, 0)} for b in range(1, 11)
    ]


def category_breakdown(conn: Connection, tenant_id: str, hours: int = 24) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        SELECT risk_category, count(*) AS n FROM risk_predictions
        WHERE tenant_id = :t AND scored_at > now() - make_interval(hours => :h)
        GROUP BY 1"""),
        {"t": tenant_id, "h": hours},
    ).mappings()
    counts = {r["risk_category"]: int(r["n"]) for r in rows}
    return [{"category": c, "count": counts.get(c, 0)} for c in ("low", "medium", "high", "critical")]


def volume_series(conn: Connection, tenant_id: str, minutes: int, bucket_seconds: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        WITH buckets AS (
          SELECT generate_series(
            to_timestamp(floor(extract(epoch FROM now() - make_interval(mins => :m)) / :b) * :b),
            to_timestamp(floor(extract(epoch FROM now()) / :b) * :b),
            make_interval(secs => :b)) AS bucket
        ), agg AS (
          SELECT to_timestamp(floor(extract(epoch FROM t.ingested_at) / :b) * :b) AS bucket,
                 count(*) AS transactions, count(a.alert_id) AS alerts, coalesce(sum(t.amount), 0) AS amount
          FROM transactions t LEFT JOIN risk_alerts a ON a.transaction_id = t.transaction_id
          WHERE t.tenant_id = :t AND t.ingested_at > now() - make_interval(mins => :m)
          GROUP BY 1
        )
        SELECT b.bucket, coalesce(a.transactions, 0) AS transactions, coalesce(a.alerts, 0) AS alerts,
               coalesce(a.amount, 0) AS amount
        FROM buckets b LEFT JOIN agg a USING (bucket) ORDER BY b.bucket"""),
        {"t": tenant_id, "m": minutes, "b": bucket_seconds},
    ).mappings()
    return [dict(r) for r in rows]


def live_label_performance(conn: Connection, tenant_id: str, since: datetime) -> dict[str, Any]:
    """Live precision/recall against *simulation* ground truth (only possible because data is synthetic)."""
    row = (
        conn.execute(
            text("""
        SELECT count(*) FILTER (WHERE l.is_fraud AND a.alert_id IS NOT NULL) AS tp,
               count(*) FILTER (WHERE NOT l.is_fraud AND a.alert_id IS NOT NULL) AS fp,
               count(*) FILTER (WHERE l.is_fraud AND a.alert_id IS NULL) AS fn,
               count(*) FILTER (WHERE NOT l.is_fraud AND a.alert_id IS NULL) AS tn
        FROM simulation_labels l
        JOIN transactions t ON t.transaction_id = l.transaction_id
        LEFT JOIN risk_alerts a ON a.transaction_id = l.transaction_id
        WHERE l.tenant_id = :t AND t.ingested_at >= :since"""),
            {"t": tenant_id, "since": since},
        )
        .mappings()
        .one()
    )
    return {k: int(v) for k, v in row.items()}
