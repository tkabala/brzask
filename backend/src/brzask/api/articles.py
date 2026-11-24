"""Articles, and why one was ranked where it was."""

from datetime import UTC, date, datetime
from http import HTTPStatus

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from brzask.api import problems
from brzask.api.auth import Auth, AuthConfig
from brzask.api.deps import DbSession, Id
from brzask.db.models import Article, ArticleState, BriefBasis
from brzask.repositories import ConversationRepository
from brzask.services import digests, opens

router = APIRouter(prefix="/articles", tags=["articles"])


class SourceRef(BaseModel):
    id: int
    name: str


class ArticleOut(BaseModel):
    id: int
    link: str
    open_url: str = Field(
        description="Follow this instead of `link` to record the open (relative to the server); "
        "signed, so it works without a session, e.g. from a feed reader."
    )
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
    has_brief: bool = Field(description="Whether `/articles/{id}/brief` has a brief to show.")
    brief_opened_at: datetime | None = Field(description="First view of the brief.")

    @classmethod
    def of(cls, article: Article, links: Auth, has_brief: bool) -> "ArticleOut":
        source = article.source
        return cls(
            id=article.id,
            link=article.link,
            open_url=links.open_url(article.id),
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
            has_brief=has_brief,
            brief_opened_at=article.brief_opened_at,
        )


class ChapterOut(BaseModel):
    start: int = Field(description="Seconds from the start of the video.")
    title: str
    open_url: str = Field(
        description="Opens the video at `start` and records the open, like the article's "
        "`open_url`."
    )


class BriefOut(BaseModel):
    """What an article says, written ahead from its text."""

    article: ArticleOut
    gist: str = Field(description="What it says, in a sentence or two.")
    points: list[str] = Field(description="Its main points, with their specifics.")
    caveats: list[str] = Field(description="What to keep in mind when reading it.")
    chapters: list[ChapterOut] = Field(description="Of a video; empty for anything else.")
    basis: BriefBasis = Field(description="What text the brief was written from.")
    conversation_questions: int = Field(description="Questions asked about the article.")


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
def get_article(session: DbSession, config: AuthConfig, article_id: Id) -> ArticleOut:
    article = digests.get_article(session, article_id)
    return ArticleOut.of(article, config, article.id in digests.briefed(session, [article]))


@router.get(
    "/{article_id}/brief",
    summary="Get an article's brief",
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def get_brief(session: DbSession, config: AuthConfig, article_id: Id) -> BriefOut:
    """404 when the article is unknown or has no brief (yet)."""
    article, brief = digests.get_brief(session, article_id)
    return BriefOut(
        article=ArticleOut.of(article, config, has_brief=True),
        gist=brief.gist,
        points=brief.points,
        caveats=brief.caveats,
        chapters=[
            ChapterOut(
                start=chapter["start"],
                title=chapter["title"],
                open_url=config.open_url(article.id, chapter["start"]),
            )
            for chapter in brief.chapters
        ],
        basis=brief.basis,
        conversation_questions=ConversationRepository(session)
        .question_counts([article.id])
        .get(article.id, 0),
    )


@router.post(
    "/{article_id}/brief-open",
    summary="Record a view of an article's brief",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def record_brief_open(session: DbSession, article_id: Id) -> None:
    """Keeps the first view only, a preference signal like opening the original.

    404, recording nothing, when the article is unknown or has no brief.
    """
    opens.open_brief(session, article_id, datetime.now(UTC))


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
