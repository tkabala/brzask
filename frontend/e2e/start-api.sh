#!/usr/bin/env bash
# Starts the API for the end-to-end tests on a fresh database with demo data.
# The database `brzask_e2e` lives on the compose Postgres next to the
# development one, which it never touches.
set -euo pipefail
cd "$(dirname "$0")/../.."

docker compose up -d --wait db
docker compose exec -T db psql -q -U brzask -d brzask \
  -c 'DROP DATABASE IF EXISTS brzask_e2e WITH (FORCE)' \
  -c 'CREATE DATABASE brzask_e2e'

cd backend
export DB_PASSWORD=brzask DB_NAME=brzask_e2e TZ=UTC
uv run brzask migrate
uv run brzask demo-data
exec uv run brzask api --port "${E2E_API_PORT:-8100}"
