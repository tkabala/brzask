"""How many of the recent digests' articles were opened, as metrics.

The open rate is a fact of the database, not of a process: an article shown
today may be opened from a feed reader next week. So the gauges read it when
they are collected, over the last digest days that exist.
"""

import time
from collections.abc import Callable, Iterable

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from brzask.log import get_logger
from brzask.repositories import ArticleRepository

log = get_logger(__name__)

# The days of a week of digests; days without a digest do not count.
OPEN_RATE_DAYS = 7

SHOWN = "brzask.digest.shown"
OPENED = "brzask.digest.opened"


def recent_opens(session: Session, days: int = OPEN_RATE_DAYS) -> tuple[int, int]:
    """(shown, opened) articles of the last `days` digest days."""
    recent = ArticleRepository(session).digest_days(days)
    return sum(day.articles for day in recent), sum(day.opened for day in recent)


def register_open_rate(sessions: sessionmaker[Session], meter: metrics.Meter | None = None) -> None:
    """Observable gauges of the shown and opened articles of the last digests.

    One collection asks the database once for both. An unreachable database
    gives no values rather than an error on every scrape.
    """
    meter = meter or metrics.get_meter("brzask.digest")
    attributes = {"days": str(OPEN_RATE_DAYS)}
    cached: list[tuple[float, tuple[int, int] | None]] = []

    def counts() -> tuple[int, int] | None:
        now = time.monotonic()
        # Both callbacks run within one collection; the second reuses the answer.
        if cached and now - cached[0][0] < 1:
            return cached[0][1]
        try:
            with sessions() as session:
                value: tuple[int, int] | None = recent_opens(session)
        except SQLAlchemyError as error:
            log.debug("open rate not read", error=str(error))
            value = None
        cached[:] = [(now, value)]
        return value

    def observe(index: int) -> Callable[[CallbackOptions], Iterable[Observation]]:
        def callback(_options: CallbackOptions) -> Iterable[Observation]:
            value = counts()
            return [] if value is None else [Observation(value[index], attributes)]

        return callback

    meter.create_observable_gauge(
        SHOWN,
        callbacks=[observe(0)],
        unit="{article}",
        description=f"Articles shown in the last {OPEN_RATE_DAYS} digests.",
    )
    meter.create_observable_gauge(
        OPENED,
        callbacks=[observe(1)],
        unit="{article}",
        description="Of those, articles opened.",
    )
