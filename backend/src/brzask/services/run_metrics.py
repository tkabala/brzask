"""Metrics of finished pipeline runs.

Every run is counted and timed, by kind and outcome, with the duration of
each stage, the tokens and cost of its LLM and embedding calls by purpose,
and, for digests, how many articles each stage left. The values come from
the run row, so they always agree with the status page; `measurements` turns
a row into data points and `RunInstruments` records them.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from opentelemetry import metrics

from brzask.db.models import Run, RunKind
from brzask.log import get_logger

log = get_logger(__name__)

# Digest runs took 113-555 s in daily use (cheap and full runs), so the
# buckets between one and fifteen minutes are the dense ones.
DURATION_BUCKETS: tuple[float, ...] = (1, 5, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)

RUNS = "brzask.pipeline.runs"
DURATION = "brzask.pipeline.duration"
STAGE_DURATION = "brzask.pipeline.stage.duration"
LLM_COST = "brzask.llm.cost"
LLM_TOKENS = "brzask.llm.tokens"
LLM_UNPRICED_CALLS = "brzask.llm.unpriced_calls"
DIGEST_ARTICLES = "brzask.digest.articles"

# Instrument name -> kind ("counter" or "histogram").
INSTRUMENTS: dict[str, str] = {
    RUNS: "counter",
    DURATION: "histogram",
    STAGE_DURATION: "histogram",
    LLM_COST: "counter",
    LLM_TOKENS: "counter",
    LLM_UNPRICED_CALLS: "counter",
    DIGEST_ARTICLES: "counter",
}

# Digest stage -> (stats section, key): how many articles each step had or dropped.
DIGEST_STAGES: dict[str, tuple[str, str]] = {
    "fresh": ("pool", "fresh"),
    "candidates": ("pool", "candidates"),
    "ranked": ("ranking", "ranked"),
    "top": ("ranking", "top"),
    "extracted": ("extraction", "embedded"),
    "cross_day_duplicates": ("deduplication", "cross_day_dropped"),
    "same_day_duplicates": ("deduplication", "same_day_dropped"),
    "kept": ("deduplication", "survivors"),
    "picked": ("selection", "picked"),
}


@dataclass(frozen=True)
class Point:
    """One value to add to an instrument."""

    name: str
    value: float
    attributes: dict[str, str]


def measurements(run: Run) -> list[Point]:
    """The data points of a finished run.

    Stats are free-form JSON written by many versions: anything missing or
    not a number is left out rather than guessed.
    """
    base = {"kind": run.kind.value, "dry_run": "true" if run.dry_run else "false"}
    status = {**base, "status": run.status.value}
    points = [Point(RUNS, 1, status)]
    if run.finished_at is not None:
        seconds = (run.finished_at - run.started_at).total_seconds()
        points.append(Point(DURATION, max(seconds, 0.0), status))
    for stage, milliseconds in _mapping(run.timings).items():
        if (value := _number(milliseconds)) is not None:
            points.append(Point(STAGE_DURATION, value / 1000, {**base, "stage": str(stage)}))
    points.extend(_usage_points(_mapping(run.stats.get("usage")), base))
    if run.kind is RunKind.DIGEST:
        points.extend(_article_points(run.stats, base))
    return points


def _usage_points(usage: Mapping[str, Any], base: dict[str, str]) -> Iterator[Point]:
    for purpose, totals in _mapping(usage.get("by_purpose")).items():
        if not isinstance(totals, Mapping):
            continue
        attributes = {**base, "purpose": str(purpose)}
        # Like the spending limits: the known part, or the total of older runs.
        cost = _number(totals.get("cost_usd_known"))
        if cost is None:
            cost = _number(totals.get("cost_usd"))
        if cost is not None:
            yield Point(LLM_COST, cost, attributes)
        for kind in ("input", "output"):
            if (tokens := _count(totals.get(f"{kind}_tokens"))) is not None:
                yield Point(LLM_TOKENS, tokens, {**attributes, "type": kind})
        if unpriced := _count(totals.get("unpriced_calls")):
            yield Point(LLM_UNPRICED_CALLS, unpriced, attributes)


def _article_points(stats: Mapping[str, Any], base: dict[str, str]) -> Iterator[Point]:
    for stage, (section, key) in DIGEST_STAGES.items():
        if (count := _count(_mapping(stats.get(section)).get(key))) is not None:
            yield Point(DIGEST_ARTICLES, count, {**base, "stage": stage})


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value >= 0 else None


def _count(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


class RunInstruments:
    """The instruments run metrics go to; the global meter provider's unless given."""

    def __init__(self, meter: metrics.Meter | None = None) -> None:
        meter = meter or metrics.get_meter("brzask.pipeline")
        self._counters = {
            RUNS: meter.create_counter(RUNS, unit="{run}", description="Finished runs."),
            LLM_COST: meter.create_counter(
                LLM_COST, unit="USD", description="Reported cost of LLM and embedding calls."
            ),
            LLM_TOKENS: meter.create_counter(
                LLM_TOKENS, unit="{token}", description="Tokens of LLM and embedding calls."
            ),
            LLM_UNPRICED_CALLS: meter.create_counter(
                LLM_UNPRICED_CALLS, unit="{call}", description="Calls without a reported cost."
            ),
            DIGEST_ARTICLES: meter.create_counter(
                DIGEST_ARTICLES, unit="{article}", description="Articles at each digest stage."
            ),
        }
        self._histograms = {
            name: meter.create_histogram(
                name,
                unit="s",
                description=description,
                explicit_bucket_boundaries_advisory=DURATION_BUCKETS,
            )
            for name, description in (
                (DURATION, "Duration of a run."),
                (STAGE_DURATION, "Duration of a stage of a run."),
            )
        }

    def record(self, run: Run) -> None:
        """Add the run's points; a failure is logged and never reaches the run."""
        try:
            for point in measurements(run):
                if point.name in self._histograms:
                    self._histograms[point.name].record(point.value, point.attributes)
                else:
                    self._counters[point.name].add(point.value, point.attributes)
        except Exception as error:
            log.warning("run metrics not recorded", run_id=str(run.id), error=str(error))
