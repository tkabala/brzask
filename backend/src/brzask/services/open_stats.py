"""Which sources and topics of recent digests were opened.

Opens are the only feedback brzask gets, so these counts are what an owner
(or an agent helping one) looks at before muting a source or editing an
interest.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from brzask.repositories import ArticleRepository
from brzask.services.errors import ServiceError

MAX_DAYS = 90
NO_KEY = "(none)"


@dataclass(frozen=True, slots=True)
class OpenCount:
    key: str  # source name or topic
    shown: int
    opened: int


@dataclass(frozen=True, slots=True)
class OpenStats:
    days: int
    since: date
    shown: int
    opened: int
    by_source: list[OpenCount]
    by_topic: list[OpenCount]


def open_stats(session: Session, today: date, days: int) -> OpenStats:
    """Shown and opened articles of the digests of the last `days` days up to `today`."""
    if not 1 <= days <= MAX_DAYS:
        raise ServiceError(f"the window must be between 1 and {MAX_DAYS} days")
    since = today - timedelta(days=days - 1)
    articles = ArticleRepository(session)

    def counts(by: Literal["source", "topic"]) -> list[OpenCount]:
        rows = [
            OpenCount(key or NO_KEY, shown, opened)
            for key, shown, opened in articles.shown_and_opened(since, today, by)
        ]
        return sorted(rows, key=lambda row: (-row.shown, row.key))

    by_source = counts("source")
    return OpenStats(
        days=days,
        since=since,
        shown=sum(row.shown for row in by_source),
        opened=sum(row.opened for row in by_source),
        by_source=by_source,
        by_topic=counts("topic"),
    )
