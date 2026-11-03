# AEGIS AI - developer entry points. Run `make help` for the list.
SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE   ?= docker compose
PY        ?= python3
BACKEND   := backend
VENV      := $(BACKEND)/.venv
VPY       := $(VENV)/bin/python
DBT_VENV  := dbt/.venv
export PYTHONPATH := $(CURDIR)/$(BACKEND)/src
export MLFLOW_DISABLE_AGENT_HINT := 1

# Host-side connection settings for tests and tools (ports published by docker-compose.yml).
-include .env
PG_PASS   := $(or $(POSTGRES_PASSWORD),aegis)
export AEGIS_TEST_DATABASE_URL ?= postgresql+psycopg://$(or $(POSTGRES_USER),aegis):$(PG_PASS)@localhost:55432/aegis_test

.PHONY: help setup up demo test test-unit test-integration test-frontend test-e2e lint down clean \
        infra train logs ps incident screenshots smoke check-docker

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

check-docker:
	@command -v docker >/dev/null || { echo "ERROR: docker is not installed (Docker Desktop, Colima or Rancher Desktop)."; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "ERROR: the Docker daemon is not running. Start Docker Desktop / 'colima start' and retry."; exit 1; }
	@$(COMPOSE) version >/dev/null 2>&1 || { echo "ERROR: 'docker compose' v2 plugin not found."; exit 1; }

setup: check-docker ## Create .env, install local dev tooling, build images
	@[ -f .env ] || { cp .env.example .env && echo "Created .env from .env.example (local, non-production values)."; }
	@if command -v uv >/dev/null; then uv venv -q --python 3.11 $(VENV) && uv pip install -q -p $(VPY) -e "$(BACKEND)[dev]"; \
	  else $(PY) -m venv $(VENV) && $(VPY) -m pip install -q -e "$(BACKEND)[dev]"; fi
	@if command -v uv >/dev/null; then uv venv -q --python 3.11 $(DBT_VENV) && uv pip install -q -p $(DBT_VENV)/bin/python -r dbt/requirements.txt; \
	  else $(PY) -m venv $(DBT_VENV) && $(DBT_VENV)/bin/pip install -q -r dbt/requirements.txt; fi
	@cd frontend && npm ci --no-audit --no-fund
	$(COMPOSE) build
	@echo "Setup complete. Next: make up  (or make demo)"

up: check-docker ## Start the full stack (migrations, seed, training, pipeline, API, UI) and wait until healthy
	@[ -f .env ] || cp .env.example .env
	$(COMPOSE) up -d --build
	@./scripts/wait-for-stack.sh

infra: check-docker ## Start only PostgreSQL, Redis, Redpanda and MLflow (for local development/tests)
	@[ -f .env ] || cp .env.example .env
	$(COMPOSE) up -d --wait postgres redis redpanda mlflow

demo: up ## Start everything, inject fraud scenarios + malformed data, build analytics, verify end to end
	$(COMPOSE) exec -T api python -m aegis.streaming.producer scenarios
	@echo "Waiting for the consumer to process the scenario pack..." && sleep 15
	$(COMPOSE) exec -T dbt sh -c "dbt build --profiles-dir . && python record_results.py"
	@$(PY) scripts/smoke_test.py --base http://localhost:3000 --password "$(or $(AEGIS_DEMO_USER_PASSWORD),AegisDemo!2026)"
	@echo ""
	@echo "  Dashboard : http://localhost:3000   (admin@northwind.demo / analyst@meridian.demo, password from .env)"
	@echo "  API docs  : http://localhost:8000/docs"
	@echo "  MLflow    : http://localhost:5050"
	@echo "  Metrics   : http://localhost:9108/metrics (consumer) · http://localhost:8000/metrics (API)"

smoke: ## Run the end-to-end smoke test against the running stack
	@$(PY) scripts/smoke_test.py --base http://localhost:3000 --password "$(or $(AEGIS_DEMO_USER_PASSWORD),AegisDemo!2026)"

incident: ## Replay the documented malformed-data incident (see docs/DEMO.md)
	$(COMPOSE) exec -T api python -m aegis.streaming.producer incident

train: ## Retrain the model inside the stack and register it as active (consumer hot-swaps it)
	$(COMPOSE) run --rm trainer python -m aegis.ml.train --register

test: test-unit test-integration test-frontend ## Run backend unit + integration tests and frontend tests

test-unit: ## Backend unit tests (no infrastructure needed)
	cd $(BACKEND) && .venv/bin/pytest tests/unit -q

test-integration: infra ## Backend integration tests against real PostgreSQL/Redis/Redpanda (+ dbt)
	cd $(BACKEND) && AEGIS_REQUIRE_INTEGRATION=1 .venv/bin/pytest tests/integration -q

test-frontend: ## Frontend typecheck + unit tests
	cd frontend && npx tsc -b && npx vitest run

test-e2e: ## Playwright browser tests against the running stack (make up first)
	cd frontend && E2E_BASE_URL=http://localhost:3000 npx playwright test

screenshots: ## Regenerate docs/screenshots from the running stack with Playwright
	cd frontend && E2E_BASE_URL=http://localhost:3000 SCREENSHOTS=1 npx playwright test e2e/screenshots.spec.ts

lint: ## Ruff, mypy, ESLint and TypeScript checks
	cd $(BACKEND) && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/mypy src
	cd frontend && npx eslint . --max-warnings=0 && npx tsc -b

logs: ## Tail logs of the pipeline services
	$(COMPOSE) logs -f --tail=50 consumer api simulator

ps: ## Show service status
	$(COMPOSE) ps

down: ## Stop the stack (keeps data volumes)
	$(COMPOSE) --profile llm --profile monitoring down

clean: ## Stop the stack and delete all volumes, build outputs and local artifacts
	$(COMPOSE) --profile llm --profile monitoring down -v --remove-orphans
	rm -rf $(BACKEND)/artifacts frontend/dist frontend/playwright-report frontend/test-results dbt/target dbt/logs
