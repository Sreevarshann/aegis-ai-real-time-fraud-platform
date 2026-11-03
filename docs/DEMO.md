# Demo guide

## 1. Start

```bash
make demo
```

Expected tail (captured from a real run; counts will differ):

```
docker compose exec -T api python -m aegis.streaming.producer scenarios
{"sent": 276, "expected_outcomes": {"accept": 264, "dead_letter": 10, "duplicate": 2}}
...
Done. PASS=34 WARN=0 ERROR=0 SKIP=0 TOTAL=34
recorded 34 dbt results for invocation e603b91d-…; failures: 0
AEGIS end-to-end smoke test
  ✓ web UI is served
  ✓ authenticated through the UI reverse proxy
  ✓ published 151 events to Kafka via the API ({'accept': 149, 'duplicate': 1, 'dead_letter': 1})
  ✓ consumer persisted new transactions (6119 -> 6272)
  ✓ every recent transaction has a stored risk prediction
  ✓ transaction detail served with model his-20261102233520
  ✓ investigation bd164bb9 completed (deterministic engine, priority P2)
  ✓ dead-letter quarantine visible (71 events)
  ✓ all services healthy: postgres, redis, redpanda, mlflow, consumer
Smoke test passed.
```

Open http://localhost:3000 and sign in as `admin@northwind.demo`. The password is `AEGIS_DEMO_USER_PASSWORD` in `.env`.

## 2. Walkthrough (≈ 5 minutes)

1. **Overview.** The live rate is ~1–3 tx/s from the background simulator. "Suspicious activity" counts open alerts.
   *Recent alerts* shows each alert's strongest model factor. The health panel lists every dependency with its latency.
2. **Synthetic traffic panel** (admin only). *Inject fraud scenarios* publishes one incident of each fraud type plus
   background traffic, duplicates and malformed messages. The confirmation shows the intended outcome counts.
3. **Live Transactions.** The badge reads *Live stream* (SSE). Stop the API (`docker compose stop api`) and the badge
   goes *Reconnecting* → *Offline*. Start it again (`docker compose start api`) and the feed resumes in *Polling
   fallback*, then upgrades back to *Live stream* after ~15 s of healthy polls. This sequence was verified against the
   running stack. Filter to *Score ≥ 60*, click a row and
   read *Main contributing factors*. Each factor is the change in probability when that feature is reset to its
   training median. The drawer also shows the Kafka partition/offset and whether the event arrived late.
4. **Fraud Investigations.** Choose an *Open* alert and press **Investigate**. The report contains:
   - a narrative with evidence citations `[E1]…[E6]`;
   - weighted indicators, each linking to its evidence;
   - evidence cards with the tool that produced them and the database IDs used;
   - a timeline, the recommended action and limitations.

   Set *Status → Closed Fraud* and save. The alert moves to *Confirmed Fraud* in the queue.
5. **Data Intelligence.** Shows the latest DQ run (10 checks), quarantined events with exact reasons, dbt node results,
   completeness pass rates and marts (hourly volume, risk by category, fraud-rate trend with alert precision).
6. **Model Intelligence.** Shows test metrics, confusion matrix, LR vs GBM comparison, per-scenario alert rates, permutation
   importance, PSI drift (reference vs live histograms) and live precision/recall against simulator labels.
7. **System Operations.** Shows consumer counters (consumed / persisted / duplicates skipped / dead-lettered / lag),
   end-to-end and scoring latency, throughput per 10-second window, recent pipeline errors and the audit log.
8. **Tenant isolation.** Sign out and sign in as `analyst@meridian.demo`. Every customer id is now `MR-…`. Pasting a
   Northwind transaction id into `/api/v1/transactions/{id}` returns 404.

## Incident scenario: malformed data is quarantined

**Scenario.** An upstream system starts emitting broken events: a missing field, a negative amount, an unknown
currency, an invalid country, a truncated JSON document, an old schema version, a naive timestamp, an unknown customer,
a 3-day-old replay and binary garbage containing NUL bytes.

```bash
make incident
```

**Observed result** (real run, 2026-11-03):

```
{"sent": 10, "expected_outcomes": {"dead_letter": 10}}

consumer log:
{"consumed": 15, "persisted": 5, "duplicates": 0,
 "dead_letters": {"schema_validation_failed": 5, "malformed_json": 2, "unsupported_schema_version": 1,
                  "stale_event": 1, "unknown_customer": 1}, ...,"event": "batch_processed"}

SELECT reason, count(*) FROM dead_letter_events WHERE received_at > now() - interval '1 minute' GROUP BY 1;
 malformed_json             |     2
 schema_validation_failed   |     6     (5 from the drill + 1 from the live simulator's own injected defects)
 stale_event                |     1
 unknown_customer           |     1
 unsupported_schema_version |     1

consumer /metrics:
aegis_events_dead_lettered_total{reason="schema_validation_failed"} 6.0
aegis_events_dead_lettered_total{reason="malformed_json"} 2.0
...
```

**What happened.**
- All 10 messages were rejected **without blocking the partition**. The 5 valid events in the same batch were
  persisted and offsets were committed.
- Each rejected message went to `transactions.dlq` with a `reason` header, and to `dead_letter_events` with the field-level
  error and the raw payload. NUL bytes are escaped, a bug this drill originally exposed.
- Re-delivery cannot double-quarantine, because of the unique `(topic, partition, offset)` index.
- The Data Intelligence page shows the new reasons. `dead_letter_rate_pct_1h` warns above 2% and fails above 10%.

**Recovery.** Fix the producer and, if needed, replay corrected events from `dead_letter_events.raw_payload`. The
pipeline needs no intervention.

## Optional: local LLM narration

```bash
docker compose --profile llm up -d ollama
docker compose exec ollama ollama pull llama3.2:3b     # ~2 GB
# set AEGIS_OLLAMA_ENABLED=true in .env, then
docker compose up -d api
```

New investigations show the **Local LLM · llama3.2:3b** badge if the narrative passes the grounding gate. If it fails,
the report says **Deterministic engine** and gives the reason. On a 4-vCPU VM one narration took about 65 s
(screenshot `docs/screenshots/09-llm-investigation.png`).

## Optional: Prometheus + Grafana

```bash
docker compose --profile monitoring up -d
```

Open Grafana at http://localhost:3001 → *AEGIS / AEGIS pipeline*. It shows throughput, dead letters by reason, p95
end-to-end latency, consumer lag, alerts per minute and API p95 by route.
