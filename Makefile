# Beyonder launcher for macOS/Linux (mirrors run.ps1).
# Usage: make up | migrate | backend | frontend | frontend-build | test | admin | reembed | down | doctor
# The host never runs npm or node: frontend targets go through docker compose only.

COMPOSE := docker compose -f docker-compose.yml
VENV    := backend/.venv
PY      := $(VENV)/bin/python

.PHONY: up migrate backend frontend frontend-build test admin reembed down doctor venv env

env:
	@test -f .env || { echo ".env missing - copying from .env.example"; cp .env.example .env; \
	  echo "Edit .env (ADMIN_EMAIL / ADMIN_PASSWORD) before 'make admin'."; }

# Create the venv and install deps (re-runs only when requirements change).
venv: $(VENV)/.installed
$(VENV)/.installed: backend/requirements.txt backend/requirements-dev.txt
	@test -d $(VENV) || { echo "Creating Python venv..."; python3 -m venv $(VENV); }
	$(PY) -m pip install --upgrade pip --disable-pip-version-check
	$(PY) -m pip install --disable-pip-version-check -r backend/requirements.txt -r backend/requirements-dev.txt
	@touch $@

up: env
	$(COMPOSE) up -d postgres qdrant

migrate: venv
	cd backend && .venv/bin/python -m alembic upgrade head

backend: env venv
	@echo "Backend on http://localhost:8000"
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend: env
	$(COMPOSE) --profile frontend up frontend-dev

frontend-build: env
	$(COMPOSE) --profile build run --rm frontend-build
	@echo "Static export written to frontend/out/"

test: venv
	cd backend && .venv/bin/python -m pytest

admin: env venv
	cd backend && .venv/bin/python -m app.scripts.create_admin

reembed: env venv
	cd backend && .venv/bin/python -m app.scripts.reembed

down:
	$(COMPOSE) down

doctor:
	@echo "Beyonder doctor"; echo "----------------"
	@if command -v python3 >/dev/null 2>&1; then echo "python3: $$(python3 --version)"; \
	  else echo "python3: MISSING (install 3.11+: brew install python)"; fi
	@if command -v docker >/dev/null 2>&1; then echo "docker: $$(docker --version)"; \
	  else echo "docker: MISSING (install Docker Desktop or OrbStack: brew install --cask orbstack)"; fi
	@if command -v node >/dev/null 2>&1; then echo "node: $$(node --version) (NOT used by Beyonder - Docker only)"; \
	  else echo "node: not on host (correct - npm runs only inside Docker)"; fi
	@if [ -f .env ]; then echo ".env: present"; else echo ".env: missing - run 'make up' or cp .env.example .env"; fi
	@echo; echo "Next: make up   # start postgres + qdrant"
