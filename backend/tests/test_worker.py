import os
import signal
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from datetime import time as clock
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from brzask.config.settings import Schedule, SchedulerSettings
from brzask.db.migrations import migrate
from brzask.db.models import Run, RunKind, RunStatus
from brzask.db.session import create_db_engine, session_factory
from brzask.services.runs import RunContext, run_pipeline
from brzask.worker import Job, build_scheduler, jobs, run_job, serve, trigger

WARSAW = ZoneInfo("Europe/Warsaw")


def settings(**schedules: str) -> SchedulerSettings:
    return SchedulerSettings.model_validate({**schedules, "TZ": "Europe/Warsaw"})


# --- Jobs from the schedule settings -------------------------------------------------------


def test_default_schedule_has_one_job_per_pipeline() -> None:
    found = jobs(SchedulerSettings())

    assert [(job.name, str(job.schedule)) for job in found] == [
        ("digest", "07:00"),
        ("review", "mon 07:30"),
        ("visited", "mon 07:45"),
        ("discovery", "mon 08:00"),
    ]


def test_pipelines_at_the_same_time_run_in_order_review_before_discovery() -> None:
    found = jobs(
        settings(
            digest_at="06:00",
            discovery_at="sun 05:00",
            review_at="sun 05:00",
            visited_at="off",
        )
    )

    assert found == [
        Job(Schedule(clock(6, 0)), (RunKind.DIGEST,)),
        Job(Schedule(clock(5, 0), weekday=6), (RunKind.REVIEW, RunKind.DISCOVERY)),
    ]
    assert found[1].name == "review+discovery"


def test_triggers_fire_at_the_local_time() -> None:
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)  # a Monday, 14:00 in Warsaw

    daily = trigger(Schedule(clock(7, 0)), WARSAW).get_next_fire_time(None, now)
    weekly = trigger(Schedule(clock(7, 30), weekday=0), WARSAW).get_next_fire_time(None, now)

    assert daily == datetime(2026, 10, 20, 7, 0, tzinfo=WARSAW)
    assert weekly == datetime(2026, 10, 26, 7, 30, tzinfo=WARSAW)


def test_a_failed_pipeline_does_not_stop_the_next_one() -> None:
    ran: list[RunKind] = []

    def run(kind: RunKind) -> None:
        ran.append(kind)
        if kind is RunKind.REVIEW:
            raise RuntimeError("boom")

    run_job((RunKind.REVIEW, RunKind.DISCOVERY), run)

    assert ran == [RunKind.REVIEW, RunKind.DISCOVERY]


def test_build_scheduler_adds_a_job_per_schedule() -> None:
    scheduler = build_scheduler(settings(visited_at="off"), lambda kind: None)

    assert [job.id for job in scheduler.get_jobs()] == ["digest", "review", "discovery"]


# --- Shutting down ---------------------------------------------------------------------------


def test_a_signal_stops_the_worker_after_the_running_job() -> None:
    started, finished = threading.Event(), threading.Event()

    def long_job() -> None:
        started.set()
        time.sleep(0.5)
        finished.set()

    scheduler = BackgroundScheduler()
    # Recurring, like the real jobs, and due at once.
    scheduler.add_job(long_job, "interval", hours=1, next_run_time=datetime.now(UTC))

    def send_sigterm() -> None:
        started.wait(5)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=send_sigterm, daemon=True).start()
    before = signal.getsignal(signal.SIGTERM)

    serve(scheduler)

    assert finished.is_set()
    assert signal.getsignal(signal.SIGTERM) is before


# --- One run at a time -------------------------------------------------------------------------


@pytest.fixture
def own_database(empty_database_url: str) -> Iterator[Engine]:
    """A database of its own: the lock test needs separate, committing connections."""
    migrate(empty_database_url)
    engine = create_db_engine(empty_database_url)
    yield engine
    engine.dispose()


def test_two_concurrent_runs_of_a_pipeline_run_it_once(own_database: Engine) -> None:
    sessions: sessionmaker[Session] = session_factory(own_database)
    entered, release = threading.Event(), threading.Event()
    calls: list[RunKind] = []

    def slow(context: RunContext) -> None:
        calls.append(context.kind)
        entered.set()
        release.wait(5)

    pipelines = {RunKind.DIGEST: slow, RunKind.REVIEW: slow}
    first: list[Run] = []
    thread = threading.Thread(
        target=lambda: first.append(run_pipeline(sessions, RunKind.DIGEST, pipelines=pipelines))
    )
    thread.start()
    assert entered.wait(5)

    second = run_pipeline(sessions, RunKind.DIGEST, pipelines=pipelines)
    # Another pipeline is not blocked by the digest's lock.
    entered.clear()
    other = threading.Thread(
        target=lambda: run_pipeline(sessions, RunKind.REVIEW, pipelines=pipelines)
    )
    other.start()
    assert entered.wait(5)
    release.set()
    thread.join(5)
    other.join(5)

    assert second.status is RunStatus.SKIPPED
    assert second.stats["reason"] == "another digest run is in progress"
    assert calls == [RunKind.DIGEST, RunKind.REVIEW]
    assert first[0].status is RunStatus.OK

    # Once the first run is over, the lock is free again.
    third = run_pipeline(sessions, RunKind.DIGEST, pipelines=pipelines)
    assert third.status is RunStatus.OK
