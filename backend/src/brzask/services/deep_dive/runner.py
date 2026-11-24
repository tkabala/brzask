"""Deep dives written one at a time, in request order, in the API process.

One worker thread takes queued dives in turn, so the run kind's advisory lock
is never contended inside one process. A run that ends without touching its
dive (skipped because another process holds the lock, or a pipeline that
failed before starting it) fails the dive with the reason, so nothing stays
queued. The thread is a daemon: a stopping API leaves the dive running, and
the next start fails it as interrupted.
"""

import contextvars
import queue
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session, sessionmaker

from brzask.db.models import DeepDiveStatus, RunKind
from brzask.log import get_logger
from brzask.repositories import DeepDiveRepository
from brzask.services.deep_dive.pipeline import deep_dive_pipeline
from brzask.services.notify import Notifier
from brzask.services.runs import FROM_SETTINGS, Pipeline, _Default, run_pipeline

log = get_logger(__name__)


class DeepDiveRunner:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        pipeline: Callable[[int], Pipeline] = deep_dive_pipeline,
        notifier: Notifier | Literal[_Default.FROM_SETTINGS] | None = FROM_SETTINGS,
    ) -> None:
        self.sessions = sessions
        self.pipeline = pipeline
        self.notifier = notifier
        self._queue: queue.Queue[tuple[int, contextvars.Context] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, dive_id: int) -> None:
        """Queue the dive; it runs after the ones submitted before it.

        Each dive runs in its own caller's context (trace, log fields), not in
        that of the request that happened to start the thread.
        """
        with self._lock:
            if self._thread is None:
                # A new thread starts with an empty context.
                self._thread = threading.Thread(target=self._work, name="deep-dives", daemon=True)
                self._thread.start()
        self._queue.put((dive_id, contextvars.copy_context()))

    def close(self, grace: float = 5.0) -> None:
        """Take nothing new; give the running dive `grace` seconds, then leave it."""
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(grace)

    def _work(self) -> None:
        while (item := self._queue.get()) is not None:
            dive_id, context = item
            context.run(self._run, dive_id)

    def _run(self, dive_id: int) -> None:
        try:
            run = run_pipeline(
                self.sessions,
                RunKind.DEEP_DIVE,
                pipelines={RunKind.DEEP_DIVE: self.pipeline(dive_id)},
                notifier=self.notifier,
            )
            reason = run.stats.get("reason") or run.error
        except Exception as error:
            # Recorded on the run's row (and the dive) already.
            log.warning("deep dive failed", dive_id=dive_id, error=type(error).__name__)
            reason = f"{type(error).__name__}: {error}"
        self._fail_if_untouched(dive_id, reason)

    def _fail_if_untouched(self, dive_id: int, reason: object) -> None:
        try:
            with self.sessions.begin() as session:
                repository = DeepDiveRepository(session)
                dive = repository.get(dive_id)
                if dive is not None and dive.status is DeepDiveStatus.QUEUED:
                    text = str(reason) if reason else "the run did not start"
                    repository.fail(dive_id, text, datetime.now(UTC))
        except Exception as error:
            log.warning("deep dive state not closed", dive_id=dive_id, error=type(error).__name__)
