"""Running a pipeline and recording the run.

Every run gets a row in `runs` before the pipeline starts, so a long or stuck
run is visible, and the row is completed with the outcome, stats (including
tokens and cost of LLM and embedding calls) and stage timings. The run ID is
the same as the `run_id` on every log line of the run.

Each pipeline holds a Postgres advisory lock while it runs, so the worker and
a command-line run never run the same pipeline at once: the second one is
recorded as skipped.
"""

import time
import uuid
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import cache
from typing import Any, Literal

from opentelemetry import trace
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.usage import UsageMeter
from brzask.config import get_settings
from brzask.db.models import Run, RunKind, RunStatus
from brzask.log import get_logger, logged_run
from brzask.repositories import RunRepository
from brzask.services.errors import NotFoundError, ServiceError
from brzask.services.notify import Notifier, message_after_run, notifier_from_settings
from brzask.services.run_metrics import RunInstruments
from brzask.telemetry import tracer

log = get_logger(__name__)


class SkipRunError(Exception):
    """Raised by a pipeline when there is nothing to do (paused, already done)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class RunContext:
    """What a pipeline gets: run options, a way to open transactions, and stats to fill."""

    run_id: uuid.UUID
    kind: RunKind
    started_at: datetime
    sessions: sessionmaker[Session]
    dry_run: bool = False  # compute everything, write nothing but the run row
    force: bool = False  # run even when paused or already done today
    stats: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, int] = field(default_factory=dict)
    usage: UsageMeter = field(default_factory=UsageMeter)  # pass to LLM and embedding calls
    instruments: RunInstruments | None = None  # where the finished run is measured

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Record how long a stage takes, in milliseconds."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.timings[name] = round((time.perf_counter() - started) * 1000)


Pipeline = Callable[[RunContext], None]


class _Default(Enum):
    FROM_SETTINGS = "from settings"


FROM_SETTINGS = _Default.FROM_SETTINGS


# First key of every pipeline lock, so brzask's locks never meet another
# application's on a shared database.
LOCK_NAMESPACE = zlib.crc32(b"brzask") - 2**31


def _lock_key(kind: RunKind) -> int:
    """A stable 32-bit key per pipeline (Postgres takes signed int4 pairs)."""
    return zlib.crc32(kind.value.encode()) - 2**31


@contextmanager
def pipeline_lock(bind: Engine | Connection, kind: RunKind) -> Iterator[bool]:
    """Hold the pipeline's advisory lock; yields False when another process holds it.

    The lock lives on a connection of its own in autocommit mode, so it is not
    tied to a transaction and is released if the process dies. When that
    connection breaks (the database restarted), the lock is already gone: the
    failed unlock is logged, and neither replaces the run's own outcome nor
    puts the connection back in the pool.
    """
    owned = isinstance(bind, Engine)
    connection = (
        bind.connect().execution_options(isolation_level="AUTOCOMMIT")
        if isinstance(bind, Engine)
        else bind  # a connection the caller keeps open, as in tests
    )
    key = (LOCK_NAMESPACE, _lock_key(kind))
    try:
        acquired = bool(connection.scalar(select(func.pg_try_advisory_lock(*key))))
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    connection.scalar(select(func.pg_advisory_unlock(*key)))
                except SQLAlchemyError as error:
                    if not owned:
                        raise
                    log.warning("pipeline lock not released", kind=kind.value, error=str(error))
                    connection.invalidate()
    finally:
        if owned:
            connection.close()


def run_pipeline(
    sessions: sessionmaker[Session],
    kind: RunKind,
    *,
    dry_run: bool = False,
    force: bool = False,
    pipelines: Mapping[RunKind, Pipeline] | None = None,
    instruments: RunInstruments | None = None,
    notifier: Notifier | Literal[_Default.FROM_SETTINGS] | None = FROM_SETTINGS,
) -> Run:
    """Run one pipeline and return its finished run row.

    `pipelines` defaults to `brzask.services.pipelines.PIPELINES`, and the
    run's metrics go to `instruments` (the global meter provider's unless
    given). The finished run is notified through `notifier` (NOTIFY_URLS
    unless given; None: off). A pipeline error is recorded on the run and
    raised again.
    """
    if pipelines is None:
        # Imported here: the pipelines themselves import this module.
        from brzask.services.pipelines import PIPELINES

        pipelines = PIPELINES
    if instruments is None:
        instruments = default_instruments()
    pipeline = pipelines.get(kind)
    if pipeline is None:
        raise ServiceError(f"the {kind.value} pipeline is not available")

    run_id = uuid.uuid4()
    lock = pipeline_lock(session_bind(sessions), kind)
    span = tracer.start_as_current_span(
        f"pipeline {kind.value}",
        attributes={
            "brzask.run_id": str(run_id),
            "brzask.run.kind": kind.value,
            "brzask.run.dry_run": dry_run,
        },
    )
    with logged_run(kind.value, str(run_id)), span, lock as acquired:
        context = RunContext(
            run_id=run_id,
            kind=kind,
            started_at=datetime.now(UTC),
            sessions=sessions,
            dry_run=dry_run,
            force=force,
            instruments=instruments,
        )
        with sessions.begin() as session:
            RunRepository(session).start(run_id, kind, context.started_at, dry_run=dry_run)
        if not acquired:
            context.stats["reason"] = f"another {kind.value} run is in progress"
            return _finish(context, RunStatus.SKIPPED)
        try:
            pipeline(context)
        except SkipRunError as skip:
            context.stats["reason"] = skip.reason
            return _finish(context, RunStatus.SKIPPED)
        except Exception as error:
            _finish(context, RunStatus.FAILED, error=f"{type(error).__name__}: {error}")
            _notify(context, notifier)
            raise
        except BaseException as error:
            # Ctrl-C or a worker shutdown: close the row so it does not stay 'running',
            # and send nothing on the way out.
            _finish(context, RunStatus.FAILED, error=f"interrupted ({type(error).__name__})")
            raise
        run = _finish(context, RunStatus.OK)
        _notify(context, notifier)
        return run


def session_bind(sessions: sessionmaker[Session]) -> Engine | Connection:
    """What `sessions` connect through, for a pipeline lock outside `run_pipeline`."""
    bind = sessions.kw.get("bind")
    if not isinstance(bind, Engine | Connection):
        raise RuntimeError("the session factory is not bound to a database")
    return bind


def _finish(context: RunContext, status: RunStatus, error: str | None = None) -> Run:
    with context.sessions.begin() as session:
        runs = RunRepository(session)
        run = runs.get(context.run_id)
        if run is None:
            raise RuntimeError(f"run {context.run_id} disappeared while running")
        runs.finish(
            run,
            status,
            datetime.now(UTC),
            stats=_with_usage(context),
            timings=dict(context.timings),
            error=error,
        )
    span = trace.get_current_span()
    span.set_attribute("brzask.run.status", status.value)
    if status is RunStatus.FAILED:
        # Also for an interruption, which the span itself does not count as an error.
        span.set_status(trace.StatusCode.ERROR, error)
    if context.instruments is not None:
        context.instruments.record(run)
    return run


def _notify(
    context: RunContext, notifier: Notifier | Literal[_Default.FROM_SETTINGS] | None
) -> None:
    """Send what the finished run calls for; never raises, never changes the run."""
    try:
        settings = get_settings()
        if notifier is FROM_SETTINGS:
            notifier = notifier_from_settings(settings.notifications)
        if notifier is None:
            return
        with context.sessions() as session:
            run = RunRepository(session).get(context.run_id)
            public_url = settings.server.public_url
            message = None if run is None else message_after_run(session, run, public_url)
        if message is not None:
            notifier.send(message)
    except Exception as error:
        # The type only: a settings error would quote the URLs, which carry tokens.
        log.warning("notification not sent", error=type(error).__name__)


@cache
def default_instruments() -> RunInstruments:
    """Instruments on the global meter provider, created once per process."""
    return RunInstruments()


def _with_usage(context: RunContext) -> dict[str, Any]:
    """The pipeline's stats, plus token and cost totals when it called paid APIs."""
    if not context.usage.calls:
        return context.stats
    return {**context.stats, "usage": context.usage.summary()}


def list_runs(
    session: Session,
    limit: int,
    *,
    kind: RunKind | None = None,
    after: tuple[datetime, uuid.UUID] | None = None,
) -> Sequence[Run]:
    """Runs newest first; `after` is the (started_at, id) of the last run already seen."""
    return RunRepository(session).page(limit, kind=kind, after=after)


def get_run(session: Session, run_id: uuid.UUID) -> Run:
    run = RunRepository(session).get(run_id)
    if run is None:
        raise NotFoundError(f"no run {run_id}")
    return run
