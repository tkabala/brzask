import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from brzask.db.models import RunKind, SourceStatus
from brzask.repositories import RunRepository
from brzask.services.pause import pause
from brzask.services.status import get_status
from tests.factories import TEST_MODEL, Factories, unit_vector

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)


def test_empty_instance(session: Session) -> None:
    status = get_status(session, NOW, TEST_MODEL)

    assert status.embedding_model == TEST_MODEL
    assert status.embeddings == {}
    assert (status.articles.total, status.last_digest, status.paused_until) == (0, None, None)
    assert set(status.sources.values()) == {0}
    assert status.last_runs == dict.fromkeys(RunKind)


def test_counts_pause_and_last_runs(session: Session, make: Factories) -> None:
    source = make.source()
    make.source(status=SourceStatus.MUTED)
    make.article(source, digest_date=date(2026, 10, 17), opened_at=NOW)
    make.article(source, embedding=unit_vector(1))
    run = RunRepository(session).start(uuid.uuid4(), RunKind.DIGEST, NOW)
    pause(session, NOW + timedelta(days=2), NOW, actor="user")

    status = get_status(session, NOW, TEST_MODEL)

    assert (status.articles.total, status.articles.shown, status.articles.opened) == (2, 1, 1)
    assert status.embeddings == {TEST_MODEL: 1}
    assert status.sources[SourceStatus.ACTIVE] == 1
    assert status.sources[SourceStatus.MUTED] == 1
    assert status.sources[SourceStatus.DEAD] == 0
    assert status.last_digest == date(2026, 10, 17)
    assert status.paused_until == NOW + timedelta(days=2)
    assert status.last_runs[RunKind.DIGEST] is run
    assert status.last_runs[RunKind.REVIEW] is None
