"""Source review: mute sources that publish without ever being worth reading,
and mark dead the ones whose feed stopped working.

Runs before discovery, so sources muted in the morning free their place the
same day. Only active sources are reviewed.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from brzask.db.models import Source, SourceStatus
from brzask.log import get_logger
from brzask.repositories import SourceRepository
from brzask.repositories.sources import SourceStats
from brzask.services.runs import RunContext
from brzask.services.sources import change_status

log = get_logger(__name__)

ACTOR = "pipeline:review"

# Articles first seen in this window are counted.
STATS_WINDOW = timedelta(days=30)
# A younger source is never muted: it has not had the chance to show what it publishes.
PROBATION = timedelta(days=21)
# Below this many articles, never reaching the top says little.
MIN_ARTICLES_TO_MUTE = 10
# Starting points, not yet measured: a feed answering 404, 410, 403 or "not a
# feed" for two weeks has moved or ended; any error for a month, the same.
# Rate limits and outages alone never kill a source within the month.
DEAD_AFTER_PERMANENT = timedelta(days=14)
DEAD_AFTER_ANY = timedelta(days=30)


class Decision(StrEnum):
    KEEP = "keep"
    PROBATION = "probation"  # too young to judge
    QUIET = "quiet"  # published nothing; costs nothing, so only reported
    MUTE = "mute"
    DEAD = "dead"


# Decisions that switch a source off.
_NEW_STATUS = {Decision.MUTE: SourceStatus.MUTED, Decision.DEAD: SourceStatus.DEAD}


@dataclass(frozen=True, slots=True)
class Verdict:
    decision: Decision
    note: str | None = None  # stored as the source's note when it is muted or marked dead


def evaluate(source: Source, stats: SourceStats | None, now: datetime) -> Verdict:
    """The decision for one active source, from its fetch health and its stats."""
    if source.permanent_failing_since is not None and (
        now - source.permanent_failing_since >= DEAD_AFTER_PERMANENT
    ):
        return Verdict(Decision.DEAD, _dead_note(source, source.permanent_failing_since))
    if source.failing_since is not None and now - source.failing_since >= DEAD_AFTER_ANY:
        return Verdict(Decision.DEAD, _dead_note(source, source.failing_since))
    if now - source.created_at < PROBATION:
        return Verdict(Decision.PROBATION)
    articles = stats.articles if stats else 0
    if articles == 0:
        return Verdict(Decision.QUIET)
    if (
        stats is not None
        and articles >= MIN_ARTICLES_TO_MUTE
        and not stats.ranked
        and not stats.opened
    ):
        days = STATS_WINDOW.days
        return Verdict(
            Decision.MUTE,
            f"muted by the review: {articles} articles in {days} days,"
            " none in the top of the ranking, none opened",
        )
    return Verdict(Decision.KEEP)


def review_sources(context: RunContext) -> None:
    """Review every active source; mute and mark dead outside a dry run."""
    now = context.started_at
    with context.sessions.begin() as session:
        repository = SourceRepository(session)
        stats = repository.stats(now - STATS_WINDOW)
        verdicts = [
            (source, evaluate(source, stats.get(source.id), now))
            for source in repository.find(SourceStatus.ACTIVE)
        ]
        if not context.dry_run:
            for source, verdict in verdicts:
                status = _NEW_STATUS.get(verdict.decision)
                if status is not None:
                    change_status(session, source, status, actor=ACTOR, reason=verdict.note)
        context.stats.update(
            {
                "sources": len(verdicts),
                "decisions": {
                    decision.value: sum(v.decision is decision for _, v in verdicts)
                    for decision in Decision
                },
                "muted": [
                    {"name": s.name, "note": v.note}
                    for s, v in verdicts
                    if v.decision is Decision.MUTE
                ],
                "dead": [
                    {"name": s.name, "note": v.note}
                    for s, v in verdicts
                    if v.decision is Decision.DEAD
                ],
                "quiet": [s.name for s, v in verdicts if v.decision is Decision.QUIET],
            }
        )
    log.info("sources reviewed", **context.stats["decisions"])


def _dead_note(source: Source, since: datetime) -> str:
    day = since.date().isoformat()
    return f"marked dead by the review: failing since {day} ({source.fetch_error})"
