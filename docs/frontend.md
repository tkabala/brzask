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
