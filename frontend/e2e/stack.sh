#!/usr/bin/env bash
# The end-to-end stack: deploy/compose.yaml on an image built from this
# checkout, with demo data. `stack.sh up` starts it afresh, `stack.sh down`
# removes it with its data. Its own compose project, so a running instance
# is never touched.
set -euo pipefail
cd "$(dirname "$0")/../.."

export COMPOSE_PROJECT_NAME=brzask-e2e
export COMPOSE_PROFILES=
export BRZASK_IMAGE=brzask:e2e
export BRZASK_PUBLISH="127.0.0.1:${E2E_PORT:-8100}"
export BRZASK_SECRETS="$PWD/frontend/e2e/secrets"

compose() {
  docker compose --file deploy/compose.yaml --file frontend/e2e/compose.yaml "$@"
}

secret() {
  printf '%s\n' "$2" > "$BRZASK_SECRETS/$1"
  chmod 644 "$BRZASK_SECRETS/$1"
}

case "${1:-}" in
  up)
    compose down --volumes --remove-orphans
    docker build --tag "$BRZASK_IMAGE" .
    rm -rf "$BRZASK_SECRETS"
    mkdir -m 700 "$BRZASK_SECRETS"
    secret db_password "$(openssl rand -hex 24)"
    secret auth_session_secret "$(openssl rand -hex 24)"
    secret auth_password_hash "${E2E_PASSWORD_HASH:?}"
    secret llm_api_key ""
    secret crawl4ai_api_token "$(openssl rand -hex 24)"
    secret searxng_secret "$(openssl rand -hex 24)"
    compose up --detach --wait
    compose exec -T api brzask seed-demo
    ;;
  down)
    compose down --volumes --remove-orphans
    rm -rf "$BRZASK_SECRETS"
    ;;
  *)
    echo "usage: $0 up|down" >&2
    exit 2
    ;;
esac
