set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load

default:
    @just --list

# Install dependencies and git hooks
setup:
    cd backend && uv sync --locked
    cd frontend && pnpm install --frozen-lockfile
    prek install --install-hooks

# Lint, type-check and test everything
check: check-backend check-frontend check-docs

check-backend:
    cd backend && uv run ruff check
    cd backend && uv run ruff format --check
    cd backend && uv run mypy
    cd backend && uv run pytest

check-frontend:
    cd frontend && pnpm lint
    cd frontend && pnpm typecheck
    cd frontend && pnpm test

check-docs:
    uv run --project backend --only-group docs mkdocs build --strict

# Serve the documentation site with live reload
docs:
    uv run --project backend --only-group docs mkdocs serve

# Apply migrations to the dev database
migrate:
    docker compose up -d --wait db
    cd backend && DB_PASSWORD="${DB_PASSWORD:-brzask}" uv run brzask migrate

# Generate a migration from model changes, e.g. just migration "add source health"
migration message: migrate
    cd backend && DB_PASSWORD="${DB_PASSWORD:-brzask}" uv run alembic revision --autogenerate -m {{quote(message)}}

# Regenerate .env.example from the settings
env-example:
    cd backend && uv run python -m brzask.config.env_example > ../.env.example.tmp && mv ../.env.example.tmp ../.env.example

# Regenerate openapi.json from the API, and the frontend client from it
openapi:
    cd backend && uv run python -m brzask.api.openapi > ../openapi.json.tmp && mv ../openapi.json.tmp ../openapi.json
    cd frontend && pnpm generate

# Serve the API on the dev database
api:
    docker compose up -d --wait db
    cd backend && DB_PASSWORD="${DB_PASSWORD:-brzask}" uv run brzask api

# End-to-end tests: Playwright on deploy/compose.yaml with demo data, on an image of this checkout
e2e:
    cd frontend && pnpm e2e

# Run all tests
test:
    cd backend && uv run pytest
    cd frontend && pnpm test

# Format all code
fmt:
    cd backend && uv run ruff format
    cd backend && uv run ruff check --fix
    cd frontend && pnpm format

# Start the database and the frontend dev server
dev:
    docker compose up -d --wait db
    cd frontend && pnpm dev

# Stop development services
down:
    docker compose down

# Regenerate the demo instance the web app's stories and tests use
demo-json:
    cd backend && uv run python -m brzask.services.demo > ../frontend/src/demo/instance.gen.json.tmp && mv ../frontend/src/demo/instance.gen.json.tmp ../frontend/src/demo/instance.gen.json
