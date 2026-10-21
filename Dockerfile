# One image for every process: `api` (the default), `worker` and `migrate`,
# or any other `brzask` command, e.g. `docker run --rm IMAGE status`.

# --- Web app -------------------------------------------------------------------
FROM node:24-slim AS web

WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
# The pnpm version pinned in package.json (`packageManager`).
RUN npm install --global --no-fund --no-audit \
        "$(node -p 'require("./package.json").packageManager')"
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# --- Python environment --------------------------------------------------------
FROM python:3.13-slim AS python

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
# Dependencies first: they change less often than the code.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# --- Runtime -------------------------------------------------------------------
FROM python:3.13-slim

# Time zones for TZ; the slim image ships none.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --user-group --no-create-home --home-dir /app brzask

COPY --from=python /app/.venv /app/.venv
COPY --from=web /src/frontend/dist /app/web

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    API_HOST=0.0.0.0 \
    API_WEB_DIR=/app/web

WORKDIR /app
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["brzask"]
CMD ["api"]
