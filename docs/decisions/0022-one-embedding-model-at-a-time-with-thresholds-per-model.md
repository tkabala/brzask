---
status: accepted
date: 2026-10-21
---

# One embedding model at a time, 768 dimensions, thresholds per model

## Context and problem statement

Embeddings carry deduplication and search. They come from whatever
OpenAI-compatible endpoint the instance uses: OpenRouter, Ollama, a local
server. Models differ in dimensions, in how they want queries and documents
marked, and in how far apart they place similar texts. How are embeddings
requested, stored and compared so that a model can be changed later without
breaking either?

## Decision drivers

- Deduplication thresholds are measured cosine values, true for one model only.
- Switching models must not leave the digest comparing against half a history.
- Any provider: no provider-specific client.
- One vector column with a fixed size, so pgvector can index it if needed.

## Considered options

- Vectors stored per article and model; one active model; thresholds per model.
- One vector per article, overwritten when the model changes.
- Each model's native dimension, in a column or table per model.

## Decision outcome

Chosen option: vectors per article and model, one model active at a time.

- **Shape.** Every vector has 768 components (the client asks for that size
  and rejects a response of any other) and unit length.
- **Storage.** `article_embeddings` is keyed by article and model; only
  vectors of the same model are ever compared. The embedded text, the first
  4,000 characters of the article, is stored, so another model can embed
  exactly the same input later.
- **Kinds.** Each call says whether it embeds a document or a search query,
  and a per-model adapter turns that into what the model expects
  (`search_query:` / `search_document:` for nomic-embed, `query:` /
  `passage:` for e5, nothing for others).
- **Switching.** `brzask reembed --model …` embeds the history again in
  resumable batches and switches the active model only when every embedded
  article has a vector of the new one. `brzask replay` can deduplicate with
  the new model's vectors before the switch.
- **Thresholds.** Deduplication looks up the active model's thresholds in a
  table in code; a model nothing was measured on uses the default model's
  thresholds, with a warning on every run.

### Evidence

`gemini-embedding-001` is the default and the model the deduplication
thresholds were measured on ([ADR 0012](0012-embedding-deduplication-across-days-and-within-the-day.md)).
It is deliberately called without a task type. Measured on OpenRouter, the
document task type moves a vector to cosine 0.89 from the untyped one for
the same text (0.92–0.95 on stored articles), which is below the 0.96
cross-day threshold measured on untyped vectors. The query task type gives
exactly the untyped vector. Typed vectors would need thresholds of their own.

### Consequences

- Good, because a new model can be tried, measured and switched to without
  losing the old vectors or the history.
- Good, because the thresholds sit next to the model they were measured on.
- Bad, because a model that cannot return 768 dimensions cannot be used
  without a schema change.
- Bad, because during a re-embedding the database holds two vectors per article.
- Bad, because the default model gets no query/document distinction, which
  could help search; it would cost re-measuring every threshold.

## Pros and cons of the options

### Per article and model

- Good, because switching is safe and reversible.
- Bad, because more rows during a switch.

### One vector, overwritten

- Good, because the table stays small.
- Bad, because a half-finished switch mixes models in one comparison.

### Native dimensions per model

- Good, because no model is excluded.
- Bad, because one table or column per model, and indexes per size.

## More information

The steps of a model change: [Measuring changes](../measuring.md#embedding-models-reembed-and-replay).
Storage and search: [ADR 0004](0004-no-vector-index-until-history-needs-one.md).
