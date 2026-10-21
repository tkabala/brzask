"""Articles, and why one was ranked where it was."""

from datetime import date, datetime
from http import HTTPStatus

from fastapi import APIRouter
from pydantic import BaseModel, Field

from brzask.api import problems
from brzask.api.deps import DbSession, Id
from brzask.db.models import Article, ArticleState
from brzask.services import digests

router = APIRouter(prefix="/articles", tags=["articles"])


class SourceRef(BaseModel):
    id: int
    name: str


class ArticleOut(BaseModel):
    id: int
    link: str
    title: str = Field(description="In the digest language when the article was in a digest.")
    original_title: str = Field(description="As the feed published it.")
    summary: str | None
    why_it_matters: str | None
    topic: str | None = Field(description="The interest it was picked for.")
    source: SourceRef | None = Field(description="Null when the source was removed.")
    state: ArticleState
    published_at: datetime | None
    first_seen_at: datetime
    digest_date: date | None
    position: int | None = Field(description="1-based place in its digest.")
    shown_at: datetime | None
    opened_at: datetime | None = Field(description="First open.")

    @classmethod
    def of(cls, article: Article) -> "ArticleOut":
        source = article.source
        return cls(
            id=article.id,
            link=article.link,
            title=article.digest_title or article.title,
            original_title=article.title,
            summary=article.summary,
            why_it_matters=article.why_it_matters,
            topic=article.topic,
            source=SourceRef(id=source.id, name=source.name) if source else None,
            state=article.state,
            published_at=article.published_at,
            first_seen_at=article.first_seen_at,
            digest_date=article.digest_date,
            position=article.digest_position,
            shown_at=article.shown_at,
            opened_at=article.opened_at,
        )


class RankingOut(BaseModel):
    """How the article reached its place; counts are null when the run did not record them."""

    article_id: int
    position: int | None = Field(description="Place in its digest, chosen by the selection.")
    topic: str | None = Field(description="The interest the selection picked it for.")
    why_it_matters: str | None = Field(description="The selection's reason, for the reader.")
    rank: int | None = Field(
        description="Place in the ranking of the whole pool; null when it was not near the top."
    )
    pool: int | None = Field(description="Candidates the digest run considered.")
    ranked: int | None = Field(description="Candidates the ranking put in order.")
    top: int | None = Field(description="Best ranked candidates kept for the next stages.")
    ranking_method: str | None = Field(description="llm, judge, or a fallback.")
    deduplicated_to: int | None = Field(description="Top candidates left after deduplication.")
    deduplication_method: str | None
    run_id: str | None = Field(description="The digest run that showed it.")


@router.get(
    "/{article_id}",
    summary="Get an article",
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def get_article(session: DbSession, article_id: Id) -> ArticleOut:
    return ArticleOut.of(digests.get_article(session, article_id))


@router.get(
    "/{article_id}/ranking",
    summary="Why an article was ranked where it was",
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def get_article_ranking(session: DbSession, article_id: Id) -> RankingOut:
    explained = digests.explain_ranking(session, article_id)
    article = explained.article
    return RankingOut(
        article_id=article.id,
        position=article.digest_position,
        topic=article.topic,
        why_it_matters=article.why_it_matters,
        rank=article.rank,
        pool=explained.pool,
        ranked=explained.ranked,
        top=explained.top,
        ranking_method=explained.ranking_method,
        deduplicated_to=explained.deduplicated_to,
        deduplication_method=explained.deduplication_method,
        run_id=str(explained.run.id) if explained.run else None,
    )
