# Measuring changes with replay

Thresholds, limits and prompts are not tuned by feel. `brzask replay` chooses past digests again with the current code, or with a candidate change, and compares the picks with what the reader actually opened.

```console
$ brzask replay --days 30
DATE        POOL  OPENED IN POOL  SHOWN: OPENED  REPLAY: OPENED  SAME  ERROR
2026-09-27  200   2               2/7            2/7             4
2026-09-28  200   2               2/7            2/7             3
2026-09-29  200   1               1/7            1/7             3
2026-09-30  200   0               1/7            0/7             3
...

Replay: opened 10 of 194 picks (5%); shown: opened 19 of 202 (9%); 67 picks also shown; over 28 days.
56 model calls, $0.2754.
```

For each day with a digest, replay rebuilds the candidate pool from the articles stored by the end of that day's run, ranks it, deduplicates the top and selects the digest again, exactly as the daily run does. It writes nothing: its database transactions are read-only.

## Columns

| Column | Meaning |
|---|---|
| `POOL` | Candidates in the rebuilt pool. |
| `OPENED IN POOL` | Opened articles among them: the most any selection of this pool could score. |
| `SHOWN: OPENED` | The digest that was really shown: opened / shown. |
| `REPLAY: OPENED` | The replayed picks: opened / picked. |
| `SAME` | Replayed picks that were also in the real digest. |

`--json FILE` also writes every day, every pick and the stage statistics (ranking, deduplication drops, selection) to a file.

## Trying a change

A configuration file overrides any of the digest's limits; everything left out keeps its current value:

```toml
llm_model = "provider/another-model"  # left out: LLM_MODEL

[pool]
max_age_days = 10
carry_over_days = 7
cap = 200

[ranking]
rank_limit = 40
top_n = 15
max_per_source = 2
min_candidates = 10

[deduplication]  # left out: the embedding model's own thresholds
cross_day = 0.96
same_day = [0.80, 0.83, 0.86, 0.90, 0.93]

[selection]
digest_size = 7
```

```console
$ brzask replay --days 30 --config candidate.toml
$ brzask replay --days 30 --prompt-dir my-prompts/   # e.g. my-prompts/ranking.md
```

`--prompt-dir` takes a directory with only the prompts being changed, named like the packaged ones (`ranking.md`, `selection.md`, …); the others stay as they are. A file named like no prompt is an error rather than silently ignored.

## Reading the result

- **Only shown articles could be opened.** A pick that was never shown counts as not opened, even if the reader would have liked it. A replay matches the real digest by picking the articles that were opened; it can hardly beat it, and a clear drop means a change loses what the reader reads.
- **The model is not deterministic.** Replaying the same setup twice gives different picks. Run the current setup more than once to see the spread before reading anything into a difference.
- **Text and vectors exist only for articles a real run extracted** (its top 15). Other candidates reach deduplication and selection with their feed snippet.
- **Interests and reader notes are today's.** Opens shown to the ranking are only those from before the replayed run.
- **Each day is replayed against the real history**: what earlier real digests showed, not what the replay picked, so one article can be picked on two replayed days.

## Baseline

Over 28 days of daily use (2026-09-21 to 2026-10-20, `deepseek/deepseek-v4-flash`), the digests actually shown were opened 19 times out of 202 articles (9%). Replaying the same days with the current setup picked 194 articles, 67 of them the same as shown, and 10 of them had been opened (5%). The pools held 28 opened articles in total. A change is worth keeping when it moves the replay's number up beyond the spread of repeated replays, not when it beats the shown digests, which the replay can hardly do.

One opened article (2026-09-30) is in no rebuilt pool: it was published two months before it was shown, and the 10-day age limit drops it.

Each day costs two model calls (ranking and selection). `--workers` (default 4) replays several days at once.
