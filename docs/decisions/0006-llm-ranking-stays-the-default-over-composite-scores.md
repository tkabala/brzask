---
status: accepted
date: 2026-10-20
---

# LLM ranking stays the default; composite scores are opt-in

## Context and problem statement

Every day the pool of about 200 candidates is ordered and its top 15 goes on
to extraction, deduplication and selection. By default an LLM ranks the whole
pool in one prompt. The alternative scores each candidate with a judge
(`DIGEST_RANKING=judge`, see [ADR 0005](0005-system-one-judgements-over-one-http-client.md))
on five dimensions (interest fit, novelty, depth, promotion, similarity to
recent opens), each a level on a scale, and orders the pool by a weighted sum
kept in code. Should the composite score replace the LLM ranking?

## Decision drivers

- What the reader opens, measured with `brzask replay`.
- Cost and duration of the daily run.
- Explainable, reusable signals: per-dimension scores can be reweighted
  without asking again, and could later be learned from opens.

## Considered options

- Keep the LLM ranking as the default; composite scores selectable.
- Make the composite score the default.

## Decision outcome

Chosen option: keep the LLM ranking as the default, because the composite
score with hand-set weights did not find more of what the reader opens, and
it costs about five times as much per day. It stays selectable, so that
learned weights and other judge models can be measured against it.

### Evidence

`brzask replay --days 30` on 2026-10-20: 28 digest days (2026-09-21 to
2026-10-20), 200 candidates a day, 27 opened articles across the rebuilt
pools. Selection with `deepseek/deepseek-v4-flash` in every run; the composite
score with `typesafe/jev-1.13` and the default weights (interest fit 1.0,
novelty 0.5, depth 0.3, promotion −0.5, opened similarity 0.2).

| Ranking | Picks | Opened | Also in the real digest | Opened of those | Ranking cost | Ranking time per day |
|---|---|---|---|---|---|---|
| LLM, earlier replay 1 | 194 | 10 | 67 | 10 | – | – |
| LLM, earlier replay 2 | 193 | 10 | 55 | 10 | – | – |
| LLM, same day as below | 192 | 7 | 56 | 7 (12.5%) | $0.080 | 148 s, one call |
| Composite (Jev) | 194 | 5 | 39 | 5 (13%) | $0.424 | 59 s of calls, 200 calls, about 8 s with 8 at once |

The two methods shared 46 of their picks; 3 opened articles were picked by
both, 4 only by the LLM ranking and 2 only by the composite score. Every one
of the 5,600 judge calls succeeded; a call read about 1,800 tokens.

The comparison leans towards the LLM ranking. Only articles that were shown
could be opened, and the shown digests were chosen with the LLM ranking. The
composite score moved further from them (39 of its picks were shown, against
55 to 67 for the LLM replays), and among the picks that were shown, both
methods found opened articles at the same rate (13% and 12.5%). The replay
can confirm that a method loses what the reader reads; it cannot show that a
method that picks differently does better. Three LLM replays scored 7, 10 and
10, so a difference of a few opens is within the spread.

### Consequences

- Good, because the default run stays at one ranking call (about $0.003 a day,
  against $0.015 for the composite score with Jev).
- Good, because the composite score is ready for the next measurements:
  another judge model (`judge_model` in the replay config), other weights
  (`[ranking.weights]`) and weights learned from opens.
- Bad, because the daily run keeps waiting about two and a half minutes for
  one reasoning call to rank, where the judge needs seconds.
- Bad, because the replay cannot settle the question in favour of a method
  that differs from the shown history; that would need it to run live for a
  while.

## Pros and cons of the options

### LLM ranking by default

- Good, because it compares candidates with each other, which avoids the tied
  scores that absolute 0–10 scores collapse into.
- Good, because it is the cheapest and the measured baseline.
- Bad, because the order cannot be explained or reweighted without asking again.

### Composite score by default

- Good, because each score is a narrow judgement, explainable per article and
  reusable with other weights.
- Good, because judging is fast and fails per article rather than per day.
- Bad, because it did not find more opened articles, and it costs about five
  times as much.

## More information

Revisit when weights learned from opens, or another judge model, beat the LLM
ranking in `brzask replay`, or after running the composite score live for a
few weeks and comparing opens. The measurement method is described in
[Measuring changes](../measuring.md).
