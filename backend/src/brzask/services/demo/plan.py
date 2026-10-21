"""The demo month, worked out in memory: every row the demo instance gets.

Deterministic for a given day and time zone, so the database seeded by
`brzask seed-demo` and the data the web app's stories and tests use (the
export in `__main__`) are the same instance.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from brzask.db.models import RunKind, RunStatus, SourceStatus
from brzask.services.demo.content import RELEASES, SOURCES, TOPICS, DemoSource

DAYS = 30
# Days before today without a digest: a paused weekend.
PAUSED = frozenset({12, 13})
DIGEST_SIZE = 7
CANDIDATES = 10  # stored each day; the rest were dropped as duplicates
DIGEST_AT = time(7, 0)
# Walks a topic's subject and event pairs in a scattered order; coprime to their count.
STRIDE = 17
# Mondays: the schedule's defaults for the weekly pipelines.
WEEKLY = (
    (RunKind.REVIEW, time(7, 30)),
    (RunKind.VISITED, time(7, 45)),
    (RunKind.DISCOVERY, time(8, 0)),
)


@dataclass(frozen=True, slots=True)
class PlannedSource:
    id: int
    spec: DemoSource
    created_at: datetime
    fetched_at: datetime | None
    failures: tuple[datetime, ...] = ()  # failed fetches, oldest first


@dataclass(frozen=True, slots=True)
class PlannedArticle:
    id: int
    source_id: int
    link: str
    title: str
    summary: str
    why_it_matters: str
    topic: str
    published_at: datetime
    first_seen_at: datetime
    rank: int
    digest_date: date | None = None
    position: int | None = None
    shown_at: datetime | None = None
    opened_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PlannedRun:
    id: uuid.UUID
    kind: RunKind
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    stats: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DemoPlan:
    today: date
    sources: tuple[PlannedSource, ...]
    articles: tuple[PlannedArticle, ...]
    runs: tuple[PlannedRun, ...]

    def digest_days(self) -> list[date]:
        return sorted({a.digest_date for a in self.articles if a.digest_date}, reverse=True)


def demo_plan(today: date, zone: ZoneInfo) -> DemoPlan:
    """The demo instance as it looks on `today`, with times in `zone`."""

    def at(day: date, moment: time = DIGEST_AT) -> datetime:
        return datetime.combine(day, moment, tzinfo=zone)

    sources = tuple(_source(n, spec, at(today)) for n, spec in enumerate(SOURCES, start=1))
    source_ids = {spec.name: n for n, spec in enumerate(SOURCES, start=1)}
    by_topic: dict[str, list[int]] = {}
    for n, spec in enumerate(SOURCES, start=1):
        if spec.topic:
            by_topic.setdefault(spec.topic, []).append(n)

    articles: list[PlannedArticle] = []
    runs: list[PlannedRun] = []
    told = dict.fromkeys((topic.name for topic in TOPICS), 0)
    for days_ago in range(DAYS - 1, -1, -1):
        day = today - timedelta(days=days_ago)
        if day.weekday() == 0:
            runs.extend(_weekly_runs(day, days_ago, zone))
        if days_ago in PAUSED:
            continue
        start = at(day)
        for k in range(CANDIDATES):
            topic = TOPICS[(days_ago + k) % len(TOPICS)]
            count = told[topic.name]
            told[topic.name] += 1
            pair = count * STRIDE % (len(topic.subjects) * len(topic.events))
            subject = topic.subjects[pair % len(topic.subjects)]
            title, summary = topic.events[pair // len(topic.subjects)]
            title = title.format(s=subject)
            title = title[0].upper() + title[1:]
            source_id = (
                source_ids[RELEASES]
                if len(articles) % 5 == 4
                else by_topic[topic.name][(count + days_ago) % len(by_topic[topic.name])]
            )
            position = k + 1 if k < DIGEST_SIZE else None
            # Today one article is opened; earlier days 0 to 4, about two on average.
            opened = position is not None and (
                position == 3
                if days_ago == 0
                else (days_ago * 5 + position * 3) % 7 < days_ago * 3 % 5
            )
            host = SOURCES[source_id - 1].host
            articles.append(
                PlannedArticle(
                    id=len(articles) + 1,
                    source_id=source_id,
                    link=f"https://{host}/{day.isoformat()}/{_slug(title)}",
                    title=title,
                    summary=summary,
                    why_it_matters=topic.why[count % len(topic.why)],
                    topic=topic.name,
                    published_at=start - timedelta(minutes=90 + 41 * k),
                    first_seen_at=start - timedelta(minutes=50 - k),
                    # Shown articles took the odd places of the ranking; the
                    # even ones were dropped as duplicates.
                    rank=2 * k + 1 if position else 2 * (k - DIGEST_SIZE + 1),
                    digest_date=day if position else None,
                    position=position,
                    shown_at=start if position else None,
                    opened_at=start + timedelta(minutes=40 + 13 * (position or 0) + days_ago)
                    if opened
                    else None,
                )
            )
        runs.append(
            PlannedRun(
                id=_run_id(RunKind.DIGEST, day),
                kind=RunKind.DIGEST,
                status=RunStatus.OK,
                started_at=start,
                finished_at=start + timedelta(minutes=3, seconds=days_ago * 7 % 50),
                stats={
                    "pool": {"candidates": 180 + days_ago * 7 % 40},
                    "ranking": {"method": "llm", "ranked": 40, "top": 15},
                    "deduplication": {"same_day_method": "judge", "survivors": 12},
                    "usage": {"cost_usd": round(0.06 + days_ago % 5 * 0.007, 4)},
                },
            )
        )
    return DemoPlan(today, sources, tuple(articles), tuple(runs))


def _source(source_id: int, spec: DemoSource, today: datetime) -> PlannedSource:
    fetched = today - timedelta(minutes=50)
    match spec.status:
        case SourceStatus.PENDING:
            return PlannedSource(source_id, spec, today - timedelta(days=2), None)
        case SourceStatus.REJECTED:
            return PlannedSource(source_id, spec, today - timedelta(days=20), None)
        case SourceStatus.MUTED:
            return PlannedSource(
                source_id, spec, today - timedelta(days=120), fetched - timedelta(days=9)
            )
    created = today - timedelta(days=120)
    if spec.error is None:
        return PlannedSource(source_id, spec, created, fetched)
    # Failing: temporarily for the last three days, or for good since the feed went.
    failing_days = range(24, -1, -1) if spec.permanent else range(2, -1, -1)
    last_success = fetched - timedelta(days=len(failing_days))
    failures = tuple(fetched - timedelta(days=d) for d in failing_days)
    return PlannedSource(source_id, spec, created, last_success, failures)


def _weekly_runs(day: date, days_ago: int, zone: ZoneInfo) -> list[PlannedRun]:
    runs = []
    for kind, moment in WEEKLY:
        started = datetime.combine(day, moment, tzinfo=zone)
        # One visited run three weeks back hit a rate limit.
        failed = kind is RunKind.VISITED and 14 < days_ago < 22
        runs.append(
            PlannedRun(
                id=_run_id(kind, day),
                kind=kind,
                status=RunStatus.FAILED if failed else RunStatus.OK,
                started_at=started,
                finished_at=started + timedelta(seconds=2 if failed else 40),
                error="aggregator answered HTTP 429 Too Many Requests" if failed else None,
            )
        )
    return runs


def _run_id(kind: RunKind, day: date) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"https://demo.example/runs/{kind.value}/{day}")


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
