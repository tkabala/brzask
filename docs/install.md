# Installation

brzask runs as four containers from one image: `db` (Postgres with
pgvector), `migrate` (creates or upgrades the schema, then exits), `api`
(the HTTP API and the web app) and `worker` (runs the pipelines on their
schedule). [`deploy/compose.yaml`](https://github.com/tkabala/brzask/blob/main/deploy/compose.yaml)
starts all of them.

## Quickstart

With Docker and Compose 2.24 or newer:

```sh
mkdir brzask && cd brzask && curl -fsSLO https://raw.githubusercontent.com/tkabala/brzask/main/deploy/compose.yaml
docker compose run --rm setup
docker compose up -d
```

`setup` asks for a login password and an LLM API key (an
[OpenRouter](https://openrouter.ai) key covers ranking and embeddings; leave
it empty for a local server) and writes them, with generated database and
session secrets, to `./secrets`, one file per secret. Running it again keeps
the files that exist. Then open <http://localhost:8000>.

## Configuration

Settings go in a `.env` file next to `compose.yaml`; every variable is
described in [Configuration](configuration.md) and listed with its default
in [`.env.example`](https://github.com/tkabala/brzask/blob/main/.env.example).
Models and endpoints other than the OpenRouter defaults are covered in
[Providers](providers.md).
Set `TZ` (for example `TZ=Europe/Warsaw`) so the daily digest is built in
your morning. The secrets `setup` writes (database password, login, session
secret, LLM API key, Crawl4AI token) are always read from `./secrets`
through `<NAME>_FILE` variables; compose ignores `DB_PASSWORD`,
`LLM_API_KEY`, `AUTH_PASSWORD_HASH`, `AUTH_SESSION_SECRET` and
`CRAWL4AI_API_TOKEN` in `.env`, so a `.env` copied from `.env.example` works
as it is. To change one of them, edit its file and restart. Other secrets,
such as `JINA_API_KEY`, go in `.env`.

Compose itself reads a few variables from the same `.env`:

| Variable | Default | What it sets |
|---|---|---|
| `BRZASK_IMAGE` | `ghcr.io/tkabala/brzask:latest` | Image for `migrate`, `api` and `worker` |
| `BRZASK_PUBLISH` | `127.0.0.1:8000` | Host address and port of the web app; `8000` alone listens on every address |
| `BRZASK_SECRETS` | `./secrets` | Directory of the secret files |
| `COMPOSE_PROFILES` | | Optional services, below |

The web app is published on the loopback address only. To reach it from
other machines, put a [reverse proxy](reverse-proxy.md) with TLS in front,
or set `BRZASK_PUBLISH`. Back up the database with `pg_dump` as described in
[Backup and restore](backup.md).

## Optional services

| Profile | Service | Enable with, in `.env` |
|---|---|---|
| `crawler` | [Crawl4AI](https://github.com/unclecode/crawl4ai): a headless browser for pages plain HTTP cannot read | `COMPOSE_PROFILES=crawler`, `EXTRACTORS=feed,trafilatura,crawl4ai` |
| `search` | [SearXNG](https://github.com/searxng/searxng): web search for source discovery, without a paid API | `COMPOSE_PROFILES=search`, `WEB_SEARCH=searxng` |

Both at once: `COMPOSE_PROFILES=crawler,search`. Their secrets come from
`setup` too. The Crawl4AI image is large (about 8 GB) and wants 2 GB of
memory.

## Images

Releases are published to `ghcr.io/tkabala/brzask` for amd64 and arm64,
tagged with the version (`0.1.0`, `0.1`) and `latest`. Pin a version in
`BRZASK_IMAGE` to upgrade on your own schedule; `docker compose pull && docker
compose up -d` upgrades, and `migrate` updates the schema on the way.

Each image carries an SBOM and build provenance, and is signed with
[cosign](https://github.com/sigstore/cosign) by the release workflow:

```sh
cosign verify ghcr.io/tkabala/brzask:latest \
  --certificate-identity-regexp '^https://github.com/tkabala/brzask/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Commands

Every `brzask` command runs in the image, for example:

```sh
docker compose exec api brzask status
docker compose exec api brzask sources add https://example.com/blog
docker compose run --rm migrate seed-demo   # fill an empty instance with demo data
```
