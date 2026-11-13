"""Pipeline runs started by an agent, in the API process.

A run takes minutes, longer than a tool call should, so it runs in a thread
and the agent follows it with `get_run`. It is the same `run_pipeline` as
the worker's and the CLI's, advisory lock included: a second run of the
same pipeline is recorded as skipped. The threads are daemons, so a run
never keeps a stopping API alive; its row is then closed by the next start
of the API or the worker (`sweep_abandoned`).
"""

import contextvars
import threading
import time
import uuid
from collections.abc import Callable, Mapping

from sqlalchemy.orm import Session, sessionmaker

from brzask.db.models import RunKind
from brzask.log import get_logger
from brzask.services.runs import Pipeline, run_pipeline

log = get_logger(__name__)

MAX_RUNS = 2  # at once; more wait their turn
STARTED_WAIT = 5.0  # seconds for the run's row to appear before start returns


class BackgroundRuns:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        pipelines: Mapping[RunKind, Pipeline] | None = None,
        max_workers: int = MAX_RUNS,
    ) -> None:
        self.sessions = sessions
        self.pipelines = pipelines
        self._slots = threading.BoundedSemaphore(max_workers)
        self._threads: set[threading.Thread] = set()
        self._lock = threading.Lock()
        self._closed = threading.Event()
        # Agent runs accepted whose row is not written yet (waiting for a slot).
        self._waiting = 0

    def waiting_agent_runs(self) -> int:
        """Runs agents started that wait for a slot and have no row yet."""
        with self._lock:
            return self._waiting

    def _row_written(self) -> None:
        with self._lock:
            self._waiting -= 1

    def start(
        self,
        kind: RunKind,
        *,
        dry_run: bool,
        force: bool,
        pipeline: Pipeline | None = None,
        started_by: str | None = None,
    ) -> uuid.UUID:
        """Start a run and return its ID once its row exists (or after a few seconds).

        `pipeline` runs instead of the one of that kind, e.g. a replay built
        for the agent's arguments.
        """
        pipelines = {kind: pipeline} if pipeline is not None else self.pipelines
        run_id = uuid.uuid4()
        started: threading.Event = threading.Event()
        if started_by is not None:
            with self._lock:
                self._waiting += 1
            started = _Started(self._row_written)
        # The caller's context (trace, log fields) goes with the run.
        context = contextvars.copy_context()
        thread = threading.Thread(
            target=context.run,
            args=(self._run, kind, run_id, started, dry_run, force, pipelines, started_by),
            name=f"agent-run-{kind.value}",
            daemon=True,
        )
        with self._lock:
            self._threads.add(thread)
        thread.start()
        started.wait(STARTED_WAIT)
        return run_id

    def close(self, grace: float = 5.0) -> None:
        """Start nothing new; give running runs `grace` seconds, then leave them."""
        self._closed.set()
        deadline = time.monotonic() + grace
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))

    def _run(
        self,
        kind: RunKind,
        run_id: uuid.UUID,
        started: threading.Event,
        dry_run: bool,
        force: bool,
        pipelines: Mapping[RunKind, Pipeline] | None,
        started_by: str | None,
    ) -> None:
        try:
            with self._slots:
                if self._closed.is_set():
                    return
                run_pipeline(
                    self.sessions,
                    kind,
                    dry_run=dry_run,
                    force=force,
                    pipelines=pipelines,
                    run_id=run_id,
                    started=started,
                    started_by=started_by,
                )
        except Exception:
            # Recorded on the run's row already; nobody is waiting for it here.
            log.warning("agent run failed", run_id=str(run_id), kind=kind.value)
        finally:
            started.set()
            with self._lock:
                self._threads.discard(threading.current_thread())


class _Started(threading.Event):
    """Set once the run's row exists (or the run ends without one); then calls
    `on_set` exactly once."""

    def __init__(self, on_set: Callable[[], None]) -> None:
        super().__init__()
        self._on_set = on_set
        self._once = threading.Lock()

    def set(self) -> None:
        with self._once:
            if not self.is_set():
                self._on_set()
            super().set()
