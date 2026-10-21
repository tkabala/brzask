# HTTP API

`brzask api` serves the JSON API, the probes and the metrics on one port
(`--host`, `--port`; 127.0.0.1:8000 by default).

| Path | What it is |
|---|---|
| `/api/v1/…` | The JSON API |
| `/api/v1/openapi.json` | Its OpenAPI 3.1 document |
| `/api/v1/docs` | Interactive documentation |
| `/open?id=` | Redirects to an article and records that it was opened |
| `/healthz` | Liveness: the process answers |
| `/readyz` | Readiness: the database answers and is fully migrated |
| `/metrics` | Prometheus metrics |

## Logging in

`AUTH_MODE` decides who may use the API:

- **`password`** (the default): one password, its argon2 hash in
  `AUTH_PASSWORD_HASH`. Make the hash with `brzask hash-password`.
- **`header`**: a reverse proxy that authenticates (Authelia, Authentik,
  oauth2-proxy, ...) puts the user name in `AUTH_HEADER` (`Remote-User` by
  default). See [Behind an authenticating proxy](#behind-an-authenticating-proxy).
- **`none`**: no login at all. Anyone who reaches the port can read and change
  everything, and the server says so in a warning at every start. Use it only
  on a machine nobody else can reach.

With a password, `POST /api/v1/auth/login` with `{"password": "..."}` sets two
cookies:

| Cookie | What it holds |
|---|---|
| `brzask_session` | A random session token. `HttpOnly`, `Secure`, `SameSite=Lax`, valid for 30 days. The server stores only its SHA-256. |
| `brzask_csrf` | The CSRF token that goes with the session, readable by the page. |

Requests that change something (`POST`, `PUT`, `PATCH`, `DELETE`) send the CSRF
token in `X-CSRF-Token`; without it they answer 403. The token is an HMAC of
the session under `AUTH_SESSION_SECRET`, so a page on another site can neither
read nor compute it. `GET /api/v1/auth/session` tells the page whether it is
logged in (and returns the token again), and `POST /api/v1/auth/logout` ends
the session for good, wherever its cookie was copied.

After 5 wrong passwords from one address within 15 minutes, or 20 from
anywhere, login answers 429 with `Retry-After` and does not check passwords
until the oldest failure is 15 minutes old. The count lives in memory and
restarts with the server.

`Secure` cookies travel only over HTTPS; browsers make an exception for
`localhost`. To log in over plain HTTP from another machine, set
`AUTH_COOKIE_SECURE=false`; better, put the server behind a reverse proxy with
TLS.

### API tokens

Scripts and agents use a token instead of a login:

```console
$ brzask tokens create backup-script --scope read
brz_...
$ curl -H "Authorization: Bearer brz_..." https://brzask.example/api/v1/status
```

- **`read`** (the default) may only read (`GET`, `HEAD`); anything else
  answers 403. **`write`** may also change things.
- The token is printed once. Only its SHA-256 is stored, with its first 12
  characters, which `brzask tokens list` shows next to its scope, when it was
  created, last used (to the hour) and revoked.
- `brzask tokens revoke <name>` stops it at once.
- A token needs no CSRF token, since no browser sends it on its own. It works
  in both `password` and `header` modes, also from outside the proxy.
- A request with an `Authorization` header is judged by it alone: a wrong
  token answers 401 even when a session cookie comes along.
- The change log records what a token changed as `token:<name>`, a user
  behind a proxy as `user:<name>`, and a password session as `user`.

### Behind an authenticating proxy

With `AUTH_MODE=header`, brzask believes the header only when the connection
itself comes from one of `TRUSTED_PROXIES` (addresses or networks, comma
separated, e.g. `172.18.0.0/16` for a Docker network). The address is that of
the connection, not of `X-Forwarded-For`, which any client can send. From
anywhere else the header is ignored and the API answers 401.

- The proxy must set the header itself and drop any copy a client sends;
  otherwise anyone who can reach the proxy can claim to be anyone.
- Keep brzask unreachable except through the proxy, or `TRUSTED_PROXIES` as
  narrow as the proxy's address.
- Changing requests still send `X-CSRF-Token`, since the proxy's own login
  cookie travels with every request; `GET /api/v1/auth/session` returns the
  token and the user name. Logging out happens at the proxy.

Behind trusted proxies the login throttle and the logs use the client's
address from `X-Forwarded-For`: the last entry that is not one of the proxies.

Without a login: `/healthz`, `/readyz`, `/metrics`, the OpenAPI document and the
interactive documentation, and `/open` links carrying their signature (below).

## Endpoints

The interactive documentation lists every field; in short:

| Endpoint | What it does |
|---|---|
| `GET /digests/today` | Today's digest, in the time zone set by `TZ`; empty until the digest has run |
| `GET /digests/{date}` | A day's digest (`YYYY-MM-DD`); empty when that day had none |
| `GET /digests` | Days with a digest, newest first, with article and open counts |
| `GET /articles/{id}` | One article |
| `GET /articles/{id}/ranking` | Why it was ranked where it was: its place in the ranking, the pool it came from, the methods used and the selection's reason |
| `GET /search?q=` | Articles closest in meaning to `q` |
| `GET /sources` | Sources by name, with fetch health and what each published in the last 30 days; `?status=pending` lists the ones waiting for a decision |
| `POST /sources` | Add a source from its feed or any page of the site |
| `GET`, `PATCH /sources/{id}` | Read, rename, or change the status of a source |
| `GET`, `POST /interests`, `GET`, `PATCH /interests/{id}` | Interests, their keywords and reader notes |
| `GET /runs`, `GET /runs/{id}` | Pipeline runs with their stats and timings |
| `GET /status` | Counts, the pause and the last run of each pipeline |
| `GET`, `PUT`, `DELETE /pause` | Read, set or end a pause of the digest |

All of them are under `/api/v1`. A few choices worth knowing:

- **Sources and interests are never deleted.** `PATCH` a source to `muted`
  (stop reading it) or `rejected` (decline a proposed one, which keeps it from
  being proposed again), and an interest to `active: false`. Both keep their
  history, and every change goes to the change log.
- **A pending source is decided with `PATCH`**: `active` approves it,
  `rejected` declines it. `dead` and `pending` are set only by the pipelines.
- **Search embeds the query as a query**, with the active embedding model, so
  it finds articles in any language. It returns the nearest `limit` (at most
  50) and is not paginated. It is the only read that calls an outside API;
  when that API fails, it answers 502.
- **The ranking explanation** uses what the digest run recorded. Runs from
  before a statistic was recorded give `null` for it. Scores per dimension
  from composite ranking are not stored, so they are not part of it.
- Small collections (interests) are plain arrays; everything that grows is
  paginated.

## The contract

The OpenAPI document is the contract. A copy is committed as `openapi.json`
at the repository root, and the frontend client is generated from it. After
changing a route or a DTO, run `just openapi`; a test fails while the copy
differs from the app. Operation IDs are the route names (`list_sources`,
`get_today_digest`, …), which become the client's function names. Another
test sends requests generated by
[Schemathesis](https://schemathesis.readthedocs.io/) from the document and
checks that every answer matches it: status codes, content types and bodies.

## Errors

Every error is an [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem,
with the media type `application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Unprocessable Content",
  "status": 422,
  "detail": "The request has invalid fields.",
  "instance": "/api/v1/runs",
  "errors": [
    {"location": ["query", "limit"], "message": "Input should be less than or equal to 200", "type": "less_than_equal"}
  ]
}
```

`title` is the status phrase and `detail`, when present, says what went wrong
in a way that can be shown as it is. `errors` appears only on validation
errors (422), one entry per invalid field. A failing outside API (embeddings)
answers 502. Unexpected errors answer 500 without details; the cause is in the
log. A 405 lists in `Allow` every method the path supports.

Text fields reject the NUL character, which Postgres cannot store; the schema
says so with a pattern.

## Pagination

Lists are paginated with cursors:

```json
{"items": [...], "next_cursor": "WyIyMDI2LTEwLTIwVDA2OjI0OjI1..."}
```

Pass `next_cursor` back as `cursor` for the following page; it is `null` on
the last one. `limit` sets the page size (1–200, 50 by default). A cursor is
opaque: it encodes the sort key of the last item, so a page never repeats or
skips items when new ones arrive meanwhile. A cursor the API did not hand out
answers 400; start again without one.

## Opening articles

Opening an article is the only preference signal, so every link to an article
goes through `/open?id=<article>&sig=<signature>`; each article in the API
carries it as `open_url`. The signature is an HMAC of the article ID under
`AUTH_SESSION_SECRET`: the link works from feed readers and mail, which send no
cookie, while an ID alone needs a session. It answers `302 Found` with the article's address in `Location`
and records the first open. Following it again, from the digest, a feed reader
or a bookmark, changes nothing, so the link can be shared and reused.

- It lives outside `/api/v1`, since its URLs end up in feed readers and mail
  and must keep working when the API changes.
- `Cache-Control: no-store` keeps browsers from caching the redirect, which
  would skip recording an open.
- `HEAD` answers the same redirect without recording it, so link checkers and
  previews that only look do not count as reading.
- Only `http` and `https` links are followed; any other link answers 400.

## Probes and metrics

`/healthz` touches nothing but the process, so a slow database never gets a
healthy process restarted. `/readyz` answers 503 while the database is
unreachable or not migrated to the latest revision, for example while
`migrate` is still running.

`/metrics` is always on and needs no collector. It serves what OpenTelemetry
measures, such as `http_server_request_duration_seconds` by route and status
(probes and scrapes are left out). With `OTEL_EXPORTER_OTLP_ENDPOINT` set,
requests are also traced, together with the SQL queries and outgoing calls
they make.
