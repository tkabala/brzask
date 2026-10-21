"""Reading digests: a day's articles, the archive, and why an article was ranked where it was."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from brzask.db.models import Article, Run
from brzask.repositories import ArticleRepository, RunRepository
from brzask.repositories.articles import DigestDay
from brzask.services.errors import NotFoundError


def digest_for(session: Session, day: date) -> Sequence[Article]:
    """The articles of `day`'s digest in order; empty when there is none."""
    return ArticleRepository(session).digest(day)


def digest_days(session: Session, limit: int, before: date | None = None) -> list[DigestDay]:
    """Days with a digest, newest first, `limit` at a time; `before` is the last day seen."""
    return ArticleRepository(session).digest_days(limit, before)


def get_article(session: Session, article_id: int) -> Article:
    article = ArticleRepository(session).get(article_id)
    if article is None:
        raise NotFoundError(f"no article {article_id}")
    return article


@dataclass(frozen=True, slots=True)
class RankingExplanation:
    """What is known about how an article reached its place.

    The run counts come from the stats of the digest run that showed it;
    they are None when that run is unknown or did not record them.
    """

    article: Article
    run: Run | None
    pool: int | None  # candidates the run considered
    ranked: int | None  # candidates the ranking put in order
    top: int | None  # best ranked, kept for extraction and deduplication
    ranking_method: str | None
    deduplicated_to: int | None  # top candidates left after deduplication
    deduplication_method: str | None


def explain_ranking(session: Session, article_id: int) -> RankingExplanation:
    article = get_article(session, article_id)
    run = (
        RunRepository(session).digest_started_at(article.shown_at)
        if article.shown_at is not None
        else None
    )
    stats = run.stats if run is not None else {}
    return RankingExplanation(
        article=article,
        run=run,
        pool=_count(stats, "pool", "candidates"),
        ranked=_count(stats, "ranking", "ranked"),
        top=_count(stats, "ranking", "top"),
        ranking_method=_text(stats, "ranking", "method"),
        deduplicated_to=_count(stats, "deduplication", "survivors"),
        deduplication_method=_text(stats, "deduplication", "same_day_method"),
    )


def _value(stats: dict[str, Any], stage: str, key: str) -> object:
    section = stats.get(stage)
    return section.get(key) if isinstance(section, dict) else None


def _count(stats: dict[str, Any], stage: str, key: str) -> int | None:
    value = _value(stats, stage, key)
    # bool is an int; a count never is one.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(stats: dict[str, Any], stage: str, key: str) -> str | None:
    value = _value(stats, stage, key)
    return value if isinstance(value, str) else None
