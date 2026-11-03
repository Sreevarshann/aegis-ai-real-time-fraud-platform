# Design decisions

Short ADR-style records. Several of these came from bugs found while running the real system. Those are marked 🐞.

### 1. Monorepo, few services
One backend image runs five roles: migrate, trainer, consumer, api and simulator. Separate processes exist only where
failure isolation or scaling differs. Consumer vs API: scoring load must not starve user requests. dbt runs as its
own image so its dependency tree stays isolated from the application.

### 2. Redpanda over Apache Kafka
Kafka-API compatible, a single binary, no ZooKeeper/KRaft tuning, and ~768 MB in dev mode. The client code
(confluent-kafka) works unchanged against Kafka.

### 3. At-least-once + idempotent writes instead of Kafka transactions
- Offsets are committed after the database commit.
- The `transaction_id` primary key with `ON CONFLICT DO NOTHING` makes replays no-ops.
- Redis feature writes are keyed by transaction id, and readers exclude the scored transaction, so recomputed features
  are identical.

This is simpler than EOS, and it holds across the DB boundary, which Kafka transactions cannot cover. Content hashes
distinguish an exact replay from a conflicting reuse of an id.

### 4. Same feature code offline and online
A `FeatureStore` protocol has in-memory and Redis implementations. Training replays the synthetic history through
`FeatureEngine` in event-time order. That removes the most common source of train/serve skew: two implementations of
the same feature.

### 5. 🐞 Simulation artifact that leaked the label
The first live run alerted on 41 of 183 normal transactions. The cause was in the generator: collusive-merchant victims
were drawn from the whole population, not the training subset. "No transaction history" therefore became a near-perfect
fraud signal in training, and every cold-start live customer looked like fraud. The fix draws victims from the same
pool and includes cold-start rows in training.

### 6. 🐞 Train/serve skew in merchant features
An investigation showed "14 merchant transactions in 1 h" adding +58 points. Training used 1,500 customers against all
600 merchants, so per-merchant traffic was ~20× lower offline than online. Training now uses an independent population
with the **same customer-to-merchant density** as live.

### 7. 🐞 Watermarks per partition, plus a processing-time bound
- A per-tenant watermark flagged 1,918 of 2,796 burst events as late, because Kafka only orders within a partition and
  partitions are consumed unevenly. Watermarks are now keyed by (tenant, partition).
- An integration test then showed that a lone 5-day-old event could define a fresh watermark and be accepted. There is
  now an absolute processing-time staleness bound as well.

### 8. 🐞 Quarantine must survive hostile payloads
Binary garbage with NUL bytes crashed the DLQ insert, because PostgreSQL text cannot contain `\x00`. The consumer
behaved correctly: it did not commit offsets, so nothing was lost. NULs are now escaped before storage.

### 9. 🐞 Data-quality check caught an id collision
`duplicate_event_ids` failed after the scenario pack. Two simulator instances shared a stream seed and generated the
same UUIDs. Each instance now has its own seed. The check stayed in place as a guard.

### 10. Explanations: occlusion rather than SHAP
- SHAP would add numba/llvmlite to every image.
- Single-feature baseline substitution is model-agnostic, exactly what it claims to be (a counterfactual on the
  deployed model), and cheap: one batched call of `n × 26` rows.
- Its limitation (no interactions) is documented in the UI and in reports. TreeSHAP is listed as future work.

### 11. Calibrated probabilities, F1-optimal threshold
- Class weighting distorts probabilities, so Platt scaling on validation restores a meaningful 0–100 score.
- The alert threshold maximises validation F1. A real deployment would pick it from investigation capacity.
- The test split is used once, for reporting.

### 12. Investigations: deterministic first, LLM optional and gated
- Evidence and indicators come from SQL tools and explicit rules, so the platform is fully functional without an LLM.
- The LLM may only rephrase. Its output is accepted only if every citation exists, at least two are present, and every
  multi-digit number appears in the evidence. Otherwise the deterministic narrative is used, with the reason recorded.
- LangGraph gives an inspectable state machine with a conditional exit (transaction not found).

### 13. SQLAlchemy Core, not ORM
Queries are explicit, reviewable SQL with bound parameters. Analytical queries (`generate_series`, `FILTER`,
`width_bucket`) read naturally. Every repository function's signature makes the tenant predicate mandatory.

### 14. SSE over fetch, with polling fallback
`EventSource` can't send an `Authorization` header, and putting a JWT in the URL leaks it into logs. A small fetch-based
SSE reader does exponential-backoff reconnects and falls back to cursor polling after repeated failures. The UI shows
which mode it is in.

### 15. 🐞 nginx resolves the API dynamically
After the API container was recreated, nginx kept proxying to its old IP and returned 502s. It now resolves `api`
through Docker's DNS (`resolver 127.0.0.11`, variable upstream).

### 16. Realistic per-customer rates with a large population
A live stream at realistic rates (~4 transactions/customer/day) needs a large population to be visibly "live". There
are 60k customers giving ~2.8 events/s. Rate multipliers exist but are documented as distorting velocity features.

### 17. Reproducibility scope
Data generation is exactly reproducible from the seed. Model training is bit-identical within the same container image
(verified twice). Across CPU architectures and BLAS builds, metrics differ in the third decimal. The README reports the
containerised result.
