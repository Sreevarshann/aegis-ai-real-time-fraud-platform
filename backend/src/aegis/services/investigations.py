"""Investigation orchestration: run the LangGraph engine, persist the report, update the alert."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import Engine

from aegis.config import Settings
from aegis.investigation.graph import InvestigationEngine
from aegis.repositories import investigations as inv_repo
from aegis.repositories import transactions as txn_repo


class TransactionNotFound(Exception):
    pass


_engine_cache: dict[int, InvestigationEngine] = {}


def _graph(engine: Engine, settings: Settings) -> InvestigationEngine:
    key = id(engine)
    if key not in _engine_cache:
        _engine_cache[key] = InvestigationEngine(engine, settings)
    return _engine_cache[key]


def run_investigation(
    engine: Engine, settings: Settings, tenant_id: str, user_id: UUID, transaction_id: UUID
) -> dict[str, Any]:
    state = _graph(engine, settings).run(tenant_id, transaction_id)
    if not state.get("transaction"):
        raise TransactionNotFound(str(transaction_id))
    report = state["report"]
    investigation_id = uuid.uuid4()
    with engine.begin() as conn:
        alert_id = txn_repo.alert_for_transaction(conn, tenant_id, transaction_id)
        inv_repo.create_investigation(
            conn,
            {
                "investigation_id": investigation_id,
                "tenant_id": tenant_id,
                "alert_id": alert_id,
                "transaction_id": transaction_id,
                "created_by": user_id,
                "engine": report["engine"],
                "llm_model": report["llm_model"],
                "priority": report["recommended_priority"],
                "report": report,
                "duration_ms": round(state.get("duration_ms", 0.0), 2),
            },
        )
        if alert_id is not None:
            txn_repo.update_alert_status(conn, tenant_id, alert_id, "investigating")
        inv_repo.audit(
            conn,
            tenant_id,
            user_id,
            "investigation_created",
            "investigation",
            str(investigation_id),
            {
                "transaction_id": str(transaction_id),
                "engine": report["engine"],
                "priority": report["recommended_priority"],
            },
        )
        detail = inv_repo.get_investigation(conn, tenant_id, investigation_id)
    assert detail is not None
    return detail


REVIEW_TO_ALERT = {
    "escalated": "escalated",
    "closed_fraud": "confirmed_fraud",
    "closed_legitimate": "dismissed",
    "in_review": "investigating",
}


def review(
    engine: Engine, tenant_id: str, user_id: UUID, investigation_id: UUID, review_status: str, notes: str | None
) -> dict[str, Any] | None:
    with engine.begin() as conn:
        if not inv_repo.update_review(conn, tenant_id, investigation_id, review_status, notes):
            return None
        detail = inv_repo.get_investigation(conn, tenant_id, investigation_id)
        assert detail is not None
        if detail["alert_id"] and review_status in REVIEW_TO_ALERT:
            txn_repo.update_alert_status(conn, tenant_id, detail["alert_id"], REVIEW_TO_ALERT[review_status])
        inv_repo.audit(
            conn,
            tenant_id,
            user_id,
            "investigation_reviewed",
            "investigation",
            str(investigation_id),
            {"review_status": review_status},
        )
    return detail
