from datetime import date
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from brzask.db.models import RunKind, SourceStatus
from brzask.repositories import ArticleRepository, RunRepository, SourceRepository
from brzask.services.demo import DIGEST_DAYS, DIGEST_SIZE, seed_demo
from brzask.services.digests import explain_ranking
from brzask.services.errors import ServiceError
from tests.factories import Factories

TODAY = date(2026, 10, 21)
ZONE = ZoneInfo("Europe/Warsaw")


def test_seeds_a_believable_instance(session: Session) -> None:
    added = seed_demo(session, TODAY, ZONE)

    articles = ArticleRepository(session)
    assert added == len(DIGEST_DAYS) * DIGEST_SIZE
    today = articles.digest(TODAY)
    assert [a.digest_position for a in today] == list(range(1, DIGEST_SIZE + 1))
    assert all(a.opened_at is None for a in today)
    assert [d.opened for d in articles.digest_days(10)] == [0, 2, 2, 2]
    counts = SourceRepository(session).count_by_status()
    assert (counts[SourceStatus.ACTIVE], counts[SourceStatus.PENDING]) == (6, 2)
    failing = [s for s in SourceRepository(session).find() if s.fetch_failures]
    assert [(s.name, s.fetch_failures) for s in failing] == [("Slow Tech News", 3)]
    runs = RunRepository(session)
    assert runs.latest(RunKind.DIGEST) is not None
    assert runs.latest(RunKind.DISCOVERY) is not None
    explained = explain_ranking(session, today[0].id)
    assert (explained.pool, explained.ranking_method) == (200, "llm")


def test_needs_an_empty_database(session: Session, make: Factories) -> None:
    make.source()

    with pytest.raises(ServiceError, match="empty database"):
        seed_demo(session, TODAY, ZONE)
