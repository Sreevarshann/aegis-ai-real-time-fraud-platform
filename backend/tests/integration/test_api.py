"""FastAPI against the real database: auth, RBAC, validation, tenant isolation, investigations."""

import re

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy import text

from aegis.features.store import RedisFeatureStore
from aegis.streaming.processor import TransactionProcessor

from .helpers import recent_events, to_messages

pytestmark = pytest.mark.integration
PASSWORD = "AegisDemo!2026"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture
def client(clean):
    from aegis.api.main import app

    return TestClient(app)


@pytest.fixture
def populated(clean, settings):
    proc = TransactionProcessor(settings, clean, RedisFeatureStore(redis.Redis.from_url(settings.redis_url)))
    proc.process_batch(to_messages(recent_events(250, seed=31)))
    from datetime import UTC, datetime, timedelta

    from aegis.simulator.generator import SimulatorConfig, TransactionSimulator

    sim = TransactionSimulator(SimulatorConfig(seed=42, stream_seed=32))
    fraud = []
    for tenant in ("northwind", "meridian"):
        fraud += sim.fraud_incident(tenant, datetime.now(UTC) - timedelta(minutes=2), "card_testing_burst")
    proc.process_batch(
        to_messages([e for e in fraud if e.payload.event_timestamp <= datetime.now(UTC)], start_offset=5000)
    )
    return clean


def token(client, email: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health_and_metrics(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
    assert "aegis_api_request_seconds" in client.get("/metrics").text


def test_login_failures_and_token_requirements(client, clean):
    assert (
        client.post("/api/v1/auth/login", json={"email": "admin@northwind.demo", "password": "nope"}).status_code == 401
    )
    assert client.post("/api/v1/auth/login", json={"email": "ghost@nowhere.demo", "password": "x"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "x"}).status_code == 422
    assert client.get("/api/v1/overview").status_code == 401
    assert client.get("/api/v1/overview", headers={"Authorization": "Bearer garbage"}).status_code == 401
    me = client.get("/api/v1/auth/me", headers=token(client, "analyst@meridian.demo")).json()
    assert me["tenant_id"] == "meridian" and me["role"] == "analyst"
    with clean.connect() as conn:
        actions = set(conn.execute(text("SELECT action FROM audit_events")).scalars())
    assert {"login", "login_failed"} <= actions


def test_tenant_isolation(client, populated):
    nw, mr = token(client, "analyst@northwind.demo"), token(client, "analyst@meridian.demo")
    nw_items = client.get("/api/v1/transactions?limit=200", headers=nw).json()["items"]
    mr_items = client.get("/api/v1/transactions?limit=200", headers=mr).json()["items"]
    assert nw_items and mr_items
    with populated.connect() as conn:
        tenant_of = dict(conn.execute(text("SELECT transaction_id::text, tenant_id FROM transactions")).all())
    assert {tenant_of[t["transaction_id"]] for t in nw_items} == {"northwind"}
    assert {tenant_of[t["transaction_id"]] for t in mr_items} == {"meridian"}

    foreign = mr_items[0]["transaction_id"]
    assert client.get(f"/api/v1/transactions/{foreign}", headers=nw).status_code == 404
    assert client.get(f"/api/v1/transactions/{foreign}", headers=mr).status_code == 200
    assert client.post("/api/v1/investigations", json={"transaction_id": foreign}, headers=nw).status_code == 404

    mr_alerts = client.get("/api/v1/alerts", headers=mr).json()["items"]
    assert mr_alerts, "card-testing incident should raise alerts for meridian"
    assert (
        client.patch(f"/api/v1/alerts/{mr_alerts[0]['alert_id']}", json={"status": "dismissed"}, headers=nw).status_code
        == 404
    )
    inv = client.post("/api/v1/investigations", json={"transaction_id": mr_alerts[0]["transaction_id"]}, headers=mr)
    assert inv.status_code == 201
    assert client.get(f"/api/v1/investigations/{inv.json()['investigation_id']}", headers=nw).status_code == 404
    assert client.get("/api/v1/investigations", headers=nw).json()["items"] == []
    # Overview statistics are tenant-scoped as well.
    assert client.get("/api/v1/overview", headers=nw).json()["stats"]["total_transactions"] == len(
        [v for v in tenant_of.values() if v == "northwind"]
    )


def test_role_based_access(client, populated):
    viewer, analyst = token(client, "viewer@northwind.demo"), token(client, "analyst@northwind.demo")
    alert = client.get("/api/v1/alerts", headers=viewer).json()["items"][0]
    assert (
        client.post(
            "/api/v1/investigations", json={"transaction_id": alert["transaction_id"]}, headers=viewer
        ).status_code
        == 403
    )
    assert (
        client.patch(f"/api/v1/alerts/{alert['alert_id']}", json={"status": "escalated"}, headers=viewer).status_code
        == 403
    )
    assert client.post("/api/v1/simulator/runs", json={"mode": "burst", "count": 5}, headers=analyst).status_code == 403
    assert client.get("/api/v1/operations/audit", headers=analyst).status_code == 403
    assert (
        client.patch(f"/api/v1/alerts/{alert['alert_id']}", json={"status": "escalated"}, headers=analyst).status_code
        == 200
    )


def test_request_validation(client, populated):
    h = token(client, "analyst@northwind.demo")
    assert client.get("/api/v1/transactions?limit=100000", headers=h).status_code == 422
    assert client.get("/api/v1/transactions?risk_category=extreme", headers=h).status_code == 422
    assert client.get("/api/v1/transactions/not-a-uuid", headers=h).status_code == 422
    assert client.patch("/api/v1/alerts/1", json={"status": "deleted"}, headers=h).status_code == 422
    assert client.post("/api/v1/investigations", json={"transaction_id": "x", "extra": 1}, headers=h).status_code == 422
    # SQL metacharacters in search are just data (parameterised queries).
    r = client.get("/api/v1/transactions", params={"q": "' OR 1=1 --"}, headers=h)
    assert r.status_code == 200 and r.json()["items"] == []


def test_investigation_is_grounded_in_database_evidence(client, populated):
    h = token(client, "analyst@northwind.demo")
    alert = client.get("/api/v1/alerts", headers=h).json()["items"][0]
    r = client.post("/api/v1/investigations", json={"transaction_id": alert["transaction_id"]}, headers=h)
    assert r.status_code == 201
    inv = r.json()
    report = inv["report"]
    assert inv["engine"] == "deterministic" and report["engine"] == "deterministic"
    assert inv["priority"] in {"P1", "P2", "P3", "P4"}
    evidence_ids = {e["id"] for e in report["evidence"]}
    assert {
        "get_transaction",
        "get_prediction",
        "get_customer_history",
        "get_device_activity",
        "get_merchant_activity",
        "analyze_velocity",
    } == {e["tool"] for e in report["evidence"]}
    for ind in report["suspicious_indicators"]:
        assert ind["evidence"] and set(ind["evidence"]) <= evidence_ids
    for cited in re.findall(r"\[(E\d+)", report["narrative"]):
        assert cited in evidence_ids
    # Every transaction id cited as evidence exists, in the investigator's tenant.
    cited_txns = {rid for e in report["evidence"] for rid in e["record_ids"] if UUID_RE.match(rid)}
    assert alert["transaction_id"] in cited_txns
    with populated.connect() as conn:
        found = conn.execute(
            text(
                "SELECT count(*) FROM transactions WHERE tenant_id = 'northwind' AND transaction_id::text = ANY(:ids)"
            ),
            {"ids": list(cited_txns)},
        ).scalar_one()
    assert found == len(cited_txns)
    # The stored score in the report matches the stored prediction.
    detail = client.get(f"/api/v1/transactions/{alert['transaction_id']}", headers=h).json()
    assert report["risk_score"] == detail["risk_score"]
    assert client.get("/api/v1/alerts?status=investigating", headers=h).json()["counts"].get("investigating", 0) >= 1

    review = client.patch(
        f"/api/v1/investigations/{inv['investigation_id']}",
        json={"review_status": "closed_fraud", "notes": "Confirmed by test"},
        headers=h,
    )
    assert review.status_code == 200 and review.json()["review_status"] == "closed_fraud"
    statuses = {a["alert_id"]: a["status"] for a in client.get("/api/v1/alerts?limit=200", headers=h).json()["items"]}
    assert statuses[alert["alert_id"]] == "confirmed_fraud"


def test_dashboard_endpoints_return_real_data(client, populated):
    h = token(client, "admin@northwind.demo")
    ov = client.get("/api/v1/overview", headers=h).json()
    assert ov["stats"]["total_transactions"] > 0 and sum(v["transactions"] for v in ov["volume"]) > 0
    model = client.get("/api/v1/models/active", headers=h).json()
    assert {"precision", "recall", "f1", "pr_auc", "roc_auc", "confusion_matrix"} <= set(model["test_metrics"])
    assert model["feature_importance"] and model["live_simulation_performance"]["tp"] >= 0
    assert client.get("/api/v1/models/drift", headers=h).json()["status"] in {"ok", "insufficient_data"}
    dq = client.post("/api/v1/data-quality/run", headers=h).json()["results"]
    by_name = {r["check_name"]: r for r in dq}
    assert by_name["prediction_coverage_pct"]["status"] == "pass"
    assert by_name["duplicate_event_ids"]["status"] == "pass"
    assert client.get("/api/v1/data-quality", headers=h).json()["latest"]
    assert client.get("/api/v1/operations/pipeline", headers=h).status_code == 200
    health = client.get("/api/v1/operations/health", headers=h).json()
    assert health["services"]["postgres"]["status"] == "up" and health["services"]["redis"]["status"] == "up"
    assert client.get("/api/v1/analytics", headers=h).status_code == 200
