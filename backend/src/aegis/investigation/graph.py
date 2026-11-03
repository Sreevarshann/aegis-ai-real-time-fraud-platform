"""LangGraph investigation workflow.

    retrieve_transaction ─▶ retrieve_prediction ─▶ customer_history ─▶ device_activity
         │ (not found)                                                       │
         ▼                                                                   ▼
        END            compose_report ◀─ narrate ◀─ correlate ◀─ velocity ◀─ merchant_activity

Each node calls an evidence tool (tenant-scoped SQL) and appends an :class:`Evidence` item.
``correlate`` derives indicators *only* from evidence data and cites the evidence ids;
``narrate`` optionally asks a local LLM to phrase the findings and enforces grounding.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import Engine

from aegis.config import Settings
from aegis.investigation import llm
from aegis.investigation import tools as t
from aegis.ml.model import humanize


class InvestigationState(TypedDict, total=False):
    tenant_id: str
    transaction_id: UUID
    duration_ms: float
    transaction: dict[str, Any] | None
    prediction: dict[str, Any] | None
    profile: dict[str, Any] | None
    history: list[dict[str, Any]]
    evidence: list[t.Evidence]
    timeline: list[dict[str, Any]]
    indicators: list[dict[str, Any]]
    priority: str
    narrative: str
    engine: str
    llm_model: str | None
    llm_note: str | None
    report: dict[str, Any]
    error: str | None


def _next_id(state: InvestigationState) -> str:
    return f"E{len(state.get('evidence', [])) + 1}"


def _ts(v: Any) -> str:
    return v.isoformat() if isinstance(v, datetime) else str(v)


class InvestigationEngine:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self.db = engine
        self.settings = settings
        self.graph = self._build()

    # ------------------------------------------------------------------ nodes
    def retrieve_transaction(self, s: InvestigationState) -> InvestigationState:
        with self.db.connect() as conn:
            txn = t.get_transaction(conn, s["tenant_id"], s["transaction_id"])
        if txn is None:
            return {"transaction": None, "error": "transaction not found for this tenant"}
        ev = t.Evidence(
            "E1",
            "get_transaction",
            "Transaction under review",
            f"{txn['currency']} {txn['amount']} at {txn['merchant_name']} ({txn['merchant_category']}) in "
            f"{txn['country']} via {txn['payment_channel']} from device {txn['device_id']}; status {txn['status']}.",
            [str(txn["transaction_id"])],
            {
                "amount": float(txn["amount"]),
                "currency": txn["currency"],
                "country": txn["country"],
                "merchant_id": txn["merchant_id"],
                "merchant_category": txn["merchant_category"],
                "device_id": txn["device_id"],
                "channel": txn["payment_channel"],
                "status": txn["status"],
                "event_timestamp": _ts(txn["event_timestamp"]),
                "is_late": txn["is_late"],
            },
        )
        return {
            "transaction": txn,
            "evidence": [ev],
            "timeline": [
                {
                    "at": _ts(txn["event_timestamp"]),
                    "event": "Transaction authorised"
                    if txn["status"] == "approved"
                    else f"Transaction {txn['status']}",
                    "ref": str(txn["transaction_id"]),
                    "evidence": "E1",
                },
                {
                    "at": _ts(txn["ingested_at"]),
                    "event": "Ingested from Kafka and persisted",
                    "ref": f"seq {txn['seq']}",
                    "evidence": "E1",
                },
            ],
        }

    def retrieve_prediction(self, s: InvestigationState) -> InvestigationState:
        with self.db.connect() as conn:
            pred = t.get_prediction(conn, s["tenant_id"], s["transaction_id"])
        evidence = list(s["evidence"])
        timeline = list(s["timeline"])
        if pred is None:
            evidence.append(
                t.Evidence(
                    _next_id(s),
                    "get_prediction",
                    "Model prediction",
                    "No stored prediction exists for this transaction.",
                    [],
                    {},
                )
            )
            return {"prediction": None, "evidence": evidence}
        eid = _next_id(s)
        factors = [humanize(e) for e in pred["explanation"]]
        evidence.append(
            t.Evidence(
                eid,
                "get_prediction",
                "Stored model prediction",
                f"Risk score {pred['risk_score']}/100 ({pred['risk_category']}) from model {pred['model_version']}; "
                f"alert threshold {round(pred['decision_threshold'] * 100)}.",
                [f"prediction:{pred['prediction_id']}"] + ([f"alert:{pred['alert_id']}"] if pred["alert_id"] else []),
                {
                    "risk_score": pred["risk_score"],
                    "risk_category": pred["risk_category"],
                    "probability": round(pred["probability"], 4),
                    "model_version": pred["model_version"],
                    "threshold_score": round(pred["decision_threshold"] * 100),
                    "top_factors": factors,
                    "alert_id": pred["alert_id"],
                    "alert_status": pred["alert_status"],
                },
            )
        )
        timeline.append(
            {
                "at": _ts(pred["scored_at"]),
                "event": f"Scored {pred['risk_score']}/100 by {pred['model_version']}",
                "ref": f"prediction:{pred['prediction_id']}",
                "evidence": eid,
            }
        )
        return {"prediction": pred, "evidence": evidence, "timeline": timeline}

    def customer_history(self, s: InvestigationState) -> InvestigationState:
        txn = s["transaction"]
        assert txn is not None
        with self.db.connect() as conn:
            profile = t.get_customer_profile(conn, s["tenant_id"], txn["customer_id"])
            history = t.get_customer_history(conn, s["tenant_id"], txn["customer_id"], txn["event_timestamp"])
            prior_alerts = t.get_prior_alerts(conn, s["tenant_id"], txn["customer_id"], txn["event_timestamp"])
        summary = t.summarize_history(history)
        eid = _next_id(s)
        p = profile or {}
        data = {
            **summary,
            "home_country": p.get("home_country"),
            "registered_devices": p.get("registered_devices", []),
            "account_opened_at": _ts(p.get("account_opened_at")),
            "reference_avg_ticket_usd": float(p.get("avg_ticket_usd") or 0),
            "prior_alerts": len(prior_alerts),
        }
        text = (
            f"Customer {txn['customer_id']} (home {data['home_country']}) has {summary['count_30d']} prior "
            f"transactions in the 30 days before this one"
            + (
                f", median amount {summary['median_amount']}"
                if summary["count_30d"]
                else " (no streaming history yet; reference profile only)"
            )
            + f"; {len(prior_alerts)} earlier alert(s)."
        )
        ev = t.Evidence(
            eid,
            "get_customer_history",
            "Customer profile and 30-day history",
            text,
            [str(h["transaction_id"]) for h in history[:10]] + [f"alert:{a['alert_id']}" for a in prior_alerts[:5]],
            data,
        )
        timeline = list(s["timeline"])
        for h in history[:6]:
            timeline.append(
                {
                    "at": _ts(h["event_timestamp"]),
                    "event": f"Prior txn {h['currency']} {h['amount']} in {h['country']} ({h['merchant_category']})",
                    "ref": str(h["transaction_id"]),
                    "evidence": eid,
                }
            )
        return {"profile": profile, "history": history, "evidence": [*s["evidence"], ev], "timeline": timeline}

    def device_activity(self, s: InvestigationState) -> InvestigationState:
        txn = s["transaction"]
        assert txn is not None
        with self.db.connect() as conn:
            rows = t.get_device_activity(conn, s["tenant_id"], txn["device_id"], txn["event_timestamp"])
        customers = sorted({r["customer_id"] for r in rows})
        registered = set((s.get("profile") or {}).get("registered_devices", []))
        seen_before = any(h["device_id"] == txn["device_id"] for h in s.get("history", []))
        data = {
            "device_id": txn["device_id"],
            "txns_24h": len(rows),
            "distinct_customers_24h": len(customers),
            "customers": customers[:10],
            "registered_to_customer": txn["device_id"] in registered,
            "seen_in_customer_history": seen_before,
        }
        text = (
            f"Device {txn['device_id']} is {'registered' if data['registered_to_customer'] else 'NOT registered'} "
            f"to the customer and was {'previously' if seen_before else 'never previously'} seen in their history; "
            f"{len(rows)} transaction(s) from {len(customers)} customer(s) on it in the surrounding 24h."
        )
        ev = t.Evidence(
            _next_id(s),
            "get_device_activity",
            "Device activity",
            text,
            [str(r["transaction_id"]) for r in rows[:10]],
            data,
        )
        return {"evidence": [*s["evidence"], ev]}

    def merchant_activity(self, s: InvestigationState) -> InvestigationState:
        txn = s["transaction"]
        assert txn is not None
        with self.db.connect() as conn:
            row = t.get_merchant_activity(conn, s["tenant_id"], txn["merchant_id"], txn["event_timestamp"])
        n = int(row.get("txns_1h") or 0)
        declined = int(row.get("declined_1h") or 0)
        data = {
            "merchant_id": txn["merchant_id"],
            "merchant_name": txn["merchant_name"],
            "txns_1h": n,
            "distinct_customers_1h": int(row.get("customers_1h") or 0),
            "declined_1h": declined,
            "decline_rate_1h": round(declined / n, 3) if n else None,
            "txns_24h": int(row.get("txns_24h") or 0),
            "alerts_24h": int(row.get("alerts_24h") or 0),
        }
        text = (
            f"Merchant {txn['merchant_name']} processed {n} transaction(s) from {data['distinct_customers_1h']} "
            f"customer(s) in the hour around this event ({declined} declined); {data['alerts_24h']} alert(s) "
            f"at this merchant in 24h."
        )
        ev = t.Evidence(
            _next_id(s), "get_merchant_activity", "Merchant activity", text, list((row.get("ids_1h") or [])[:10]), data
        )
        return {"evidence": [*s["evidence"], ev]}

    def velocity(self, s: InvestigationState) -> InvestigationState:
        txn = s["transaction"]
        assert txn is not None
        ts = txn["event_timestamp"]
        hist = s.get("history", [])
        w10 = [h for h in hist if h["event_timestamp"] >= ts - timedelta(minutes=10)]
        w1h = [h for h in hist if h["event_timestamp"] >= ts - timedelta(hours=1)]
        w24 = [h for h in hist if h["event_timestamp"] >= ts - timedelta(hours=24)]
        other = [h for h in w24 if h["country"] != txn["country"]]
        last_other = max(other, key=lambda h: h["event_timestamp"]) if other else None
        data = {
            "txns_10m": len(w10),
            "txns_1h": len(w1h),
            "txns_24h": len(w24),
            "spend_1h": round(sum(float(h["amount"]) for h in w1h), 2),
            "countries_24h": sorted({h["country"] for h in w24} | {txn["country"]}),
            "minutes_since_other_country": round((ts - last_other["event_timestamp"]).total_seconds() / 60, 1)
            if last_other
            else None,
            "other_country": last_other["country"] if last_other else None,
        }
        countries = sorted({h["country"] for h in w24} | {txn["country"]})
        text = (
            f"{len(w10)} prior transaction(s) in 10 minutes, {len(w1h)} in 1 hour and {len(w24)} in 24 hours; "
            f"countries in 24h: {', '.join(countries)}."
        )
        refs = [str(h["transaction_id"]) for h in w1h[:10]]
        if last_other:
            refs.append(str(last_other["transaction_id"]))
        ev = t.Evidence(_next_id(s), "analyze_velocity", "Velocity and behavioural anomalies", text, refs, data)
        return {"evidence": [*s["evidence"], ev]}

    def correlate(self, s: InvestigationState) -> InvestigationState:
        ev = {e.tool: e for e in s["evidence"]}
        txn = ev["get_transaction"].data
        indicators: list[dict[str, Any]] = []

        def add(code: str, text: str, weight: int, *sources: str) -> None:
            indicators.append(
                {
                    "code": code,
                    "description": text,
                    "weight": weight,
                    "evidence": [ev[x].id for x in sources if x in ev],
                }
            )

        pred = ev.get("get_prediction")
        if pred and pred.data and pred.data["risk_score"] >= pred.data["threshold_score"]:
            add(
                "model_alert",
                f"Model score {pred.data['risk_score']} is at or above the alert threshold "
                f"{pred.data['threshold_score']}",
                2,
                "get_prediction",
            )
        hist = ev["get_customer_history"].data
        median = hist.get("median_amount")
        if median and txn["amount"] >= 5 * median:
            add(
                "amount_spike",
                f"Amount {txn['amount']:.2f} is {txn['amount'] / median:.1f}x the 30-day median {median}",
                2,
                "get_transaction",
                "get_customer_history",
            )
        if hist.get("home_country") and txn["country"] != hist["home_country"]:
            add(
                "foreign_country",
                f"Transaction country {txn['country']} differs from home country {hist['home_country']}",
                1,
                "get_transaction",
                "get_customer_history",
            )
        dev = ev["get_device_activity"].data
        if not dev["registered_to_customer"] and not dev["seen_in_customer_history"]:
            add(
                "new_device",
                f"Device {dev['device_id']} is neither registered nor previously used",
                2,
                "get_device_activity",
                "get_customer_history",
            )
        if dev["distinct_customers_24h"] > 1:
            add(
                "shared_device",
                f"Device used by {dev['distinct_customers_24h']} customers within 24h",
                2,
                "get_device_activity",
            )
        vel = ev["analyze_velocity"].data
        if vel["txns_10m"] >= 3:
            add("burst", f"{vel['txns_10m']} transactions in the preceding 10 minutes", 2, "analyze_velocity")
        if vel["minutes_since_other_country"] is not None and vel["minutes_since_other_country"] <= 120:
            add(
                "impossible_travel",
                f"Transaction in {txn['country']} {vel['minutes_since_other_country']} minutes "
                f"after one in {vel['other_country']}",
                3,
                "analyze_velocity",
            )
        mer = ev["get_merchant_activity"].data
        if mer["distinct_customers_1h"] >= 4:
            add(
                "merchant_spike",
                f"Merchant saw {mer['distinct_customers_1h']} distinct customers in one hour",
                1,
                "get_merchant_activity",
            )
        if mer["decline_rate_1h"] is not None and mer["txns_1h"] >= 4 and mer["decline_rate_1h"] >= 0.25:
            add(
                "merchant_declines",
                f"Merchant decline rate {mer['decline_rate_1h']:.0%} in the hour",
                1,
                "get_merchant_activity",
            )
        if mer["alerts_24h"] >= 3:
            add(
                "merchant_alert_cluster",
                f"{mer['alerts_24h']} alerts at this merchant in 24h",
                2,
                "get_merchant_activity",
            )
        if txn["status"] == "declined":
            add("declined", "Authorisation was declined", 1, "get_transaction")

        score = pred.data.get("risk_score", 0) if pred and pred.data else 0
        weight = sum(i["weight"] for i in indicators)
        if score >= 85 and weight >= 5:
            priority = "P1"
        elif score >= 60 or weight >= 5:
            priority = "P2"
        elif indicators:
            priority = "P3"
        else:
            priority = "P4"
        return {"indicators": indicators, "priority": priority}

    def narrate(self, s: InvestigationState) -> InvestigationState:
        evidence = [e.as_dict() for e in s["evidence"]]
        deterministic = self._deterministic_narrative(s)
        if llm.ollama_available(self.settings):
            res = llm.narrate(self.settings, evidence, s["indicators"], s["priority"])
            if res.text:
                return {"narrative": res.text, "engine": "ollama", "llm_model": res.model, "llm_note": None}
            return {
                "narrative": deterministic,
                "engine": "deterministic",
                "llm_model": None,
                "llm_note": res.rejected_reason,
            }
        note = None if not self.settings.ollama_enabled else "Ollama enabled but model not available"
        return {"narrative": deterministic, "engine": "deterministic", "llm_model": None, "llm_note": note}

    def compose_report(self, s: InvestigationState) -> InvestigationState:
        txn = s["transaction"]
        assert txn is not None
        pred = s.get("prediction")
        actions = {
            "P1": "Escalate to a senior analyst now; verify with the customer through a known channel before any "
            "account action. A human must make any hold or block decision.",
            "P2": "Review within the shift: confirm recent activity with the customer and inspect linked "
            "transactions listed in the evidence.",
            "P3": "Queue for routine review; monitor the customer and merchant for further anomalies.",
            "P4": "No strong indicators found; close as low risk unless new evidence appears.",
        }
        report = {
            "transaction_summary": next(e.summary for e in s["evidence"] if e.tool == "get_transaction"),
            "risk_score": pred["risk_score"] if pred else None,
            "risk_category": pred["risk_category"] if pred else None,
            "model_version": pred["model_version"] if pred else None,
            "suspicious_indicators": s["indicators"],
            "evidence": [e.as_dict() for e in s["evidence"]],
            "timeline": sorted(s["timeline"], key=lambda x: x["at"]),
            "narrative": s["narrative"],
            "recommended_priority": s["priority"],
            "recommended_action": actions[s["priority"]],
            "engine": s["engine"],
            "llm_model": s.get("llm_model"),
            "llm_note": s.get("llm_note"),
            "limitations": [
                "All data is synthetic; patterns reflect the simulator's fraud scenarios, not real-world fraud.",
                "Model metrics were measured on a synthetic chronological test split and may not transfer.",
                "Feature contributions use single-feature baseline substitution and ignore interactions.",
                "Evidence covers only data persisted by this platform (30-day customer window, 24h device, "
                "24h merchant); no external data sources were consulted.",
                "This report supports human review only; it is not an automated decision.",
            ],
        }
        return {"report": report}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _deterministic_narrative(s: InvestigationState) -> str:
        ev = {e.tool: e for e in s["evidence"]}
        parts = [f"{ev['get_transaction'].summary} [{ev['get_transaction'].id}]"]
        if (p := ev.get("get_prediction")) and p.data:
            parts.append(f"The model scored it {p.data['risk_score']}/100 ({p.data['risk_category']}) [{p.id}].")
            if p.data["top_factors"]:
                parts.append("Main model factors: " + "; ".join(p.data["top_factors"][:3]) + f" [{p.id}].")
        if s["indicators"]:
            parts.append(
                "Indicators found: "
                + "; ".join(f"{i['description']} [{', '.join(i['evidence'])}]" for i in s["indicators"])
                + "."
            )
        else:
            parts.append("No rule-based indicators were triggered by the retrieved evidence.")
        parts.append(f"Recommended review priority: {s['priority']}.")
        return " ".join(parts)

    def _build(self) -> Any:
        g = StateGraph(InvestigationState)
        for name in (
            "retrieve_transaction",
            "retrieve_prediction",
            "customer_history",
            "device_activity",
            "merchant_activity",
            "velocity",
            "correlate",
            "narrate",
            "compose_report",
        ):
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "retrieve_transaction")
        g.add_conditional_edges(
            "retrieve_transaction",
            lambda s: "found" if s.get("transaction") else "missing",
            {"found": "retrieve_prediction", "missing": END},
        )
        for a, b in (
            ("retrieve_prediction", "customer_history"),
            ("customer_history", "device_activity"),
            ("device_activity", "merchant_activity"),
            ("merchant_activity", "velocity"),
            ("velocity", "correlate"),
            ("correlate", "narrate"),
            ("narrate", "compose_report"),
        ):
            g.add_edge(a, b)
        g.add_edge("compose_report", END)
        return g.compile()

    def run(self, tenant_id: str, transaction_id: UUID) -> InvestigationState:
        started = time.perf_counter()
        state: InvestigationState = self.graph.invoke(
            {"tenant_id": tenant_id, "transaction_id": transaction_id, "evidence": [], "timeline": []}
        )
        state["duration_ms"] = (time.perf_counter() - started) * 1000
        return state
