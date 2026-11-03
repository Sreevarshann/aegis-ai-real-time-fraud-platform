"""ML pipeline tests on a small, fast synthetic dataset."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aegis.features.compute import BASE_FEATURES
from aegis.ml import train as tr
from aegis.ml.model import RiskModelBundle, humanize, risk_category


@pytest.fixture(scope="module")
def trained(tmp_path_factory) -> tuple[RiskModelBundle, Path]:
    out = tmp_path_factory.mktemp("models")
    return tr.train(seed=3, customers_per_tenant=600, days=4, out_dir=out)


def test_chronological_split_has_no_time_overlap():
    df = pd.DataFrame(
        {"event_timestamp": pd.date_range("2026-01-01", periods=100, freq="h", tz="UTC"), "label": [0] * 100}
    )
    a, b, c = tr.chronological_split(df)
    assert a.event_timestamp.max() < b.event_timestamp.min() <= b.event_timestamp.max() < c.event_timestamp.min()
    assert len(a) + len(b) + len(c) == 100


def test_category_encoding_is_smoothed_toward_prior():
    df = pd.DataFrame({"merchant_category": ["a"] * 10 + ["b"] * 1000, "label": [1] * 10 + [0] * 1000})
    enc, prior = tr.fit_category_risk(df, smoothing=50)
    assert prior < enc["a"] < 1.0  # 10/10 observed fraud is shrunk heavily toward the prior
    assert enc["b"] < prior


def test_training_produces_truthful_metrics(trained):
    bundle, path = trained
    m = bundle.metrics
    cm = m["confusion_matrix"]
    assert cm["tp"] + cm["fn"] == m["support_positive"]
    assert sum(cm.values()) == m["support_total"]
    precision = cm["tp"] / (cm["tp"] + cm["fp"]) if cm["tp"] + cm["fp"] else 0.0
    assert math.isclose(precision, m["precision"], rel_tol=1e-9)
    assert 0.0 <= m["pr_auc"] <= 1.0 and 0.5 < m["roc_auc"] <= 1.0
    assert set(m["summary"]["candidates"]) == {"logistic_regression", "hist_gradient_boosting"}
    assert path.exists() and (path.parent / "metadata.json").exists()


def test_bundle_round_trips_and_scores_with_explanations(trained, tmp_path):
    bundle, path = trained
    loaded = RiskModelBundle.load(path)
    assert loaded.version == bundle.version and loaded.feature_names[-1] == "merchant_category_risk"
    base = {f: bundle.baselines[f] for f in BASE_FEATURES}
    risky = base | {
        "amount_vs_typical_log": 3.0,
        "is_new_device": 1.0,
        "is_foreign_country": 1.0,
        "is_new_country": 1.0,
        "customer_txn_count_1h": 6.0,
        "channel_ecommerce": 1.0,
    }
    [low, high] = loaded.score_batch([(base, "grocery"), (risky, "electronics")])
    assert 0 <= low.risk_score <= 100 and low.risk_category == risk_category(low.risk_score)
    assert high.probability > low.probability
    # Explanations are real counterfactuals: contribution == p(x) - p(x with feature at baseline).
    for e in high.explanation:
        ablated = loaded.to_row(risky, "electronics") | {e["feature"]: loaded.baselines[e["feature"]]}
        p_ablated = float(loaded.predict_proba([ablated])[0])
        assert math.isclose(e["contribution"], round(high.probability - p_ablated, 4), abs_tol=1e-4)
        assert "pts" in humanize(e)


def test_scores_do_not_depend_on_label(trained):
    """The model input is built from features only; there is no label column to leak."""
    bundle, _ = trained
    assert not {"label", "scenario", "ground_truth_label"} & set(bundle.feature_names)


def test_risk_bands():
    assert [risk_category(s) for s in (0, 29, 30, 59, 60, 84, 85, 100)] == [
        "low",
        "low",
        "medium",
        "medium",
        "high",
        "high",
        "critical",
        "critical",
    ]


def test_psi_drift_metric():
    from aegis.services.models import psi, psi_status

    ref = list(np.full(10, 0.1))
    assert psi(ref, ref) == 0.0 and psi_status(0.0) == "stable"
    shifted = [0.0] * 5 + [0.2] * 5
    assert psi_status(psi(ref, shifted)) == "significant"
