import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from brzask.db.models import RunKind, RunStatus
from brzask.repositories import RunRepository

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)


def test_start_and_finish(session: Session) -> None:
    runs = RunRepository(session)
    run_id = uuid.uuid4()

    run = runs.start(run_id, RunKind.DIGEST, NOW, dry_run=True)
    assert run.status is RunStatus.RUNNING

    runs.finish(
        run,
        RunStatus.OK,
        NOW + timedelta(minutes=2),
        stats={"selected": 7},
        timings={"ranking": 12000},
    )
    session.expire_all()

    stored = runs.get(run_id)
    assert stored is not None
    assert stored.dry_run
    assert (stored.status, stored.stats, stored.timings) == (
        RunStatus.OK,
        {"selected": 7},
        {"ranking": 12000},
    )
    assert stored.finished_at == NOW + timedelta(minutes=2)


def test_finish_with_an_error(session: Session) -> None:
    runs = RunRepository(session)
    run = runs.start(uuid.uuid4(), RunKind.REVIEW, NOW)

    runs.finish(run, RunStatus.FAILED, NOW, error="RuntimeError: no sources")

    assert (run.status, run.error, run.stats) == (RunStatus.FAILED, "RuntimeError: no sources", {})


def test_recent_and_latest(session: Session) -> None:
    runs = RunRepository(session)
    old_digest = runs.start(uuid.uuid4(), RunKind.DIGEST, NOW - timedelta(days=1))
    review = runs.start(uuid.uuid4(), RunKind.REVIEW, NOW - timedelta(hours=1))
    digest = runs.start(uuid.uuid4(), RunKind.DIGEST, NOW)

    assert list(runs.recent(10)) == [digest, review, old_digest]
    assert list(runs.recent(10, RunKind.DIGEST)) == [digest, old_digest]
    assert runs.latest(RunKind.REVIEW) is review
    assert runs.latest(RunKind.DISCOVERY) is None
