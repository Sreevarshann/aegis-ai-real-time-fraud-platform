"""Model intelligence: registry views and prediction-drift monitoring (PSI)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import Engine

from aegis.repositories import operations as ops
from aegis.repositories import transactions as txn_repo

PSI_STABLE, PSI_MODERATE = 0.1, 0.25


def psi(expected: list[float], actual: list[float], eps: float = 1e-4) -> float:
    """Population Stability Index between two binned distributions (same bins)."""
    total = 0.0
    for e, a in zip(expected, actual, strict=True):
        e, a = max(e, eps), max(a, eps)
        total += (a - e) * math.log(a / e)
    return round(total, 4)


def psi_status(value: float) -> str:
    return "stable" if value < PSI_STABLE else "moderate" if value < PSI_MODERATE else "significant"


def _hist(values: np.ndarray, edges: list[float]) -> list[float]:
    counts, _ = np.histogram(values, bins=edges)
    return (counts / max(counts.sum(), 1)).tolist()


def drift_report(engine: Engine, sample: int = 2000, min_sample: int = 200) -> dict[str, Any]:
    with engine.connect() as conn:
        model = ops.active_model_detail(conn)
        if model is None:
            return {"status": "no_model"}
        ref = model["metrics"].get("reference", {})
        probs = ops.recent_score_histogram(conn, model["model_version_id"], None, sample)
        features = {
            f: ops.recent_feature_values(conn, model["model_version_id"], f, sample) for f in ref.get("features", {})
        }
    if len(probs) < min_sample:
        return {
            "status": "insufficient_data",
            "sample_size": len(probs),
            "min_sample": min_sample,
            "model_version": model["version"],
        }
    edges = ref["score_bins"]
    live = _hist(np.array(probs) * 100, edges)
    score_psi = psi(ref["score_distribution"], live)
    feature_rows = []
    for name, spec in ref.get("features", {}).items():
        e = spec["edges"]
        vals = np.array([v if v is not None else e[0] for v in features[name]], dtype=float)
        dist = _hist(vals, [-np.inf, *e[1:-1], np.inf])
        value = psi(spec["distribution"], dist)
        feature_rows.append({"feature": name, "psi": value, "status": psi_status(value)})
    return {
        "status": "ok",
        "model_version": model["version"],
        "sample_size": len(probs),
        "score_psi": score_psi,
        "score_status": psi_status(score_psi),
        "score_bins": [f"{edges[i]}-{edges[i + 1]}" for i in range(len(edges) - 1)],
        "reference_distribution": ref["score_distribution"],
        "live_distribution": [round(x, 6) for x in live],
        "features": sorted(feature_rows, key=lambda r: r["psi"], reverse=True),
        "thresholds": {"stable_below": PSI_STABLE, "significant_above": PSI_MODERATE},
    }


def model_summary(engine: Engine, tenant_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        model = ops.active_model_detail(conn)
        if model is None:
            return None
        live = txn_repo.live_label_performance(conn, tenant_id, datetime.now(UTC) - timedelta(days=7))
    tp, fp, fn = live["tp"], live["fp"], live["fn"]
    metrics = model["metrics"]
    return {
        "model_version_id": model["model_version_id"],
        "version": model["version"],
        "algorithm": model["algorithm"],
        "created_at": model["created_at"],
        "mlflow_run_id": model["mlflow_run_id"],
        "decision_threshold": model["decision_threshold"],
        "feature_names": model["feature_names"],
        "test_metrics": {
            k: metrics[k]
            for k in (
                "precision",
                "recall",
                "f1",
                "pr_auc",
                "roc_auc",
                "confusion_matrix",
                "support_positive",
                "support_total",
            )
        },
        "feature_importance": metrics.get("feature_importance", []),
        "training_summary": model["training_summary"],
        "live_simulation_performance": {
            **live,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "note": "Computed against simulator ground truth for transactions ingested in the last 7 days.",
        },
    }
