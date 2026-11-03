"""Reproducible training pipeline.

    python -m aegis.ml.train --seed 42 [--register] [--skip-if-active]

1. Generate a seeded synthetic history and compute point-in-time features (no labels used).
2. Chronological 70/15/15 train/validation/test split (no shuffling across time).
3. Fit the merchant-category target encoding on the *training* split only.
4. Fit a logistic-regression baseline and a histogram gradient-boosting model, both with
   balanced class weights to handle the ~2% positive rate.
5. Platt-calibrate each candidate on validation, choose by validation PR-AUC, and choose
   the alert threshold that maximises validation F1.
6. Report metrics on the untouched test split, log everything to MLflow, persist the
   bundle and (optionally) register it as the active model in PostgreSQL.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from aegis.config import get_settings
from aegis.ml.dataset import build_training_frame
from aegis.ml.model import ALL_FEATURES, RiskModelBundle
from aegis.observability.logging import configure_logging, get_logger

log = get_logger(__name__)
SCORE_BINS: list[float] = [float(x) for x in range(0, 101, 10)]
DRIFT_FEATURES = [
    "amount_usd_log",
    "amount_vs_typical_log",
    "customer_txn_count_1h",
    "is_new_device",
    "is_foreign_country",
    "merchant_distinct_customers_1h",
]


def chronological_split(
    df: pd.DataFrame, train: float = 0.70, val: float = 0.15
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("event_timestamp", kind="mergesort").reset_index(drop=True)
    t1 = df["event_timestamp"].quantile(train)
    t2 = df["event_timestamp"].quantile(train + val)
    return (
        df[df.event_timestamp < t1],
        df[(df.event_timestamp >= t1) & (df.event_timestamp < t2)],
        df[df.event_timestamp >= t2],
    )


def fit_category_risk(train: pd.DataFrame, smoothing: float = 50.0) -> tuple[dict[str, float], float]:
    prior = float(train["label"].mean())
    g = train.groupby("merchant_category")["label"].agg(["sum", "count"])
    enc = ((g["sum"] + smoothing * prior) / (g["count"] + smoothing)).to_dict()
    return {str(k): float(v) for k, v in enc.items()}, prior


def candidates(seed: int) -> dict[str, Any]:
    return {
        "logistic_regression": make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
            StandardScaler(),
            LogisticRegression(class_weight="balanced", max_iter=3000, C=0.5),
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            learning_rate=0.06,
            max_iter=350,
            max_leaf_nodes=31,
            min_samples_leaf=40,
            l2_regularization=1.0,
            class_weight="balanced",
            random_state=seed,
        ),
    }


def evaluate(y: np.ndarray, p: np.ndarray, threshold: float) -> dict[str, Any]:
    pred = (p >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y, p)),
        "roc_auc": float(roc_auc_score(y, p)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "threshold": float(threshold),
        "support_positive": int(y.sum()),
        "support_total": len(y),
    }


def best_f1_threshold(y: np.ndarray, p: np.ndarray) -> float:
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec[:-1] * rec[:-1] / np.clip(prec[:-1] + rec[:-1], 1e-12, None)
    return float(thr[int(np.argmax(f1))])


def _histogram(values: np.ndarray, edges: list[float]) -> list[float]:
    counts, _ = np.histogram(values, bins=edges)
    return (counts / max(counts.sum(), 1)).round(6).tolist()


def train(seed: int, customers_per_tenant: int, days: int, out_dir: Path) -> tuple[RiskModelBundle, Path]:
    t0 = time.perf_counter()
    df = build_training_frame(seed=seed, customers_per_tenant=customers_per_tenant, days=days)
    log.info(
        "training_frame_built", rows=len(df), positives=int(df.label.sum()), seconds=round(time.perf_counter() - t0, 1)
    )
    tr, va, te = chronological_split(df)
    cat_risk, prior = fit_category_risk(tr)
    for part in (tr, va, te):
        part.loc[:, "merchant_category_risk"] = part["merchant_category"].map(cat_risk).fillna(prior)

    xtr, ytr = tr[ALL_FEATURES].astype("float64"), tr["label"].to_numpy()
    xva, yva = va[ALL_FEATURES].astype("float64"), va["label"].to_numpy()
    xte, yte = te[ALL_FEATURES].astype("float64"), te["label"].to_numpy()

    results: dict[str, dict[str, Any]] = {}
    fitted: dict[str, Any] = {}
    for name, est in candidates(seed).items():
        t = time.perf_counter()
        est.fit(xtr, ytr)
        cal = CalibratedClassifierCV(FrozenEstimator(est), method="sigmoid").fit(xva, yva)
        p_va = cal.predict_proba(xva)[:, 1]
        thr = best_f1_threshold(yva, p_va)
        results[name] = {
            "validation": evaluate(yva, p_va, thr),
            "test": evaluate(yte, cal.predict_proba(xte)[:, 1], thr),
            "fit_seconds": round(time.perf_counter() - t, 2),
        }
        fitted[name] = cal
        log.info(
            "candidate_evaluated",
            model=name,
            val_pr_auc=results[name]["validation"]["pr_auc"],
            test_pr_auc=results[name]["test"]["pr_auc"],
        )

    best = max(results, key=lambda n: results[n]["validation"]["pr_auc"])
    model = fitted[best]
    threshold = results[best]["validation"]["threshold"]
    p_te = model.predict_proba(xte)[:, 1]

    # Per-scenario recall on test (simulation ground truth makes this possible; real data would not).
    te_eval = te.assign(alert=(p_te >= threshold).astype(int))
    by_scenario = (
        te_eval.groupby("scenario")
        .agg(n=("label", "size"), alerts=("alert", "sum"))
        .assign(alert_rate=lambda d: (d.alerts / d.n).round(4))
        .reset_index()
        .to_dict("records")
    )

    sample = xte.sample(n=min(len(xte), 15_000), random_state=seed)
    perm = permutation_importance(
        model,
        sample,
        te.loc[sample.index, "label"].to_numpy(),
        scoring="average_precision",
        n_repeats=3,
        random_state=seed,
        n_jobs=1,
    )
    ranked = sorted(
        zip(ALL_FEATURES, perm.importances_mean, perm.importances_std, strict=True), key=lambda t: t[1], reverse=True
    )
    importance = [{"feature": f, "importance": float(m), "std": float(s)} for f, m, s in ranked]

    baselines = {f: float(np.nanmedian(xtr[f])) if xtr[f].notna().any() else 0.0 for f in ALL_FEATURES}
    feature_edges = {
        f: sorted(set(np.nanquantile(xtr[f], np.linspace(0, 1, 11)).round(6).tolist())) for f in DRIFT_FEATURES
    }
    reference = {
        "score_bins": SCORE_BINS,
        "score_distribution": _histogram(p_te * 100, SCORE_BINS),
        "features": {
            f: {"edges": e, "distribution": _histogram(xte[f].fillna(e[0]).to_numpy(), [-np.inf, *e[1:-1], np.inf])}
            for f, e in feature_edges.items()
            if len(e) > 2
        },
    }
    version = f"{best.split('_')[0][:3]}-{datetime.now(UTC):%Y%m%d%H%M%S}"
    summary = {
        "seed": seed,
        "customers_per_tenant": customers_per_tenant,
        "days": days,
        "rows": {"train": len(tr), "validation": len(va), "test": len(te)},
        "positive_rate": {"train": float(ytr.mean()), "validation": float(yva.mean()), "test": float(yte.mean())},
        "time_ranges": {
            k: [str(v.event_timestamp.min()), str(v.event_timestamp.max())]
            for k, v in (("train", tr), ("validation", va), ("test", te))
        },
        "selected": best,
        "candidates": results,
        "test_recall_by_scenario": by_scenario,
        "calibration": "sigmoid (Platt) on validation split",
        "threshold_rule": "maximise F1 on validation split",
        "training_seconds": round(time.perf_counter() - t0, 1),
    }
    bundle = RiskModelBundle(
        version=version,
        algorithm=best,
        estimator=model,
        feature_names=list(ALL_FEATURES),
        category_risk=cat_risk,
        category_risk_default=prior,
        baselines=baselines,
        decision_threshold=threshold,
        metrics={**results[best]["test"], "summary": summary},
        feature_importance=importance,
        reference=reference,
    )
    path = bundle.save(out_dir / version)
    (out_dir / version / "metadata.json").write_text(
        json.dumps(
            {
                "version": version,
                "algorithm": best,
                "test_metrics": results[best]["test"],
                "feature_importance": importance,
                "summary": summary,
            },
            indent=2,
            default=str,
        )
    )
    log.info("model_saved", version=version, path=str(path), test=results[best]["test"])
    return bundle, path


def log_to_mlflow(bundle: RiskModelBundle, path: Path, tracking_uri: str, experiment: str) -> str | None:
    try:
        import mlflow

        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment)
        summary = bundle.metrics["summary"]
        with mlflow.start_run(run_name=bundle.version) as run:
            mlflow.log_params(
                {
                    "seed": summary["seed"],
                    "customers_per_tenant": summary["customers_per_tenant"],
                    "days": summary["days"],
                    "selected_algorithm": bundle.algorithm,
                    "decision_threshold": round(bundle.decision_threshold, 6),
                    "n_features": len(bundle.feature_names),
                }
            )
            for name, res in summary["candidates"].items():
                for split in ("validation", "test"):
                    for metric in ("precision", "recall", "f1", "pr_auc", "roc_auc"):
                        mlflow.log_metric(f"{name}.{split}.{metric}", res[split][metric])
            mlflow.log_artifact(str(path.parent / "metadata.json"))
            mlflow.log_artifact(str(path))
            return str(run.info.run_id)
    except Exception as exc:
        log.warning("mlflow_logging_failed", error=str(exc), tracking_uri=tracking_uri)
        return None


def register(bundle: RiskModelBundle, path: Path, run_id: str | None) -> int:
    from sqlalchemy import insert, update

    from aegis.db.engine import transaction
    from aegis.db.tables import model_versions

    with transaction() as conn:
        conn.execute(update(model_versions).where(model_versions.c.is_active).values(is_active=False))
        mid = conn.execute(
            insert(model_versions)
            .values(
                version=bundle.version,
                algorithm=bundle.algorithm,
                artifact_path=str(path),
                feature_names=bundle.feature_names,
                metrics={k: v for k, v in bundle.metrics.items() if k != "summary"}
                | {"feature_importance": bundle.feature_importance, "reference": bundle.reference},
                training_summary=bundle.metrics["summary"],
                decision_threshold=bundle.decision_threshold,
                mlflow_run_id=run_id,
                is_active=True,
            )
            .returning(model_versions.c.model_version_id)
        ).scalar_one()
    log.info("model_registered", version=bundle.version, model_version_id=mid)
    return int(mid)


def active_model_exists() -> bool:
    from sqlalchemy import select

    from aegis.db.engine import get_engine
    from aegis.db.tables import model_versions

    with get_engine().connect() as conn:
        row = conn.execute(select(model_versions.c.artifact_path).where(model_versions.c.is_active)).first()
    return row is not None and Path(row[0]).exists()


def main(argv: list[str] | None = None) -> None:
    s = get_settings()
    ap = argparse.ArgumentParser(description="Train the AEGIS fraud risk model")
    ap.add_argument("--seed", type=int, default=s.simulator_seed)
    ap.add_argument("--customers-per-tenant", type=int, default=3000)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", type=Path, default=Path(s.model_dir))
    ap.add_argument("--register", action="store_true", help="register as the active model in PostgreSQL")
    ap.add_argument("--skip-if-active", action="store_true", help="do nothing if an active model exists")
    args = ap.parse_args(argv)
    configure_logging(s.log_level, s.log_json)
    if args.skip_if_active and active_model_exists():
        log.info("training_skipped_active_model_present")
        return
    bundle, path = train(args.seed, args.customers_per_tenant, args.days, args.out)
    run_id = log_to_mlflow(bundle, path, s.mlflow_tracking_uri, s.mlflow_experiment)
    if args.register:
        register(bundle, path, run_id)


if __name__ == "__main__":
    main()
