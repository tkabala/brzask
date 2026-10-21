---
status: accepted
date: 2026-10-21
---

# Sources maintain themselves: review, visited sites and discovery

## Context and problem statement

A digest is only as good as its sources. Left alone, a source list decays:
feeds move or end, some sources publish a lot that never makes the cut, and
good new sources appear that the reader never hears of. Curating by hand is
exactly the chore a calm digest should remove. What can the system decide on
its own, and what must stay with the reader?

## Decision drivers

- Sources that cost attention and tokens without ever being read should go.
- New sources should come from evidence of the reader's taste, not from
  popularity lists.
- Nothing the reader added should be removed on thin evidence.
- Every automatic change must be visible and reversible.

## Considered options

- Manual curation only.
- Three weekly pipelines: a source review, new sites from opened links, and
  web discovery vetted by a judge.
- A recommendation service or a shared catalogue of feeds.

## Decision outcome

Chosen option: three weekly pipelines, run on Monday morning in a fixed
order, review first so that muted sources free their place the same day.

- **Review** mutes an active source older than 21 days that, over the last
  30 days, had at least 10 articles, none in a daily top 15 and none opened.
  It marks a source dead after two weeks of permanent errors (404, 410, 403,
  not a feed) or a month of any errors; rate limits and outages alone never
  kill a source within the month. Sources that published nothing are only
  reported: they cost nothing.
- **Visited** looks at opened links that reached a site through an
  aggregator (Hacker News, Lobsters, Reddit). A site the reader reads from
  but does not follow yet becomes a `pending` source, for the reader to
  accept or reject; there are a few a week.
- **Discovery** asks a web search for sites per interest, resolves each to a
  feed (blog, YouTube channel, GitHub releases), drops feeds with nothing in
  60 days, and has a judge score the newest items for interest fit (0–3) and
  substance (0–2). Fit ≥ 2 and substance ≥ 1.5 enables the source at once;
  fit < 1 rejects it for good; anything else waits as `pending`.

Each change is recorded in the change log with its reason and shown on the
Sources page, where the reader can switch any source back.

### Evidence

From daily use since July 2026, as of 2026-10-21:

| Origin | Active sources | Shown articles | Opened | Opened of shown |
|---|---|---|---|---|
| Added by hand | 44 | 502 | 23 | 4.6% |
| Discovery | 49 | 174 | 13 | 7.5% |
| Visited sites | 2 | 4 | 0 | – |

Discovery rejected 61 feeds. The review muted 7 sources on its own, each
with 10 to 33 articles in 30 days and none reaching the top 15 or opened.
The discovery thresholds were compared on one real run of 16 feeds with a
0–10 LLM judge: the same four enabled, 12 of 16 statuses the same, and every
difference a feed that one judge left pending and the other rejected.

### Consequences

- Good, because about half of the active sources were found by discovery,
  and their articles are opened at least as often.
- Good, because sources that never deliver leave without anyone deciding.
- Bad, because discovery needs a web search (see
  [ADR 0003](0003-paid-web-search-for-discovery-is-optional.md)) and a judge.
- Bad, because the dead-source limits are starting points, not yet measured.
- Bad, because a muted source is never tried again on its own.

## Pros and cons of the options

### Manual curation

- Good, because nothing changes without the reader.
- Bad, because it does not happen.

### Weekly pipelines

- Good, because every decision rests on what the reader opened or what the
  feed actually publishes.
- Bad, because three more pipelines to run and test.

### A catalogue or recommendation service

- Good, because no judge is needed.
- Bad, because it reflects what is popular, not this reader, and it is an
  outside dependency.

## More information

Revisit the review thresholds when muted sources are found worth keeping,
and the dead-source limits once enough feeds have failed to measure them on.
