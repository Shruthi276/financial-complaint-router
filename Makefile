# Financial Complaint Router - one-word commands for every lifecycle step.
# Run `make help` to list them. Designed for Ubuntu (bash, docker compose v2).
SHELL := /bin/bash
COMPOSE := docker compose
RUN_ML := $(COMPOSE) run --rm --no-deps -e MLFLOW_TRACKING_URI=http://mlflow:5000 retrainer
VENV := .venv
PY := $(VENV)/bin/python
# The pinned stack (numpy 1.26, Ray 2.38, MLflow 2.17) supports Python 3.10-3.12,
# so the venv uses a uv-managed Python 3.11 (same as the Docker images) instead of
# the system python3, which is 3.14 on recent Ubuntu releases.
PYTHON_VERSION := 3.11
UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)

.DEFAULT_GOAL := help
.PHONY: help env setup venv lock build up down restart logs ps train train-sample repro dag metrics \
        test test-unit test-integration test-e2e lint report ci smoke drift rollback clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

env: ## Create .env with fresh secrets (admin token, encryption key, your UID/GID)
	@bash scripts/make_env.sh

setup: ## One-time Ubuntu setup: git, git-lfs, DVC repo, local DVC remote, venv
	@bash scripts/setup_ubuntu.sh

venv: ## Create .venv (Python 3.11 via uv) for tests, lint and dvc on the host
	@[ -x "$(UV)" ] || curl -LsSf https://astral.sh/uv/install.sh | sh
	rm -rf $(VENV)
	$(UV) venv --python $(PYTHON_VERSION) $(VENV)
	$(UV) pip install --python $(PY) -r requirements/dev.lock.txt -e .

lock: ## Re-pin all transitive dependencies (requirements/*.lock.txt) after editing requirements/*.txt
	@[ -x "$(UV)" ] || curl -LsSf https://astral.sh/uv/install.sh | sh
	for f in ml backend dev; do \
	  $(UV) pip compile requirements/$$f.txt --python-version $(PYTHON_VERSION) \
	    --python-platform x86_64-unknown-linux-gnu --exclude-newer 2025-03-01 --no-header \
	    -o requirements/$$f.lock.txt; \
	done

build: env ## Build all docker images
	$(COMPOSE) build

up: env ## Start the whole stack (UI http://localhost:8080)
	mkdir -p reports data/feedback logs models
	$(COMPOSE) up -d --build
	@echo ""
	@echo "  Web app      http://localhost:8080"
	@echo "  API docs     http://localhost:8000/docs"
	@echo "  MLflow       http://localhost:5000"
	@echo "  Grafana      http://localhost:3000   (admin / see .env)"
	@echo "  Prometheus   http://localhost:9090"
	@echo ""
	@echo "  First time? Train a model:  make train"

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

restart: ## Restart all services
	$(COMPOSE) restart

logs: ## Follow logs of all services (Ctrl+C to stop)
	$(COMPOSE) logs -f --tail=100

ps: ## Show service status
	$(COMPOSE) ps

train: ## Run the full DVC pipeline (real CFPB data) inside the ML container
	$(COMPOSE) up -d mlflow
	$(RUN_ML) dvc repro

train-sample: ## Fast pipeline on the bundled sample (no download, ~1 min)
	$(COMPOSE) up -d mlflow
	$(RUN_ML) dvc exp run -S ingest.source=sample -S validate.min_rows=500 -S validate.min_rows_per_class=50 \
	  -S split.max_per_class=250 -S train.similar_index_size=1000 -S register.min_macro_f1=0.4 -S register.min_priority_recall=0.4 -S register.max_priority_flag_rate=1.0
	git checkout -- params.yaml   # the experiment is recorded by DVC + MLflow; restore the real-data params

repro: ## Same as train but on the host venv (needs MLflow at localhost:5000)
	MLFLOW_TRACKING_URI=http://localhost:5000 $(VENV)/bin/dvc repro

dag: ## Print the DVC pipeline DAG
	$(RUN_ML) dvc dag

metrics: ## Show DVC metrics of the current workspace
	$(RUN_ML) dvc metrics show

lint: ## PEP8 / style checks (ruff)
	$(VENV)/bin/ruff check src backend services tests scripts

test-unit: ## Unit tests
	$(PY) -m pytest tests/unit -q

test-integration: ## Integration tests (pipeline on sample + API contract)
	$(PY) -m pytest tests/integration -q

test-e2e: ## End-to-end tests against the running stack (make up && make train first)
	$(PY) -m pytest tests/e2e -m e2e -q

test: ## Unit + integration tests with JUnit XML and coverage
	mkdir -p reports/tests
	$(PY) -m pytest tests -q --junitxml=reports/tests/junit.xml --cov=src/complaint_router --cov=backend/app --cov-report=term

report: test ## Generate docs/test_report.md from the latest test run
	$(PY) scripts/generate_test_report.py reports/tests/junit.xml docs/test_report.md

ci: ## Local CI: lint -> tests -> report -> docker build (also run by the git pre-push hook)
	bash scripts/ci.sh

smoke: ## Quick health check of the running stack
	bash scripts/smoke_test.sh

drift: ## Send off-domain traffic to demonstrate drift detection + auto-retraining
	$(PY) scripts/simulate_drift.py --n 120

rollback: ## Move @champion back to a previous version: make rollback VERSION=3
	$(RUN_ML) python scripts/rollback.py --version $(VERSION)

clean: ## Remove caches (keeps data, models and docker volumes)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
