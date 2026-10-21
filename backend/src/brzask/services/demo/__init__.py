"""A believable instance to try brzask on, and to run the end-to-end tests against.

Everything is invented and deterministic (see `content` and `plan`): a month
of digests with opened articles, sources in every state, interests and the
runs that built it all. `python -m brzask.services.demo` prints the same
instance as JSON for the web app's stories and tests.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from brzask.db.models import Article, Source
from brzask.repositories import (
    ArticleRepository,
    InterestRepository,
    RunRepository,
    SourceRepository,
)
from brzask.repositories.articles import DigestEntry, NewArticle
from brzask.services.demo.content import INTERESTS
from brzask.services.demo.plan import DIGEST_AT, DemoPlan, demo_plan
from brzask.services.errors import ServiceError

__all__ = ["DemoPlan", "demo_plan", "seed_demo"]


def seed_demo(session: Session, today: date, zone: ZoneInfo) -> DemoPlan:
    """Fill an empty database with the demo instance as of `today`."""
    if session.scalar(select(func.count()).select_from(Source)) or session.scalar(
        select(func.count()).select_from(Article)
    ):
        raise ServiceError("demo data goes into an empty database; this one has data")
    plan = demo_plan(today, zone)

    sources = SourceRepository(session)
    rows: dict[int, Source] = {}
    for planned in plan.sources:
        spec = planned.spec
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
        source.created_at = planned.created_at
        if planned.fetched_at is not None:
            sources.record_fetch(source, planned.fetched_at)
        for failed_at in planned.failures:
            sources.record_fetch(source, failed_at, error=spec.error, temporary=not spec.permanent)
        rows[planned.id] = source

    for interest in INTERESTS:
        InterestRepository(session).add(
            interest.topic,
            keywords=interest.keywords,
            notes=interest.notes,
            active=interest.active,
        )

    articles = ArticleRepository(session)
    ids = articles.add_new(
        [
            NewArticle(
                link=a.link,
                title=a.title,
                source_id=rows[a.source_id].id,
                snippet=a.summary,
                published_at=a.published_at,
            )
            for a in plan.articles
        ]
    )
    session.execute(
        update(Article),
        [{"id": ids[a.link], "first_seen_at": a.first_seen_at} for a in plan.articles],
    )
    articles.set_ranks({ids[a.link]: a.rank for a in plan.articles})
    for day in plan.digest_days():
        shown = [a for a in plan.articles if a.digest_date == day]
        entries = [
            DigestEntry(
                article_id=ids[a.link],
                position=a.position or 0,
                title=a.title,
                summary=a.summary,
                why_it_matters=a.why_it_matters,
                topic=a.topic,
            )
            for a in shown
        ]
        articles.mark_shown(day, entries, shown_at=datetime.combine(day, DIGEST_AT, tzinfo=zone))
        for a in shown:
            if a.opened_at is not None:
                articles.record_open(ids[a.link], a.opened_at)

    runs = RunRepository(session)
    for planned_run in plan.runs:
        run = runs.start(planned_run.id, planned_run.kind, planned_run.started_at)
        runs.finish(
            run,
            planned_run.status,
            planned_run.finished_at,
            stats=planned_run.stats,
            error=planned_run.error,
        )
    return plan
