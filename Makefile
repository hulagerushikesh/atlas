# Atlas — developer convenience commands
# Run `make help` to see all targets.

PYTHON     := .venv/bin/python
UVICORN    := .venv/bin/uvicorn
PYTEST     := .venv/bin/pytest
PORT       ?= 8010
CORPUS_DIR := data/corpus/fastapi
EVAL_DATA  := eval_data/fastapi_dataset.json

.PHONY: help install serve test test-unit test-integration \
        lint typecheck fetch-corpus ingest eval \
        docker-up docker-down clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}' | sort

# ── Setup ──────────────────────────────────────────────────────────────────────

install: ## Create venv and install all dependencies
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"
	@echo "\n✓ Installed. Copy .env.example → .env and fill OPENAI_API_KEY."

# ── Dev server ─────────────────────────────────────────────────────────────────

serve: ## Start the API server with hot-reload (reads .env automatically)
	$(UVICORN) atlas.api.asgi:app --port $(PORT) --reload

serve-prod: ## Start without hot-reload (for Docker / staging)
	$(UVICORN) atlas.api.asgi:app --host 0.0.0.0 --port $(PORT) --workers 2

# ── Tests ──────────────────────────────────────────────────────────────────────

test: ## Run the full test suite (unit + integration)
	$(PYTEST)

test-unit: ## Run unit tests only (fast, no I/O)
	$(PYTEST) tests/unit

test-integration: ## Run integration tests (mocked infra, still fast)
	$(PYTEST) tests/integration

test-cov: ## Run tests and open HTML coverage report
	$(PYTEST) --cov-report=html
	open htmlcov/index.html

# ── Code quality ───────────────────────────────────────────────────────────────

lint: ## Run ruff linter
	.venv/bin/ruff check src tests

typecheck: ## Run mypy type checker
	.venv/bin/mypy src

# ── Corpus & eval ──────────────────────────────────────────────────────────────

fetch-corpus: ## Download FastAPI docs into data/corpus/fastapi/
	$(PYTHON) scripts/fetch_corpus.py --out $(CORPUS_DIR)

ingest: ## Index the FastAPI corpus into Qdrant (requires OPENAI_API_KEY + Qdrant)
	$(PYTHON) scripts/ingest.py $(CORPUS_DIR) --chunker recursive --verbose

ingest-dry: ## Preview which files would be ingested (no API calls)
	$(PYTHON) scripts/ingest.py $(CORPUS_DIR) --dry-run

eval: ## Run eval harness against the FastAPI question set (requires ingested corpus)
	$(PYTHON) scripts/run_eval.py --dataset $(EVAL_DATA) --run-name fastapi-v1

eval-compare: ## Compare latest eval against a baseline (set BASELINE=path/to/report.json)
	$(PYTHON) scripts/run_eval.py --dataset $(EVAL_DATA) --run-name fastapi-v1 \
	  --compare $(BASELINE)

# ── Infrastructure ─────────────────────────────────────────────────────────────

docker-up: ## Start Qdrant + Redis via docker-compose
	docker compose up -d

docker-down: ## Stop Qdrant + Redis
	docker compose down

# ── Cleanup ────────────────────────────────────────────────────────────────────

clean: ## Remove __pycache__, .coverage, htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov .pytest_cache
