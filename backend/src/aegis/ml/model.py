"""Serialisable model bundle: estimator + everything needed to score and explain consistently.

Explanations use *single-feature baseline substitution* (occlusion): for each feature we
replace the observed value with the training-set median and measure how much the predicted
fraud probability changes. The reported contribution of feature *j* is

    p(x) - p(x with x_j := median_j)

This is model-agnostic, exact for what it claims (a counterfactual on the real model), and
cheap (one batched predict call with ``n_features + 1`` rows). It does not capture
interaction effects, which is documented in docs/ML_MODEL.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from aegis.features.compute import BASE_FEATURES, FEATURE_DESCRIPTIONS

RISK_BANDS: tuple[tuple[int, str], ...] = ((85, "critical"), (60, "high"), (30, "medium"), (0, "low"))


def risk_category(score: int) -> str:
    for floor, name in RISK_BANDS:
        if score >= floor:
            return name
    return "low"


@dataclass
class Explanation:
    feature: str
    value: float | None
    baseline: float
    contribution: float
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "value": self.value,
            "baseline": self.baseline,
            "contribution": round(self.contribution, 4),
            "description": self.description,
        }


@dataclass
class ScoredTransaction:
    probability: float
    risk_score: int
    risk_category: str
    is_alert: bool
    explanation: list[dict[str, Any]]
    features: dict[str, float | None]


@dataclass
class RiskModelBundle:
    version: str
    algorithm: str
    estimator: Any  # fitted sklearn estimator exposing predict_proba
    feature_names: list[str]
    category_risk: dict[str, float]
    category_risk_default: float
    baselines: dict[str, float]
    decision_threshold: float
    metrics: dict[str, Any] = field(default_factory=dict)
    feature_importance: list[dict[str, Any]] = field(default_factory=list)
    reference: dict[str, Any] = field(default_factory=dict)  # drift reference distributions

    # ---------------------------------------------------------------- persistence
    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "model.joblib"
        joblib.dump(self, path)
        return path

    @staticmethod
    def load(path: str | Path) -> RiskModelBundle:
        bundle = joblib.load(path)
        if not isinstance(bundle, RiskModelBundle):
            raise TypeError(f"{path} does not contain a RiskModelBundle")
        return bundle

    # ---------------------------------------------------------------- scoring
    def to_row(self, base: dict[str, float], merchant_category: str) -> dict[str, float]:
        row = dict(base)
        row["merchant_category_risk"] = self.category_risk.get(merchant_category, self.category_risk_default)
        return row

    def _matrix(self, rows: list[dict[str, float]]) -> pd.DataFrame:
        return pd.DataFrame(rows, columns=self.feature_names).astype("float64")

    def predict_proba(self, rows: list[dict[str, float]]) -> np.ndarray:
        return np.asarray(self.estimator.predict_proba(self._matrix(rows))[:, 1])

    def score_batch(self, items: list[tuple[dict[str, float], str]], top_k: int = 4) -> list[ScoredTransaction]:
        """Score and explain many transactions with a single predict call."""
        if not items:
            return []
        rows = [self.to_row(base, cat) for base, cat in items]
        n_feat = len(self.feature_names)
        expanded: list[dict[str, float]] = []
        for row in rows:
            expanded.append(row)
            for name in self.feature_names:
                ablated = dict(row)
                ablated[name] = self.baselines[name]
                expanded.append(ablated)
        probs = self.predict_proba(expanded).reshape(len(rows), n_feat + 1)
        results: list[ScoredTransaction] = []
        for row, p in zip(rows, probs, strict=True):
            prob = float(p[0])
            contribs = [
                Explanation(
                    name,
                    _clean(row[name]),
                    self.baselines[name],
                    prob - float(p[j + 1]),
                    FEATURE_DESCRIPTIONS.get(name, name),
                )
                for j, name in enumerate(self.feature_names)
            ]
            contribs.sort(key=lambda e: e.contribution, reverse=True)
            top = [e.as_dict() for e in contribs[:top_k] if e.contribution > 0.0005]
            score = round(prob * 100)
            results.append(
                ScoredTransaction(
                    probability=prob,
                    risk_score=score,
                    risk_category=risk_category(score),
                    is_alert=prob >= self.decision_threshold,
                    explanation=top,
                    features={k: _clean(v) for k, v in row.items()},
                )
            )
        return results


def _clean(v: float) -> float | None:
    """JSON-safe feature value (NaN -> None)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), 6)


def humanize(expl: dict[str, Any]) -> str:
    """Readable sentence for one explanation entry, derived only from the stored values."""
    f, v = expl["feature"], expl.get("value")
    pts = expl["contribution"] * 100
    if v is None:
        return f"{expl['description']} unavailable (+{pts:.1f} pts)"
    text = {
        "amount_vs_typical_log": lambda: f"amount is {math.exp(v):.1f}x the customer's typical spend",
        "amount_usd_log": lambda: f"amount of about ${math.expm1(v):,.0f}",
        "amount_zscore_customer": lambda: f"amount is {v:.1f} standard deviations from the customer's norm",
        "customer_txn_count_1h": lambda: f"{int(v)} customer transactions in the previous hour",
        "customer_txn_count_24h": lambda: f"{int(v)} customer transactions in the previous 24h",
        "is_new_device": lambda: "device never seen for this customer" if v else "known device",
        "is_foreign_country": lambda: "outside the customer's home country" if v else "home country",
        "is_new_country": lambda: "first transaction in this country" if v else "previously seen country",
        "minutes_since_other_country": lambda: f"{v:.0f} min after a transaction in another country",
        "merchant_distinct_customers_1h": lambda: f"{int(v)} distinct customers at this merchant in 1h",
        "merchant_txn_count_1h": lambda: f"{int(v)} merchant transactions in 1h",
        "merchant_decline_rate_24h": lambda: f"merchant decline rate {v:.0%} over 24h",
        "merchant_category_risk": lambda: f"merchant category historical fraud rate {v:.1%}",
        "hour_rarity": lambda: f"hour is unusual for this customer (rarity {v:.2f})",
        "minutes_since_last_txn": lambda: f"{v:.1f} min since previous transaction",
        "device_customer_count_24h": lambda: f"device used by {int(v)} customers in 24h",
    }.get(f, lambda: f"{expl['description']} = {v:g}")()
    return f"{text} (+{pts:.1f} pts)"


ALL_FEATURES: list[str] = [*BASE_FEATURES, "merchant_category_risk"]
