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
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.usage import UsageMeter
from brzask.db.models import Run, RunKind, RunStatus
from brzask.log import logged_run
from brzask.repositories import RunRepository
from brzask.services.errors import ServiceError


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

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Record how long a stage takes, in milliseconds."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.timings[name] = round((time.perf_counter() - started) * 1000)


Pipeline = Callable[[RunContext], None]


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
    tied to a transaction and is released if the process dies.
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
                connection.scalar(select(func.pg_advisory_unlock(*key)))
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
) -> Run:
    """Run one pipeline and return its finished run row.

    `pipelines` defaults to `brzask.services.pipelines.PIPELINES`. A pipeline
    error is recorded on the run and raised again.
    """
    if pipelines is None:
        # Imported here: the pipelines themselves import this module.
        from brzask.services.pipelines import PIPELINES

        pipelines = PIPELINES
    pipeline = pipelines.get(kind)
    if pipeline is None:
        raise ServiceError(f"the {kind.value} pipeline is not available")

    run_id = uuid.uuid4()
    with logged_run(kind.value, str(run_id)), pipeline_lock(_bind(sessions), kind) as acquired:
        context = RunContext(
            run_id=run_id,
            kind=kind,
            started_at=datetime.now(UTC),
            sessions=sessions,
            dry_run=dry_run,
            force=force,
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
            raise
        except BaseException as error:
            # Ctrl-C or a worker shutdown: close the row so it does not stay 'running'.
            _finish(context, RunStatus.FAILED, error=f"interrupted ({type(error).__name__})")
            raise
        return _finish(context, RunStatus.OK)


def _bind(sessions: sessionmaker[Session]) -> Engine | Connection:
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
    return run


def _with_usage(context: RunContext) -> dict[str, Any]:
    """The pipeline's stats, plus token and cost totals when it called paid APIs."""
    if not context.usage.calls:
        return context.stats
    return {**context.stats, "usage": context.usage.summary()}
