"""The worker: runs the pipelines on their schedule.

One process, no queue: APScheduler fires each pipeline at its time in the
configured time zone. Pipelines scheduled for the same moment run one after
another in a fixed order, so the source review always comes before discovery
(sources it mutes free their place the same morning). Each run is the same as
`brzask run <pipeline>`, advisory lock included.

On SIGTERM or SIGINT the worker stops scheduling and waits for a running
pipeline to finish, so no run is left half done.
"""

import logging
import signal
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import FrameType
from zoneinfo import ZoneInfo

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session, sessionmaker

from brzask.config.settings import Schedule, SchedulerSettings
from brzask.db.models import RunKind
from brzask.log import get_logger
from brzask.services.runs import run_pipeline

log = get_logger(__name__)

# The order of pipelines that share a schedule.
ORDER = (RunKind.DIGEST, RunKind.REVIEW, RunKind.VISITED, RunKind.DISCOVERY)
# A run that could not start on time (the machine slept, the worker restarted)
# still runs if it is at most this late; later ones wait for the next time.
MISFIRE_GRACE_SECONDS = 3 * 3600
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True, slots=True)
class Job:
    schedule: Schedule
    kinds: tuple[RunKind, ...]  # run one after another, in this order

    @property
    def name(self) -> str:
        return "+".join(kind.value for kind in self.kinds)


def jobs(settings: SchedulerSettings) -> list[Job]:
    """One job per distinct schedule; pipelines switched off ('off') are left out."""
    schedules = {
        RunKind.DIGEST: settings.digest_at,
        RunKind.REVIEW: settings.review_at,
        RunKind.VISITED: settings.visited_at,
        RunKind.DISCOVERY: settings.discovery_at,
    }
    grouped: dict[Schedule, list[RunKind]] = {}
    for kind in ORDER:
        schedule = schedules[kind]
        if schedule is not None:
            grouped.setdefault(schedule, []).append(kind)
    return [Job(schedule, tuple(kinds)) for schedule, kinds in grouped.items()]


def trigger(schedule: Schedule, zone: ZoneInfo) -> CronTrigger:
    return CronTrigger(
        day_of_week="*" if schedule.weekday is None else _WEEKDAYS[schedule.weekday],
        hour=schedule.at.hour,
        minute=schedule.at.minute,
        timezone=zone,
    )


def run_job(kinds: Sequence[RunKind], run: Callable[[RunKind], object]) -> None:
    """Run each pipeline; a failed one is logged (and recorded) and the next still runs."""
    for kind in kinds:
        try:
            run(kind)
        except Exception:
            log.exception("scheduled run failed", pipeline=kind.value)


def build_scheduler(
    settings: SchedulerSettings, run: Callable[[RunKind], object]
) -> BackgroundScheduler:
    # One job at a time: runs are long and share the LLM budget; a second job
    # due meanwhile starts when the first finishes.
    scheduler = BackgroundScheduler(
        executors={"default": ThreadPoolExecutor(max_workers=1)},
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": MISFIRE_GRACE_SECONDS,
        },
        timezone=settings.timezone,
    )
    for job in jobs(settings):
        scheduler.add_job(
            run_job,
            trigger(job.schedule, settings.timezone),
            args=[job.kinds, run],
            id=job.name,
            name=job.name,
        )
    return scheduler


def run_worker(settings: SchedulerSettings, sessions: sessionmaker[Session]) -> None:
    """Run the schedule until SIGTERM or SIGINT."""
    # The schedule is logged below; APScheduler's own lines about adding jobs only repeat it.
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
    scheduler = build_scheduler(settings, lambda kind: run_pipeline(sessions, kind))
    for job in scheduler.get_jobs():
        log.info("scheduled", job=job.name, trigger=str(job.trigger))
    log.info("worker started", timezone=str(settings.timezone), jobs=len(scheduler.get_jobs()))
    serve(scheduler)
    log.info("worker stopped")


def serve(scheduler: BackgroundScheduler) -> None:
    """Run `scheduler` until SIGTERM or SIGINT, then wait for the running job.

    The scheduler runs in its own thread; this one only waits for a signal and
    then shuts it down, holding none of the scheduler's locks. Must be called
    from the main thread, where Python delivers signals.
    """
    stop_requested = threading.Event()

    def stop(signum: int, _frame: FrameType | None) -> None:
        log.info("worker stopping; waiting for a running pipeline", signal=signum)
        stop_requested.set()

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        scheduler.start()
        stop_requested.wait()
        scheduler.shutdown(wait=True)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
