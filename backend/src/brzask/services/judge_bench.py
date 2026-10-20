"""Judge bench: how well a judge's scores tell opened articles from the others.

Only articles that were shown are scored. Each of them could be opened, so
the comparison does not favour whichever ranking chose the digests, as
`replay` does. For each shown article of each digest day, the judge answers
the composite ranking's dimensions with the reader's interests (today's) and
the titles opened before that day's run. The measure is the AUC of each
dimension and of the weighted composite: the probability that an opened
article scores above one that was not opened (0.5 is chance, ties count half).

The rows (each article's scores and whether it was opened) are also the
features for learning weights from opens. Nothing is written.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.judge import Judge, JudgeError
from brzask.clients.usage import UsageMeter
from brzask.log import get_logger
from brzask.repositories import ArticleRepository
from brzask.services.digest import scoring
from brzask.services.digest.pool import FeedSource, carried_candidates
from brzask.services.digest.ranking import (
    OPENED_TITLES,
    OPENS_LIMIT,
    OPENS_WINDOW,
    interest_context,
)

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ScoredArticle:
    day: date
    article_id: int
    title: str
    opened: bool
    scores: dict[str, float]  # by dimension, each scaled to 0..1


@dataclass(frozen=True, slots=True)
class BenchResult:
    model: str
    rows: list[ScoredArticle]
    failed: int  # shown articles the judge gave no answer for
    usage: dict[str, Any] = field(default_factory=dict)

    def composite(self, weights: Mapping[str, float]) -> list[float]:
        return [scoring.weighted(row.scores, weights) for row in self.rows]

    def aucs(self, weights: Mapping[str, float] = scoring.WEIGHTS) -> dict[str, float | None]:
        """AUC per dimension and of the composite; None without both kinds of article."""
        labels = [row.opened for row in self.rows]
        result = {
            name: auc([row.scores[name] for row in self.rows], labels)
            for name in scoring.DIMENSIONS
        }
        result["composite"] = auc(self.composite(weights), labels)
        return result


def auc(scores: Sequence[float], opened: Sequence[bool]) -> float | None:
    """The probability that an opened article scores above one that was not; ties count half."""
    positive = [score for score, label in zip(scores, opened, strict=True) if label]
    negative = [score for score, label in zip(scores, opened, strict=True) if not label]
    if not positive or not negative:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positive for n in negative)
    return wins / (len(positive) * len(negative))


def score_shown(
    sessions: sessionmaker[Session],
    judge: Judge,
    since: date,
    workers: int = scoring.JUDGE_WORKERS,
) -> BenchResult:
    """Every article shown by each day's first run from `since` on, scored by `judge`."""
    meter = UsageMeter()
    rows: list[ScoredArticle] = []
    failed = 0
    with sessions.begin() as session:
        interests = interest_context(session)
        runs = ArticleRepository(session).digest_runs(since)
    for run in runs:
        with sessions.begin() as session:
            articles = ArticleRepository(session)
            # Only what this run showed: a forced run later that day appends.
            shown = [a for a in articles.digest(run.day) if a.shown_at == run.started_at]
            opens = articles.recent_opens(
                run.started_at - OPENS_WINDOW, OPENS_LIMIT, before=run.started_at
            )
            sources = {a.source.id: FeedSource.of(a.source) for a in shown if a.source}
            candidates, _ = carried_candidates(shown, sources)
            by_id = {article.id: article for article in shown}
        titles = [opened.title for opened in opens[:OPENED_TITLES]]
        try:
            scored = scoring.score_candidates(
                candidates, judge, interests, titles, meter=meter, workers=workers
            )
        except JudgeError as error:
            # Every call of this day failed; the other days are still worth scoring.
            log.warning("day not scored", day=run.day.isoformat(), error=str(error))
            scored = []
        failed += len(candidates) - len(scored)
        for item in scored:
            candidate = candidates[item.position]
            assert candidate.article_id is not None  # noqa: S101  (built from stored rows)
            rows.append(
                ScoredArticle(
                    day=run.day,
                    article_id=candidate.article_id,
                    title=candidate.title,
                    opened=by_id[candidate.article_id].opened_at is not None,
                    scores={name: scoring.scaled(answer) for name, answer in item.answers.items()},
                )
            )
        log.info("day scored", day=run.day.isoformat(), articles=len(scored))
    return BenchResult(judge.model, rows, failed, meter.summary())


def report(results: Sequence[BenchResult]) -> dict[str, Any]:
    """Everything about a bench as JSON-ready data; the rows are the features for weights."""
    return {
        "weights": dict(scoring.WEIGHTS),
        "models": [
            {
                "model": result.model,
                "articles": len(result.rows),
                "opened": sum(row.opened for row in result.rows),
                "failed": result.failed,
                "auc": result.aucs(),
                "usage": result.usage,
                "rows": [
                    {
                        "day": row.day.isoformat(),
                        "article_id": row.article_id,
                        "title": row.title,
                        "opened": row.opened,
                        "scores": row.scores,
                    }
                    for row in result.rows
                ],
            }
            for result in results
        ],
    }
