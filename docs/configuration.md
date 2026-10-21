# Configuration

<!-- Generated from backend/src/brzask/config/settings.py by `just env-example`. -->

brzask is configured with environment variables. With Docker Compose they go
in a `.env` file next to `compose.yaml`; [`.env.example`](https://github.com/tkabala/brzask/blob/main/.env.example)
lists all of them with their defaults, ready to copy.

Every secret can also be read from a file: set `<NAME>_FILE` to its path
instead of setting `<NAME>`. The compose file does this for the secrets
`brzask setup` writes to `./secrets`. Set a secret one way, not both.

Which models and endpoints to use is described in [Providers](providers.md).

## Database

Postgres 17 with the pgvector extension.

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | Postgres host. |
| `DB_PORT` | `5432` | Postgres port. |
| `DB_NAME` | `brzask` | Database name. |
| `DB_USER` | `brzask` | Database user. |
| `DB_PASSWORD` | required | Database password. |

## LLM

Any OpenAI-compatible chat completions API.

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | Base URL of the OpenAI-compatible API (OpenRouter, Ollama, ...). |
| `LLM_MODEL` | `deepseek/deepseek-v4-flash` | Model used for ranking and selection. |
| `LLM_API_KEY` | secret | API key; leave empty for local servers. |
| `LLM_TIMEOUT_SECONDS` | `300` | How long one request may take; ranking prompts are long. |

## Embeddings

Any OpenAI-compatible /embeddings API.

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_BASE_URL` | (none) | Base URL of the embeddings API; defaults to LLM_BASE_URL. |
| `EMBEDDING_MODEL` | `google/gemini-embedding-001` | Embedding model; `brzask reembed` moves stored vectors to another one. |
| `EMBEDDING_API_KEY` | secret | API key; defaults to LLM_API_KEY. |

## Judgements

Short typed questions (yes/no, one of a set, a level) about articles.

| Variable | Default | Description |
|---|---|---|
| `JUDGE_BACKEND` | `system-one` | system-one (a System One model such as Jev or d1) or llm (the chat model answers in JSON; works with local servers). |
| `JUDGE_MODEL` | (none) | Model with its author prefix; defaults to typesafe/jev-1.13 for system-one and to LLM_MODEL for llm. |
| `JUDGE_BASE_URL` | (none) | Base URL of the API; defaults to LLM_BASE_URL. |
| `JUDGE_API_KEY` | secret | API key; defaults to LLM_API_KEY. |

## Article text extraction

| Variable | Default | Description |
|---|---|---|
| `EXTRACTORS` | `feed,trafilatura,jina` | Extractors tried in order; the feed snippet is the final fallback. |
| `JINA_API_KEY` | secret | Jina Reader API key; optional, raises rate limits. |
| `FIRECRAWL_BASE_URL` | `https://api.firecrawl.dev/` | Firecrawl API URL; change it for a self-hosted instance. |
| `FIRECRAWL_API_KEY` | secret | Firecrawl API key; required for the hosted service. |
| `CRAWL4AI_BASE_URL` | (none) | Crawl4AI server URL; required when crawl4ai is enabled. |
| `CRAWL4AI_API_TOKEN` | secret | Crawl4AI API token; its server accepts outside connections only with one. |

## Web search used by source discovery

| Variable | Default | Description |
|---|---|---|
| `WEB_SEARCH` | (none) | searxng, llm-online (recommended with OpenRouter) or brave; empty turns source discovery off. |
| `SEARXNG_URL` | (none) | SearXNG instance URL (JSON format must be enabled). |
| `BRAVE_API_KEY` | secret | Brave Search API key. |
| `WEB_SEARCH_MODEL` | `perplexity/sonar` | Online model used by llm-online, through the LLM API. |

## Authentication for the web UI and API

| Variable | Default | Description |
|---|---|---|
| `AUTH_MODE` | `password` | password, header (trust a reverse proxy) or none (no login, local use only). |
| `AUTH_PASSWORD_HASH` | secret | Argon2 hash of the login password (mode=password). |
| `AUTH_SESSION_SECRET` | secret | Random string of at least 32 characters that signs CSRF tokens and article links. |
| `AUTH_COOKIE_SECURE` | `auto` | Mark the session cookie Secure (sent over HTTPS only): auto when the request came over HTTPS, directly or as X-Forwarded-Proto from TRUSTED_PROXIES; true always; false never. |
| `AUTH_HEADER` | `Remote-User` | Header with the user name (mode=header). |
| `TRUSTED_PROXIES` | (none) | Comma-separated proxy addresses or networks allowed to set the header. |

## HTTP server of `brzask api`

| Variable | Default | Description |
|---|---|---|
| `API_HOST` | `127.0.0.1` | Address to listen on; 0.0.0.0 for all. |
| `API_PORT` | `8000` | Port to listen on. |
| `API_WEB_DIR` | (none) | Directory of the built web app (frontend/dist) to serve at /; empty serves the API only. |

## Pipeline schedule for the worker

'HH:MM' runs daily, '<mon..sun> HH:MM' weekly, 'off' never.

| Variable | Default | Description |
|---|---|---|
| `DIGEST_AT` | `07:00` | When the daily digest is built. |
| `REVIEW_AT` | `mon 07:30` | When sources are reviewed. |
| `VISITED_AT` | `mon 07:45` | When opened links are checked for new sources. |
| `DISCOVERY_AT` | `mon 08:00` | When new sources are searched for. |
| `TZ` | `UTC` | Time zone of the schedule and digest dates. |

## Digest output

| Variable | Default | Description |
|---|---|---|
| `DIGEST_LANGUAGE` | `en` | Language of digest titles and summaries. |
| `DIGEST_RANKING` | `llm` | llm (the LLM orders the pool) or judge (each article scored on several dimensions by JUDGE_BACKEND, weighted in code). |
| `DIGEST_DEDUPLICATION` | `judge` | judge (JUDGE_BACKEND decides same-day pairs in the grey zone; the threshold if it fails) or threshold (an adaptive similarity threshold). |

## LLM spending limits

Above a limit, expensive steps are skipped.

| Variable | Default | Description |
|---|---|---|
| `LLM_BUDGET_DAILY_USD` | (none) | Daily limit in USD; empty for none. |
| `LLM_BUDGET_MONTHLY_USD` | (none) | Monthly limit in USD; empty for none. |

## Logging

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Minimum level: DEBUG, INFO, WARNING or ERROR. |
| `LOG_FORMAT` | `auto` | json (one object per line), console (readable) or auto (console on a TTY). |

## Traces, metrics and error reports

All off unless configured.

| Variable | Default | Description |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | (none) | OTLP/HTTP collector URL; traces and metrics are sent only when set. |
| `OTEL_SERVICE_NAME` | `brzask` | Service name in traces. |
| `SENTRY_DSN` | secret | Sentry DSN; errors are reported only when set. |
| `SENTRY_ENVIRONMENT` | `production` | Environment name attached to Sentry reports. |
