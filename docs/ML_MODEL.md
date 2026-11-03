# ML model

## Training data

`python -m aegis.ml.train --seed 42` (or `make train`):

- Generates a seeded synthetic history: 3,000 customers per tenant × 2 tenants, 7 days, starting 2026-08-01. With
  the default seed this is **172,512 transactions, 3,683 fraud (2.1%)**.
- The training population is independent of the live one but drawn from the same distributions. The merchant
  catalogue is scaled so **customers per merchant matches the live population** (60 merchants for 3,000 customers vs
  600 for 30,000). See DECISIONS #6 for the skew this fixed.
- Events are replayed in event-time order through `FeatureEngine(InMemoryFeatureStore())`, the same feature code as
  the live consumer. Labels are attached only after features are computed.

### Simulated scenarios

| Label | Scenario | Signature |
|---|---|---|
| 1 | `card_testing_burst` | 4–9 tiny e-commerce charges at digital goods/gambling within minutes, usually a new device, sometimes a final larger charge |
| 1 | `account_takeover` | New device, 60% foreign country, 1–3 charges of 2–25× typical spend at electronics/money transfer/crypto |
| 1 | `high_value_anomaly` | 3–30× typical spend, 60% shifted into local small hours, half from a known device |
| 1 | `impossible_travel` | Genuine home purchase, then a card-present purchase in a far country 8–60 min later |
| 1 | `collusive_merchant` | One compromised merchant charges 4–8 different customers within an hour; 35% declined |
| 0 | `legit_travel`, `legit_new_device`, `legit_large_purchase`, quick legit runs | Hard negatives |

## Features (25)

`amount_usd_log`, `amount_vs_typical_log`, `amount_zscore_customer`, `customer_txn_count_1h`,
`customer_txn_count_24h`, `customer_amount_sum_1h_log`, `minutes_since_last_txn`, `local_hour_sin/cos`,
`hour_rarity`, `is_new_device`, `device_customer_count_24h`, `is_foreign_country`, `is_new_country`,
`minutes_since_other_country`, `distinct_countries_24h`, `merchant_txn_count_1h`,
`merchant_distinct_customers_1h`, `merchant_decline_rate_24h`, `channel_{ecommerce,mobile_wallet,bank_transfer}`,
`is_declined`, `account_age_days`, `merchant_category_risk`.

- History-dependent features are `NaN` when history is insufficient (e.g. a z-score needs ≥ 5 prior transactions).
  Gradient boosting handles `NaN` natively; the LR pipeline uses median imputation with missing indicators.
- `merchant_category_risk` is a smoothed target encoding, `(fraud + 50·prior)/(n + 50)`, fit **on the training split
  only** and stored in the model bundle.
- "Typical spend", "registered devices" and "home country" come from the customer reference profile (KYC-style data a
  bank has before the transaction). That limits cold-start bias in live scoring.

## Leakage controls

1. The label is structurally absent from the scoring input (`TransactionPayload` has no label field and forbids
   extras). Covered by `test_payload_model_has_no_label_field`.
2. Point-in-time features only see events at or before the scored event's time, and never the event itself. Covered by
   `test_late_event_does_not_see_the_future` and `test_replaying_a_transaction_does_not_change_its_features`.
3. The split is chronological: train 2026-08-01→08-05, validation 08-05→08-06, test 08-06→08-07.
4. The target encoding, calibration and threshold never see the test split.
5. A simulation artifact that leaked the label was found and removed. Collusive-merchant victims were drawn from
   outside the training subset, so "no history" correlated with fraud (DECISIONS #5).

## Training & selection

| Step | Choice |
|---|---|
| Imbalance | `class_weight="balanced"` for both candidates |
| Candidates | `LogisticRegression(C=0.5)` with imputer + scaler; `HistGradientBoostingClassifier(lr=0.06, 350 iters, 31 leaves, min_samples_leaf=40, l2=1.0)` |
| Calibration | `CalibratedClassifierCV(FrozenEstimator(model), method="sigmoid")` on validation |
| Selection | Highest validation PR-AUC |
| Threshold | Maximise F1 on validation (selected: 0.432) |
| Importance | Permutation importance (Δ average precision, 3 repeats, 15k test sample) |
| Tracking | MLflow params, both candidates' val/test metrics, `metadata.json` and the joblib bundle |
| Registry | `model_versions` row with metrics, importance, drift reference, threshold and MLflow run id; the consumer hot-swaps within 30 s |

## Results (held-out test split, 25,877 rows, 564 fraud)

| Model | Precision | Recall | F1 | PR-AUC | ROC-AUC |
|---|---|---|---|---|---|
| Logistic regression | 0.564 | 0.601 | 0.582 | 0.614 | 0.976 |
| **HistGradientBoosting (selected)** | **0.842** | **0.885** | **0.863** | **0.926** | **0.997** |

Confusion matrix: TN 25,219 · FP 94 · FN 65 · TP 499. Test alert rate per scenario: card testing 228/231,
impossible travel 27/27, account takeover 61/73, collusive merchant 162/198, high-value anomaly 21/35,
legit large purchase 2/211, legit new device 14/160, legit travel 6/1,061, normal 72/23,881.

Top permutation importances: `channel_ecommerce` 0.356, `minutes_since_last_txn` 0.269, `amount_vs_typical_log`
0.195, `merchant_category_risk` 0.187, `amount_usd_log` 0.180, `merchant_decline_rate_24h` 0.150, `is_new_device`
0.080.

**Honesty notes.**
- These metrics are from synthetic data generated by the same simulator family, so they are optimistic relative to
  real fraud.
- Results are bit-identical across repeated runs in the same container image. Runs on a different CPU or BLAS build
  (e.g. macOS host vs Linux container) differ in the third decimal.
- The live dashboard also reports precision and recall against simulator labels for recently ingested traffic.

## Scoring & explanations

- `risk_score = round(100 × calibrated probability)`. Bands: low < 30 ≤ medium < 60 ≤ high < 85 ≤ critical.
- An alert is raised when `probability ≥ decision_threshold`. Severity is the band, with a minimum of `medium`.
- **Explanations: single-feature baseline substitution (occlusion).** For each feature *j*,
  `contribution_j = p(x) − p(x with x_j := training median_j)`. The top 4 positive contributions are stored with the
  prediction and rendered as text such as "amount is 4.6x the customer's typical spend (+37.2 pts)". This is a real
  counterfactual on the deployed model, and a unit test recomputes it. It is **not** additive and ignores
  interactions, so contributions can sum to more than the score. That is documented in the UI and in each
  investigation's limitations.
- Measured latency in the stack: ~20 ms per event when scored singly; much less per event in large batches.

## Drift monitoring

At training time the bundle stores the test-split score histogram (10 bins) and decile edges with reference
distributions for 6 key features. `/models/drift` compares the latest 2,000 live predictions using the
**Population Stability Index**: < 0.1 stable, 0.1–0.25 moderate, > 0.25 significant. At least 200 predictions are
required. Cold-start live traffic (customers without Redis history) is expected to show drift on history-based
features; the monitor makes that visible rather than hiding it.
