---
status: accepted
date: 2026-10-21
---

# Measure changes by replaying past days

## Context and problem statement

Every part of the digest has a knob: pool size, prompt wording, ranking
method, thresholds, judge model, extractor, embedding model. A change that
looks better on one day's output can lose what the reader reads, and with
seven articles a day and about four opens a week, nobody notices for weeks.
How are changes to the pipeline decided?

## Decision drivers

- Evidence from the reader's own history, not from a benchmark dataset.
- The same code path as the daily run, so the measurement is of what ships.
- Cheap enough to run before every change to a measured constant.

## Considered options

- Judge changes by reading a day's output.
- A/B test live: alternate methods across days.
- Replay: rebuild past days with the current code or a candidate change and
  count how many picks were actually opened.

## Decision outcome

Chosen option: replay, plus narrower benchmarks for single parts.

`brzask replay --days N` rebuilds each past day's pool from what was stored
that day, runs ranking, deduplication and selection again (optionally with a
TOML file of changes), and reports per day and in total how many of the
replayed picks were opened, next to the digest that was really shown. Nothing
is written. The narrower tools work the same way: `judge-bench` (how well a
judge's scores separate opened from not opened shown articles, as an AUC),
`extract-bench` (usable text and time per extractor) and `reembed` with a
replay (a new embedding model).

Every measured constant in the code keeps a comment saying what it was
measured on, and changes only with such evidence.

### Evidence

Baseline over 28 days of daily use (2026-09-21 to 2026-10-20,
`deepseek/deepseek-v4-flash`): the digests actually shown were opened 19
times out of 195 articles (10%). Replaying the same days picked 193
articles, 55 of them the same as shown, of which 10 had been opened (5%).
Three replays of the same setup scored 7, 10 and 10 opened, which is the
spread a change has to beat.

### Consequences

- Good, because every ADR with a measurement in it was decided this way:
  ranking methods ([0006](0006-llm-ranking-stays-the-default-over-composite-scores.md)),
  the same-day judge ([0007](0007-a-judge-decides-same-day-duplicates-in-the-grey-zone.md)),
  judge models ([0008](0008-jev-stays-the-default-judge.md)) and extractors
  ([0002](0002-trafilatura-as-the-default-page-extractor.md)).
- Good, because it costs cents: the replay of 28 days above made 56 model
  calls for $0.11.
- Bad, because only shown articles could be opened. A replay can hardly beat
  the shown digests and cannot show that a method which picks differently
  does better; it can show that a change loses what the reader reads.
- Bad, because with about four opens a week, differences of a few opens are
  noise.

## Pros and cons of the options

### Reading the output

- Good, because it is immediate.
- Bad, because it measures what looks good, not what is read.

### Live A/B

- Good, because it measures opens of what was really shown.
- Bad, because with four opens a week it takes months to tell two methods
  apart, and the reader lives with the worse one meanwhile.

### Replay

- Good, because it runs in minutes on months of history.
- Bad, because it is biased towards whatever chose the shown digests.

## More information

How to run each tool and read its output: [Measuring changes](../measuring.md).
