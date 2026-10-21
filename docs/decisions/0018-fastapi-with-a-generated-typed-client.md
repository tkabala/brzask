---
status: accepted
date: 2026-10-21
---

# FastAPI, with the frontend client generated from its OpenAPI schema

## Context and problem statement

brzask has one backend serving a single-page web app, scripts with API
tokens, and later agents. The data shapes (articles, digests, sources, runs
with their statistics) change as the pipelines grow. Which web framework
should the backend use, and how does the frontend keep up with its shapes?

## Decision drivers

- One definition of every request and response, checked on both sides.
- Typed Python end to end (`mypy --strict` in CI).
- Small: the API is a thin layer over services that the CLI and the worker
  call as well.
- No server-side rendering to run next to the API.

## Considered options

- FastAPI with Pydantic models; the OpenAPI schema generates the TypeScript client.
- Django with Django REST Framework.
- A server-rendered app (Django templates, or Next.js in front of an API).

## Decision outcome

Chosen option: FastAPI with Pydantic v2. Routers in `api/` validate input
into DTOs and call `services/`, which the CLI and the worker share; nothing
in a router holds logic. `just openapi` writes `openapi.json` at the root of
the repository, and `@hey-api/openapi-ts` turns it into the frontend's
types, zod schemas and TanStack Query hooks. A test fails while the
checked-in schema differs from the app's, and Schemathesis fuzzes the API
against the schema in CI. Errors are RFC 9457 problem responses. The built
web app is served by the same process (see [ADR 0021](0021-one-image-for-every-command.md)).

### Consequences

- Good, because a changed field breaks the frontend's type check, not a
  page at run time.
- Good, because the schema is also the reference for anyone scripting the
  API with a token.
- Good, because Pydantic settings give `*_FILE` secrets and typed
  configuration with the same library.
- Bad, because generated code is checked in and has to be regenerated with
  every API change (the test makes forgetting it fail).
- Bad, because FastAPI has no admin, ORM or migrations of its own; those come
  from SQLAlchemy and Alembic (see [ADR 0019](0019-typed-sqlalchemy-and-raw-sql-only-where-needed.md)).

## Pros and cons of the options

### FastAPI and a generated client

- Good, because the schema comes from the code and the client from the schema.
- Bad, because two generators (OpenAPI, client) sit in the build.

### Django with DRF

- Good, because admin, ORM and auth come built in.
- Bad, because its ORM has no typed query API for `mypy --strict`, and the
  admin duplicates a web app that has to exist anyway.

### Server-rendered

- Good, because no client generation.
- Bad, because a second runtime (Node for Next.js) or a second UI in
  templates, and an agent or script still needs a JSON API.

## More information

The API is described in [HTTP API](../api.md); the frontend's use of the
generated client in [Frontend](../frontend.md).
