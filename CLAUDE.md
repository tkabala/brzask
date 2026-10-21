# Agent instructions

Conventions for anyone (human or agent) working in this repository.

## Layout

- `backend/`: Python 3.13 package `brzask` (src layout, uv). Layers: `api/` (routers, DTOs) → `services/` (logic, pipelines) → `repositories/` (data access). CLI, worker, MCP and HTTP all call `services`.
- `frontend/`: React 19 + TypeScript (Vite, pnpm).
- `docs/`: mkdocs-material site (`mkdocs.yml` at the root; `just docs` to preview); architecture decisions in `docs/decisions/` (MADR, copy `0000-template.md`).
- `deploy/`: compose files, reverse proxy examples, Helm chart.

## Commands

- Backend: `uv run ruff check`, `uv run ruff format`, `uv run mypy`, `uv run pytest` (from `backend/`).
- Frontend: `pnpm lint`, `pnpm format`, `pnpm typecheck`, `pnpm test`, `pnpm build` (from `frontend/`). Node 24; pnpm version pinned in `package.json` (`packageManager`).
- Whole repo: `just check`, `just test`, `just fmt`, `just dev`. After changing a setting run `just env-example` (a test fails while `.env.example` or `docs/configuration.md` is stale).

## Conventions

- English everywhere: code, comments, docs, commits. UI strings in English; other languages only as i18n translations.
- Commits follow Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`, `ci:`, `build:`), optional scope, e.g. `feat(digest): …`.
- Tests ship with the change. Pure functions get unit tests; anything touching SQL gets a testcontainers test against Postgres with pgvector.
  Database tests take the `session` fixture (one migrated database per run, rolled back after each test) and build rows with `make` (`tests/factories.py`).
- Schema changes: edit `backend/src/brzask/db/models.py`, run `just migration "<what changed>"`, review the generated file in `backend/src/brzask/migrations/versions/`. A test fails while models and migrations differ.
- `mypy --strict` must pass. Raw SQL (`text()`) only for vector/ranking queries, each with a comment explaining why.
- Measured constants (thresholds, limits) keep a short comment stating what they were measured on. Change them only with evidence from `brzask replay`.
- Keep the default deployment simple: `migrate` + `api` + `worker` + `db`. Everything else is opt-in.
