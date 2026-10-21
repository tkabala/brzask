---
status: accepted
date: 2026-10-21
---

# Embedding deduplication: a fixed threshold across days, an adaptive one within the day

## Context and problem statement

Stories repeat. A feed republishes an article under a new link, an aggregator
links what a source already carried, and on a busy day several outlets report
the same event. Links alone catch none of this. The top 15 candidates are
embedded anyway (for search), so their vectors can be compared. How should
similarity decide what is a duplicate?

## Decision drivers

- A repeat of something shown in the last days must not be shown again.
- A distinct article must not be dropped: the selection can only choose from
  what survives.
- At least 9 candidates should be left for the selection of 7.
- Thresholds of one embedding model mean nothing for another.

## Considered options

- No deduplication beyond links.
- One threshold for both passes.
- Two passes: a fixed cross-day threshold, and a same-day threshold that adapts
  to the day.

## Decision outcome

Chosen option: two passes, because repeats across days and duplicates within
a day sit at clearly different similarities.

- **Cross-day.** Each candidate is compared with the articles shown in the
  last 7 days; at cosine ≥ 0.96 it is a repeat and dropped, but never below 9
  candidates.
- **Same day.** Of two candidates telling one story, the better ranked stays.
  The thresholds 0.80, 0.83, 0.86, 0.90 and 0.93 are tried in that order, and
  the first that still leaves 9 candidates is used; on a day full of real
  duplicates the last one is.

Both sets are stored per embedding model (see
[ADR 0022](0022-one-embedding-model-at-a-time-with-thresholds-per-model.md)).
A candidate without an embedding is never dropped.

### Evidence

Measured on daily digests with `gemini-embedding-001` (768 dimensions): every
real repeat of a shown article had cosine ≥ 0.962, and distinct but similar
articles ≤ 0.959, so 0.96 splits them cleanly. Same-day duplicates sit lower,
at 0.80–0.88, because two outlets word one story differently.

### Consequences

- Good, because repeats are caught across feeds and links.
- Good, because the same-day pass cannot empty a day: it backs off until 9
  candidates remain.
- Bad, because 0.80–0.88 overlaps with distinct articles that only share a
  topic. Replayed over 28 days, the threshold chose 0.80 every day and 11 of
  its 12 drops were different news. A judge now decides that grey zone by
  default ([ADR 0007](0007-a-judge-decides-same-day-duplicates-in-the-grey-zone.md));
  the adaptive threshold is the fallback.
- Bad, because a new embedding model needs its own measurement before its
  thresholds can be trusted.

## Pros and cons of the options

### Links only

- Good, because it is exact and free.
- Bad, because republished and syndicated stories come through.

### One threshold

- Good, because it is one number.
- Bad, because a value low enough for same-day duplicates (0.80) drops many
  distinct articles against a week of history, and one high enough for
  repeats (0.96) misses every same-day duplicate.

### Two passes

- Good, because each pass uses the range it was measured on.
- Bad, because the same-day range needs a judge to be precise.

## More information

Change the thresholds only with evidence from `brzask replay`
([Measuring changes](../measuring.md)); the drops of every run are in its
statistics.
