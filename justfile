set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install dependencies and git hooks
setup:
    cd backend && uv sync
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
