import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask.db.models import RunKind, RunStatus
from brzask.repositories import RunRepository
from brzask.services.errors import ServiceError
from brzask.services.runs import RunContext, SkipRunError, run_pipeline


def succeed(context: RunContext) -> None:
    with context.stage("fetch"):
        context.stats["fetched"] = 3
    context.stats["flags"] = {"dry_run": context.dry_run, "force": context.force}


def skip(context: RunContext) -> None:
    raise SkipRunError("paused")


def fail(context: RunContext) -> None:
    context.stats["fetched"] = 1
    raise RuntimeError("no sources")


def test_successful_run_is_recorded(sessions: sessionmaker[Session], session: Session) -> None:
    run = run_pipeline(
        sessions, RunKind.DIGEST, dry_run=True, force=True, pipelines={RunKind.DIGEST: succeed}
    )

    stored = RunRepository(session).get(run.id)
    assert stored is not None
    assert (stored.kind, stored.status, stored.dry_run) == (RunKind.DIGEST, RunStatus.OK, True)
    assert stored.stats == {"fetched": 3, "flags": {"dry_run": True, "force": True}}
    assert set(stored.timings) == {"fetch"}
    assert stored.finished_at is not None


def test_skipped_run_keeps_the_reason(sessions: sessionmaker[Session]) -> None:
    run = run_pipeline(sessions, RunKind.DIGEST, pipelines={RunKind.DIGEST: skip})

    assert (run.status, run.stats) == (RunStatus.SKIPPED, {"reason": "paused"})


def test_failed_run_is_recorded_and_raised(
    sessions: sessionmaker[Session], session: Session
) -> None:
    with pytest.raises(RuntimeError, match="no sources"):
        run_pipeline(sessions, RunKind.REVIEW, pipelines={RunKind.REVIEW: fail})

    [run] = RunRepository(session).recent(5)
    assert (run.status, run.error, run.stats) == (
        RunStatus.FAILED,
        "RuntimeError: no sources",
        {"fetched": 1},
    )


def test_a_run_is_visible_while_in_progress(
    sessions: sessionmaker[Session], session: Session
) -> None:
    seen: list[RunStatus] = []

    def look(context: RunContext) -> None:
        with context.sessions() as other:
            run = RunRepository(other).get(context.run_id)
            assert run is not None
            seen.append(run.status)

    run_pipeline(sessions, RunKind.VISITED, pipelines={RunKind.VISITED: look})

    assert seen == [RunStatus.RUNNING]


def test_unknown_pipeline(sessions: sessionmaker[Session], session: Session) -> None:
    with pytest.raises(ServiceError, match="discovery pipeline is not available"):
        run_pipeline(sessions, RunKind.DISCOVERY, pipelines={})

    assert RunRepository(session).recent(5) == []
