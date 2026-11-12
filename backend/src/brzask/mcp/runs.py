"""Pipeline runs started by an agent, in the API process.

A run takes minutes, longer than a tool call should, so it runs in a thread
and the agent follows it with `get_run`. It is the same `run_pipeline` as
the worker's and the CLI's, advisory lock included: a second run of the
same pipeline is recorded as skipped. If the API stops mid-run, the next
start of the API or the worker closes the row (`sweep_abandoned`).
"""

import threading
import time
import uuid
from collections.abc import Mapping
from concurrent.futures import Future
from contextlib import suppress

from sqlalchemy.orm import Session, sessionmaker

from brzask.concurrency import ContextThreadPoolExecutor
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
        self._executor = ContextThreadPoolExecutor(max_workers, thread_name_prefix="agent-run")
        self._futures: set[Future[None]] = set()
        self._lock = threading.Lock()

    def start(self, kind: RunKind, *, dry_run: bool, force: bool) -> uuid.UUID:
        """Start a run and return its ID once its row exists (or after a few seconds)."""
        run_id = uuid.uuid4()
        started = threading.Event()
        future = self._executor.submit(self._run, kind, run_id, started, dry_run, force)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._forget)
        started.wait(STARTED_WAIT)
        return run_id

    def close(self, grace: float = 5.0) -> None:
        """Stop taking runs; give running ones `grace` seconds, then leave them."""
        deadline = time.monotonic() + grace
        with self._lock:
            futures = list(self._futures)
        for future in futures:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            # A timeout, or the run's own error, which its row already holds.
            with suppress(Exception):
                future.result(timeout=remaining)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(
        self, kind: RunKind, run_id: uuid.UUID, started: threading.Event, dry_run: bool, force: bool
    ) -> None:
        try:
            run_pipeline(
                self.sessions,
                kind,
                dry_run=dry_run,
                force=force,
                pipelines=self.pipelines,
                run_id=run_id,
                started=started,
            )
        except Exception:
            # Recorded on the run's row already; nobody is waiting for it here.
            log.warning("agent run failed", run_id=str(run_id), kind=kind.value)
        finally:
            started.set()

    def _forget(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)
