# Data pipeline

## Event contract (schema version 1.0)

Topic `transactions.v1`, key = `customer_id` (so a customer's events stay ordered within a partition), JSON value:

```json
{
  "schema_version": "1.0",
  "event_type": "transaction.created",
  "event_id": "b1e2…",
  "produced_at": "2026-11-02T23:10:18.931Z",
  "payload": {
    "transaction_id": "ef89310f-d9cf-4298-b422-0259bbd6ed1e",
    "tenant_id": "northwind",
    "event_timestamp": "2026-11-02T23:10:17.402Z",
    "customer_id": "NW-C009125",
    "merchant_id": "NW-M00596",
    "merchant_category": "gambling",
    "transaction_amount": "8.88",
    "currency": "USD",
    "transaction_country": "US",
    "device_id": "dev-e13bc6d38f33",
    "payment_channel": "ecommerce",
    "transaction_status": "approved"
  },
  "simulation": { "ground_truth_label": 1, "scenario": "card_testing_burst" }
}
```

`TransactionPayload` (in `aegis/events/schema.py`) is frozen and `extra="forbid"`. Its rules: positive amount with
two decimals, currency in an allowlist, ISO-3166 alpha-2 uppercase country, enum category/channel/status,
timezone-aware timestamp (normalised to UTC), and identifiers matching `[A-Za-z0-9_-]{1,64}`.
**The payload has no label field.** The `simulation` block exists only because the data is synthetic. It is
written to `simulation_labels` and never passed to feature computation or the model.

Unknown `schema_version` values are rejected with `unsupported_schema_version` rather than guessed at. That gives a
version bump an explicit migration point.

## Consumer processing (per batch of ≤ 200 messages)

1. **Parse & validate.** Failures get a stable reason code: `malformed_json`, `unsupported_schema_version`, or
   `schema_validation_failed` (with field-level detail).
2. **Referential integrity** against cached reference data: `unknown_tenant`, `unknown_customer`, `unknown_merchant`,
   `merchant_category_mismatch`.
3. **Time.**
   - `future_timestamp` if more than 5 minutes in the future.
   - `stale_event` if older than `max_event_lateness_s` (2 days) relative to **processing time**. This bound stops an
     old event from defining a fresh watermark (a bug found by an integration test).
   - Otherwise the event-time **watermark for (tenant, partition)** advances. An event more than
     `late_event_tolerance_s` (5 min) behind it is persisted with `is_late = true`; one more than 2 days behind is
     `stale_event`. Watermarks are per partition because Kafka only orders within a partition. A per-tenant watermark
     falsely flagged 1,918 of 2,796 burst events as late during development.
4. **Deduplicate.** Batch-select existing `(transaction_id, payload_hash)`. If the id exists with the same hash, it is
   an idempotent replay and counted as a duplicate. If the hash differs, it is `conflicting_duplicate` and goes to the
   dead-letter queue. Within-batch repeats are handled the same way.
5. **Features.** The feature engine reads customer (30 d), merchant (2 d) and device (2 d) history from Redis
   sorted sets, **excluding the transaction being scored**, and only history at or before its event time.
6. **Score.** One batched `predict_proba` over `n × (features + 1)` rows gives scores plus occlusion explanations.
7. **Persist atomically** in one transaction:
   - `INSERT … ON CONFLICT DO NOTHING RETURNING` for transactions;
   - labels, predictions and alerts are written only for ids that were actually inserted;
   - dead letters go in with `ON CONFLICT DO NOTHING` on (topic, partition, offset).
8. **Publish dead letters** to `transactions.dlq` (with a `reason` header) and flush. If the flush fails, the consumer
   refuses to commit.
9. **Commit offsets synchronously.** This happens after step 7 succeeds.

Retries: DB or Redis connection errors retry the whole batch with exponential backoff (5 attempts). After that the
consumer exits without committing, Docker restarts it and the batch is redelivered. Poison messages never block the
partition, because they are quarantined and committed.

### Delivery guarantees

| Failure | Outcome |
|---|---|
| Crash before DB commit | Redelivered; processed normally |
| Crash after DB commit, before offset commit | Redelivered; every event counted as a duplicate; no new rows, scores unchanged (test: `test_replayed_events_never_create_duplicate_transactions`) |
| Producer retry / duplicate send | Same as above |
| Consumer restart | Resumes from committed offsets; no reprocessing (test: `test_kafka_pipeline_end_to_end_with_dlq_and_restart`) |
| Redis written, DB commit failed | Redis entries are keyed by txn id and excluded when that txn is re-scored, so features are identical on retry |

## Feature store layout (Redis)

```
aegis:{tenant}:cust:{customer_id}   ZSET  member = {"txn_id","ts","amount_usd","country","device_id","local_hour"}  score = epoch
aegis:{tenant}:merch:{merchant_id}  ZSET  member = {"txn_id","ts","customer_id","declined"}
aegis:{tenant}:dev:{device_id}      ZSET  member = {"txn_id","ts","customer_id"}
aegis:{tenant}:p{partition}:watermark  ZSET (ZADD GT ⇒ monotonic)
```

Retention is trimmed on write (30 d / 500 events per customer, 2 d per merchant and device) and keys expire.
Offline training uses `InMemoryFeatureStore`, which implements the same protocol, so the **same**
`compute_features` code produces training and serving features.

## Data quality checks (every 60 s, `aegis/quality/checks.py`)

| Check | Dimension | Rule |
|---|---|---|
| `prediction_coverage_pct` | completeness | ≥ 99.9% of last-24h transactions have a prediction |
| `duplicate_event_ids` | uniqueness | 0 |
| `dead_letter_rate_pct_1h` | validity | warn > 2%, fail > 10% |
| `large_amount_outliers_24h` | validity | warn > 5 |
| `future_dated_transactions` | validity | 0 |
| `late_event_rate_pct_1h` | timeliness | warn > 5%, fail > 20% |
| `seconds_since_last_event` | timeliness | warn > 120 s, fail > 900 s |
| `alert_rate_pct_24h` | consistency | warn > 10%, fail > 25% |
| `cross_tenant_reference_violations` | consistency | 0 |
| `failed_dbt_tests_latest_run` | consistency | 0 |

## dbt

`dbt/` builds into the `analytics` schema on a 120-second loop. Each invocation's `run_results.json` is recorded
into `public.transformation_runs` by `record_results.py`, and that table feeds the UI and the
`failed_dbt_tests_latest_run` check.

| Layer | Model | Purpose |
|---|---|---|
| seed | `fx_rates` | Synthetic FX to USD |
| staging (views) | `stg_transactions`, `stg_predictions`, `stg_labels` | Typed, USD-normalised, alert flag joined |
| marts (tables) | `fct_hourly_volume` | Hourly volume, USD value, alerts, avg score, late events |
| | `fct_daily_summary` | Daily customers, merchants, value, decline and late shares |
| | `fct_fraud_rate_daily` | Simulated fraud rate vs alert rate and alert precision |
| | `fct_risk_by_category` | Risk profile per merchant category |
| | `fct_risk_distribution` | Score histogram, all bands present |
| | `dim_customer_behavior` | Per-customer stats (devices, countries, max score, alerts) |
| | `dq_completeness` | Pass rates: prediction coverage, FX availability, known customer, not late, not future |

There are 23 tests. Schema tests cover unique, not_null, accepted_values and relationships, plus a custom
unique-combination generic test. Singular tests cover score range vs category band, mart reconciliation against
staging, and tenant attribution. Source freshness is declared on `transactions`.
