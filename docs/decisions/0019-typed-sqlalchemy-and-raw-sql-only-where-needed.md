---
status: accepted
date: 2026-10-21
---

# Typed SQLAlchemy for data access; raw SQL only for vector and ranking queries

## Context and problem statement

The data is relational (sources, articles, digests, runs, a change log)
with one kind of query that is not: nearest neighbours over embeddings in
pgvector. How should the code reach Postgres: an ORM, a query builder, or
plain SQL?

## Decision drivers

- `mypy --strict` over the whole backend, queries included.
- Schema changes reviewed as migrations, and a test that catches a model
  and its migrations drifting apart.
- Vector queries written in the form pgvector documents, without a layer
  that hides how they run.

## Considered options

- SQLAlchemy 2.0 typed ORM everywhere, raw SQL (`text()`) allowed only for
  vector and ranking queries the ORM cannot express well.
- Raw SQL everywhere (psycopg with hand-written queries).
- SQLModel or another ORM.

## Decision outcome

Chosen option: the typed ORM, with raw SQL as a documented exception. Models
use `Mapped[...]` columns, repositories in `repositories/` own every query,
and services never build SQL. Alembic generates migrations from the models
(`just migration`), each reviewed by hand; a test fails while models and
migrations differ. Database tests run against a real Postgres with pgvector
in a container.

The exception is narrow: `text()` only for a vector or ranking query, with a
comment saying why. So far none needed it. Search orders by pgvector's
typed `cosine_distance` comparator, which compiles to `<=>` on the model's
vectors, and deduplication compares the 15 candidates with the last week's
shown articles in Python, since both sets are already in memory and small.

### Consequences

- Good, because a renamed column breaks the type check, not a query at run
  time.
- Good, because repositories are the only place to look for a slow query.
- Good, because the vector search reads as a query, with the distance, the
  model filter and the order in plain sight.
- Bad, because ORM sessions and the unit of work are a lot of machinery for
  a small schema.
- Bad, because the exception needs discipline in review, not tooling.

## Pros and cons of the options

### Typed ORM with a raw SQL exception

- Good, because types, migrations and vector queries are all covered.
- Bad, because two ways to write a query exist, one of them rare.

### Raw SQL everywhere

- Good, because every query is exactly what runs.
- Bad, because results are untyped rows, and schema drift shows up only in tests.

### SQLModel

- Good, because one class for the table and the API model.
- Bad, because it couples the schema to the API's shapes, and it trails
  SQLAlchemy's typing.

## More information

Whether to add a vector index: [ADR 0004](0004-no-vector-index-until-history-needs-one.md).
The data model: [Data model](../data-model.md).
