# Frontend

The web app in `frontend/`: React 19, TypeScript, Vite, TanStack Router and
Query, Tailwind with shadcn/ui, i18next.

## Running it

```console
$ just api     # the API on http://127.0.0.1:8000 (database started if needed)
$ just dev     # the app on http://localhost:5173
```

`just api` needs a way to log in: put `AUTH_PASSWORD_HASH` (from
`brzask hash-password`) and `AUTH_SESSION_SECRET` (e.g. `openssl rand -hex 32`)
in `.env`, or `AUTH_MODE=none` on a machine nobody else can reach.

The Vite dev server passes `/api`, `/open`, `/healthz` and `/readyz` on to the
API (`BRZASK_API` points it elsewhere), so the app and the API share one
origin, as they do in production. Over plain HTTP the session cookie is not
`Secure`, so logging in works on `localhost` without TLS.

## Screens

| Path | Screen |
|---|---|
| `/` | Today's digest: a card per article, "why here?" from the ranking explanation |
| `/archive`, `/archive/<day>` | Days with a digest, and any day's digest |
| `/search?q=` | Search by meaning; the query stays in the address |
| `/sources?show=` | Pending decisions, every source with its fetch health and 30-day counts, adding one from any page of a site |
| `/interests` | Topics, keywords and reader notes; turning one off |
| `/status` | Counts, the last run of each pipeline, recent runs, pausing the digest |

An article's link is its signed `open_url`, opened in a new tab. Following it
marks the card opened at once in the cached digest, while the server records
the open as the browser passes through `/open`.

Each screen is a route that fetches and changes data (`src/routes/`) and a view
that only takes props (`src/features/<screen>/`).

## Demo API, stories and tests

`src/demo/handlers.ts` is the API on demo data (`src/demo/data.ts`), written by
hand with [MSW](https://mswjs.io/): the same paths, cursor pages and problem
details as the server, a session (the password is `demo`), and changes that
last until the next story or test. Storybook and the tests share it.

The demo data is the instance `brzask seed-demo` writes to a database, as of
2026-10-21: a month of invented digests, sources in every state, interests and
runs. The backend works it out (`brzask.services.demo`) and `just demo-json`
exports it to `src/demo/instance.gen.json`, which `data.ts` shapes like the
API; a backend test fails while the export is stale. Stories, unit tests, the
end-to-end tests and screenshots therefore all show the same articles.

- **Storybook** (`pnpm storybook`; CI runs `pnpm build-storybook`): each view
  has stories with props, and *Pages* renders the whole app at every route
  against the demo API in the browser. A story replaces single endpoints with
  `parameters: withApi(http.get(...))`. The service worker is in
  `.storybook/public`, so the app never ships it.
- **Tests** (`pnpm test`): `msw/node` answers every request the app makes; a
  request no handler answers fails the test. `fakeApi({...})` overrides
  endpoints for one test and records what was sent.

## The API client

`src/client` is generated from `openapi.json` by
[`@hey-api/openapi-ts`](https://heyapi.dev/): types, an SDK function per
operation (named like the route, e.g. `listSources`), zod schemas, and
TanStack Query options (`getTodayDigestOptions()`, `loginMutation()`, ...).

- `just openapi` regenerates `openapi.json` from the backend and then the
  client from it (`pnpm generate` does only the latter). CI fails while the
  committed client differs.
- The generator copies its fetch runtime into `src/client/client` and
  `src/client/core`; that code does not compile under the project's
  `exactOptionalPropertyTypes`, so `scripts/mark-client-runtime.mjs` leaves
  just those files out of type checking.
- `src/lib/api.ts` points the client at the server, adds `X-CSRF-Token` to
  requests that change something, and turns every error answer into an
  `ApiProblem` carrying the [problem](api.md#errors) and `Retry-After`.

## Logging in

The root layout asks `GET /api/v1/auth/session` first and shows the app only
when the API may be used. Otherwise it shows the password form, or with
`AUTH_MODE=header` a note to sign in through the proxy. Pages fetch their
data in components, not in route loaders, because loaders would run before
the session is known. A 401 from any request asks for the session again, so
an expired session leads back to the login.

## Errors

`ProblemMessage` shows a problem's `title` and `detail` as the API wrote them,
or a note that the server cannot be reached, with a retry. The root route's
error boundary uses it for anything a page throws.

## Languages

English, and Polish as a translation (`src/i18n/en.ts`, `src/i18n/pl.ts`).
The language comes from an earlier choice, then the browser; the header
switches it. `pl.ts` must have every key of `en.ts`, which the type checker
enforces.

## End-to-end tests

`just e2e` (`pnpm e2e` in `frontend/`) runs Playwright against the app as
people run it: `e2e/stack.sh` builds the image from the checkout and starts
`deploy/compose.yaml` as its own compose project (`brzask-e2e`, so a running
instance is never touched) with a test password, then fills it with
`brzask seed-demo`. The tests log in, use every screen and check each with
[axe](https://github.com/dequelabs/axe-core) for WCAG 2.1 A and AA violations.
They share one database and run one after another; the stack is removed
afterwards. CI runs them in the `e2e` job and keeps the report when they fail.

`brzask seed-demo` also works on its own, to try brzask without feeds: it
fills an empty database with the demo instance, dated to today.
