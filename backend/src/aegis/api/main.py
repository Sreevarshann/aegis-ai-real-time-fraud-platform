"""FastAPI application: routing, middleware, health/readiness and Prometheus metrics."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from aegis.api.routers import core, intel
from aegis.config import get_settings
from aegis.db.engine import get_engine
from aegis.observability.logging import configure_logging, get_logger
from aegis.observability.metrics import API_LATENCY

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
log = get_logger("aegis.api")

app = FastAPI(
    title="AEGIS AI API",
    version="0.1.0",
    description="Real-time fraud risk scoring, investigation and data-quality API over synthetic data.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def observe(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled_error", path=request.url.path)
        response = JSONResponse({"detail": "Internal server error", "request_id": request_id}, status_code=500)
    elapsed = time.perf_counter() - started
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    API_LATENCY.labels(request.method, path, str(response.status_code)).observe(elapsed)
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    if response.status_code >= 500:
        log.error("request_failed", method=request.method, path=path, status=response.status_code)
    structlog.contextvars.clear_contextvars()
    return response


@app.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def ready() -> JSONResponse:
    checks: dict[str, Any] = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
            active = conn.execute(text("SELECT version FROM model_versions WHERE is_active")).scalar()
            checks["active_model"] = active or "missing"
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"
    ok = checks.get("database") == "ok" and checks.get("active_model") not in (None, "missing")
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(core.router, prefix="/api/v1")
app.include_router(intel.router, prefix="/api/v1")
