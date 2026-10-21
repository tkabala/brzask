---
status: accepted
date: 2026-10-21
---

# Opening an article is the only preference signal

## Context and problem statement

To learn what the reader wants beyond their written interests, the digest
needs feedback. Feeds readers and recommenders usually ask for it: stars,
thumbs, "more like this". What should brzask learn from?

## Decision drivers

- Feedback that keeps coming after the first week, without discipline.
- A calm reading experience: nothing to grade, no buttons next to every card.
- A signal that the ranking, the source review and measurement can all use.

## Considered options

- Explicit ratings (thumbs or stars) on each article.
- Opens only: every link goes through brzask, which records the first open.
- Both, ratings optional on top of opens.

## Decision outcome

Chosen option: opens only, because explicit ratings were given up within days
in daily use, twice, while opens keep coming without any effort.

Every link in the digest is `/open?id=…&sig=…`. The signature lets the link
work without a login (from a feed reader or a bookmark) while nobody can make
up a link for another article. It records the time of the first open and
redirects. The ranking prompt lists the titles, topics and
sources opened in the last 90 days as "a positive signal; not opening an
article is not evidence of dislike". The source review mutes only sources
whose articles are never ranked high *and* never opened. `brzask replay` and
`brzask judge-bench` measure changes against opens.

### Evidence

- Explicit ratings were tried twice in daily use. Both times they stopped
  within days: grading every article is a chore, and skipped ratings are
  missing data, not neutral data.
- Opens: 36 of 802 shown articles since July 2026 (4.5%), about 4 a week,
  19 of 195 (10%) over the 28 days to 2026-10-20. Rare, but steady, and
  without asking.

### Consequences

- Good, because the reader does nothing beyond reading.
- Good, because one signal serves ranking, source review, replay and judge
  benchmarks alike.
- Bad, because the signal is sparse: about four a week. The preference
  window is wide (90 days, up to 100 opens) to make up for it, and every
  measurement built on opens has a wide spread.
- Bad, because an article read elsewhere, or judged from its summary alone,
  looks the same as one not wanted. The prompt treats a non-open as no
  evidence for that reason.
- Bad, because opens are positive only: a story the reader disliked cannot
  be told apart from one they had no time for. Writing a "skip:" note on the
  interest is the way to say no (see [ADR 0013](0013-reader-notes-outrank-keywords.md)).

## Pros and cons of the options

### Explicit ratings

- Good, because they carry negative feedback.
- Bad, because they stop within days, measured twice.

### Opens only

- Good, because they cost nothing and keep coming.
- Bad, because they are sparse and positive only.

### Both

- Good, because ratings would add negative feedback when given.
- Bad, because the buttons stay on screen after the ratings stop, and sparse
  ratings next to opens are hard to weigh.

## More information

Revisit if opens become too sparse to measure with, for example for a reader
who reads the summaries and seldom clicks.
