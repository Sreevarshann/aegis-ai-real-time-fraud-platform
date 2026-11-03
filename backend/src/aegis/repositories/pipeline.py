"""Persistence for the streaming path. All statements are parameterised SQLAlchemy Core."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from aegis.db.tables import (
    customers,
    dead_letter_events,
    merchants,
    model_versions,
    pipeline_stats,
    risk_alerts,
    risk_predictions,
    simulation_labels,
    tenants,
    transactions,
)
from aegis.features.compute import CustomerReference


def tenant_ids(conn: Connection) -> set[str]:
    return set(conn.execute(select(tenants.c.tenant_id)).scalars())


def load_customer_references(conn: Connection, tenant_id: str) -> dict[str, CustomerReference]:
    rows = conn.execute(select(customers).where(customers.c.tenant_id == tenant_id))
    return {
        r.customer_id: CustomerReference(
            r.home_country, frozenset(r.registered_devices), r.account_opened_at, float(r.avg_ticket_usd)
        )
        for r in rows
    }


def load_merchant_categories(conn: Connection, tenant_id: str) -> dict[str, str]:
    rows = conn.execute(select(merchants.c.merchant_id, merchants.c.category).where(merchants.c.tenant_id == tenant_id))
    return {r.merchant_id: r.category for r in rows}


def active_model(conn: Connection) -> Any | None:
    return conn.execute(select(model_versions).where(model_versions.c.is_active)).first()


def existing_hashes(conn: Connection, ids: Sequence[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = conn.execute(
        select(transactions.c.transaction_id, transactions.c.payload_hash).where(
            transactions.c.transaction_id.in_(list(ids))
        )
    )
    return {r.transaction_id: r.payload_hash for r in rows}


def insert_transactions(conn: Connection, rows: list[dict[str, Any]]) -> set[UUID]:
    """Insert, skipping ids that already exist. Returns the ids actually inserted."""
    if not rows:
        return set()
    stmt = (
        pg_insert(transactions)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[transactions.c.transaction_id])
        .returning(transactions.c.transaction_id)
    )
    return set(conn.execute(stmt).scalars())


def insert_labels(conn: Connection, rows: list[dict[str, Any]]) -> None:
    if rows:
        conn.execute(pg_insert(simulation_labels).values(rows).on_conflict_do_nothing())


def insert_predictions(conn: Connection, rows: list[dict[str, Any]]) -> dict[UUID, int]:
    if not rows:
        return {}
    stmt = (
        pg_insert(risk_predictions)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[risk_predictions.c.transaction_id])
        .returning(risk_predictions.c.transaction_id, risk_predictions.c.prediction_id)
    )
    return {r.transaction_id: r.prediction_id for r in conn.execute(stmt)}


def insert_alerts(conn: Connection, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stmt = (
        pg_insert(risk_alerts)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[risk_alerts.c.transaction_id])
        .returning(risk_alerts.c.alert_id)
    )
    return len(conn.execute(stmt).all())


def insert_dead_letters(conn: Connection, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stmt = (
        pg_insert(dead_letter_events)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=[
                dead_letter_events.c.source_topic,
                dead_letter_events.c.source_partition,
                dead_letter_events.c.source_offset,
            ]
        )
        .returning(dead_letter_events.c.dead_letter_id)
    )
    return len(conn.execute(stmt).all())


def insert_pipeline_stats(conn: Connection, row: dict[str, Any]) -> None:
    conn.execute(pipeline_stats.insert().values(**row))
