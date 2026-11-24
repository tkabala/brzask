"""Conversations: the reader's questions about an article, answered from stored material."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints

from brzask import prompts
from brzask.api import problems
from brzask.api.auth import AuthConfig
from brzask.api.deps import NO_NUL, DbSession, Id
from brzask.config import get_settings
from brzask.db.models import (
    ConversationMessage,
    ConversationSource,
    ConversationSourceOrigin,
    MessageRole,
    MessageStatus,
)
from brzask.repositories import ConversationRepository
from brzask.services.conversation import ask as asking
from brzask.services.conversation.markdown import filename, render_conversation
from brzask.services.conversation.search import start_search
from brzask.services.digests import get_article
from brzask.services.errors import NotFoundError

router = APIRouter(tags=["conversations"])

QUESTION_CHARS = 1000  # a question, typed on a phone


class ConversationArticle(BaseModel):
    id: int
    title: str = Field(description="In the digest language when the article was in a digest.")


class ConversationParagraph(BaseModel):
    text: str
    sources: list[int] = Field(description="Numbers of the sources it rests on.")


class ConversationAnswer(BaseModel):
    paragraphs: list[ConversationParagraph]
    enough: bool = Field(description="False when the material did not answer the question.")
    suggestions: list[str] = Field(description="Follow-up questions to offer.")


class ConversationMessageOut(BaseModel):
    id: int
    role: MessageRole
    text: str | None = Field(description="The question; null for answers.")
    answer: ConversationAnswer | None = Field(description="Null until written.")
    status: MessageStatus
    searched: bool = Field(description="Written again after a search round.")
    note: str | None = Field(description="Shown under the answer, e.g. a search's outcome.")
    error: str | None
    created_at: datetime

    @classmethod
    def of(cls, message: ConversationMessage) -> "ConversationMessageOut":
        answer = message.answer
        return cls(
            id=message.id,
            role=message.role,
            text=message.text,
            answer=None
            if answer is None
            else ConversationAnswer(
                paragraphs=[ConversationParagraph(**p) for p in answer["answer"]],
                enough=answer["enough"],
                suggestions=answer["suggestions"],
            ),
            status=message.status,
            searched=message.searched,
            note=message.note,
            error=message.error,
            created_at=message.created_at,
        )


class ConversationSourceOut(BaseModel):
    n: int
    url: str
    title: str
    origin: ConversationSourceOrigin
    open_url: str | None = Field(
        description="For stored articles: follow this to record the open; null otherwise."
    )

    @classmethod
    def of(cls, source: ConversationSource, config: AuthConfig) -> "ConversationSourceOut":
        return cls(
            n=source.n,
            url=source.url,
            title=source.title,
            origin=source.origin,
            open_url=config.open_url(source.article_id) if source.article_id else None,
        )


class ConversationOut(BaseModel):
    article: ConversationArticle
    messages: list[ConversationMessageOut] = Field(description="Oldest first.")
    sources: list[ConversationSourceOut] = Field(description="By number.")
    can_ask: bool
    reason: str | None = Field(description="Why a question cannot be asked now; null when it can.")
    web_search: bool = Field(description="A search round also searches the web.")


class AskRequest(BaseModel):
    text: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=QUESTION_CHARS, pattern=NO_NUL
        ),
    ]


class AskResult(BaseModel):
    question: ConversationMessageOut
    answer: ConversationMessageOut = Field(
        description="Done or failed; a failed one can be retried."
    )


def _limits() -> tuple[Any, Any]:
    settings = get_settings()
    return settings.budget, settings.scheduler.timezone


@contextmanager
def _clients(request: Request) -> Iterator[asking.Clients]:
    budget, tz = _limits()
    with request.app.state.clients.conversation_model() as model:
        yield asking.Clients(
            llm=model,
            language=prompts.language(get_settings().digest.language),
            budget=budget,
            timezone=tz,
        )


def _message(session: DbSession, message_id: int, *, fresh: bool = True) -> ConversationMessageOut:
    if fresh:
        # Written by the service in its own transactions.
        session.expire_all()
    message = ConversationRepository(session).message(message_id)
    if message is None:
        raise NotFoundError(f"no conversation message {message_id}")
    return ConversationMessageOut.of(message)


@router.get(
    "/articles/{article_id}/conversation",
    summary="Get the conversation about an article",
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def get_conversation(session: DbSession, config: AuthConfig, article_id: Id) -> ConversationOut:
    """Empty lists when nothing was asked yet; nothing is created."""
    article = get_article(session, article_id)
    budget, tz = _limits()
    reason = asking.refusal(session, article_id, budget, tz, datetime.now(UTC))
    repository = ConversationRepository(session)
    conversation = repository.for_article(article_id)
    messages = repository.messages(conversation.id) if conversation else []
    sources = repository.sources(conversation.id) if conversation else []
    return ConversationOut(
        article=ConversationArticle(id=article.id, title=article.digest_title or article.title),
        messages=[ConversationMessageOut.of(m) for m in messages],
        sources=[ConversationSourceOut.of(s, config) for s in sources],
        can_ask=reason is None,
        reason=reason,
        web_search=get_settings().web_search.provider is not None,
    )


@router.post(
    "/articles/{article_id}/conversation/messages",
    summary="Ask about an article",
    responses=problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
)
def ask_question(
    request: Request, session: DbSession, article_id: Id, body: AskRequest
) -> AskResult:
    """Answered within the request (at most about 45 s). A model that fails or is
    too slow gives a failed answer, which can be retried. 409 when the article has
    no stored text, an answer is in progress, or the spending limit is reached."""
    with _clients(request) as clients:
        question_id, answer_id = asking.ask(
            request.app.state.sessions, clients, article_id, body.text, datetime.now(UTC)
        )
    return AskResult(question=_message(session, question_id), answer=_message(session, answer_id))


@router.post(
    "/conversation-messages/{message_id}/retry",
    summary="Answer a failed answer again",
    responses=problems.responses(HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
)
def retry_answer(request: Request, session: DbSession, message_id: Id) -> ConversationMessageOut:
    """409 unless it is the conversation's latest answer and failed."""
    with _clients(request) as clients:
        asking.answer_again(request.app.state.sessions, clients, message_id, datetime.now(UTC))
    return _message(session, message_id)


@router.post(
    "/conversation-messages/{message_id}/search",
    summary="Search and answer again",
    status_code=status.HTTP_202_ACCEPTED,
    responses=problems.responses(HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
)
def search_answer(request: Request, session: DbSession, message_id: Id) -> ConversationMessageOut:
    """One search round in the background (the archive, and the web when configured);
    poll the conversation until the answer is no longer `searching`. 409 unless it is
    the latest answer and done or failed, or when the spending limit is reached."""
    budget, tz = _limits()
    start_search(session, message_id, budget, tz, datetime.now(UTC))
    out = _message(session, message_id, fresh=False)
    # Committed first: the worker reads the row in its own transaction.
    session.commit()
    request.app.state.conversation_search.submit(message_id)
    return out


@router.get(
    "/articles/{article_id}/conversation/markdown",
    summary="Export the conversation about an article as Markdown",
    response_class=Response,
    responses={
        200: {"content": {"text/markdown": {"schema": {"type": "string"}}}},
        **problems.responses(HTTPStatus.NOT_FOUND),
    },
)
def conversation_markdown(session: DbSession, article_id: Id) -> Response:
    """Answered questions and the sources they cite; 404 when nothing was asked."""
    article = get_article(session, article_id)
    repository = ConversationRepository(session)
    conversation = repository.for_article(article_id)
    if conversation is None:
        raise NotFoundError(f"no conversation about article {article_id}")
    settings = get_settings()
    messages = repository.messages(conversation.id)
    tz = settings.scheduler.timezone
    text = render_conversation(
        article,
        messages,
        repository.sources(conversation.id),
        prompts.language(settings.digest.language),
        tz,
    )
    return Response(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename(article, messages, tz)}"'
        },
    )
