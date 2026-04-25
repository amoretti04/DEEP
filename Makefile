# DIP developer Makefile
# See README.md for full workflow. Targets are phony and ordered by frequency of use.

.PHONY: help install dev lint format typecheck test test-unit test-integration coverage \
        sources-validate blueprint-import migrate revision api web compose-up compose-down \
        compose-logs clean precommit sbom secrets-scan

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\n\033[1mDIP — common make targets\033[0m\n\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ─── Environment ──────────────────────────────────────────────────────────────
install:  ## Install production deps
	pip install -e .

dev:  ## Install dev deps + pre-commit hooks
	pip install -e ".[dev]"
	pre-commit install --hook-type pre-commit --hook-type commit-msg

# ─── Code quality ─────────────────────────────────────────────────────────────
lint:  ## Run ruff lint
	ruff check libs services scripts tests

format:  ## Run ruff format (and fix lint where safe)
	ruff format libs services scripts tests
	ruff check --fix libs services scripts tests

typecheck:  ## Strict mypy
	mypy libs services scripts

precommit:  ## Run all pre-commit hooks
	pre-commit run --all-files

secrets-scan:  ## Scan for leaked credentials
	detect-secrets scan --all-files --baseline .secrets.baseline

# ─── Tests ────────────────────────────────────────────────────────────────────
test: lint typecheck test-unit  ## Full local CI loop

test-unit:  ## Run unit tests (fast)
	pytest -m "not integration" --cov --cov-report=term-missing

test-integration:  ## Run integration tests (requires docker)
	pytest -m integration

coverage:  ## Coverage report with branch coverage
	pytest --cov --cov-report=html --cov-report=term --cov-branch
	@echo "HTML report: htmlcov/index.html"

# ─── Sources & taxonomy ───────────────────────────────────────────────────────
sources-validate:  ## Validate every Source Card against the JSON schema
	python -m scripts.validate_sources

blueprint-import:  ## Import the implementation blueprint xlsx into the DB
	python -m scripts.blueprint_import \
		--file $${BLUEPRINT_FILE:-Distressed_Investment_Sources_Implementation_Blueprint.xlsx} \
		--mode $${IMPORT_MODE:-upsert}

# ─── Database ─────────────────────────────────────────────────────────────────
migrate:  ## Run Alembic upgrade head
	cd infra && alembic upgrade head

revision:  ## Create a new Alembic revision. Usage: make revision MSG="add_foo"
	cd infra && alembic revision --autogenerate -m "$(MSG)"

# ─── Services ─────────────────────────────────────────────────────────────────
api:  ## Run FastAPI locally (reload)
	uvicorn services.api.main:app --reload --host 0.0.0.0 --port 8000

web:  ## Run React dev server
	cd services/web && npm run dev

# ─── Docker compose ───────────────────────────────────────────────────────────
compose-up:  ## Start local stack (postgres, redis, opensearch, kafka, temporal, prefect, minio)
	docker compose -f infra/docker-compose.yaml up -d

compose-down:  ## Stop local stack
	docker compose -f infra/docker-compose.yaml down

compose-logs:  ## Tail logs
	docker compose -f infra/docker-compose.yaml logs -f --tail=200

# ─── Supply chain ─────────────────────────────────────────────────────────────
sbom:  ## Generate SBOM (CycloneDX JSON)
	cyclonedx-py -o sbom.json .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null; true
	rm -rf .coverage htmlcov dist build *.egg-info
