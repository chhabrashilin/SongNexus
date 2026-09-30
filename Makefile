# Convenience targets (POSIX paths). On Windows, run the underlying commands
# with .venv\Scripts\ instead of .venv/bin/ - see README.md.
BIN ?= .venv/bin

.PHONY: setup data fetch dev-backend dev-frontend lint typecheck test quality eval bench up down

setup: ## Create the virtualenv and install everything
	python -m venv .venv
	$(BIN)/pip install -e "backend[dev,llm]"
	cd frontend && npm ci

data: ## Load the committed MusicBrainz sample into the local database and check it
	$(BIN)/songnexus ingest
	$(BIN)/songnexus quality

fetch: ## Re-fetch the sample from MusicBrainz (network, about 1 request/second)
	$(BIN)/songnexus fetch

dev-backend: ## API on :8000 with auto-reload
	cd backend && ../$(BIN)/uvicorn songnexus.api.app:create_app --factory --reload --port 8000

dev-frontend: ## UI on :5173, proxying /api to :8000
	cd frontend && npm run dev

lint:
	cd backend && ../$(BIN)/ruff check songnexus tests && ../$(BIN)/ruff format --check songnexus tests
	cd frontend && npm run lint

typecheck:
	cd backend && ../$(BIN)/mypy songnexus
	cd frontend && npm run typecheck

test:
	cd backend && ../$(BIN)/pytest
	cd frontend && npm test

quality:
	$(BIN)/songnexus quality

eval: ## Search and agent evaluation (deterministic mode; free and reproducible)
	$(BIN)/songnexus eval-search
	$(BIN)/songnexus eval-agent

bench:
	$(BIN)/songnexus bench

up:
	docker compose up --build

down:
	docker compose down
