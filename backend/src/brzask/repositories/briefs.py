"""Briefs of picked articles."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload

from brzask.db.models import Article, ArticleBrief, ArticleContent, BriefBasis


@dataclass(frozen=True, slots=True)
class Chapter:
    start: int  # seconds from the start of the video
    title: str


@dataclass(frozen=True, slots=True)
class Brief:
    """A brief as `services.briefs` checked it, ready to store."""

    gist: str
    points: list[str]
    caveats: list[str]
    chapters: list[Chapter]


class BriefRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def missing(self, since: date, until: date) -> Sequence[tuple[Article, ArticleContent]]:
        """Digest articles from `since` to `until` with a stored text and no brief, in digest order.

        Each article comes with its source loaded.
        """
        rows = self.session.execute(
            select(Article, ArticleContent)
            .join(ArticleContent, ArticleContent.article_id == Article.id)
            .outerjoin(ArticleBrief, ArticleBrief.article_id == Article.id)
            .where(
                Article.digest_date >= since,
                Article.digest_date <= until,
                ArticleBrief.article_id.is_(None),
            )
            .order_by(Article.digest_date, Article.digest_position, Article.id)
            .options(joinedload(Article.source))
        )
        return [(article, content) for article, content in rows.tuples()]

    def save(self, article_id: int, brief: Brief, basis: BriefBasis, model: str) -> None:
        """Store a brief; an article keeps the brief it was first given."""
        self.session.execute(
            insert(ArticleBrief)
            .values(
                article_id=article_id,
                gist=brief.gist,
                points=list(brief.points),
                caveats=list(brief.caveats),
                chapters=[
                    {"start": chapter.start, "title": chapter.title} for chapter in brief.chapters
                ],
                basis=basis,
                model=model,
            )
            .on_conflict_do_nothing(index_elements=[ArticleBrief.article_id])
        )

    def get(self, article_id: int) -> ArticleBrief | None:
        return self.session.get(ArticleBrief, article_id)

    def ids_with_brief(self, article_ids: Iterable[int]) -> set[int]:
        ids = list(article_ids)
        if not ids:
            return set()
        return set(
            self.session.scalars(
                select(ArticleBrief.article_id).where(ArticleBrief.article_id.in_(ids))
            )
        )
