# Measuring changes

Thresholds, limits, prompts and extractors are not tuned by feel. Two commands measure a change on real data before it is made.

## Digest choices: replay

`brzask replay` chooses past digests again with the current code, or with a candidate change, and compares the picks with what the reader actually opened.

```console
$ brzask replay --days 30
DATE        POOL  OPENED IN POOL  SHOWN: OPENED  REPLAY: OPENED  SAME  ERROR
2026-09-27  200   2               2/7            2/7             3
2026-09-28  200   2               2/7            2/7             2
2026-09-29  200   1               1/7            0/7             2
2026-09-30  200   0               1/7            0/7             0
...

Replay: opened 10 of 193 picks (5%); shown: opened 19 of 195 (10%); 55 picks also shown; over 28 days.
56 model calls, $0.1057.
```

For each day with a digest, replay rebuilds the candidate pool from the articles stored by the end of that day's run, ranks it, deduplicates the top and selects the digest again, exactly as the daily run does. It writes nothing: its database transactions are read-only.

### Columns

| Column | Meaning |
|---|---|
| `POOL` | Candidates in the rebuilt pool. |
| `OPENED IN POOL` | Opened articles among them: the most any selection of this pool could score. |
| `SHOWN: OPENED` | The digest that was really shown: opened / shown. |
| `REPLAY: OPENED` | The replayed picks: opened / picked. |
| `SAME` | Replayed picks that were also in the real digest. |

`--json FILE` also writes every day, every pick and the stage statistics (ranking, deduplication drops, selection) to a file.

### Trying a change

A configuration file overrides any of the digest's limits; everything left out keeps its current value:

```toml
llm_model = "provider/another-model"  # left out: LLM_MODEL
embedding_model = "provider/new-model"  # left out: the active model; its stored vectors are used
judge_model = "liquid/d1"  # left out: JUDGE_MODEL; used when [ranking] method = "judge"

[pool]
max_age_days = 10
carry_over_days = 7
cap = 200

[ranking]
method = "llm"  # or "judge": score every candidate with JUDGE_BACKEND (see below); left out: DIGEST_RANKING
rank_limit = 40
top_n = 15
max_per_source = 2
min_candidates = 10

[ranking.weights]  # method = "judge"; dimensions left out keep their weight
interest_fit = 1.0
novelty = 0.5
depth = 0.3
promotion = -0.5
opened_similarity = 0.2

[deduplication]
method = "judge"  # or "threshold"; left out: DIGEST_DEDUPLICATION
cross_day = 0.96  # cross_day and same_day: both or neither; neither keeps the model's own
same_day = [0.80, 0.83, 0.86, 0.90, 0.93]

[selection]
digest_size = 7
```

```console
$ brzask replay --days 30 --config candidate.toml
$ brzask replay --days 30 --prompt-dir my-prompts/   # e.g. my-prompts/ranking.md
```

With `method = "judge"`, the LLM does not rank. Instead the judge scores every candidate on the dimensions above (how well it fits the interests, how new it is, how much substance it promises, how promotional it is, how close it is to what the reader opened), and the candidates are ordered by the weighted sum of the scores, each scaled to 0–1. The daily run does the same with `DIGEST_RANKING=judge`. This costs one judge call per candidate, about 200 a day.

With `[deduplication] method = "judge"`, the same-day pass does not choose a threshold. It asks the judge about every pair of top candidates whose similarity lies between the lowest same-day threshold and the cross-day threshold (0.80–0.96 for Gemini): "do these two articles report the same event?". Pairs above the zone are duplicates without asking. All pairs of a day go in one call. This is the daily run's default (`DIGEST_DEDUPLICATION=judge`, see [ADR 0007](decisions/0007-a-judge-decides-same-day-duplicates-in-the-grey-zone.md)); set `method = "threshold"` to compare with the adaptive threshold.

`--prompt-dir` takes a directory with only the prompts being changed, named like the packaged ones (`ranking.md`, `selection.md`, …); the others stay as they are. A file named like no prompt is an error rather than silently ignored.

### Reading the result

- **Only shown articles could be opened.** A pick that was never shown counts as not opened, even if the reader would have liked it. A replay matches the real digest by picking the articles that were opened; it can hardly beat it, and a clear drop means a change loses what the reader reads.
- **The model is not deterministic.** Replaying the same setup twice gives different picks. Run the current setup more than once to see the spread before reading anything into a difference.
- **Text and vectors exist only for articles a real run extracted** (its top 15). Other candidates reach deduplication and selection with their feed snippet.
- **Interests and reader notes are today's.** Opens shown to the ranking are only those from before the replayed run.
- **Each day is replayed against the real history**: what earlier real digests showed, not what the replay picked, so one article can be picked on two replayed days.

### Baseline

Over 28 days of daily use (2026-09-21 to 2026-10-20, `deepseek/deepseek-v4-flash`), the digests actually shown (by each day's first run) were opened 19 times out of 195 articles (10%). Replaying the same days with the current setup picked 193 articles, 55 of them the same as shown, and 10 of them had been opened (5%). The pools held 27 opened articles in total. A change is worth keeping when it moves the replay's number up beyond the spread of repeated replays, not when it beats the shown digests, which the replay can hardly do.

One opened article (2026-09-30) is in no rebuilt pool: it was published two months before it was shown, and the 10-day age limit drops it.

Each day costs two model calls (ranking and selection). `--workers` (default 4) replays several days at once.

## Embedding models: reembed and replay

Deduplication thresholds are cosine values measured on one embedding model and mean nothing for another (see `THRESHOLDS` in the deduplication stage). Moving to another model is therefore three steps:

```console
$ brzask reembed --model provider/new-model --no-switch   # compute vectors, keep using the current model
$ brzask replay --days 30 --config new-model.toml          # embedding_model = "provider/new-model", [deduplication] ...
$ brzask reembed --model provider/new-model               # embed what came in since, then switch
```

`reembed` embeds every article that has a vector of another model again, from its stored text, in batches; it can be stopped and run again. Digests keep using the active model until the switch, which waits for no digest to be running. `brzask status` shows the active model and the stored vectors per model. Add the measured thresholds for the new model to `THRESHOLDS` before or right after switching; until then the digest uses the default ones and logs a warning. After the switch, set `EMBEDDING_MODEL` to the new model too: the active model wins, but every digest logs a warning while the two differ. A replay naming a model with no stored vectors stops with an error instead of deduplicating nothing.

## Judge models: judge-bench

`brzask judge-bench` scores every article the digests showed with one or more judges, using the questions of the composite ranking. It then reports how well each score tells the articles the reader opened from those they did not, as an AUC: the chance that an opened article scores above one that was not opened. 0.5 is chance. Because every scored article was shown, each could be opened, so the measure does not favour the ranking that chose the digests, as `replay` does.

```console
$ brzask judge-bench --days 30 --model typesafe/jev-1.13 --model liquid/d1 --model llm --json bench.json
MODEL                       OPENED  FAILED  AUC COMPOSITE  AUC INTEREST_FIT  AUC NOVELTY  AUC DEPTH  AUC PROMOTION  AUC OPENED_SIMILARITY  COST     PER CALL
typesafe/jev-1.13           19/195  0       0.51           0.45              0.48         0.42       0.33           0.49                   $0.0148  312 ms
liquid/d1                   19/195  0       0.62           0.60              0.47         0.41       0.31           0.56                   $0.0059  310 ms
deepseek/deepseek-v4-flash  19/195  0       0.47           0.54              0.49         0.48       0.47           0.53                   $0.2087  47266 ms
```

`--model llm` uses `LLM_MODEL` as the judge; without `--model`, the configured judge runs. `--json` writes every article's scores and whether it was opened, ready for fitting weights.

An AUC below 0.5 means the reverse relation. For promotion it is the expected direction: opened articles were less promotional.

### Judge models compared

Measured on 2026-10-20, on daily use. Each row comes from its own measurement:

| | Jev 1.13 | d1 | LLM judge (deepseek-v4-flash) |
|---|---|---|---|
| Opened vs. not opened among 195 shown articles (19 opened), composite AUC, 95% bootstrap interval | 0.51 (0.37–0.64) | 0.62 (0.49–0.74) | 0.47 (0.33–0.60) |
| Same, promotion score alone | 0.33 (0.21–0.47) | 0.31 (0.20–0.44) | 0.47 (0.33–0.59) |
| Same-day duplicate pairs judged right, of 12 labelled by hand | 12 | 11 | 10 |
| Discovery: same status as a 0–10 LLM judge, of 16 feeds | 12 | 12 | 13 |
| Discovery: feeds enabled that the 0–10 judge did not enable | 0 | 1 | 1 |
| Cost per article (five ranking questions) | $0.000076 | $0.000030 | $0.0011 |
| Time per call | 0.3 s | 0.3 s | 47 s |

None of the three tells the opened articles from the rest better than chance with the composite score: every interval includes 0.5. The shown articles had already been ranked into the top 7 of about 200, so they differ little in what the dimensions measure. Promotion is the one clear signal, for Jev and d1. Jev and d1 cannot be told apart on these numbers. The LLM judge is no better, and is about 15 to 35 times as expensive and 150 times as slow. See [ADR 0008](decisions/0008-jev-stays-the-default-judge.md).

## Extractors: extract-bench

`brzask extract-bench` runs every extractor on the same sample of stored links and compares them: how often each gets usable text, how long the text is, how fast and at what cost, in total and per site.

```console
$ brzask extract-bench --extractors feed,trafilatura,jina --sample 60 --per-site 3
```

The sample is drawn at random from links first seen in the last `--days` (10), at most `--per-site` from one site, so one large site cannot dominate. The sampled sources' feeds are fetched again, so the `feed` extractor sees the content it would have had. Each extractor runs on its own, through the same robots.txt, per-site and usable-text rules as a digest run.

| Column | Meaning |
|---|---|
| `TRIED` | Links the extractor was allowed to fetch (`SKIPPED`: a site rule or robots.txt said no). |
| `USABLE`, `SHORT`, `BLOCKED`, `EMPTY`, `FAILED` | Outcomes, by the rule every digest run uses. |
| `MEDIAN WORDS` | Of usable texts, without Markdown link targets and images. |
| `UNDER HALF` | Usable, but under half the words another extractor got for the link: either it missed part of the article, or the other one kept the page around it. Look at both texts. |
| `ONLY ONE` | Links no other extractor got. |
| `TOKENS` | Billed by a hosted reader. |

A last line checks the feed threshold: feed content long enough to be taken as the article, against the page text a chain would have used instead.

The bench fetches real pages. Keep `--workers` low and runs infrequent: sites start answering with bot checks when hit repeatedly. Jina Reader without a key is paced to its 20 requests a minute. The current default order is explained in [ADR 0002](decisions/0002-trafilatura-as-the-default-page-extractor.md).
