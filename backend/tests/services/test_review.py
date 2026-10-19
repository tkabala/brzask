from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask.db.models import ChangeStatus, Source, SourceStatus
from brzask.repositories import ChangeRepository, SourceRepository
from brzask.repositories.sources import SourceStats
from brzask.services.review import ACTOR, Decision, evaluate, review_sources
from brzask.services.sources import enable_source
from tests.factories import Factories
from tests.services.digest.fakes import context

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)
DAY = timedelta(days=1)


def source(age_days: int = 60, **health: Any) -> Source:
    return Source(
        name="Feed",
        url="https://feed.example/rss",
        status=SourceStatus.ACTIVE,
        created_at=NOW - age_days * DAY,
        fetch_error=health.pop("fetch_error", "HTTPStatusError: 404"),
        **health,
    )


def stats(articles: int, ranked: int = 0, opened: int = 0) -> SourceStats:
    return SourceStats(source_id=1, articles=articles, ranked=ranked, shown=0, opened=opened)


@pytest.mark.parametrize(
    ("name", "subject", "numbers", "expected"),
    [
        ("ranked sometimes", source(), stats(20, ranked=1), Decision.KEEP),
        ("opened once", source(), stats(20, opened=1), Decision.KEEP),
        ("too few to judge", source(), stats(9), Decision.KEEP),
        ("chatty and ignored", source(), stats(10), Decision.MUTE),
        ("young and ignored", source(age_days=20), stats(30), Decision.PROBATION),
        ("published nothing", source(), stats(0), Decision.QUIET),
        ("no stats row", source(), None, Decision.QUIET),
        (
            "permanent errors for two weeks",
            source(failing_since=NOW - 14 * DAY, permanent_failing_since=NOW - 14 * DAY),
            stats(0),
            Decision.DEAD,
        ),
        (
            "permanent errors for 13 days",
            source(failing_since=NOW - 13 * DAY, permanent_failing_since=NOW - 13 * DAY),
            stats(0),
            Decision.QUIET,
        ),
        (
            "permanent errors after temporary ones",
            source(failing_since=NOW - 20 * DAY, permanent_failing_since=NOW - 5 * DAY),
            stats(0),
            Decision.QUIET,
        ),
        (
            "rate limited for 29 days",
            source(failing_since=NOW - 29 * DAY, fetch_error="HTTPStatusError: 429"),
            stats(12, ranked=2),
            Decision.KEEP,
        ),
        (
            "any error for a month",
            source(failing_since=NOW - 30 * DAY, fetch_error="ReadTimeout: slow"),
            stats(0),
            Decision.DEAD,
        ),
        (
            "young and gone",
            source(
                age_days=15, failing_since=NOW - 14 * DAY, permanent_failing_since=NOW - 14 * DAY
            ),
            None,
            Decision.DEAD,
        ),
    ],
)
def test_evaluate(
    name: str, subject: Source, numbers: SourceStats | None, expected: Decision
) -> None:
    assert evaluate(subject, numbers, NOW).decision is expected, name


def test_notes_say_why() -> None:
    muted = evaluate(source(), stats(12), NOW)
    dead = evaluate(
        source(failing_since=NOW - 30 * DAY, fetch_error="HTTPStatusError: 410"), None, NOW
    )

    assert muted.note == (
        "muted by the review: 12 articles in 30 days, none in the top of the ranking, none opened"
    )
    assert dead.note == "marked dead by the review: failing since 2026-09-18 (HTTPStatusError: 410)"
    assert evaluate(source(), stats(20, ranked=1), NOW).note is None


def test_a_source_that_recovers_is_kept(session: Session, make: Factories) -> None:
    feed = make.source(created_at=NOW - 60 * DAY)
    sources = SourceRepository(session)
    sources.record_fetch(feed, NOW - 20 * DAY, error="HTTPStatusError: 404")
    sources.record_fetch(feed, NOW - DAY)
    make.article(feed, first_seen_at=NOW - DAY, rank=3)

    verdict = evaluate(feed, sources.stats(NOW - 30 * DAY)[feed.id], NOW)

    assert verdict.decision is Decision.KEEP


# --- The pipeline --------------------------------------------------------------------------


def old_source(make: Factories, **fields: Any) -> Source:
    return make.source(created_at=NOW - 60 * DAY, **fields)


def test_review_mutes_and_marks_dead_with_a_change_log_entry(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    chatty = old_source(make, name="Chatty")
    for _ in range(10):
        make.article(chatty, first_seen_at=NOW - 2 * DAY)
    gone = old_source(
        make,
        name="Gone",
        failing_since=NOW - 20 * DAY,
        permanent_failing_since=NOW - 20 * DAY,
        fetch_error="HTTPStatusError: 404",
    )
    good = old_source(make, name="Good")
    make.article(good, first_seen_at=NOW - DAY, opened_at=NOW)
    old_source(make, name="Muted already", status=SourceStatus.MUTED)
    run = context(sessions)

    review_sources(run)

    session.expire_all()
    assert (chatty.status, gone.status, good.status) == (
        SourceStatus.MUTED,
        SourceStatus.DEAD,
        SourceStatus.ACTIVE,
    )
    assert (chatty.note or "").startswith("muted by the review: 10 articles")
    changes = ChangeRepository(session).find(limit=10, entity_type="source", entity_id=str(gone.id))
    assert [(c.actor, c.action, c.status, c.after) for c in changes] == [
        (ACTOR, "source.dead", ChangeStatus.APPLIED, {"status": "dead"})
    ]
    assert run.stats["sources"] == 3
    assert run.stats["decisions"] == {
        "keep": 1,
        "probation": 0,
        "quiet": 0,
        "mute": 1,
        "dead": 1,
    }
    assert [entry["name"] for entry in run.stats["muted"]] == ["Chatty"]
    assert [entry["name"] for entry in run.stats["dead"]] == ["Gone"]


def test_a_dry_run_changes_nothing(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    quiet = old_source(make)
    gone = old_source(make, failing_since=NOW - 40 * DAY)
    run = context(sessions, dry_run=True)

    review_sources(run)

    session.expire_all()
    assert (quiet.status, gone.status) == (SourceStatus.ACTIVE, SourceStatus.ACTIVE)
    assert run.stats["decisions"]["dead"] == 1
    assert run.stats["quiet"] == [quiet.name]


def test_enabling_a_dead_source_gives_it_a_fresh_start(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    gone = old_source(
        make,
        failing_since=NOW - 40 * DAY,
        permanent_failing_since=NOW - 40 * DAY,
        fetch_failures=40,
        fetch_error="HTTPStatusError: 410",
    )
    review_sources(context(sessions))
    session.expire_all()
    assert gone.status is SourceStatus.DEAD

    assert enable_source(session, str(gone.id), actor="user")

    revived = session.get_one(Source, gone.id)
    assert revived.status is SourceStatus.ACTIVE
    assert (revived.failing_since, revived.permanent_failing_since) == (None, None)
    assert (revived.fetch_failures, revived.fetch_error) == (0, None)
    assert evaluate(revived, None, NOW).decision is Decision.QUIET
