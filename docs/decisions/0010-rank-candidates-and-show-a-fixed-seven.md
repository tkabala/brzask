---
status: accepted
date: 2026-10-21
---

# Rank candidates against each other and show a fixed 7

## Context and problem statement

Every day about 200 candidates compete for a short list. The reader's
interests are free text, so deciding what is worth reading needs a language
model. The obvious design asks the model to score each article from 0 to 10
and shows everything above a threshold. Should the digest be a score
threshold, or a fixed number of articles chosen by comparing them?

## Decision drivers

- The digest must be finite and predictable: a list one finishes, every day.
- Whatever the model returns must separate a good article from a merely
  relevant one.
- One cheap model call for the whole pool, not one per article.

## Considered options

- Score each article 0–10 and show those above a threshold.
- Score each article 0–10 and show the 7 best scored.
- Ask the model for a strict order of the best candidates, then choose a fixed 7.

## Decision outcome

Chosen option: a strict order, then a fixed 7, because absolute scores
collapse onto one value and cannot separate the candidates, while an order
cannot tie.

The ranking prompt lists the pool and asks for the ids of the best 40 in
strict order, best first, "no ties, and do not pad the list". The top 15 of
that order, at most 2 per source (lifted on a thin day so that at least 10
remain), go on to extraction and deduplication; a second call chooses the
final 7 from the survivors and writes a title, summary and reason for each.
`DIGEST_SIZE = 7` is a product decision, not a measured constant.

### Evidence

In daily use, asked for 0–10 scores of the articles in the daily top 15,
the model gave exactly 8 to 196 of 294 articles. With two thirds of the
candidates on one value, a threshold at 8 shows most of them and a threshold
above it shows almost none; the order among the tied ones is whatever the
code breaks ties with. Asked for an order instead, the model has to decide
between every pair it lists.

### Consequences

- Good, because the digest has the same length every day, whatever the pool.
- Good, because one call ranks the pool: about $0.003 a day with
  `deepseek/deepseek-v4-flash`.
- Bad, because a weak day still shows 7 articles; there is no "nothing worth
  reading today". The pause (`brzask pause`) covers days off, not weak days.
- Bad, because a position says nothing absolute: rank 3 on one day and rank 3
  on another are not comparable, so ranks cannot be reused as scores.

## Pros and cons of the options

### Score threshold

- Good, because a weak day could show fewer articles.
- Bad, because the scores tie: 196 of 294 at exactly 8.
- Bad, because the length of the digest would follow the model's mood, not the reader.

### Fixed 7 of the scored

- Good, because the length is fixed.
- Bad, because choosing 7 among dozens of 8s is decided by tie-breaking.

### Strict order, fixed 7

- Good, because every listed pair is decided by the model.
- Good, because the list is finite by construction.
- Bad, because one long reasoning call takes about two and a half minutes a day.

## More information

The ordering itself can come from an LLM (the default) or from per-article
judge scores combined with weights; [ADR 0006](0006-llm-ranking-stays-the-default-over-composite-scores.md)
compares the two. Both feed the same fixed selection of 7.
