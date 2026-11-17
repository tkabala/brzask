---
status: accepted
date: 2026-11-17
---

# Entering the brief counts with opening the original

## Context and problem statement

Opening an article is the only preference signal
([0011](0011-opens-are-the-only-preference-signal.md)), and it is sparse:
19 opens of 195 shown articles (10%) over the 28 days to 2026-10-20. The web
app now opens a picked article's brief (its gist, points, caveats and, for a
video, chapters) before the original. A reader who learns enough from the
brief has no reason to open the original, so the brief is expected to take
most of the opens. If only `opened_at` counted, the signal would get rarer
still, and the ranking prompt's opened history, the source review and every
measurement built on opens (`replay`, `judge-bench`) would starve. What does
entering the brief mean for the signal?

## Decision drivers

- The signal must not get rarer because the app got better at answering
  "what is this about?".
- Ranking, source review and measurement must agree on what "opened" means,
  so the readers cannot drift apart.
- Entering the brief and opening the original may turn out to be worth
  different weights; that must stay possible to learn later.

## Considered options

- Only opening the original counts; the brief view is not recorded.
- The brief view is recorded and counts like an open, kept in its own
  column.
- The brief view writes `opened_at` itself.

## Decision outcome

Chosen option: the brief view counts like an open and is kept in its own
column, because it keeps the signal flowing without losing which of the two
happened.

`articles.brief_opened_at` holds the first view of the brief, next to
`opened_at` for the first open of the original. An article is *engaged* when
either is set, and its engagement time is the earlier of the two
(`Article.engaged_at`, `LEAST(opened_at, brief_opened_at)` in SQL). Every
reader that treats an open as "the reader wanted this" uses that one rule:
the opened history given to the ranking prompt (still bounded by the run's
start), the source review's and source statistics' opened counts, the
digests' opened counts and the open-rate gauges, the visited-sites proposals,
`brzask replay` and `brzask judge-bench`. Recording an open through `/open`
still writes `opened_at` only, and both timestamps stay visible separately
(`opened_at`, `brief_opened_at`); the web app's opened mark shows either. The open statistics (the `/status` counts and the
`open_stats` agent tool) show the two as separate numbers: originals opened
and briefs entered.

### Evidence

None yet. Whether a brief view predicts interest as well as an open of the
original can only be measured with `brzask replay` and `brzask judge-bench`
once there is brief history; until then the two count the same. Keeping the
timestamps apart is what makes that measurement possible later.

### Consequences

- Good, because the brief does not take the signal away from ranking, review
  and measurement.
- Good, because one rule in the repository layer serves every reader.
- Good, because both timestamps are kept, so they can be weighed differently
  later on replay evidence.
- Bad, because the open rate steps up on the day this is deployed: a brief
  is viewed more readily than an original is opened. Open rates before and
  after that date are not comparable, and a replay or bench spanning it mixes
  the two.
- Bad, because a brief entered and found uninteresting still counts as a
  positive signal, as an open of the original always did.

## Pros and cons of the options

### Only the original counts

- Good, because the signal keeps its meaning and its history stays
  comparable.
- Bad, because the signal gets rarer as the brief answers what the original
  used to.

### Counted, in its own column

- Good, because nothing is lost and the weight can change later.
- Bad, because every reader must use the shared rule instead of the column.

### The brief view writes `opened_at`

- Good, because no reader changes.
- Bad, because the two signals can never be told apart again.

## More information

Amends [0011](0011-opens-are-the-only-preference-signal.md). Revisit when
`brzask replay` or `brzask judge-bench` has enough brief history to compare
brief views with opens of the original.
