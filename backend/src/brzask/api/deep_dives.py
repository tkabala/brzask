"""Deep dives: reports on an article, written in the background on request."""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints

from brzask import prompts
from brzask.api import problems
from brzask.api.auth import AuthConfig
from brzask.api.deps import DbSession, Id
from brzask.api.pagination import DEFAULT_LIMIT, CursorParam, Limit, decode_cursor, page
from brzask.config import get_settings
from brzask.db.models import DeepDive, DeepDiveStatus
from brzask.repositories import ConversationRepository, DeepDiveRepository
from brzask.services import deep_dives

router = APIRouter(tags=["deep dives"])

FOCUS_CHARS = 300


class DeepDiveArticle(BaseModel):
    id: int
    title: str = Field(description="In the digest language when the article was in a digest.")


class DeepDiveRef(BaseModel):
    id: int
    article: DeepDiveArticle
    focus: str = Field(description="What the reader asked to focus on; empty when nothing.")
    status: DeepDiveStatus
    created_at: datetime
    finished_at: datetime | None
    read_at: datetime | None = Field(description="First time the finished report was opened.")

    @classmethod
    def of(cls, dive: DeepDive) -> "DeepDiveRef":
        article = dive.article
        return cls(
            id=dive.id,
            article=DeepDiveArticle(id=article.id, title=article.digest_title or article.title),
            focus=dive.focus,
            status=dive.status,
            created_at=dive.created_at,
            finished_at=dive.finished_at,
            read_at=dive.read_at,
        )


class ArticleDeepDives(BaseModel):
    items: list[DeepDiveRef] = Field(description="Newest first.")
    can_start: bool
    reason: str | None = Field(description="Why a new deep dive cannot start; null when it can.")


class DeepDiveList(BaseModel):
    items: list[DeepDiveRef] = Field(description="Newest first.")
    next_cursor: str | None = Field(
        description="Pass as `cursor` for the next page; null on the last page."
    )
    unread: int = Field(description="Finished and not opened yet.")
    active: int = Field(description="Queued or being written.")


class DeepDiveRequest(BaseModel):
    focus: Annotated[str, StringConstraints(strip_whitespace=True, max_length=FOCUS_CHARS)] = ""


class DeepDiveSource(BaseModel):
    n: int
    url: str
    title: str
    origin: Literal["article", "archive", "web"]
    open_url: str | None = Field(
        description="For archive articles: follow this to record the open; null otherwise."
    )


class DeepDiveParagraph(BaseModel):
    text: str
    sources: list[int] = Field(description="Numbers of the sources it rests on.")


class DeepDiveStep(BaseModel):
    text: str
    command: str | None = Field(description="Verbatim from a source; never run by brzask.")
    sources: list[int]


class DeepDiveReading(BaseModel):
    source: int
    why: str


class DeepDiveReport(BaseModel):
    background: list[DeepDiveParagraph]
    practice: list[DeepDiveStep]
    further: list[DeepDiveReading]


class DeepDiveOut(DeepDiveRef):
    article_link: str
    report: DeepDiveReport | None = Field(description="Null until the deep dive is done.")
    sources: list[DeepDiveSource]
    thin: bool = Field(description="Written from the article alone.")
    searched_web: bool = Field(description="A web search was configured and answered.")
    error: str | None
    conversation_questions: int = Field(description="Questions asked about the article.")


def _limits() -> tuple[Any, Any]:
    settings = get_settings()
    return settings.budget, settings.scheduler.timezone


def _parse_key(values: list[str]) -> tuple[datetime, int]:
    # Unpacked, so a cursor with too few or too many values is a ValueError (a 400).
    created_at, dive_id = values
    return datetime.fromisoformat(created_at), int(dive_id)


def _submit(request: Request, session: DbSession, dive: DeepDive) -> DeepDiveRef:
    # Committed first: the runner reads the dive in its own transaction.
    ref = DeepDiveRef.of(dive)
    session.commit()
    request.app.state.deep_dives.submit(dive.id)
    return ref


@router.get(
    "/articles/{article_id}/deep-dives",
    summary="List an article's deep dives",
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def list_article_dives(session: DbSession, article_id: Id) -> ArticleDeepDives:
    budget, tz = _limits()
    dives, reason = deep_dives.article_dives(session, article_id, datetime.now(UTC), budget, tz)
    return ArticleDeepDives(
        items=[DeepDiveRef.of(dive) for dive in dives], can_start=reason is None, reason=reason
    )


@router.post(
    "/articles/{article_id}/deep-dives",
    summary="Ask for a deep dive",
    status_code=status.HTTP_202_ACCEPTED,
    responses=problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
)
def start_dive(
    request: Request, session: DbSession, article_id: Id, body: DeepDiveRequest
) -> DeepDiveRef:
    """Queued and written in the background. 409 when the article has no stored text,
    the spending limit is reached, or the same focus is already being written."""
    budget, tz = _limits()
    dive = deep_dives.request_dive(session, article_id, body.focus, datetime.now(UTC), budget, tz)
    return _submit(request, session, dive)


@router.get(
    "/deep-dives",
    summary="List deep dives",
    responses=problems.responses(HTTPStatus.BAD_REQUEST),
)
def list_dives(
    session: DbSession, limit: Limit = DEFAULT_LIMIT, cursor: CursorParam = None
) -> DeepDiveList:
    repository = DeepDiveRepository(session)
    before = decode_cursor(cursor, _parse_key)
    items, next_cursor = page(
        repository.page(limit + 1, before),
        limit,
        lambda dive: [dive.created_at.isoformat(), str(dive.id)],
    )
    unread, active = repository.counts()
    return DeepDiveList(
        items=[DeepDiveRef.of(dive) for dive in items],
        next_cursor=next_cursor,
        unread=unread,
        active=active,
    )


@router.get(
    "/deep-dives/{dive_id}",
    summary="Get a deep dive",
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def get_dive(session: DbSession, config: AuthConfig, dive_id: Id) -> DeepDiveOut:
    dive = deep_dives.get_dive(session, dive_id)
    ref = DeepDiveRef.of(dive)
    return DeepDiveOut(
        **ref.model_dump(),
        article_link=dive.article.link,
        report=DeepDiveReport.model_validate(dive.report) if dive.report is not None else None,
        sources=[
            DeepDiveSource(
                n=source["n"],
                url=source["url"],
                title=source["title"],
                origin=source["origin"],
                open_url=config.open_url(source["article_id"])
                if source["origin"] == "archive" and source.get("article_id")
                else None,
            )
            for source in dive.sources
        ],
        thin=dive.thin,
        searched_web=dive.searched_web,
        error=dive.error,
        conversation_questions=ConversationRepository(session)
        .question_counts([dive.article_id])
        .get(dive.article_id, 0),
    )


@router.post(
    "/deep-dives/{dive_id}/read",
    summary="Mark a deep dive read",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def read_dive(session: DbSession, dive_id: Id) -> None:
    """Records the first time only."""
    deep_dives.mark_read(session, dive_id, datetime.now(UTC))


@router.post(
    "/deep-dives/{dive_id}/retry",
    summary="Try a failed deep dive again",
    status_code=status.HTTP_202_ACCEPTED,
    responses=problems.responses(HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
)
def retry_dive(request: Request, session: DbSession, dive_id: Id) -> DeepDiveRef:
    """A new deep dive with the same article and focus; 409 unless this one failed."""
    budget, tz = _limits()
    dive = deep_dives.retry_dive(session, dive_id, datetime.now(UTC), budget, tz)
    return _submit(request, session, dive)


@router.get(
    "/deep-dives/{dive_id}/markdown",
    summary="Export a deep dive as Markdown",
    response_class=Response,
    responses={
        200: {"content": {"text/markdown": {"schema": {"type": "string"}}}},
        **problems.responses(HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
    },
)
def dive_markdown(session: DbSession, dive_id: Id) -> Response:
    """409 until the deep dive is done."""
    settings = get_settings()
    language = prompts.language(settings.digest.language)
    text, name = deep_dives.export_markdown(session, dive_id, language, settings.scheduler.timezone)
    return Response(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
