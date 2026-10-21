"""A small, believable instance to try brzask on, and to run the end-to-end tests against.

Everything is made up and deterministic: sources on `.example` hosts, a
digest for today and a few earlier days, opened articles, pending and failing
sources, interests and the runs that built it all.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brzask.db.models import Article, RunKind, RunStatus, Source, SourceOrigin, SourceStatus
from brzask.repositories import (
    ArticleRepository,
    InterestRepository,
    RunRepository,
    SourceRepository,
)
from brzask.repositories.articles import DigestEntry, NewArticle
from brzask.services.errors import ServiceError

# Days before today that also have a digest; the gap (3) is a paused weekend.
DIGEST_DAYS = (0, 1, 2, 4)
DIGEST_SIZE = 7
DIGEST_AT = time(7, 0)


@dataclass(frozen=True, slots=True)
class DemoSource:
    name: str
    host: str
    status: SourceStatus = SourceStatus.ACTIVE
    origin: SourceOrigin = SourceOrigin.MANUAL
    origin_detail: str | None = None
    note: str | None = None
    error: str | None = None  # failing with this error


SOURCES = (
    DemoSource("Postgres Weekly", "postgres-weekly.example"),
    DemoSource("Kernel Notes", "kernel-notes.example"),
    DemoSource("Agent Engineering", "agents.example"),
    DemoSource("Homelab Diaries", "homelab.example"),
    DemoSource("Release Radar", "releases.example"),
    DemoSource("Slow Tech News", "slow-tech.example", error="HTTP 503 Service Unavailable"),
    DemoSource(
        "Query Planner Blog",
        "planner-blog.example",
        status=SourceStatus.PENDING,
        origin=SourceOrigin.DISCOVERY,
        origin_detail="searxng",
        note="discovery judge: interest fit 2.6/3, substance 1.7/2",
    ),
    DemoSource(
        "Small Models Weekly",
        "small-models.example",
        status=SourceStatus.PENDING,
        origin=SourceOrigin.VISITED,
        note='You opened "Distilling a 4B planner" through Hacker News.',
    ),
    DemoSource("Webinar Wire", "webinars.example", status=SourceStatus.MUTED, note="never opened"),
)

INTERESTS = (
    ("Postgres", ("PostgreSQL", "pgvector"), "want: releases, planner work; skip: vendor webinars"),
    ("AI agents", ("agent", "MCP"), "want: real deployments; skip: funding news"),
    ("Homelab", ("self-hosting",), ""),
)

# (topic, source index, title, summary)
STORIES = (
    (
        "Postgres",
        0,
        "PostgreSQL 19 beta makes asynchronous reads the default",
        "The first beta turns on asynchronous I/O for every sequential scan.",
    ),
    (
        "AI agents",
        2,
        "An agent that files its own regression tests",
        "A team let its coding agent add a failing test before every fix.",
    ),
    (
        "Postgres",
        0,
        "Skip scans arrive for multicolumn B-tree indexes",
        "Queries that filter on a later column can now use the index.",
    ),
    (
        "Homelab",
        3,
        "Running a whole home lab on one mini PC",
        "Twelve services, one box, and the power bill to prove it.",
    ),
    (
        "AI agents",
        1,
        "Kernel maintainers merge an agent-drafted patch series",
        "Reviewers kept the series after three rounds of human changes.",
    ),
    (
        "Postgres",
        4,
        "pgvector 0.9 adds iterative index scans",
        "Filtered nearest-neighbour queries no longer return too few rows.",
    ),
    (
        "Homelab",
        3,
        "Backups that restore: a quarterly drill",
        "Restoring from scratch found two services nobody had backed up.",
    ),
)


def _day_start(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, DIGEST_AT, tzinfo=zone)


def seed_demo(session: Session, today: date, zone: ZoneInfo) -> int:
    """Fill an empty database with the demo instance; returns the articles added."""
    if session.scalar(select(func.count()).select_from(Source)) or session.scalar(
        select(func.count()).select_from(Article)
    ):
        raise ServiceError("demo data goes into an empty database; this one has data")

    sources = SourceRepository(session)
    rows: list[Source] = []
    for spec in SOURCES:
        source = sources.add(
            name=spec.name,
            url=f"https://{spec.host}/feed.xml",
            site_url=f"https://{spec.host}/",
            status=spec.status,
            origin=spec.origin,
            origin_detail=spec.origin_detail,
            note=spec.note,
        )
        if source is None:  # cannot happen in an empty database
            raise ServiceError(f"could not add {spec.name}")
        fetched = _day_start(today, zone)
        if spec.status is SourceStatus.ACTIVE:
            if spec.error is None:
                sources.record_fetch(source, fetched)
            else:
                for days_ago in (2, 1, 0):
                    sources.record_fetch(
                        source, fetched - timedelta(days=days_ago), error=spec.error, temporary=True
                    )
        rows.append(source)

    interests = InterestRepository(session)
    for topic, keywords, notes in INTERESTS:
        interests.add(topic, keywords=keywords, notes=notes)

    articles = ArticleRepository(session)
    runs = RunRepository(session)
    added = 0
    for days_ago in DIGEST_DAYS:
        day = today - timedelta(days=days_ago)
        started = _day_start(day, zone)
        new = [
            NewArticle(
                link=f"https://{SOURCES[source].host}/{day.isoformat()}/{n}",
                title=title,
                source_id=rows[source].id,
                snippet=summary,
                published_at=started - timedelta(hours=3),
            )
            for n, (_, source, title, summary) in enumerate(STORIES, start=1)
        ]
        ids = articles.add_new(new)
        entries = [
            DigestEntry(
                article_id=ids[article.link],
                position=position,
                title=article.title,
                summary=summary,
                why_it_matters=f"Matches your interest in {topic}.",
                topic=topic,
            )
            for position, (article, (topic, _, _, summary)) in enumerate(
                zip(new, STORIES, strict=True), start=1
            )
        ]
        articles.set_ranks({entry.article_id: entry.position * 2 for entry in entries})
        articles.mark_shown(day, entries, shown_at=started)
        if days_ago:
            # Earlier days have a couple of articles opened.
            for entry in entries[:2]:
                articles.record_open(entry.article_id, started + timedelta(hours=1))
        run = runs.start(uuid.uuid4(), RunKind.DIGEST, started)
        runs.finish(
            run,
            RunStatus.OK,
            started + timedelta(minutes=3, seconds=12),
            stats={
                "pool": {"candidates": 200},
                "ranking": {"method": "llm", "ranked": 40, "top": 15},
                "deduplication": {"same_day_method": "judge", "survivors": 12},
                "usage": {"cost_usd": 0.08},
            },
        )
        added += len(new)

    monday = today - timedelta(days=today.weekday())
    for kind, minutes in ((RunKind.REVIEW, 30), (RunKind.DISCOVERY, 60)):
        started = _day_start(monday, zone) + timedelta(minutes=minutes)
        run = runs.start(uuid.uuid4(), kind, started)
        runs.finish(run, RunStatus.OK, started + timedelta(seconds=40), stats={})
    return added
