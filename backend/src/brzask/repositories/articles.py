"""Articles: candidates, rankings, digests and opens."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.util import identity_key

from brzask.db.models import Article, ArticleState, Source


@dataclass(frozen=True, slots=True)
class NewArticle:
    link: str
    title: str
    source_id: int | None
    snippet: str | None = None
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Extraction:
    article_id: int
    text: str | None
    extracted_by: str | None
    embedding: Sequence[float] | None
    embedding_model: str | None


@dataclass(frozen=True, slots=True)
class DigestEntry:
    """One picked article, written in the digest language."""

    article_id: int
    position: int
    title: str
    summary: str
    why_it_matters: str
    topic: str


@dataclass(frozen=True, slots=True)
class OpenedArticle:
    title: str
    topic: str | None
    source_name: str | None
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class DigestDay:
    day: date
    articles: int
    opened: int


@dataclass(frozen=True, slots=True)
class SimilarArticle:
    article: Article
    similarity: float  # cosine similarity, 1.0 for identical direction


@dataclass(frozen=True, slots=True)
class ArticleCounts:
    total: int
    shown: int
    opened: int


class ArticleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, article_id: int) -> Article | None:
        return self.session.get(Article, article_id)

    # --- Candidates --------------------------------------------------------------

    def add_new(self, articles: Sequence[NewArticle]) -> dict[str, int]:
        """Store fetched entries; links already stored are left as they are.

        Returns the ID of every given link, new or not, so later stages can
        update candidates by ID.
        """
        if not articles:
            return {}
        rows = [
            {
                "link": article.link,
                "title": article.title,
                "source_id": article.source_id,
                "snippet": article.snippet,
                "published_at": article.published_at,
            }
            for article in articles
        ]
        self.session.execute(insert(Article).values(rows).on_conflict_do_nothing())
        links = [article.link for article in articles]
        query = select(Article.link, Article.id).where(Article.link.in_(links))
        return dict(self.session.execute(query).all())

    def shown_links(self, since: datetime) -> set[str]:
        query = select(Article.link).where(
            Article.state == ArticleState.SHOWN, Article.shown_at >= since
        )
        return set(self.session.scalars(query))

    def carry_over(self, since: datetime) -> Sequence[Article]:
        """Articles first seen at or after `since` that no digest has shown yet."""
        query = (
            select(Article)
            .where(Article.state == ArticleState.SEEN, Article.first_seen_at >= since)
            .order_by(Article.first_seen_at, Article.id)
        )
        return self.session.scalars(query).all()

    def shown_embeddings(self, since: datetime, model: str) -> list[list[float]]:
        """Vectors of articles shown at or after `since`, from `model` only."""
        query = select(Article.embedding).where(
            Article.state == ArticleState.SHOWN,
            Article.shown_at >= since,
            Article.embedding_model == model,
        )
        return [list(vector) for vector in self.session.scalars(query) if vector is not None]

    def recent_opens(self, since: datetime, limit: int) -> list[OpenedArticle]:
        """Most recently opened articles first."""
        query = (
            select(Article.title, Article.topic, Source.name, Article.opened_at)
            .outerjoin(Source, Article.source_id == Source.id)
            .where(Article.opened_at >= since)
            .order_by(Article.opened_at.desc())
            .limit(limit)
        )
        return [
            OpenedArticle(title, topic, source_name, opened_at)
            for title, topic, source_name, opened_at in self.session.execute(query)
            if opened_at is not None
        ]

    def opened_since(self, since: datetime) -> Sequence[Article]:
        query = select(Article).where(Article.opened_at >= since).order_by(Article.opened_at.desc())
        return self.session.scalars(query).all()

    # --- Pipeline results --------------------------------------------------------

    def set_ranks(self, ranks: Mapping[int, int]) -> None:
        """Store ranking positions by article ID."""
        if ranks:
            self.session.execute(
                update(Article),
                [{"id": article_id, "rank": rank} for article_id, rank in ranks.items()],
            )
            self._expire_cached(ranks)

    def save_extractions(self, extractions: Sequence[Extraction]) -> None:
        if extractions:
            self.session.execute(
                update(Article),
                [
                    {
                        "id": extraction.article_id,
                        "extracted_text": extraction.text,
                        "extracted_by": extraction.extracted_by,
                        "embedding": (
                            list(extraction.embedding) if extraction.embedding is not None else None
                        ),
                        "embedding_model": extraction.embedding_model,
                    }
                    for extraction in extractions
                ],
            )
            self._expire_cached(extraction.article_id for extraction in extractions)

    def last_digest_position(self, day: date) -> int | None:
        """Highest position in the digest for `day`; None when there is no digest yet."""
        query = select(func.max(Article.digest_position)).where(Article.digest_date == day)
        return self.session.scalar(query)

    def mark_shown(self, day: date, entries: Sequence[DigestEntry], shown_at: datetime) -> None:
        if entries:
            self.session.execute(
                update(Article),
                [
                    {
                        "id": entry.article_id,
                        "state": ArticleState.SHOWN,
                        "shown_at": shown_at,
                        "digest_date": day,
                        "digest_position": entry.position,
                        "digest_title": entry.title,
                        "summary": entry.summary,
                        "why_it_matters": entry.why_it_matters,
                        "topic": entry.topic,
                    }
                    for entry in entries
                ],
            )
            self._expire_cached(entry.article_id for entry in entries)

    def _expire_cached(self, article_ids: Iterable[int]) -> None:
        """Bulk updates by ID skip the identity map; reload already-loaded rows on next access."""
        for article_id in article_ids:
            cached = self.session.identity_map.get(identity_key(Article, article_id))
            if cached is not None:
                self.session.expire(cached)

    # --- Reading digests ---------------------------------------------------------

    def digest(self, day: date) -> Sequence[Article]:
        """The digest for `day` in position order, with sources loaded."""
        query = (
            select(Article)
            .options(joinedload(Article.source))
            .where(Article.digest_date == day)
            .order_by(Article.digest_position)
        )
        return self.session.scalars(query).all()

    def latest_digest_date(self) -> date | None:
        return self.session.scalar(select(func.max(Article.digest_date)))

    def digest_days(self, limit: int, before: date | None = None) -> list[DigestDay]:
        """Days with a digest, newest first; `before` continues a previous page."""
        query = (
            select(Article.digest_date, func.count(), func.count(Article.opened_at))
            .where(Article.digest_date.is_not(None))
            .group_by(Article.digest_date)
            .order_by(Article.digest_date.desc())
            .limit(limit)
        )
        if before is not None:
            query = query.where(Article.digest_date < before)
        return [
            DigestDay(day, articles, opened)
            for day, articles, opened in self.session.execute(query)
            if day is not None
        ]

    def record_open(self, article_id: int, opened_at: datetime) -> str | None:
        """Keep the first open only; returns the link, or None for an unknown ID."""
        statement = (
            update(Article)
            .where(Article.id == article_id)
            .values(opened_at=func.coalesce(Article.opened_at, opened_at))
            .returning(Article.link)
        )
        return self.session.scalar(statement)

    # --- Search ------------------------------------------------------------------

    def search_similar(
        self, vector: Sequence[float], model: str, limit: int
    ) -> list[SimilarArticle]:
        """Nearest articles by cosine similarity, among vectors of the same model."""
        distance = Article.embedding.cosine_distance(list(vector))
        query = (
            select(Article, distance)
            .where(Article.embedding_model == model)
            .order_by(distance)
            .limit(limit)
        )
        return [
            SimilarArticle(article, 1.0 - float(value))
            for article, value in self.session.execute(query)
        ]

    def search_text(self, text: str, limit: int) -> Sequence[Article]:
        """Articles whose title, digest title or summary contains `text`, newest first."""
        query = (
            select(Article)
            .where(
                Article.title.icontains(text, autoescape=True)
                | Article.digest_title.icontains(text, autoescape=True)
                | Article.summary.icontains(text, autoescape=True)
            )
            .order_by(Article.first_seen_at.desc(), Article.id.desc())
            .limit(limit)
        )
        return self.session.scalars(query).all()

    def counts(self) -> ArticleCounts:
        query = select(
            func.count(),
            func.count().filter(Article.state == ArticleState.SHOWN),
            func.count(Article.opened_at),
        ).select_from(Article)
        total, shown, opened = self.session.execute(query).one()
        return ArticleCounts(total, shown, opened)
