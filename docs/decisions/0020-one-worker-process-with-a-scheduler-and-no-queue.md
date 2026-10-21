---
status: accepted
date: 2026-10-21
---

# One worker process with a scheduler, no task queue

## Context and problem statement

brzask has four pipelines: the digest every morning and three weekly ones
(source review, visited sites, discovery). Each must run at its local time,
never twice at once, and be runnable by hand. Background work in Python web
apps usually means Celery or a similar queue with a broker. Does brzask need
one?

## Decision drivers

- The default deployment stays `migrate` + `api` + `worker` + `db`: nothing
  else to run, secure or back up.
- A pipeline must never overlap with itself, whether started by the
  schedule or by hand.
- Runs are visible: when, how long, what it cost, why it failed.
- Shutting down must not leave a run half done.

## Considered options

- One `worker` process with APScheduler, Postgres advisory locks and a `runs` table.
- Celery (or RQ, Dramatiq) with Redis as broker and beat as scheduler.
- Cron or systemd timers calling the CLI.

## Decision outcome

Chosen option: one worker process with APScheduler. It fires each pipeline
at its time in the configured time zone (`DIGEST_AT`, `REVIEW_AT`, … each
`off` to disable), one job at a time, in a fixed order when two fall on the
same moment, so the review runs before discovery. A run is exactly
`brzask run <pipeline>`: it takes the pipeline's advisory lock (a second run
of the same pipeline is recorded as skipped), gets a row in `runs` before it
starts, and completes it with the outcome, statistics, timings and cost. On
SIGTERM the worker stops scheduling and waits for the running pipeline. A job
that is late by up to 3 hours (a machine that slept, an earlier job that ran
long) still runs; later ones wait for the next time.

### Evidence

The work is small and rare. Over the recorded runs, a digest took about a
minute on average and five minutes at most, discovery a minute and a half on
average; the weekly review takes under a second. That is ten runs a week,
each a sequence of a few API calls with their own parallelism inside (feeds,
extraction and judging use thread pools).

### Consequences

- Good, because there is no broker: one fewer service, and the database is
  the only state.
- Good, because the lock lives in Postgres, so the CLI, the worker and a
  second worker by mistake all respect it.
- Good, because the status page and `brzask status` read the same `runs` rows.
- Bad, because jobs live in memory: a worker started after a scheduled time
  does not catch up on it, and a missed digest has to be run by hand.
- Bad, because there is no retry queue: a failed run waits for the next
  schedule or a manual run (API calls inside a run do retry).
- Bad, because it does not scale out; nothing here needs it to.

## Pros and cons of the options

### Worker with APScheduler

- Good, because it is one process and one library.
- Bad, because missed runs are not persisted.

### Celery and Redis

- Good, because retries, persistence and scaling come with it.
- Bad, because a broker and a beat process for ten jobs a week, and Celery
  is weakly typed.

### Cron or systemd timers

- Good, because the operating system schedules.
- Bad, because it lives outside the container and the compose file, and
  every install sets it up differently.

## More information

Revisit if brzask serves many readers from one instance, where per-reader
digests would make the work grow with the number of readers.
