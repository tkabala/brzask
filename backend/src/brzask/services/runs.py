"""Running a pipeline and recording the run.

Every run gets a row in `runs` before the pipeline starts, so a long or stuck
run is visible, and the row is completed with the outcome, stats (including
tokens and cost of LLM and embedding calls) and stage timings. The run ID is
the same as the `run_id` on every log line of the run.
"""

import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

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
    with logged_run(kind.value, str(run_id)):
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
