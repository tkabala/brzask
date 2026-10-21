from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from brzask.db.models import RunKind, RunStatus, SourceStatus
from brzask.repositories import (
    ArticleRepository,
    InterestRepository,
    RunRepository,
    SourceRepository,
)
from brzask.services.demo import demo_plan, seed_demo
from brzask.services.demo.__main__ import render
from brzask.services.demo.plan import CANDIDATES, DAYS, DIGEST_SIZE, PAUSED
from brzask.services.digests import explain_ranking
from brzask.services.errors import ServiceError
from tests.factories import Factories

TODAY = date(2026, 10, 21)
ZONE = ZoneInfo("Europe/Warsaw")


def test_a_month_of_digests_with_a_pause() -> None:
    plan = demo_plan(TODAY, ZONE)

    days = plan.digest_days()
    assert len(days) == DAYS - len(PAUSED)
    assert days[0] == TODAY
    assert TODAY - timedelta(days=min(PAUSED)) not in days
    assert len(plan.articles) == len(days) * CANDIDATES
    for day in days:
        shown = [a for a in plan.articles if a.digest_date == day]
        assert sorted(a.position or 0 for a in shown) == list(range(1, DIGEST_SIZE + 1))


def test_every_story_is_told_once() -> None:
    plan = demo_plan(TODAY, ZONE)

    assert len({a.title for a in plan.articles}) == len(plan.articles)
    assert len({a.link for a in plan.articles}) == len(plan.articles)
    assert all(".example/" in a.link for a in plan.articles)


def test_some_articles_are_opened_on_most_days() -> None:
    plan = demo_plan(TODAY, ZONE)

    opened = [a for a in plan.articles if a.opened_at]
    assert 0.2 < len(opened) / (len(plan.digest_days()) * DIGEST_SIZE) < 0.4
    assert all(a.shown_at and a.opened_at and a.opened_at > a.shown_at for a in opened)


def test_seeds_the_plan(session: Session) -> None:
    plan = seed_demo(session, TODAY, ZONE)

    articles = ArticleRepository(session)
    today = articles.digest(TODAY)
    assert [a.digest_position for a in today] == list(range(1, DIGEST_SIZE + 1))
    assert [a.title for a in today] == [a.title for a in plan.articles if a.digest_date == TODAY]
    assert sum(d.opened for d in articles.digest_days(40)) == sum(
        1 for a in plan.articles if a.opened_at
    )
    counts = SourceRepository(session).count_by_status()
    assert counts == {
        SourceStatus.ACTIVE: 11,
        SourceStatus.PENDING: 2,
        SourceStatus.MUTED: 1,
        SourceStatus.DEAD: 1,
        SourceStatus.REJECTED: 1,
    }
    failing = {
        s.name: s.fetch_failures for s in SourceRepository(session).find() if s.fetch_failures
    }
    assert failing == {"Slow Tech News": 3, "Old Dispatch": 25}
    assert [i.active for i in InterestRepository(session).find()].count(False) == 1
    runs = RunRepository(session)
    for kind in RunKind:
        latest = runs.latest(kind)
        assert latest is not None
        assert latest.status is RunStatus.OK
    explained = explain_ranking(session, today[0].id)
    assert (explained.ranking_method, explained.article.rank) == ("llm", 1)


def test_needs_an_empty_database(session: Session, make: Factories) -> None:
    make.source()

    with pytest.raises(ServiceError, match="empty database"):
        seed_demo(session, TODAY, ZONE)


def test_the_web_app_export_is_up_to_date() -> None:
    path = Path(__file__).parents[3] / "frontend/src/demo/instance.gen.json"

    assert path.read_text() == render(), "stale demo export: run `just demo-json`"
