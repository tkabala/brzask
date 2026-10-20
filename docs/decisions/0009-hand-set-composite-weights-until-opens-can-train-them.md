---
status: accepted
date: 2026-10-20
---

# Hand-set composite weights until opens can train them

## Context and problem statement

The composite ranking ([ADR 0006](0006-llm-ranking-stays-the-default-over-composite-scores.md))
weighs five judged dimensions with hand-set weights: interest fit 1.0,
novelty 0.5, depth 0.3, promotion −0.5, opened similarity 0.2. Opens are the
only preference signal brzask has. Can a model fitted to them (the dimension
scores as features, opened or not as the label) choose better weights?

## Decision drivers

- Out-of-sample results: weights must win on days they were not fitted on.
- Opens can only label articles that were shown.
- A ranking weighs the whole pool of about 200 candidates, not only the 7 shown.

## Considered options

- Learned weights (logistic regression with an L2 penalty, `brzask fit-weights`).
- Hand-set weights.

## Decision outcome

Chosen option: hand-set weights, because the learned weights lost clearly in
replay on held-out days. The reason is structural, not a lack of tuning.
The only labelled articles are the shown ones, which the ranking had already
judged relevant. Among them, interest fit and novelty barely vary, so the fit
learns they do not matter, or even count against. Applied to the whole pool,
such weights rank irrelevant and routine articles first.

### Evidence

Features: Jev's scores of the 195 articles shown over 28 digest days
(`brzask judge-bench`, 2026-09-21 to 2026-10-20), 19 of them opened.

| Fitted on | interest fit | novelty | depth | promotion | opened similarity |
|---|---|---|---|---|---|
| Hand-set | 1.0 | 0.5 | 0.3 | −0.5 | 0.2 |
| All 28 days | −0.11 | −0.10 | −0.31 | −0.66 | 0.01 |
| Days up to 2026-10-06 (16 days, 10 opened) | 0.01 | −0.18 | −0.14 | −0.19 | −0.11 |
| All 28 days, d1's scores | 0.28 | −0.08 | −0.39 | −0.80 | 0.13 |

Among the shown articles, the learned weights looked slightly better, scored
leave one day out: AUC 0.57 against 0.51 for Jev, 0.62 against 0.62 for d1.
On the earlier 16 days alone the same measure gave 0.31, so the fit is not
stable.

**Replay on held-out days.** `brzask replay --days 14` (12 digest days,
2026-10-07 to 2026-10-20) ranked with Jev, once with the hand-set weights and
once with the weights fitted on the days up to 2026-10-06:

| Weights | Picks opened | Picks also shown | Cost |
|---|---|---|---|
| Hand-set | 4 of 84 | 17 | $0.196 |
| Learned | 0 of 84 | 1 | $0.191 |

The learned weights' picks were release candidates and minor releases
(Tailscale 1.104.1, an abandoned Hermes Agent RC, cline v0.0.92) and forum
chatter ("How well did you guys pace yourself this week?"). The hand-set
weights picked articles on the reader's interests.

### Consequences

- Good, because the composite ranking keeps weights that rank the pool sensibly.
- Good, because the tools stay for later: `brzask judge-bench --json` writes
  the features, `brzask fit-weights` fits and prints a `[ranking.weights]`
  block for `brzask replay`.
- Bad, because opens do not tune the composite yet; promotion is the one
  dimension the data supports (it counts against opens in every fit, as the
  hand-set weight does).

## Pros and cons of the options

### Learned weights

- Good, because they would follow the reader without anyone setting them.
- Bad, because shown-only labels describe differences inside the top 7, not
  between the top and the rest of the pool.
- Bad, because 19 positives give unstable weights.

### Hand-set weights

- Good, because they encode what relevance means for the whole pool.
- Bad, because nothing measures them except replay, which favours the
  ranking that chose the shown history.

## More information

Fitting needs labels from across the pool. Showing an occasional article
from lower in the ranking (exploration) would provide them; so would many
more opens. Revisit when the bench has at least 100 opened articles, fitting
on shown articles together with a sample of unshown pool articles as
negatives, and validate with `brzask replay` on held-out days as above.
