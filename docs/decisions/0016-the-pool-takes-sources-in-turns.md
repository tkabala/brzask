---
status: accepted
date: 2026-10-21
---

# The candidate pool takes sources in turns

## Context and problem statement

The ranking prompt holds at most 200 candidates, and a day brings far more:
fresh entries from every active feed plus a week of carry-over. Something has
to cut the list before the model sees it. A few sources (aggregators, busy
news sites, subreddits) publish many times more than the rest. How should the
200 be chosen?

## Decision drivers

- Every active source should get a chance to be ranked every day.
- The cut must be cheap: it happens before any model call.
- Stale entries must not take places from fresh ones.

## Considered options

- The newest 200 entries.
- Sources in turns: each source gives its newest entry, then its next newest, until 200.
- A fixed quota per source.

## Decision outcome

Chosen option: sources in turns. Before the cut, entries older than 10 days
and links already shown are dropped, and one candidate is kept per link
(fresh wins over carried-over, since only the fresh one has the feed's full
content). Then, round after round, every source contributes its next newest
entry until the pool holds 200. Undated entries come last within their
source. Entries cut off are not stored and come back with the next change to
their feed.

### Evidence

Fetching the active feeds on 2026-10-21 gave 1,080 unique candidates from 68
sources:

| Pool of 200 | Sources in the pool | Largest source | Top three sources |
|---|---|---|---|
| Newest 200 | 32 | 48 articles (one aggregator) | 52% of the pool |
| Sources in turns | 68 | 4 articles | 6% of the pool |

The age limit is measured too: feeds bring old entries back to the top, and
without the cut stale entries were about 89% of the pool, the oldest 340
days old.

### Consequences

- Good, because every source that published something is ranked every day.
- Good, because a chatty source has to win on content, not on volume.
- Bad, because a quiet source's single weak entry takes a place that a busy
  source's second-best article would have had; the ranking sorts that out.
- Bad, because with many more sources than 200 / 2, sources would get one
  entry each and the newest-first order within a round would decide who is in.

## Pros and cons of the options

### Newest 200

- Good, because it is the simplest.
- Bad, because half the pool goes to three sources and half the sources are
  never ranked.

### Sources in turns

- Good, because it adapts to however many sources and entries there are.
- Bad, because one entry of each source is treated alike, however good the source.

### Fixed quota

- Good, because it is predictable.
- Bad, because a quota fits only one number of sources, and the source list
  changes every week.

## More information

The ranking keeps the variety: at most 2 of the top 15 per source (see
[ADR 0010](0010-rank-candidates-and-show-a-fixed-seven.md)). Pool counts of
every run (fresh, carried over, stale, already shown, candidates) are in its
statistics.
