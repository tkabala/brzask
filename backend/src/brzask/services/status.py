"""What the instance holds and what ran last."""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from brzask.db.models import Run, RunKind, SourceStatus
from brzask.repositories import ArticleRepository, RunRepository, SourceRepository
from brzask.repositories.articles import ArticleCounts
from brzask.services.pause import paused_until


@dataclass(frozen=True, slots=True)
class Status:
    articles: ArticleCounts
    sources: dict[SourceStatus, int]  # every status, zero included
    last_digest: date | None
    paused_until: datetime | None
    last_runs: dict[RunKind, Run | None]  # every pipeline, None when it never ran


def get_status(session: Session, now: datetime) -> Status:
    counts = SourceRepository(session).count_by_status()
    runs = RunRepository(session)
    articles = ArticleRepository(session)
    return Status(
        articles=articles.counts(),
        sources={status: counts.get(status, 0) for status in SourceStatus},
        last_digest=articles.latest_digest_date(),
        paused_until=paused_until(session, now),
        last_runs={kind: runs.latest(kind) for kind in RunKind},
    )
