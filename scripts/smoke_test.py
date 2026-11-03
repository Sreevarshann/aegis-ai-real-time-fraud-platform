#!/usr/bin/env python3
"""End-to-end smoke test against a running stack (stdlib only).

Verifies: events published to Kafka are consumed, persisted and scored; results are served by
FastAPI through the UI's reverse proxy; an investigation can be run; the web UI is served.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def call(base: str, path: str, token: str | None = None, body: dict | None = None, method: str | None = None):
    req = urllib.request.Request(base + path, method=method or ("POST" if body is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=60) as r:  # noqa: S310 - local URL
        return json.loads(r.read() or b"null")


def step(msg: str) -> None:
    print(f"  ✓ {msg}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:3000")
    ap.add_argument("--password", required=True)
    args = ap.parse_args()
    base = args.base.rstrip("/")
    print("AEGIS end-to-end smoke test")
    try:
        html = urllib.request.urlopen(base + "/", timeout=10).read().decode()  # noqa: S310
        assert "AEGIS" in html, "web UI did not serve the dashboard"
        step("web UI is served")
        token = call(base, "/api/v1/auth/login", body={"email": "admin@northwind.demo", "password": args.password})[
            "access_token"]
        step("authenticated through the UI reverse proxy")
        before = call(base, "/api/v1/overview", token)["stats"]["total_transactions"]
        sim = call(base, "/api/v1/simulator/runs", token, {"mode": "burst", "count": 150, "include_defects": True})
        step(f"published {sim['sent']} events to Kafka via the API ({sim['expected_outcomes']})")
        deadline = time.time() + 90
        after = before
        while time.time() < deadline:
            after = call(base, "/api/v1/overview", token)["stats"]["total_transactions"]
            if after >= before + sim["expected_outcomes"].get("accept", 1) * 0.9:
                break
            time.sleep(2)
        assert after > before, "no new transactions were persisted by the consumer"
        step(f"consumer persisted new transactions ({before} -> {after})")
        txns = call(base, "/api/v1/transactions?limit=50", token)["items"]
        assert txns and all(t["risk_score"] is not None for t in txns), "transactions lack risk predictions"
        step("every recent transaction has a stored risk prediction")
        detail = call(base, f"/api/v1/transactions/{txns[0]['transaction_id']}", token)
        assert detail["model_version"] and isinstance(detail["explanation"], list)
        step(f"transaction detail served with model {detail['model_version']}")
        alerts = call(base, "/api/v1/alerts?limit=5", token)["items"]
        target = alerts[0]["transaction_id"] if alerts else txns[0]["transaction_id"]
        inv = call(base, "/api/v1/investigations", token, {"transaction_id": target})
        assert inv["report"]["evidence"] and inv["priority"] in {"P1", "P2", "P3", "P4"}
        step(f"investigation {inv['investigation_id'][:8]} completed ({inv['engine']} engine, priority {inv['priority']})")
        dlq = call(base, "/api/v1/dead-letters?limit=5", token)
        step(f"dead-letter quarantine visible ({sum(r['count'] for r in dlq['by_reason'])} events)")
        health = call(base, "/api/v1/operations/health", token)
        down = [k for k, v in health["services"].items() if v["status"] == "down"]
        assert not down, f"services down: {down}"
        step("all services healthy: " + ", ".join(health["services"]))
    except (AssertionError, urllib.error.URLError, KeyError) as exc:
        print(f"  ✗ SMOKE TEST FAILED: {exc}")
        return 1
    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
