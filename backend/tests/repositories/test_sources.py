from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from brzask.db.models import ArticleState, SourceKind, SourceOrigin, SourceStatus
from brzask.repositories import SourceRepository
from tests.factories import Factories

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)


def test_add_returns_the_new_source(session: Session) -> None:
    sources = SourceRepository(session)

    source = sources.add(
        name="Example",
        url="https://example.com/feed.xml",
        status=SourceStatus.PENDING,
        origin=SourceOrigin.DISCOVERY,
        kind=SourceKind.RELEASE,
        origin_detail="interest:Rust",
    )

    assert source is not None
    assert source.id is not None
    assert sources.get(source.id) is source
    assert sources.get_by_url("https://example.com/feed.xml") is source
    assert source.kind is SourceKind.RELEASE


def test_add_skips_a_known_url_even_when_rejected(session: Session, make: Factories) -> None:
    make.source(url="https://example.com/feed.xml", status=SourceStatus.REJECTED)

    again = SourceRepository(session).add(
        name="Other name",
        url="https://example.com/feed.xml",
        status=SourceStatus.PENDING,
        origin=SourceOrigin.VISITED,
    )

    assert again is None


def test_add_skips_a_name_taken_ignoring_case(session: Session, make: Factories) -> None:
    make.source("Hacker News")

    again = SourceRepository(session).add(
        name="hacker news",
        url="https://other.example/feed.xml",
        status=SourceStatus.PENDING,
        origin=SourceOrigin.VISITED,
    )

    assert again is None


def test_find_filters_by_status_and_sorts_by_name(session: Session, make: Factories) -> None:
    make.source("b")
    make.source("a")
    make.source("c", status=SourceStatus.MUTED)
    make.source("d", status=SourceStatus.PENDING)
    sources = SourceRepository(session)

    assert [s.name for s in sources.find()] == ["a", "b", "c", "d"]
    assert [s.name for s in sources.find(SourceStatus.ACTIVE)] == ["a", "b"]
    assert [s.name for s in sources.find(SourceStatus.MUTED, SourceStatus.PENDING)] == ["c", "d"]


def test_get_by_name_ignores_case(session: Session, make: Factories) -> None:
    source = make.source("Hacker News")
    sources = SourceRepository(session)

    assert sources.get_by_name("hacker news") is source
    assert sources.get_by_name("Lobsters") is None


def test_names_are_unique_ignoring_case(session: Session, make: Factories) -> None:
    make.source("Hacker News")

    with pytest.raises(IntegrityError, match="uq_sources_lower_name"):
        make.source("hacker news")


def test_count_by_status(session: Session, make: Factories) -> None:
    make.source()
    make.source()
    make.source(status=SourceStatus.PENDING)

    counts = SourceRepository(session).count_by_status()

    assert counts == {SourceStatus.ACTIVE: 2, SourceStatus.PENDING: 1}


def test_set_status_stores_the_reason(session: Session, make: Factories) -> None:
    source = make.source()

    SourceRepository(session).set_status(source, SourceStatus.MUTED, "30 articles, none opened")
    session.expire_all()

    assert source.status is SourceStatus.MUTED
    assert source.note == "30 articles, none opened"


def test_set_fetch_validators(session: Session, make: Factories) -> None:
    source = make.source()

    SourceRepository(session).set_fetch_validators(source, '"abc"', "Sat, 17 Oct 2026 06:00:00 GMT")
    session.expire_all()

    assert (source.etag, source.last_modified) == ('"abc"', "Sat, 17 Oct 2026 06:00:00 GMT")


def test_stats_count_by_source_id_within_the_window(session: Session, make: Factories) -> None:
    busy = make.source("Busy")
    renamed = make.source("Old name")
    quiet = make.source("Quiet")
    recent = NOW - timedelta(days=3)
    make.article(busy, first_seen_at=recent)
    make.article(busy, first_seen_at=recent, rank=4)
    make.article(busy, first_seen_at=recent, rank=1, digest_date=recent.date(), opened_at=NOW)
    make.article(busy, first_seen_at=NOW - timedelta(days=40), opened_at=NOW)  # outside
    make.article(renamed, first_seen_at=recent, opened_at=NOW)
    renamed.name = "New name"
    session.flush()

    stats = SourceRepository(session).stats(since=NOW - timedelta(days=30))

    assert stats[busy.id].articles == 3
    assert stats[busy.id].ranked == 2
    assert stats[busy.id].shown == 1
    assert stats[busy.id].opened == 1
    assert stats[renamed.id].articles == 1
    assert stats[renamed.id].opened == 1
    assert (stats[quiet.id].articles, stats[quiet.id].opened) == (0, 0)


def test_stats_ignore_articles_without_a_source(session: Session, make: Factories) -> None:
    make.article(None, first_seen_at=NOW, state=ArticleState.SEEN)

    assert SourceRepository(session).stats(since=NOW - timedelta(days=1)) == {}
