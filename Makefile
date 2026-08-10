# Toolgate: common developer tasks. Local services run from native binaries (no Docker needed).
# Backend settings come from ./.env (cp .env.example .env); console settings from web/.env.local.

PY := backend/.venv/bin
SHELL := /bin/bash
# The project targets Python 3.12+; CI runs 3.12 and 3.13. Override with `make setup PYTHON=python3.12`.
PYTHON ?= python3.13
LOAD_ENV := set -a && . ../.env && set +a

.PHONY: help setup services services-stop migrate migrate-check seed seed-reset dev-api dev-web \
        demo traffic test attack-report e2e lint format typecheck check build stop clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Create the Python venv and install backend + web deps
	$(PYTHON) -m venv backend/.venv
	$(PY)/pip install -q --upgrade pip
	cd backend && .venv/bin/pip install -q -e ".[dev]"
	cd web && pnpm install

services: ## Start local Postgres + Redis (data under .data/)
	./scripts/local-services.sh start

services-stop: ## Stop local Postgres + Redis
	./scripts/local-services.sh stop

migrate: ## Apply database migrations
	cd backend && $(LOAD_ENV) && .venv/bin/alembic upgrade head

migrate-check: ## Fail if the models and migrations disagree
	cd backend && $(LOAD_ENV) && .venv/bin/alembic upgrade head && .venv/bin/alembic check

seed: ## Add demo + red-team upstreams, policies and accounts (keeps existing data)
	cd backend && $(LOAD_ENV) && .venv/bin/toolgate seed

seed-reset: ## Delete all upstreams and policies, then seed again
	cd backend && $(LOAD_ENV) && .venv/bin/toolgate seed --reset

demo: ## Approve the benign demo tools and stage the rug pull (needs the API running)
	cd backend && $(LOAD_ENV) && .venv/bin/python -m fixtures.demo prepare

TRAFFIC_ARGS ?= --burst 24
traffic: ## Send scripted agent calls through the gateway (needs the API running)
	cd backend && $(LOAD_ENV) && .venv/bin/python -m fixtures.demo traffic $(TRAFFIC_ARGS)

dev-api: ## Run the gateway API with reload on :8101
	cd backend && $(LOAD_ENV) && .venv/bin/uvicorn toolgate.main:app --reload --port 8101

dev-web: ## Run the console with hot reload on :3101
	cd web && pnpm dev

test: ## Run the backend test suite (unit + integration + red-team)
	cd backend && .venv/bin/pytest -q

attack-report: ## Run the red-team suite and write docs/attack-blocked.json
	cd backend && TOOLGATE_WRITE_ATTACK_REPORT=1 .venv/bin/pytest -q tests/redteam

e2e: ## Playwright smoke test of the console (needs services, migrate and seed)
	cd web && pnpm run test:e2e

lint: ## Lint and format-check backend (ruff) and lint web (eslint)
	cd backend && .venv/bin/ruff check src fixtures tests migrations && .venv/bin/ruff format --check src fixtures tests migrations
	cd web && pnpm run lint

format: ## Apply ruff formatting
	cd backend && .venv/bin/ruff format src fixtures tests migrations

typecheck: ## Type-check backend (mypy --strict) and web (tsc)
	cd backend && .venv/bin/mypy
	cd web && pnpm run typecheck

check: lint typecheck test ## Run every quality gate

build: ## Build the production console bundle
	cd web && pnpm run build

stop: services-stop ## Stop local services

clean: ## Remove caches and build output
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache web/.next
