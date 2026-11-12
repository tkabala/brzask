from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from brzask.services.errors import ServiceError
from brzask.services.open_stats import OpenCount, open_stats
from tests.factories import Factories

TODAY = date(2026, 11, 12)
OPENED = datetime(2026, 11, 12, 9, tzinfo=UTC)


def test_counts_shown_and_opened_by_source_and_topic(session: Session, make: Factories) -> None:
    blog, news = make.source("Blog"), make.source("News")
    make.article(blog, digest_date=TODAY, topic="AI", opened_at=OPENED)
    make.article(blog, digest_date=date(2026, 11, 11), topic="AI")
    make.article(news, digest_date=date(2026, 11, 10), topic="Rust", opened_at=OPENED)
    make.article(news, digest_date=date(2026, 11, 10))
    make.article(news, digest_date=date(2026, 11, 5), topic="AI", opened_at=OPENED)  # too old
    make.article(news)  # never shown

    stats = open_stats(session, TODAY, days=3)

    assert (stats.days, stats.since, stats.shown, stats.opened) == (3, date(2026, 11, 10), 4, 2)
    assert stats.by_source == [OpenCount("Blog", 2, 1), OpenCount("News", 2, 1)]
    assert stats.by_topic == [
        OpenCount("AI", 2, 1),
        OpenCount("(none)", 1, 0),
        OpenCount("Rust", 1, 1),
    ]


def test_nothing_shown(session: Session) -> None:
    stats = open_stats(session, TODAY, days=7)

    assert (stats.shown, stats.opened, stats.by_source, stats.by_topic) == (0, 0, [], [])


@pytest.mark.parametrize("days", [0, 91])
def test_window_is_bounded(session: Session, days: int) -> None:
    with pytest.raises(ServiceError, match="between 1 and 90 days"):
        open_stats(session, TODAY, days=days)
