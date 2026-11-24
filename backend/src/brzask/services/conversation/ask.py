"""Asking a question about an article, answered inside the request.

The question and an answer row in progress are stored first, so a slow or
failing model never loses the question. The model is called with no
database transaction open and gives up within `ANSWER_TIMEOUT`, so the
request ends before a reverse proxy would cut it.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.llm import InvalidJSONError
from brzask.clients.usage import UsageMeter, combined
from brzask.config.settings import BudgetSettings
from brzask.db.models import ConversationSourceOrigin, MessageRole, MessageStatus
from brzask.log import get_logger
from brzask.prompts import Language
from brzask.repositories import (
    BriefRepository,
    ContentRepository,
    ConversationRepository,
    DeepDiveRepository,
)
from brzask.repositories.conversations import (
    AnswerInProgressError,
    NewSource,
    NotLatestAnswerError,
)
from brzask.services.budget import check_budget
from brzask.services.conversation import context
from brzask.services.conversation.answer import Answer, AnswerError, parse_answer
from brzask.services.digest.ranking import ChatModel, interest_context
from brzask.services.digests import get_article
from brzask.services.errors import ConflictError, NotFoundError

log = get_logger(__name__)

# Real check (2026-11-24, 24 answers and 4 search rounds on 3 articles, deepseek-v4-flash): the
# answer call took 2.2-34.9 s (median about 7 s), so 45 s leaves room for slow
# answers and still ends before a proxy's usual 60 s.
ANSWER_TIMEOUT = 45.0  # seconds; reverse proxies commonly cut requests at 60
MIN_RETRY_SECONDS = 10.0  # an unusable answer is asked again only with this much time left
ERROR_CHARS = 300

NO_CONTENT = "this article has no stored text to ask about"
BUSY = "an answer is still being written"


class NoContentError(ConflictError):
    pass


class BudgetReachedError(ConflictError):
    pass


class AnswerBusyError(ConflictError):
    pass


class BoundedModel(Protocol):
    """A chat model that can give up after a number of seconds (`LLMClient`)."""

    def bounded(self, seconds: float) -> ChatModel: ...


@dataclass(frozen=True, slots=True)
class Clients:
    llm: BoundedModel
    language: Language
    budget: BudgetSettings | None
    timezone: tzinfo
    clock: Callable[[], float] = field(default=time.monotonic)


def can_ask(
    session: Session, article_id: int, clients: Clients, now: datetime
) -> tuple[bool, str | None]:
    """Whether a question about the article can be asked now, and why not."""
    reason = refusal(session, article_id, clients.budget, clients.timezone, now)
    return reason is None, reason


def refusal(
    session: Session,
    article_id: int,
    budget: BudgetSettings | None,
    tz: tzinfo,
    now: datetime,
    *,
    needs_content: bool = True,
) -> str | None:
    """Why the article's conversation cannot take a model call now; None when it can."""
    if needs_content and ContentRepository(session).get(article_id) is None:
        return NO_CONTENT
    if budget is None:
        return None
    state = check_budget(session, now, budget, tz)
    return state.reason if state is not None else None


def ask(
    sessions: sessionmaker[Session], clients: Clients, article_id: int, text: str, now: datetime
) -> tuple[int, int]:
    """Store the question, answer it, and return the ids of both rows.

    Raises before writing anything: `NotFoundError` for an unknown article,
    `NoContentError`, `BudgetReachedError`, `AnswerBusyError`. A failing or
    slow model ends as a failed answer, not as an error.
    """
    started = clients.clock()
    with sessions.begin() as session:
        article = get_article(session, article_id)
        if ContentRepository(session).get(article_id) is None:
            raise NoContentError(NO_CONTENT)
        reason = refusal(
            session, article_id, clients.budget, clients.timezone, now, needs_content=False
        )
        if reason is not None:
            raise BudgetReachedError(reason)
        repository = ConversationRepository(session)
        conversation = repository.get_or_create(article_id)
        article_source = NewSource(
            article.link,
            article.digest_title or article.title,
            ConversationSourceOrigin.ARTICLE,
            article.id,
        )
        dives = list(reversed(DeepDiveRepository(session).for_article(article_id)))
        repository.add_sources(conversation.id, [article_source, *context.dive_sources(dives)])
        try:
            question, answer = repository.add_question(conversation.id, text.strip(), now)
        except AnswerInProgressError:
            raise AnswerBusyError(BUSY) from None
        ids = (question.id, answer.id)
    _answer(sessions, clients, ids[1], started)
    return ids


def answer_again(
    sessions: sessionmaker[Session], clients: Clients, message_id: int, now: datetime
) -> None:
    """Answer a failed latest answer again, in the same row."""
    started = clients.clock()
    with sessions.begin() as session:
        repository = ConversationRepository(session)
        message = repository.message(message_id)
        if message is None or message.role is not MessageRole.ASSISTANT:
            raise NotFoundError(f"no answer {message_id}")
        if message.status is not MessageStatus.FAILED:
            raise ConflictError("only a failed answer can be tried again")
        article_id = message.conversation.article_id
        reason = refusal(session, article_id, clients.budget, clients.timezone, now)
        if reason is not None:
            raise BudgetReachedError(reason)
        try:
            repository.begin(message_id, MessageStatus.ANSWERING)
        except NotLatestAnswerError:
            raise ConflictError("only the latest answer can be tried again") from None
        except AnswerInProgressError:
            raise AnswerBusyError(BUSY) from None
    _answer(sessions, clients, message_id, started)


@dataclass(frozen=True, slots=True)
class Material:
    """What an answer is written from, read in one short transaction."""

    prompt: str
    numbers: frozenset[int]
    question: str
    usage: dict[str, Any]  # what the row's earlier calls cost


def material(
    session: Session, message_id: int, language: Language, fresh: Sequence[int] = ()
) -> Material:
    """The prompt for answer `message_id`: its question and everything stored about
    the article; `fresh` numbers the sources a search round just added."""
    repository = ConversationRepository(session)
    message = repository.message(message_id)
    if message is None:
        raise NotFoundError(f"no answer {message_id}")
    conversation = message.conversation
    article = conversation.article
    content = ContentRepository(session).get(article.id)
    if content is None:
        raise NoContentError(NO_CONTENT)
    messages = repository.messages(conversation.id)
    earlier = [m for m in messages if m.id < message_id]
    question = next(m.text for m in reversed(earlier) if m.role is MessageRole.USER)
    sources = repository.sources(conversation.id)
    prompt = context.prompt(
        article,
        content,
        BriefRepository(session).get(article.id),
        list(reversed(DeepDiveRepository(session).for_article(article.id))),
        sources,
        earlier,
        question or "",
        interest_context(session),
        language,
        fresh,
    )
    # The context's size per answer, to check the caps against real conversations.
    log.info(
        "conversation context",
        message_id=message_id,
        chars=len(prompt),
        sources=len(sources),
        source_text_chars=sum(len(s.text or "") for s in sources),
        exchanges=sum(1 for m in earlier if m.role is MessageRole.USER) - 1,
    )
    return Material(prompt, frozenset(s.n for s in sources), question or "", message.usage)


def write(
    llm: BoundedModel,
    found: Material,
    meter: UsageMeter,
    clock: Callable[[], float],
    started: float,
    purpose: str = "conversation",
) -> tuple[Answer, str]:
    """The answer and the model that wrote it; asked once more when the first answer
    is unusable and time is left. Raises the last error otherwise."""
    for attempt in (1, 2):
        left = ANSWER_TIMEOUT - (clock() - started)
        try:
            value, completion = llm.bounded(left).complete_json(
                found.prompt, purpose=purpose, meter=meter
            )
            return parse_answer(value, found.numbers, found.question), completion.usage.model
        except (AnswerError, InvalidJSONError) as error:
            if attempt == 2 or ANSWER_TIMEOUT - (clock() - started) < MIN_RETRY_SECONDS:
                raise
            log.info("conversation answer unusable; asking again", error=str(error))
    raise AssertionError("unreachable")  # pragma: no cover


def _answer(
    sessions: sessionmaker[Session], clients: Clients, message_id: int, started: float
) -> None:
    meter = UsageMeter()
    try:
        with sessions() as session:
            found = material(session, message_id, clients.language)
        answer, model = write(clients.llm, found, meter, clients.clock, started)
        # Inside the try: an answer that cannot be stored must not stay in
        # progress, which would refuse every later question until a restart.
        with sessions.begin() as session:
            ConversationRepository(session).finish(
                message_id,
                answer=answer.as_json(),
                model=model,
                usage=combined(found.usage, meter.summary()),
                searched=False,
                note=None,
                at=datetime.now(UTC),
            )
    except Exception as error:
        log.warning("conversation answer failed", message_id=message_id, error=str(error))
        with sessions.begin() as session:
            usage = _usage(session, message_id, meter)
            ConversationRepository(session).fail(
                message_id, _short(error), usage, datetime.now(UTC)
            )


def _usage(session: Session, message_id: int, meter: UsageMeter) -> dict[str, Any]:
    message = ConversationRepository(session).message(message_id)
    earlier = message.usage if message is not None else {}
    return combined(earlier, meter.summary()) if meter.calls else earlier


def _short(error: Exception) -> str:
    return (str(error) or type(error).__name__)[:ERROR_CHARS]
