"""Evidence-retrieval tools used by the investigation graph.

Every tool is a tenant-scoped, parameterised read against PostgreSQL that returns an
:class:`Evidence` item carrying the database identifiers it was derived from. Nothing in an
investigation report may be stated unless it came out of one of these tools.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text


@dataclass
class Evidence:
    id: str
    tool: str
    title: str
    summary: str
    record_ids: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "title": self.title,
            "summary": self.summary,
            "record_ids": self.record_ids,
            "data": self.data,
        }


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def get_transaction(conn: Connection, tenant_id: str, transaction_id: UUID) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text("""
        SELECT t.transaction_id, t.seq, t.event_timestamp, t.ingested_at, t.customer_id, t.merchant_id,
               m.name AS merchant_name, t.merchant_category, t.amount, t.currency, t.country, t.device_id,
               t.payment_channel, t.status, t.is_late
        FROM transactions t
        JOIN merchants m ON m.tenant_id = t.tenant_id AND m.merchant_id = t.merchant_id
        WHERE t.tenant_id = :tenant AND t.transaction_id = :tid"""),
            {"tenant": tenant_id, "tid": transaction_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_prediction(conn: Connection, tenant_id: str, transaction_id: UUID) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text("""
        SELECT p.prediction_id, p.risk_score, p.probability, p.risk_category, p.explanation, p.features,
               p.scored_at, mv.version AS model_version, mv.algorithm, mv.decision_threshold,
               a.alert_id, a.severity AS alert_severity, a.status AS alert_status
        FROM risk_predictions p
        JOIN model_versions mv USING (model_version_id)
        LEFT JOIN risk_alerts a ON a.transaction_id = p.transaction_id AND a.tenant_id = p.tenant_id
        WHERE p.tenant_id = :tenant AND p.transaction_id = :tid"""),
            {"tenant": tenant_id, "tid": transaction_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_customer_profile(conn: Connection, tenant_id: str, customer_id: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text("""
        SELECT customer_id, home_country, registered_devices, account_opened_at, avg_ticket_usd
        FROM customers WHERE tenant_id = :tenant AND customer_id = :cid"""),
            {"tenant": tenant_id, "cid": customer_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_customer_history(
    conn: Connection, tenant_id: str, customer_id: str, before: datetime, days: int = 30, limit: int = 200
) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            text("""
        SELECT t.transaction_id, t.event_timestamp, t.amount, t.currency, t.country, t.device_id,
               t.merchant_id, t.merchant_category, t.payment_channel, t.status, p.risk_score
        FROM transactions t LEFT JOIN risk_predictions p USING (transaction_id)
        WHERE t.tenant_id = :tenant AND t.customer_id = :cid
          AND t.event_timestamp < :before AND t.event_timestamp >= :since
        ORDER BY t.event_timestamp DESC LIMIT :limit"""),
            {
                "tenant": tenant_id,
                "cid": customer_id,
                "before": before,
                "since": before - timedelta(days=days),
                "limit": limit,
            },
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_device_activity(
    conn: Connection, tenant_id: str, device_id: str, around: datetime, hours: int = 24
) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            text("""
        SELECT transaction_id, customer_id, event_timestamp, amount, currency, merchant_id
        FROM transactions
        WHERE tenant_id = :tenant AND device_id = :dev
          AND event_timestamp BETWEEN :lo AND :hi
        ORDER BY event_timestamp"""),
            {
                "tenant": tenant_id,
                "dev": device_id,
                "lo": around - timedelta(hours=hours),
                "hi": around + timedelta(hours=1),
            },
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_merchant_activity(conn: Connection, tenant_id: str, merchant_id: str, around: datetime) -> dict[str, Any]:
    row = (
        conn.execute(
            text("""
        SELECT count(*) AS txns_1h,
               count(DISTINCT customer_id) AS customers_1h,
               count(*) FILTER (WHERE status = 'declined') AS declined_1h,
               (SELECT count(*) FROM risk_alerts a JOIN transactions t2 USING (transaction_id)
                 WHERE t2.tenant_id = :tenant AND t2.merchant_id = :mid
                   AND t2.event_timestamp BETWEEN :lo24 AND :hi) AS alerts_24h,
               (SELECT count(*) FROM transactions t3 WHERE t3.tenant_id = :tenant AND t3.merchant_id = :mid
                   AND t3.event_timestamp BETWEEN :lo24 AND :hi) AS txns_24h,
               array_agg(transaction_id::text ORDER BY event_timestamp) AS ids_1h
        FROM transactions
        WHERE tenant_id = :tenant AND merchant_id = :mid AND event_timestamp BETWEEN :lo AND :hi"""),
            {
                "tenant": tenant_id,
                "mid": merchant_id,
                "lo": around - timedelta(hours=1),
                "lo24": around - timedelta(hours=24),
                "hi": around + timedelta(minutes=10),
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def get_prior_alerts(conn: Connection, tenant_id: str, customer_id: str, before: datetime) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            text("""
        SELECT a.alert_id, a.transaction_id, a.severity, a.status, a.created_at
        FROM risk_alerts a JOIN transactions t USING (transaction_id)
        WHERE a.tenant_id = :tenant AND t.customer_id = :cid AND t.event_timestamp < :before
        ORDER BY a.created_at DESC LIMIT 20"""),
            {"tenant": tenant_id, "cid": customer_id, "before": before},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def summarize_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    if not history:
        return {"count_30d": 0}
    amounts = [float(h["amount"]) for h in history]
    return {
        "count_30d": len(history),
        "median_amount": round(statistics.median(amounts), 2),
        "max_amount": round(max(amounts), 2),
        "countries": sorted({h["country"] for h in history}),
        "devices": sorted({h["device_id"] for h in history}),
        "first_seen": _iso(min(h["event_timestamp"] for h in history)),
    }
