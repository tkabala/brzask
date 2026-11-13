import threading
import uuid
from datetime import UTC, date, datetime

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from structlog.testing import capture_logs

from brzask.clients.usage import CallUsage
from brzask.db.models import RunKind, RunStatus
from brzask.db.session import create_db_engine, session_factory
from brzask.repositories import RunRepository
from brzask.services.errors import ServiceError
from brzask.services.notify import Message
from brzask.services.run_metrics import RunInstruments
from brzask.services.runs import (
    Pipeline,
    RunContext,
    SkipRunError,
    pipeline_lock,
    run_pipeline,
    sweep_abandoned,
)
from tests.factories import Factories


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


def test_interrupted_run_is_closed_and_raised(
    sessions: sessionmaker[Session], session: Session
) -> None:
    def interrupt(context: RunContext) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_pipeline(sessions, RunKind.DIGEST, pipelines={RunKind.DIGEST: interrupt})

    [run] = RunRepository(session).recent(5)
    assert (run.status, run.error) == (RunStatus.FAILED, "interrupted (KeyboardInterrupt)")
    assert run.finished_at is not None


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


def test_usage_of_paid_calls_is_added_to_the_stats(sessions: sessionmaker[Session]) -> None:
    def call_llm(context: RunContext) -> None:
        context.stats["selected"] = 7
        context.usage.add(CallUsage("m", "ranking", 1000, 200, 0.003, 4000))

    run = run_pipeline(sessions, RunKind.DIGEST, pipelines={RunKind.DIGEST: call_llm})

    assert run.stats["selected"] == 7
    assert run.stats["usage"]["calls"] == 1
    assert run.stats["usage"]["cost_usd"] == 0.003
    assert run.stats["usage"]["by_purpose"]["ranking"]["input_tokens"] == 1000


def test_runs_without_paid_calls_have_no_usage(sessions: sessionmaker[Session]) -> None:
    run = run_pipeline(sessions, RunKind.REVIEW, pipelines={RunKind.REVIEW: succeed})

    assert "usage" not in run.stats


def run_points(reader: InMemoryMetricReader, name: str) -> dict[str, float]:
    """The data points of one instrument by status."""
    data = reader.get_metrics_data()
    assert data is not None
    return {
        str((point.attributes or {})["status"]): point.value  # type: ignore[union-attr]
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    }


def test_finished_runs_are_measured(sessions: sessionmaker[Session]) -> None:
    reader = InMemoryMetricReader()
    instruments = RunInstruments(MeterProvider(metric_readers=[reader]).get_meter("test"))
    pipelines = {RunKind.DIGEST: succeed}

    run_pipeline(sessions, RunKind.DIGEST, pipelines=pipelines, instruments=instruments)
    run_pipeline(
        sessions, RunKind.DIGEST, pipelines={RunKind.DIGEST: skip}, instruments=instruments
    )
    with pytest.raises(RuntimeError):
        run_pipeline(
            sessions, RunKind.DIGEST, pipelines={RunKind.DIGEST: fail}, instruments=instruments
        )

    assert run_points(reader, "brzask.pipeline.runs") == {"ok": 1, "skipped": 1, "failed": 1}


class BrokenInstruments(RunInstruments):
    def __init__(self) -> None:
        super().__init__(MeterProvider().get_meter("test"))
        self._counters = {}  # every point now fails to find its counter


def test_a_failing_recorder_keeps_the_run(
    sessions: sessionmaker[Session], session: Session
) -> None:
    run = run_pipeline(
        sessions,
        RunKind.DIGEST,
        pipelines={RunKind.DIGEST: succeed},
        instruments=BrokenInstruments(),
    )

    stored = RunRepository(session).get(run.id)
    assert stored is not None and stored.status is RunStatus.OK


# --- Notifications -------------------------------------------------------------------


class FakeNotifier:
    """Records each message with the run's status in the database at sending time."""

    def __init__(self, sessions: sessionmaker[Session], error: Exception | None = None) -> None:
        self.sessions = sessions
        self.error = error
        self.sent: list[tuple[Message, RunStatus | None]] = []

    def send(self, message: Message) -> bool:
        with self.sessions() as session:
            [run] = RunRepository(session).recent(1)
            self.sent.append((message, run.status))
        if self.error is not None:
            raise self.error
        return True


def test_failed_run_notifies_and_still_raises(sessions: sessionmaker[Session]) -> None:
    notifier = FakeNotifier(sessions)

    with pytest.raises(RuntimeError, match="no sources"):
        run_pipeline(sessions, RunKind.REVIEW, pipelines={RunKind.REVIEW: fail}, notifier=notifier)

    [(message, status)] = notifier.sent
    assert message.title == "brzask: review run failed"
    assert message.body.startswith("RuntimeError: no sources\n")
    assert status is RunStatus.FAILED  # the row is final before anything is sent


def test_interrupted_run_does_not_notify(sessions: sessionmaker[Session]) -> None:
    notifier = FakeNotifier(sessions)

    def interrupt(context: RunContext) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_pipeline(
            sessions, RunKind.DIGEST, pipelines={RunKind.DIGEST: interrupt}, notifier=notifier
        )

    assert notifier.sent == []


def test_dry_and_skipped_runs_do_not_notify(sessions: sessionmaker[Session]) -> None:
    notifier = FakeNotifier(sessions)

    run_pipeline(sessions, RunKind.DIGEST, pipelines={RunKind.DIGEST: skip}, notifier=notifier)
    with pytest.raises(RuntimeError):
        run_pipeline(
            sessions,
            RunKind.REVIEW,
            dry_run=True,
            pipelines={RunKind.REVIEW: fail},
            notifier=notifier,
        )

    assert notifier.sent == []


def test_notifier_errors_never_change_the_run(sessions: sessionmaker[Session]) -> None:
    notifier = FakeNotifier(sessions, error=OSError("service down"))

    run = run_pipeline(
        sessions, RunKind.DIGEST, pipelines={RunKind.DIGEST: digest_of(1)}, notifier=notifier
    )
    assert run.status is RunStatus.OK
    with pytest.raises(RuntimeError, match="no sources"):
        run_pipeline(sessions, RunKind.REVIEW, pipelines={RunKind.REVIEW: fail}, notifier=notifier)

    assert len(notifier.sent) == 2


def test_bad_notify_setting_does_not_fail_the_run(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOTIFY_URLS", "nope://secret-x")

    with capture_logs() as logs:
        run = run_pipeline(sessions, RunKind.REVIEW, pipelines={RunKind.REVIEW: succeed})

    assert run.status is RunStatus.OK
    warnings = [line for line in logs if line["event"] == "notification not sent"]
    assert [line["error"] for line in warnings] == ["ValidationError"]
    assert "secret-x" not in str(logs)


def digest_of(count: int) -> Pipeline:
    """A digest pipeline that puts `count` articles into today's digest."""

    def pipeline(context: RunContext) -> None:
        day = date(2026, 11, 6)
        context.stats["date"] = day.isoformat()
        with context.sessions.begin() as session:
            for _ in range(count):
                Factories(session).article(
                    digest_date=day, link=f"https://news.example/{uuid.uuid4()}"
                )

    return pipeline


def test_digest_run_notifies_once_per_day(sessions: sessionmaker[Session]) -> None:
    notifier = FakeNotifier(sessions)
    pipelines = {RunKind.DIGEST: digest_of(2)}

    run_pipeline(sessions, RunKind.DIGEST, pipelines=pipelines, notifier=notifier)
    run_pipeline(
        sessions,
        RunKind.DIGEST,
        force=True,
        pipelines={RunKind.DIGEST: digest_of(0)},
        notifier=notifier,
    )

    [(message, _)] = notifier.sent
    assert message.title == "brzask: today's 2 are ready"


def test_run_pipeline_uses_the_given_run_id(sessions: sessionmaker[Session]) -> None:
    run_id = uuid.uuid4()

    run = run_pipeline(sessions, RunKind.REVIEW, pipelines={RunKind.REVIEW: succeed}, run_id=run_id)

    assert run.id == run_id


def test_started_is_set_once_the_row_exists(sessions: sessionmaker[Session]) -> None:
    started = threading.Event()
    seen: list[tuple[bool, RunStatus | None]] = []

    def look(context: RunContext) -> None:
        with context.sessions() as other:
            run = RunRepository(other).get(context.run_id)
            seen.append((started.is_set(), run.status if run else None))

    run_pipeline(sessions, RunKind.VISITED, pipelines={RunKind.VISITED: look}, started=started)

    assert seen == [(True, RunStatus.RUNNING)]


NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)


def running_row(session: Session, kind: RunKind) -> uuid.UUID:
    run_id = uuid.uuid4()
    RunRepository(session).start(run_id, kind, datetime(2026, 11, 12, 7, tzinfo=UTC), dry_run=False)
    session.flush()
    return run_id


@pytest.mark.parametrize("kind", [RunKind.DIGEST, RunKind.REPLAY])
def test_sweep_fails_a_running_row_whose_lock_is_free(
    sessions: sessionmaker[Session], session: Session, kind: RunKind
) -> None:
    run_id = running_row(session, kind)
    session.commit()

    swept = sweep_abandoned(sessions, NOW)

    assert swept == [run_id]
    session.expire_all()
    run = RunRepository(session).get(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error == "abandoned (the process running it stopped)"
    assert run.finished_at == NOW


def test_sweep_keeps_a_running_row_whose_lock_is_held(
    sessions: sessionmaker[Session], session: Session, db_engine: Engine
) -> None:
    run_id = running_row(session, RunKind.DIGEST)
    session.commit()

    with pipeline_lock(db_engine, RunKind.DIGEST) as acquired:
        assert acquired
        swept = sweep_abandoned(sessions, NOW)

    assert swept == []
    session.expire_all()
    run = RunRepository(session).get(run_id)
    assert run is not None
    assert run.status is RunStatus.RUNNING


def test_sweep_ignores_finished_runs(sessions: sessionmaker[Session], session: Session) -> None:
    run_pipeline(sessions, RunKind.REVIEW, pipelines={RunKind.REVIEW: succeed})

    assert sweep_abandoned(sessions, NOW) == []


def test_sweep_survives_an_unreachable_database() -> None:
    engine = create_db_engine("postgresql+psycopg://brzask:x@127.0.0.1:1/brzask")
    try:
        with capture_logs() as logs:
            assert sweep_abandoned(session_factory(engine), NOW) == []
    finally:
        engine.dispose()

    assert any(log["event"] == "abandoned runs not checked" for log in logs)
