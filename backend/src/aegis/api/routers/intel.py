"""Investigations, model intelligence, data intelligence, operations and simulator control."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine

from aegis.api.deps import Principal, current_user, db_engine, require_role, settings
from aegis.api.schemas import InvestigationCreate, InvestigationReview, SimulationRequest
from aegis.config import Settings
from aegis.quality.checks import run_data_quality
from aegis.repositories import investigations as inv_repo
from aegis.repositories import operations as ops
from aegis.repositories.transactions import risk_distribution
from aegis.security import Role
from aegis.services import health as health_service
from aegis.services import investigations as inv_service
from aegis.services import models as model_service

router = APIRouter()


# ----------------------------------------------------------------------------- investigations
@router.post("/investigations", status_code=status.HTTP_201_CREATED, tags=["investigations"])
async def create_investigation(
    body: InvestigationCreate,
    engine: Engine = Depends(db_engine),
    cfg: Settings = Depends(settings),
    user: Principal = Depends(require_role(Role.ANALYST)),
) -> dict[str, Any]:
    try:
        return await run_in_threadpool(
            inv_service.run_investigation, engine, cfg, user.tenant_id, user.user_id, body.transaction_id
        )
    except inv_service.TransactionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found") from exc


@router.get("/investigations", tags=["investigations"])
def list_investigations(
    user: Principal = Depends(current_user), engine: Engine = Depends(db_engine), limit: int = Query(50, ge=1, le=200)
) -> dict[str, Any]:
    with engine.connect() as conn:
        return {"items": inv_repo.list_investigations(conn, user.tenant_id, limit)}


@router.get("/investigations/{investigation_id}", tags=["investigations"])
def get_investigation(
    investigation_id: UUID, user: Principal = Depends(current_user), engine: Engine = Depends(db_engine)
) -> dict[str, Any]:
    with engine.connect() as conn:
        row = inv_repo.get_investigation(conn, user.tenant_id, investigation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation not found")
    return row


@router.patch("/investigations/{investigation_id}", tags=["investigations"])
def review_investigation(
    investigation_id: UUID,
    body: InvestigationReview,
    engine: Engine = Depends(db_engine),
    user: Principal = Depends(require_role(Role.ANALYST)),
) -> dict[str, Any]:
    row = inv_service.review(engine, user.tenant_id, user.user_id, investigation_id, body.review_status, body.notes)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation not found")
    return row


# ----------------------------------------------------------------------------- models
@router.get("/models/active", tags=["models"])
def active_model(user: Principal = Depends(current_user), engine: Engine = Depends(db_engine)) -> dict[str, Any]:
    summary = model_service.model_summary(engine, user.tenant_id)
    if summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active model")
    with engine.connect() as conn:
        summary["prediction_distribution"] = risk_distribution(conn, user.tenant_id, hours=24 * 7)
    return summary


@router.get("/models", tags=["models"])
def list_models(_: Principal = Depends(current_user), engine: Engine = Depends(db_engine)) -> dict[str, Any]:
    with engine.connect() as conn:
        return {"items": ops.model_versions(conn)}


@router.get("/models/drift", tags=["models"])
def drift(_: Principal = Depends(current_user), engine: Engine = Depends(db_engine)) -> dict[str, Any]:
    return model_service.drift_report(engine)


# ----------------------------------------------------------------------------- data intelligence
@router.get("/data-quality", tags=["data"])
def data_quality(
    _: Principal = Depends(current_user),
    engine: Engine = Depends(db_engine),
    history_hours: int = Query(6, ge=1, le=168),
) -> dict[str, Any]:
    with engine.connect() as conn:
        return {"latest": ops.latest_dq_results(conn), "history": ops.dq_history(conn, history_hours)}


@router.post("/data-quality/run", tags=["data"])
def run_dq(
    engine: Engine = Depends(db_engine), user: Principal = Depends(require_role(Role.ANALYST))
) -> dict[str, Any]:
    results = run_data_quality(engine)
    with engine.begin() as conn:
        inv_repo.audit(
            conn,
            user.tenant_id,
            user.user_id,
            "data_quality_run",
            "data_quality",
            str(results[0]["run_id"]) if results else None,
            {},
        )
    return {"results": results}


@router.get("/dead-letters", tags=["data"])
def dead_letters(
    user: Principal = Depends(current_user), engine: Engine = Depends(db_engine), limit: int = Query(50, ge=1, le=200)
) -> dict[str, Any]:
    admin = user.role is Role.ADMIN  # unattributable (no valid tenant) messages are visible to admins only
    with engine.connect() as conn:
        return {
            "items": ops.dead_letters(conn, user.tenant_id, admin, limit),
            "by_reason": ops.dead_letter_reasons(conn, user.tenant_id, admin),
        }


@router.get("/analytics", tags=["data"])
def analytics(user: Principal = Depends(current_user), engine: Engine = Depends(db_engine)) -> dict[str, Any]:
    with engine.connect() as conn:
        marts = {name: ops.mart(conn, user.tenant_id, name) for name in ops.MART_QUERIES}
        return {
            "marts": marts,
            "available": any(v is not None for v in marts.values()),
            "transformations": ops.transformation_runs(conn, 5),
        }


# ----------------------------------------------------------------------------- operations
@router.get("/operations/health", tags=["operations"])
async def operations_health(
    _: Principal = Depends(current_user), engine: Engine = Depends(db_engine), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    return await run_in_threadpool(health_service.system_health, engine, cfg)


@router.get("/operations/pipeline", tags=["operations"])
async def pipeline(
    _: Principal = Depends(current_user),
    engine: Engine = Depends(db_engine),
    cfg: Settings = Depends(settings),
    minutes: int = Query(60, ge=5, le=1440),
) -> dict[str, Any]:
    with engine.connect() as conn:
        windows = ops.pipeline_windows(conn, minutes)
        totals = ops.pipeline_totals(conn)
    metrics = await run_in_threadpool(health_service.consumer_metrics, cfg)
    return {"windows": windows, "totals": totals, "consumer_metrics": metrics}


@router.get("/operations/audit", tags=["operations"])
def audit_log(
    user: Principal = Depends(require_role(Role.ADMIN)),
    engine: Engine = Depends(db_engine),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    with engine.connect() as conn:
        return {"items": inv_repo.recent_audit(conn, user.tenant_id, limit)}


# ----------------------------------------------------------------------------- simulator
@router.post("/simulator/runs", tags=["simulator"])
async def simulate(
    body: SimulationRequest,
    engine: Engine = Depends(db_engine),
    cfg: Settings = Depends(settings),
    user: Principal = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    """Publish synthetic events for the caller's tenant to Kafka (they flow through the real pipeline)."""
    from aegis.streaming import producer

    seed = int(time.time() * 1000) % 2**31
    if body.mode == "burst":
        summary = await run_in_threadpool(
            producer.run_burst, body.count, user.tenant_id, body.include_defects, seed, cfg
        )
    else:
        summary = await run_in_threadpool(producer.run_pack, body.mode, user.tenant_id, seed, cfg)
    with engine.begin() as conn:
        inv_repo.audit(
            conn,
            user.tenant_id,
            user.user_id,
            "simulation_published",
            "simulator",
            None,
            {"mode": body.mode, "count": body.count, **summary.as_dict()},
        )
    return {"mode": body.mode, "published_at": datetime.now(UTC), **summary.as_dict()}
