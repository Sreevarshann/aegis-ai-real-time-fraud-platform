# API reference

Base URL: `http://localhost:8000` directly, or `http://localhost:3000` through the UI's nginx proxy. Interactive
OpenAPI docs are at `/docs`. Every `/api/v1` endpoint except login requires `Authorization: Bearer <token>`. Results
are always limited to the tenant in the token. A resource from another tenant returns **404**, the same as one that
does not exist.

Roles: `viewer` < `analyst` < `admin`. Errors return `{"detail": "..."}`. Validation errors are `422` with field
details.

## Auth

```bash
curl -s -X POST localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"email":"analyst@northwind.demo","password":"<AEGIS_DEMO_USER_PASSWORD>"}'
# {"access_token":"eyJ…","token_type":"bearer","expires_in":28800,"user":{…,"role":"analyst","tenant_id":"northwind"}}
```

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/api/v1/auth/login` | — | `{email, password}` → JWT (HS256, 8 h). Failures audited. |
| GET | `/api/v1/auth/me` | any | Current user |

## Transactions & alerts

| Method | Path | Role | Parameters / body |
|---|---|---|---|
| GET | `/api/v1/overview` | any | `window_minutes` (5–1440). KPIs, `transactions_per_second`, volume series, risk distribution and categories, 8 recent alerts with top reasons |
| GET | `/api/v1/transactions` | any | `limit` ≤ 200, `before_seq` / `after_seq` cursors, `min_score`, `risk_category`, `channel`, `status`, `q` (customer/merchant/device/id search). Returns `{items, next_before_seq}` |
| GET | `/api/v1/transactions/stream` | any | Server-Sent Events. `event: ready` with `{cursor}`, then `event: transactions` with arrays of new rows; keep-alive comments every ~15 s. Optional `after_seq` to resume |
| GET | `/api/v1/transactions/{id}` | any | Detail incl. `features`, `explanation`, `explanation_text`, Kafka partition/offset, model version and threshold |
| GET | `/api/v1/alerts` | any | `status` filter, `limit`, `offset`. Returns `{items, counts}`; items include `top_reasons` and any linked investigation |
| PATCH | `/api/v1/alerts/{id}` | analyst | `{status: open|investigating|escalated|dismissed|confirmed_fraud}` |

## Investigations

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/api/v1/investigations` | analyst | `{transaction_id}` runs the LangGraph workflow synchronously (~20 ms deterministic; 30–90 s with CPU Ollama) and returns `201` with the report. Marks the alert `investigating` |
| GET | `/api/v1/investigations` | any | Recent list with priority, engine and indicator count |
| GET | `/api/v1/investigations/{id}` | any | Full report: `transaction_summary`, `risk_score`, `suspicious_indicators[{code,description,weight,evidence[]}]`, `evidence[{id,tool,title,summary,record_ids,data}]`, `timeline`, `narrative`, `recommended_priority`, `recommended_action`, `engine`, `llm_model`, `llm_note`, `limitations` |
| PATCH | `/api/v1/investigations/{id}` | analyst | `{review_status: in_review|escalated|closed_fraud|closed_legitimate, notes?}`. Synchronises the alert status |

## Models

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/api/v1/models/active` | any | Version, algorithm, threshold, test metrics + confusion matrix, candidate comparison, per-scenario recall, feature importance, 7-day prediction distribution, live performance vs simulator labels |
| GET | `/api/v1/models` | any | Registry history |
| GET | `/api/v1/models/drift` | any | `status`, `score_psi`, `score_status`, reference vs live histograms, per-feature PSI |

## Data & operations

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/api/v1/data-quality` | any | `latest` check results + `history` per run (`history_hours`) |
| POST | `/api/v1/data-quality/run` | analyst | Run all checks now |
| GET | `/api/v1/dead-letters` | any | Tenant's quarantined events + counts by reason (admins also see unattributable ones) |
| GET | `/api/v1/analytics` | any | dbt marts for the tenant + last 5 dbt invocations |
| GET | `/api/v1/operations/health` | any | Per-dependency status + latency, consumer heartbeat age, dbt last-run age |
| GET | `/api/v1/operations/pipeline` | any | 10 s consumer windows, lifetime totals, scraped consumer Prometheus counters and latencies |
| GET | `/api/v1/operations/audit` | admin | Tenant audit log |
| POST | `/api/v1/simulator/runs` | admin | `{mode: burst|scenarios|incident, count ≤ 5000, include_defects}`. Publishes to Kafka for the caller's tenant only |

## Health & metrics

| Path | Notes |
|---|---|
| `GET /health/live` | Process is up |
| `GET /health/ready` | `200` only if the DB is reachable **and** an active model is registered; otherwise `503` with details |
| `GET /metrics` | Prometheus exposition (API). The consumer exposes its own on `:9108/metrics` |
