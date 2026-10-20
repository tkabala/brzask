---
status: accepted
date: 2026-10-20
---

# No vector index until the history needs one

## Context and problem statement

Article vectors live in `article_embeddings`, one row per article and
embedding model. Nearest-neighbour search (`search_similar`) orders them by
cosine distance; without an index Postgres computes the distance to every
vector of the model. pgvector's HNSW index answers the same query
approximately, in a fraction of the time. Should the table have one now?

## Decision drivers

- Search must stay fast enough to feel instant, for a person or an agent.
- Results should be exact while that is cheap: a missed duplicate or a
  missing search hit is hard to notice.
- Disk and memory on a small self-hosted server.
- The history grows by about 15 vectors a day per model (the extracted top 15
  of each digest), around 5,500 a year.

## Considered options

- No vector index; exact search.
- One HNSW index (`vector_cosine_ops`) over all models' vectors.
- One partial HNSW index per embedding model.

## Decision outcome

Chosen option: no vector index for now, because exact search stays well under
100 ms for years of history, while an index would be about as large as the
table, make results approximate and, with vectors of several models in one
table, need pgvector's iterative scan for the model filter. The deduplication
query does not order by distance (it reads the vectors shown in the last days),
so an index would not speed up the daily run either.

### Evidence

pgvector 0.8.7 on Postgres 17, the dev server: `EXPLAIN ANALYZE` of the
`search_similar` query (top 10 of one model, joined to `articles`), with a
second model's vectors in the table at half the count. Median of three runs;
the HNSW runs use default build settings, `ef_search` 40 and
`hnsw.iterative_scan = relaxed_order`.

| Vectors of the model | Table | Exact search | HNSW search | HNSW index |
|---|---|---|---|---|
| 2,000 (today: 1,072) | 12 MB | 6.9 ms | 1.9 ms | 12 MB |
| 20,000 (about 3.5 years) | 120 MB | 63 ms | 5.3 ms | 117 MB |
| 100,000 | – | 430 ms | 11 ms | 586 MB |

The 2,000 and 20,000 rows used random vectors; the HNSW index built on the
real vectors (1,072 per model, two models) returned the exact top 10 for 50 of
50 sample queries (recall 1.0). On 20,000 random vectors, recall at `ef_search`
40 was only 0.42 (0.59 at 200, taking 16 ms): random vectors are the hardest
case for HNSW, and real embeddings cluster, but the number shows that recall
has to be checked on real history before relying on the index.

### Consequences

- Good, because search results are exact and need no tuning.
- Good, because the database stays half the size it would be with the index.
- Bad, because search time grows linearly: about 3–4 ms per 1,000 vectors of a model.

## Pros and cons of the options

### No vector index

- Good, because exact, simple and small.
- Bad, because linear in the history; slow beyond about 100,000 vectors.

### One HNSW index over all models

- Good, because 10–40 times faster from 20,000 vectors on.
- Bad, because the index is as large as the table, results are approximate,
  and the model filter needs iterative scans.

### One partial HNSW index per model

- Good, because each index holds only the vectors it searches; no filtering problem.
- Bad, because indexes would have to be created and dropped as models change
  (for example by `brzask reembed`), outside the migrations.

## More information

Revisit when a model has more than 20,000 vectors (`brzask status` shows the
counts), or when a feature calls `search_similar` on every request. Before
adding an index, measure recall on the real history.
