# Architecture

## Services and responsibilities

| Service | Image | Responsibility | Why it is separate |
|---|---|---|---|
| `postgres` | postgres:16-alpine | System of record + dbt warehouse (`public` operational, `analytics` marts) | Durable, transactional, constraint-enforcing |
| `redis` | redis:7.4-alpine (AOF on) | Rolling behavioural state for online features; per-partition watermarks | Sub-ms sorted-set windows; survives restarts |
| `redpanda` | redpanda v24 (dev mode) | Kafka API: `transactions.v1` (3 partitions) and `transactions.dlq` | Decouples producers from scoring; replay; backpressure |
| `mlflow` | mlflow v3.1 | Experiment tracking (SQLite backend + proxied artifacts) | Standard tooling, off the hot path |
| `migrate` | backend (one-shot) | `alembic upgrade head` + idempotent seed | Schema changes run exactly once before anything else |
| `trainer` | backend (one-shot) | Train, evaluate, log to MLflow, register the active model | Training is a batch job, not a service |
| `consumer` | backend | Validate → dedup → featurise → score → persist; DQ checks every 60s; metrics on :9108 | Isolates scoring load from user traffic; scales with partitions |
| `api` | backend | FastAPI: auth, tenant-scoped reads, investigations, simulator control, SSE | User-facing latency and security boundary |
| `simulator` | backend | Live synthetic traffic at realistic per-customer rates (~2.8 ev/s) | Keeps the demo "live" |
| `dbt` | dbt Core | `dbt build` every 120 s; records run results | Analytics are batch; failure doesn't affect the hot path |
| `frontend` | nginx | Static React build + reverse proxy to `api` (SSE unbuffered) | Single origin, no CORS needed in the stack |
| `ollama` *(profile llm)* | ollama | Optional local LLM for narration | Heavy; opt-in |
| `prometheus`, `grafana` *(profile monitoring)* | | Scrape consumer + API, dashboard | Optional |

Startup ordering is expressed with health checks and `service_completed_successfully`:
`postgres → migrate → trainer → {consumer, api} → {simulator, frontend}`.
`scripts/wait-for-stack.sh` fails fast with logs if a one-shot job exits non-zero or a service crash-loops.

## Backend layering

```
api/routers/*      HTTP: request validation (Pydantic), auth dependencies, status codes
services/*         orchestration: investigations, drift, health, auth
repositories/*     SQL only: every function takes tenant_id; SQLAlchemy Core or bound text()
db/tables.py       Core table metadata (mirrors the Alembic DDL)
```

The streaming path (`streaming/processor.py`) uses `repositories/pipeline.py` the same way. `TransactionProcessor`
is pure Python with injected engine, feature store, reference cache and model provider, so it is tested directly
against real infrastructure without Kafka. `ConsumerService` adds the Kafka loop, retry and commit semantics.

```
aegis/
  events/schema.py         versioned envelope + payload contract (no label field)
  simulator/               reference population + seeded generator
  features/                FeatureStore protocol, in-memory & Redis stores, point-in-time features
  ml/                      dataset builder, training CLI, model bundle (score + explain)
  streaming/               kafka helpers, defects, producer CLI, processor, consumer service
  investigation/           evidence tools, LangGraph graph, Ollama + grounding gate
  quality/checks.py        operational data-quality checks
  observability/           structlog config, Prometheus metrics
  api/, services/, repositories/, security.py, seed.py, config.py
```

## Database

Operational schema (`public`, created by `backend/alembic/versions/0001_initial_schema.py`):

| Table | Key points |
|---|---|
| `tenants` | `tenant_id` slug PK |
| `users` | bcrypt hash, `role` CHECK (admin/analyst/viewer), FK tenant, unique email |
| `customers`, `merchants` | Synthetic reference data; composite PK `(tenant_id, id)` keeps ids tenant-local |
| `transactions` | PK `transaction_id` (idempotency key); `seq` identity cursor; composite FKs to customers/merchants; `amount > 0`; status CHECK; `payload_hash`; Kafka partition/offset for lineage |
| `simulation_labels` | Ground truth, separate table, never read by scoring |
| `model_versions` | Registry; partial unique index ⇒ at most one `is_active` |
| `risk_predictions` | 1:1 with transactions; score CHECK 0–100; category CHECK; features + explanation JSONB |
| `risk_alerts` | 1:1 with flagged transactions; severity/status CHECKs |
| `investigations` | Report JSONB, engine CHECK (deterministic/ollama), priority P1–P4, review status |
| `dead_letter_events` | Unique `(topic, partition, offset)` so redelivery never double-quarantines |
| `data_quality_results`, `pipeline_stats`, `transformation_runs`, `audit_events` | Observability history |

Indexes and the queries they serve:

| Index | Serves |
|---|---|
| `transactions (tenant_id, seq DESC)` | Live feed, cursor pagination, SSE polling |
| `transactions (tenant_id, event_timestamp DESC)` | Time-window analytics, overview |
| `transactions (tenant_id, customer_id, event_timestamp DESC)` | Investigation customer history |
| `transactions (tenant_id, device_id, …)`, `(tenant_id, merchant_id, …)` | Device/merchant evidence tools |
| `risk_predictions (tenant_id, scored_at DESC)`, `(model_version_id, scored_at DESC)` | Distributions, drift sampling |
| `risk_alerts (tenant_id, status, created_at DESC)` | Analyst queue tabs |
| `investigations (tenant_id, created_at DESC)`, `(tenant_id, transaction_id)` | Lists, alert → investigation lookup |
| `ux_model_versions_single_active` (partial) | Registry invariant |

Analytical schema (`analytics`, built by dbt): see [DATA_PIPELINE.md](DATA_PIPELINE.md#dbt).

## Multi-tenancy

- The tenant comes **only** from the verified JWT (`tid` claim); it is never taken from request parameters.
- Every repository function takes `tenant_id` and applies it in SQL. Platform-level tables (model registry,
  pipeline stats, DQ results) contain no tenant business data.
- Dead letters whose tenant can't be determined (e.g. malformed JSON) are visible to admins only.
- The `cross_tenant_reference_violations` DQ check and a dbt test assert that predictions and alerts always carry
  their transaction's tenant.

## Observability

- **Logs:** structlog JSON to stdout, with `request_id` bound per API request (and returned as `x-request-id`).
- **Metrics:** the consumer exposes `aegis_events_{consumed,persisted,duplicate,late}_total`,
  `aegis_events_dead_lettered_total{reason}`, `aegis_validation_failures_total{reason}`,
  `aegis_processing_errors_total{stage}`, `aegis_alerts_created_total{severity}`, histograms for batch time, per-event
  scoring time, end-to-end latency and risk scores, plus a consumer-lag gauge. The API exposes
  `aegis_api_request_seconds{method,route,status}`.
- **Health:** `/health/live`; `/health/ready` checks the DB and the active model (used by Compose). The Operations
  page probes Postgres, Redis, Redpanda, MLflow, the consumer and (if enabled) Ollama, with latency.
- **Pipeline windows:** the consumer writes a row to `pipeline_stats` every 10 s (consumed, persisted, duplicates,
  dead-lettered, late, errors, lag, average batch ms), which gives history without Prometheus.
