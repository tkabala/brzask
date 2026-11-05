import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from brzask.db.models import Run, RunKind, RunStatus
from brzask.services.run_metrics import DURATION_BUCKETS, INSTRUMENTS, Point, measurements

START = datetime(2026, 11, 5, 6, 0, tzinfo=UTC)


def run(
    kind: RunKind = RunKind.DIGEST,
    status: RunStatus = RunStatus.OK,
    *,
    seconds: float | None = 300,
    stats: dict[str, Any] | None = None,
    timings: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> Run:
    return Run(
        id=uuid.uuid4(),
        kind=kind,
        status=status,
        dry_run=dry_run,
        started_at=START,
        finished_at=None if seconds is None else START + timedelta(seconds=seconds),
        stats=stats or {},
        timings=timings or {},
    )


def named(points: list[Point], name: str) -> dict[tuple[tuple[str, str], ...], float]:
    return {
        tuple(sorted(point.attributes.items())): point.value
        for point in points
        if point.name == name
    }


DIGEST_STATS: dict[str, Any] = {
    "pool": {"fresh": 40, "candidates": 200, "sources": 85},
    "ranking": {"ranked": 200, "top": 15},
    "extraction": {"embedded": 15, "candidates": 15},
    "deduplication": {"cross_day_dropped": 1, "same_day_dropped": 2, "survivors": 12},
    "selection": {"picked": 7},
    "usage": {
        "calls": 2,
        "cost_usd_known": 0.0045,
        "by_purpose": {
            "ranking": {
                "cost_usd_known": 0.0026,
                "input_tokens": 9000,
                "output_tokens": 10000,
                "unpriced_calls": 0,
            },
            "selection": {
                "cost_usd_known": 0.0019,
                "input_tokens": 5000,
                "output_tokens": 4000,
                "unpriced_calls": 1,
            },
        },
    },
}


def test_ok_digest_run() -> None:
    points = measurements(run(stats=DIGEST_STATS, timings={"pool": 12000, "ranking": 90500}))

    base = (("dry_run", "false"), ("kind", "digest"))
    assert named(points, "brzask.pipeline.runs") == {(*base, ("status", "ok")): 1}
    assert named(points, "brzask.pipeline.duration") == {(*base, ("status", "ok")): 300.0}
    assert named(points, "brzask.pipeline.stage.duration") == {
        (*base, ("stage", "pool")): 12.0,
        (*base, ("stage", "ranking")): 90.5,
    }
    assert named(points, "brzask.llm.cost") == {
        (*base, ("purpose", "ranking")): 0.0026,
        (*base, ("purpose", "selection")): 0.0019,
    }
    assert named(points, "brzask.llm.tokens") == {
        (*base, ("purpose", "ranking"), ("type", "input")): 9000,
        (*base, ("purpose", "ranking"), ("type", "output")): 10000,
        (*base, ("purpose", "selection"), ("type", "input")): 5000,
        (*base, ("purpose", "selection"), ("type", "output")): 4000,
    }
    assert named(points, "brzask.llm.unpriced_calls") == {(*base, ("purpose", "selection")): 1}
    articles = named(points, "brzask.digest.articles")
    assert {dict(key)["stage"]: value for key, value in articles.items()} == {
        "fresh": 40,
        "candidates": 200,
        "ranked": 200,
        "top": 15,
        "extracted": 15,
        "cross_day_duplicates": 1,
        "same_day_duplicates": 2,
        "kept": 12,
        "picked": 7,
    }
    assert all(dict(key)["dry_run"] == "false" for key in articles)


def test_dry_runs_are_labelled() -> None:
    points = measurements(run(dry_run=True))

    assert {point.attributes["dry_run"] for point in points} == {"true"}


def test_skipped_run_counts_and_has_no_cost() -> None:
    points = measurements(run(status=RunStatus.SKIPPED, seconds=0.2, stats={"reason": "paused"}))

    assert {point.name for point in points} == {"brzask.pipeline.runs", "brzask.pipeline.duration"}


def test_review_run_has_no_digest_articles() -> None:
    points = measurements(run(RunKind.REVIEW, stats={"pool": {"fresh": 3}, "decisions": {}}))

    assert not named(points, "brzask.digest.articles")


def test_odd_stats_are_skipped() -> None:
    stats: dict[str, Any] = {
        "pool": "x",
        "selection": {"picked": None},
        "ranking": {"ranked": True, "top": 15.0},
        "usage": {
            "by_purpose": {
                "ranking": {"cost_usd_known": "abc", "input_tokens": "many"},
                # Written before cost_usd_known existed: the same fallback as the budget.
                "embedding": {"cost_usd": 0.01, "input_tokens": 10, "output_tokens": 0},
                "selection": "nonsense",
            }
        },
    }
    points = measurements(run(stats=stats, timings={"pool": "slow", "rank": None}))

    assert {
        dict(key)["stage"]: v for key, v in named(points, "brzask.digest.articles").items()
    } == {"top": 15}
    assert {dict(key)["purpose"]: v for key, v in named(points, "brzask.llm.cost").items()} == {
        "embedding": 0.01
    }
    assert not named(points, "brzask.pipeline.stage.duration")


def test_usage_that_is_not_a_mapping_is_ignored() -> None:
    points = measurements(run(stats={"usage": [1, 2]}))

    assert not named(points, "brzask.llm.cost")


def test_running_run_without_finish_has_no_duration() -> None:
    points = measurements(run(status=RunStatus.RUNNING, seconds=None))

    assert not named(points, "brzask.pipeline.duration")
    assert named(points, "brzask.pipeline.runs")


def test_every_point_names_a_declared_instrument() -> None:
    points = measurements(run(stats=DIGEST_STATS, timings={"pool": 1}))

    assert {point.name for point in points} == set(INSTRUMENTS)


def test_buckets_cover_measured_digest_durations() -> None:
    assert list(DURATION_BUCKETS) == sorted(DURATION_BUCKETS)
    assert DURATION_BUCKETS[0] <= 1 and DURATION_BUCKETS[-1] >= 3600
    assert sum(113 <= bucket <= 555 for bucket in DURATION_BUCKETS) >= 2
