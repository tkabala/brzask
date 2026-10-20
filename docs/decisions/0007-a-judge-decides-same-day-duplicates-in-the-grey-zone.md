---
status: accepted
date: 2026-10-20
---

# A judge decides same-day duplicates in the grey zone

## Context and problem statement

The same-day pass of deduplication drops the worse ranked of two top
candidates that tell the same story. By similarity alone it cannot be told
apart from two articles that only share a topic: same-day duplicates measured
0.80–0.88 (two outlets word one story differently), and distinct articles from
one project or source reach the same range. The adaptive threshold tries 0.80
first and keeps it whenever at least 9 candidates survive. Should a judge
(see [ADR 0005](0005-system-one-judgements-over-one-http-client.md)) decide
the pairs between the lowest same-day threshold and the cross-day threshold
instead?

## Decision drivers

- A wrong drop removes a distinct article from the top 15, which the
  selection can no longer pick.
- A missed duplicate shows one story twice.
- The digest must not fail because of a second API.
- Cost and duration of the daily run.

## Considered options

- Judge the grey zone (0.80–0.96 for Gemini) by default, falling back to the threshold.
- Keep the adaptive threshold by default; the judge selectable.

## Decision outcome

Chosen option: judge the grey zone by default
(`DIGEST_DEDUPLICATION=judge`), because almost every pair the threshold
dropped was two different stories, the judge told them apart, and it costs a
fraction of a cent a month. If the judge cannot be reached, the threshold
decides that day, with a warning.

### Evidence

**Pairs.** Over 28 replayed digest days (2026-09-21 to 2026-10-20), the
threshold made 16 same-day drops, 12 different pairs. It picked 0.80, the
most aggressive threshold, on every day. Read by hand, one pair was one event
(OpenAI's "Introducing dots" and the Hacker News post about it, 0.83). The
others were different news:

- consecutive Claude Code releases with different changes (0.82–0.84);
- an SDK and a CLI release of one project (0.96);
- two Google DeepMind announcements (0.95);
- two unrelated Phoronix stories (0.81);
- two different Towards Data Science articles on one model (0.87).

Each pair was then asked in the shape deduplication uses: title, source and
the first 1000 characters of the stored text. At probability ≥ 0.5 for "same
event":

| Judge | Correct | Wrong | Cost of the 12 pairs |
|---|---|---|---|
| Adaptive threshold (0.80) | 1 | 11 dropped wrongly | – |
| `typesafe/jev-1.13` | 12 | 0 (the two Towards Data Science articles at 0.31) | $0.00026 |
| `liquid/d1` | 11 | 1 (the two Towards Data Science articles at 0.59) | $0.00012 |
| `deepseek/deepseek-v4-flash` (LLM judge) | 10 | 2 (Towards Data Science 1.00, v2.1.292 / v2.1.293 1.00) | $0.00058 |

**Replay.** `brzask replay --days 30` with `[deduplication] method = "judge"`
(Jev), ranking and selection as usual. The judge was asked on 9 of the 28
days, about 12 pairs in all. It dropped 2 articles (the dots pair, 0.95 both
times), where a threshold replay dropped 10. Picks opened: 9 of 192, against
7, 10 and 10 of about 193 in three replays with the threshold. That is
within the spread, so the replay shows no loss; it cannot show a gain,
because only shown articles could be opened and dedup changes few picks.
Judge calls: $0.0004 for the 28 days, 0.3 s each.

### Consequences

- Good, because distinct releases and announcements from one source stay
  in the top 15 instead of being dropped as duplicates.
- Good, because the judge reads the articles, so the grey zone no longer
  depends on how far one embedding model spreads its similarities.
- Bad, because the daily run calls a second model by default. On endpoints
  without a System One model, set `JUDGE_BACKEND=llm` (the chat model judges,
  measured above with two wrong pairs) or `DIGEST_DEDUPLICATION=threshold`;
  otherwise the run falls back with a warning every day.
- Bad, because the 0.5 cut-off is not tuned: 12 labelled pairs, with one
  near-miss for d1, are too few to tune it on.

## Pros and cons of the options

### Judge by default

- Good, because the measured wrong drops disappear.
- Good, because it costs about a cent a year.
- Bad, because it adds an API dependency, softened by the fallback.

### Threshold by default

- Good, because it needs nothing but the embeddings.
- Bad, because 11 of its 12 grey-zone pairs were different news.

## More information

The cut-off and the cross-day threshold are unchanged; the cross-day pass is
not judged (repeats measured ≥ 0.962 and distinct articles ≤ 0.959, a clean
split). Revisit with more labelled pairs. Collect them from the `drops` in
the run statistics (`same_event` is recorded for judged pairs), and compare
judge models with `judge_model` in the replay configuration.
