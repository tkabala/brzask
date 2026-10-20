---
status: accepted
date: 2026-10-20
---

# Jev stays the default judge

## Context and problem statement

Judgements (same-day duplicates by default, discovery, and the composite
ranking when chosen) go to the model in `JUDGE_MODEL`. Three judges are
available through one OpenRouter key: TypeSafe's Jev 1.13, Liquid's d1,
and the chat model answering the same questions in JSON (`JUDGE_BACKEND=llm`).
[ADR 0005](0005-system-one-judgements-over-one-http-client.md) set Jev as the
default before any comparison. Which should be the default?

## Decision drivers

- Correct answers where a wrong one costs: a distinct story dropped as a
  duplicate, a source enabled or rejected for good.
- What the reader opens.
- Cost and time per call.
- One key and no extra setup by default.

## Considered options

- Jev 1.13
- d1
- The LLM judge

## Decision outcome

Chosen option: Jev 1.13, because no measurement separates it from d1 on what
the reader opens. Where a wrong answer costs, it made the fewest mistakes:
all 12 duplicate pairs right, and in discovery it enabled no feed the
previous judge had not enabled. d1 is the cheaper alternative and stays one
setting away; the LLM judge is for endpoints without a System One model.

### Evidence

All measured on 2026-10-20, on daily use; [Measuring changes](../measuring.md#judge-models-compared)
has the full table and how to rerun it.

| | Jev 1.13 | d1 | LLM judge (deepseek-v4-flash) |
|---|---|---|---|
| Composite AUC, opened vs. not among 195 shown articles (19 opened) | 0.51 (0.37–0.64) | 0.62 (0.49–0.74) | 0.47 (0.33–0.60) |
| Duplicate pairs right, of 12 | 12 | 11 | 10 |
| Discovery feeds enabled that the 0–10 judge did not, of 16 | 0 | 1 | 1 |
| Cost per article, five questions | $0.000076 | $0.000030 | $0.0011 |
| Time per call | 0.3 s | 0.3 s | 47 s |

d1's higher composite AUC lies within the overlap of the two 95% bootstrap
intervals; with 19 opened articles a difference of 0.11 is not evidence.

### Consequences

- Good, because the default makes no measured wrong drop and enables
  nothing the previous judge rejected.
- Good, because the daily cost is small with either model. With the
  defaults (judged deduplication only), it is well under a cent a day.
- Bad, because d1 would cost about 40% of Jev for answers that are not
  measurably worse on what the reader opens.

## Pros and cons of the options

### Jev 1.13

- Good, because it had the fewest wrong answers where they cost.
- Bad, because it is the more expensive of the two System One models.

### d1

- Good, because it is about 2.5 times cheaper at the same speed.
- Good, because it has the best point estimate on opens, though not a
  significant one.
- Bad, because it has one wrong duplicate pair and one feed enabled the
  previous judge only held.

### LLM judge

- Good, because it works with any chat endpoint, local ones included.
- Bad, because it is no better on any measure, costs 15 to 35 times as much
  and takes 47 s a call with a reasoning model.

## More information

Rerun `brzask judge-bench` as opens accumulate: 19 opened articles are
too few to tell the models apart. Revisit when a model's interval no longer
overlaps the others', or when Jev releases a new version (pin it in
`JUDGE_MODEL` and compare first).
