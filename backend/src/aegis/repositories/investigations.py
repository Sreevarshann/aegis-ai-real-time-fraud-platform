"""Investigations, users and audit-log persistence (tenant-scoped)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, insert, select, text, update

from aegis.db.tables import audit_events, investigations, users


def create_investigation(conn: Connection, row: dict[str, Any]) -> None:
    conn.execute(insert(investigations).values(**row))


def get_investigation(conn: Connection, tenant_id: str, investigation_id: UUID) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text("""
        SELECT i.*, u.full_name AS created_by_name
        FROM investigations i JOIN users u ON u.user_id = i.created_by
        WHERE i.tenant_id = :t AND i.investigation_id = :iid"""),
            {"t": tenant_id, "iid": investigation_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_investigations(conn: Connection, tenant_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        SELECT i.investigation_id, i.transaction_id, i.alert_id, i.engine, i.llm_model, i.priority,
               i.review_status, i.created_at, i.updated_at, i.duration_ms, u.full_name AS created_by_name,
               (i.report->>'risk_score')::int AS risk_score,
               jsonb_array_length(i.report->'suspicious_indicators') AS indicator_count
        FROM investigations i JOIN users u ON u.user_id = i.created_by
        WHERE i.tenant_id = :t ORDER BY i.created_at DESC LIMIT :limit"""),
        {"t": tenant_id, "limit": limit},
    )
    return [dict(r) for r in rows.mappings()]


def update_review(
    conn: Connection, tenant_id: str, investigation_id: UUID, review_status: str, notes: str | None
) -> bool:
    res = conn.execute(
        update(investigations)
        .where(investigations.c.tenant_id == tenant_id, investigations.c.investigation_id == investigation_id)
        .values(review_status=review_status, reviewer_notes=notes, updated_at=text("now()"))
    )
    return res.rowcount == 1


def get_user_by_email(conn: Connection, email: str) -> dict[str, Any] | None:
    row = conn.execute(select(users).where(users.c.email == email.lower())).mappings().first()
    return dict(row) if row else None


def get_user(conn: Connection, user_id: UUID) -> dict[str, Any] | None:
    row = conn.execute(select(users).where(users.c.user_id == user_id)).mappings().first()
    return dict(row) if row else None


def audit(
    conn: Connection,
    tenant_id: str | None,
    actor: UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        insert(audit_events).values(
            tenant_id=tenant_id,
            actor_user_id=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )


def recent_audit(conn: Connection, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
        SELECT a.audit_id, a.action, a.entity_type, a.entity_id, a.details, a.created_at, u.email AS actor
        FROM audit_events a LEFT JOIN users u ON u.user_id = a.actor_user_id
        WHERE a.tenant_id = :t ORDER BY a.created_at DESC LIMIT :limit"""),
        {"t": tenant_id, "limit": limit},
    )
    return [dict(r) for r in rows.mappings()]
