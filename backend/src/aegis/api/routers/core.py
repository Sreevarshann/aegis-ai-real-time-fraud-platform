"""Auth, overview, transactions (incl. live SSE feed) and alerts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine

from aegis.api.deps import Principal, current_user, db_engine, require_role
from aegis.api.schemas import AlertStatusUpdate, LoginRequest
from aegis.ml.model import humanize
from aegis.repositories import investigations as inv_repo
from aegis.repositories import transactions as repo
from aegis.security import Role
from aegis.services import auth as auth_service

router = APIRouter()


# ----------------------------------------------------------------------------- auth
@router.post("/auth/login", tags=["auth"])
def login(body: LoginRequest, engine: Engine = Depends(db_engine)) -> dict[str, Any]:
    try:
        return auth_service.login(engine, body.email, body.password)
    except auth_service.InvalidCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password") from exc


@router.get("/auth/me", tags=["auth"])
def me(user: Principal = Depends(current_user), engine: Engine = Depends(db_engine)) -> dict[str, Any]:
    with engine.connect() as conn:
        row = inv_repo.get_user(conn, user.user_id)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return {
        "user_id": str(row["user_id"]),
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
        "tenant_id": row["tenant_id"],
    }


# ----------------------------------------------------------------------------- overview
@router.get("/overview", tags=["overview"])
def overview(
    user: Principal = Depends(current_user),
    engine: Engine = Depends(db_engine),
    window_minutes: int = Query(60, ge=5, le=1440),
) -> dict[str, Any]:
    bucket = 60 if window_minutes <= 180 else 300 if window_minutes <= 720 else 900
    with engine.connect() as conn:
        stats = repo.overview(conn, user.tenant_id)
        return {
            "tenant_id": user.tenant_id,
            "stats": {**stats, "transactions_per_second": round(stats["last_60s"] / 60, 2)},
            "volume": repo.volume_series(conn, user.tenant_id, window_minutes, bucket),
            "bucket_seconds": bucket,
            "risk_distribution": repo.risk_distribution(conn, user.tenant_id),
            "risk_categories": repo.category_breakdown(conn, user.tenant_id),
            "recent_alerts": _with_reasons(repo.list_alerts(conn, user.tenant_id, status=None, limit=8, offset=0)),
        }


def _with_reasons(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for a in alerts:
        a["top_reasons"] = [humanize(e) for e in (a.pop("explanation", None) or [])[:3]]
    return alerts


# ----------------------------------------------------------------------------- transactions
@router.get("/transactions", tags=["transactions"])
def list_transactions(
    user: Principal = Depends(current_user),
    engine: Engine = Depends(db_engine),
    limit: int = Query(50, ge=1, le=200),
    before_seq: int | None = Query(None, ge=0),
    after_seq: int | None = Query(None, ge=0),
    min_score: int | None = Query(None, ge=0, le=100),
    risk_category: Literal["low", "medium", "high", "critical"] | None = None,
    channel: Literal["card_present", "ecommerce", "mobile_wallet", "bank_transfer"] | None = None,
    status_: Literal["approved", "declined", "pending"] | None = Query(None, alias="status"),
    q: str | None = Query(None, min_length=2, max_length=64),
) -> dict[str, Any]:
    with engine.connect() as conn:
        rows = repo.list_transactions(
            conn,
            user.tenant_id,
            limit=limit,
            before_seq=before_seq,
            after_seq=after_seq,
            min_score=min_score,
            risk_category=risk_category,
            search=q,
            channel=channel,
            status=status_,
        )
    return {"items": rows, "next_before_seq": rows[-1]["seq"] if len(rows) == limit else None}


@router.get("/transactions/stream", tags=["transactions"])
async def stream_transactions(
    request: Request,
    user: Principal = Depends(current_user),
    engine: Engine = Depends(db_engine),
    after_seq: int | None = Query(None, ge=0),
) -> StreamingResponse:
    """Server-Sent Events feed of newly persisted transactions for the caller's tenant."""

    async def events() -> AsyncIterator[str]:
        cursor = after_seq
        if cursor is None:
            with engine.connect() as conn:
                latest = repo.list_transactions(conn, user.tenant_id, limit=1)
            cursor = latest[0]["seq"] if latest else 0
        yield f"event: ready\ndata: {json.dumps({'cursor': cursor})}\n\n"
        idle = 0
        while not await request.is_disconnected():
            rows = await asyncio.to_thread(_fetch_after, engine, user.tenant_id, cursor)
            if rows:
                cursor = rows[-1]["seq"]
                yield f"event: transactions\ndata: {json.dumps(jsonable_encoder(rows))}\n\n"
                idle = 0
            else:
                idle += 1
                if idle % 15 == 0:
                    yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


def _fetch_after(engine: Engine, tenant_id: str, cursor: int) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return repo.list_transactions(conn, tenant_id, limit=100, after_seq=cursor)


@router.get("/transactions/{transaction_id}", tags=["transactions"])
def transaction_detail(
    transaction_id: UUID, user: Principal = Depends(current_user), engine: Engine = Depends(db_engine)
) -> dict[str, Any]:
    with engine.connect() as conn:
        row = repo.get_transaction_detail(conn, user.tenant_id, transaction_id)
    if row is None:
        # Same response whether the id is unknown or belongs to another tenant.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    row["explanation_text"] = [humanize(e) for e in row.get("explanation") or []]
    return row


# ----------------------------------------------------------------------------- alerts
@router.get("/alerts", tags=["alerts"])
def list_alerts(
    user: Principal = Depends(current_user),
    engine: Engine = Depends(db_engine),
    status_: Literal["open", "investigating", "escalated", "dismissed", "confirmed_fraud"] | None = Query(
        None, alias="status"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    with engine.connect() as conn:
        return {
            "items": _with_reasons(repo.list_alerts(conn, user.tenant_id, status=status_, limit=limit, offset=offset)),
            "counts": repo.alert_counts(conn, user.tenant_id),
        }


@router.patch("/alerts/{alert_id}", tags=["alerts"])
def update_alert(
    alert_id: int,
    body: AlertStatusUpdate,
    engine: Engine = Depends(db_engine),
    user: Principal = Depends(require_role(Role.ANALYST)),
) -> dict[str, Any]:
    with engine.begin() as conn:
        if not repo.update_alert_status(conn, user.tenant_id, alert_id, body.status):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
        inv_repo.audit(
            conn, user.tenant_id, user.user_id, "alert_status_changed", "alert", str(alert_id), {"status": body.status}
        )
    return {"alert_id": alert_id, "status": body.status}
