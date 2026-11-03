# How this Git history was produced

**This history is a reconstruction, not the original development timeline.**

AEGIS AI was built and verified as a single working snapshot on 2026-11-02/03. The snapshot was:
- verified with `make clean` and then `make demo` from a clean state;
- tested: 56 backend tests, 11 frontend unit tests, 7 Playwright tests and dbt PASS=34;
- first published by mistake to a different account as two commits.

The snapshot is preserved as tag `snapshot-verified-2026-11-03` (tree `cb46ee77984962cc18e7e39961208148cc602bb5`)
on the branch `backup/sreevarshan12-snapshot` in the author's local clone.

On 2026-11-03 that snapshot was reorganised into the commits below, ordered by real module dependencies so that each
commit only adds code whose imports already exist. The procedure for every commit was:

1. Restore exactly the relevant files from the verified snapshot (`git checkout <snapshot> -- <paths>`). File
   contents are byte-identical to the snapshot except for the two intentional changes listed below.
2. Inspect the staged diff.
3. Run the checks feasible at that point:
   - ruff lint and format on the backend;
   - an import of every backend module present;
   - mypy, once the full backend existed;
   - the 42 unit tests, in the commit that adds them;
   - the 14 integration tests against real PostgreSQL, Redis and Redpanda, in the commit that adds them;
   - `dbt parse` and then `dbt build` (PASS=34);
   - tsc, ESLint and Vitest at every frontend commit, plus a production build;
   - Compose config validation, a Makefile dry-run, and workflow/monitoring config parsing.
4. Commit with the real current timestamp. No dates were back-dated.
5. Push and confirm that the remote SHA matches.

## Intentional differences from the snapshot
- `frontend/tsconfig.tsbuildinfo` (a TypeScript build artifact accidentally tracked in the snapshot) is not carried
  over, and `*.tsbuildinfo` is now ignored.
- The README clone URL points to `github.com/Sreevarshann/...` instead of the mistaken account.

Everything else (source, tests, docs, screenshots, Docker and CI configuration) is unchanged.

## Commits (43 including this one)
1. `40c31ab` chore: initialize repository with ignore rules, example config and license
1. `a02e7f3` build(backend): add Python package and dependency management
1. `150e3a3` feat(core): add typed environment configuration and structured logging
1. `4675dbb` feat(db): define PostgreSQL schema metadata and engine helpers
1. `fad539a` feat(db): add Alembic migration with constraints and documented indexes
1. `005a4cb` feat(events): define versioned transaction event contract
1. `4646600` feat(simulator): add deterministic synthetic population and transaction generator
1. `1dede70` feat(features): add point-in-time feature engine with in-memory and Redis stores
1. `da2e8d2` feat(ml): add model bundle with calibrated risk scoring and occlusion explanations
1. `dcdf366` feat(ml): add reproducible training pipeline with MLflow tracking and model registry
1. `43d81b9` feat(streaming): add Kafka client helpers and data-defect injection
1. `f32a6f3` feat(streaming): add synthetic transaction producer CLI
1. `bd8d05d` feat(quality): add Prometheus metrics and operational data quality checks
1. `b39d117` feat(streaming): implement idempotent batch processor with validation, dedup and DLQ
1. `2a709a0` feat(streaming): add Kafka consumer service with retries and safe offset commits
1. `8efd339` feat(auth): add password hashing, JWT tokens and demo data seeding
1. `b91837b` feat(agents): add tenant-scoped investigation evidence tools
1. `3d0f618` feat(agents): add optional Ollama narration with a grounding gate
1. `4d618ae` feat(agents): implement LangGraph investigation workflow
1. `d66e14e` feat(api): add tenant-scoped repositories for transactions, investigations and operations
1. `b859c2f` feat(api): add service layer for auth, investigations, drift and health
1. `f96a3ec` feat(api): add FastAPI application with JWT auth, RBAC and request validation
1. `efe5a50` test(backend): add unit tests for simulator, schema, features, ML and security
1. `3098453` feat(analytics): add dbt project with FX seed, sources and staging models
1. `e63e289` feat(analytics): add analytical marts and data tests
1. `b063700` feat(analytics): add scheduled dbt runner that records run results
1. `99ce0f0` test(integration): verify pipeline, Kafka, API isolation and dbt against real services
1. `0aaf184` feat(frontend): scaffold React + TypeScript dashboard with Tailwind design tokens
1. `c8e2d58` feat(frontend): add authentication, UI primitives and application layout
1. `dde544f` feat(frontend): build overview dashboard with charts and simulator controls
1. `fdd6d1b` feat(frontend): add live transaction feed with SSE and polling fallback
1. `c772d47` feat(frontend): add investigation queue and report views
1. `ef8685d` feat(frontend): add data intelligence and model intelligence dashboards
1. `ab2bef9` feat(frontend): add system operations page and wire application routes
1. `2ee47c1` build(docker): add Dockerfiles, nginx proxy and Compose orchestration
1. `a00baad` feat(ops): add Makefile, stack readiness check and end-to-end smoke test
1. `8547e37` feat(observability): add optional Prometheus and Grafana monitoring profile
1. `a66f766` test(e2e): add Playwright browser tests and documentation screenshot capture
1. `9abbc07` ci: add GitHub Actions pipeline with integration, end-to-end and secret scanning
1. `759ff3f` chore(frontend): ignore TypeScript incremental build info
1. `d1092c4` docs: add architecture, data pipeline, ML model, API, demo and design decision docs
1. `bae0925` docs: add README with architecture diagrams and genuine dashboard screenshots
1. *(this commit)* docs: record how this history was reconstructed
