from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.llm import LLMError
from brzask.config.settings import BudgetSettings
from brzask.db.models import (
    ConversationMessage,
    ConversationSourceOrigin,
    DeepDiveStatus,
    MessageRole,
    MessageStatus,
)
from brzask.repositories import ConversationRepository
from brzask.services.conversation.ask import (
    ANSWER_TIMEOUT,
    AnswerBusyError,
    BudgetReachedError,
    NoContentError,
    answer_again,
    ask,
    can_ask,
)
from brzask.services.errors import ConflictError, NotFoundError
from tests.factories import Factories
from tests.services.conversation_fakes import (
    NOW,
    VALID,
    FakeModel,
    always,
    clients,
    readable,
)

DIVE_SOURCES = [
    {"n": 1, "url": "https://pg.example/18", "title": "Postgres 18", "origin": "article"},
    {"n": 2, "url": "https://docs.example/io", "title": "Docs", "origin": "web"},
    {
        "n": 3,
        "url": "https://old.example/",
        "title": "Old",
        "origin": "archive",
        "article_id": None,
    },
]


def stored(session: Session, message_id: int) -> ConversationMessage:
    session.expire_all()
    message = ConversationRepository(session).message(message_id)
    assert message is not None
    return message


def message_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ConversationMessage)) or 0


def test_ask_stores_question_and_answer(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    model = FakeModel(always(VALID))

    question_id, answer_id = ask(sessions, clients(model), article.id, "  Why?  ", NOW)

    question, answer = stored(session, question_id), stored(session, answer_id)
    assert (question.role, question.text, question.status) == (
        MessageRole.USER,
        "Why?",
        MessageStatus.DONE,
    )
    assert (answer.status, answer.answer, answer.model, answer.error) == (
        MessageStatus.DONE,
        VALID,
        "test/brief-model",
        None,
    )
    assert answer.usage["calls"] == 1 and answer.usage["cost_usd"] == 0.001
    assert answer.finished_at is not None
    assert model.llm.purposes == ["conversation"]
    assert 0 < model.bounds[0] <= ANSWER_TIMEOUT
    assert "Why?" in model.llm.prompts[0]
    sources = ConversationRepository(session).sources(answer.conversation_id)
    assert [(s.n, s.url, s.origin) for s in sources] == [
        (1, article.link, ConversationSourceOrigin.ARTICLE)
    ]


def test_ask_adds_the_sources_of_a_finished_dive_once(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make, link="https://pg.example/18")
    make.deep_dive(article, status=DeepDiveStatus.DONE, sources=DIVE_SOURCES)
    make.deep_dive(
        article,
        status=DeepDiveStatus.RUNNING,
        sources=[{"n": 2, "url": "https://running.example/", "title": "R", "origin": "web"}],
    )
    session.commit()

    _, first = ask(sessions, clients(), article.id, "Why?", NOW)
    ask(sessions, clients(), article.id, "And?", NOW)

    sources = ConversationRepository(session).sources(stored(session, first).conversation_id)
    assert [(s.n, s.url, s.origin) for s in sources] == [
        (1, "https://pg.example/18", ConversationSourceOrigin.ARTICLE),
        (2, "https://docs.example/io", ConversationSourceOrigin.REPORT),
        (3, "https://old.example/", ConversationSourceOrigin.ARCHIVE),
    ]


def test_a_dive_finished_later_adds_its_sources_after_the_others(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make, link="https://pg.example/18")
    _, first = ask(sessions, clients(), article.id, "Why?", NOW)
    make.deep_dive(article, status=DeepDiveStatus.DONE, sources=DIVE_SOURCES)
    session.commit()

    ask(sessions, clients(), article.id, "And?", NOW)

    sources = ConversationRepository(session).sources(stored(session, first).conversation_id)
    assert [s.n for s in sources] == [1, 2, 3]
    assert sources[0].url == "https://pg.example/18"


def test_the_answer_may_cite_only_the_conversations_sources(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    model = FakeModel(always({"answer": [{"text": "A.", "sources": [1, 2, 9]}]}))
    _, answer_id = ask(sessions, clients(model), article.id, "Why?", NOW)
    answer = stored(session, answer_id).answer
    assert answer is not None and answer["answer"] == [{"text": "A.", "sources": [1]}]


def test_a_failing_model_keeps_the_question(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    model = FakeModel(always(LLMError("conversation: status 500")))

    question_id, answer_id = ask(sessions, clients(model), article.id, "Why?", NOW)

    answer = stored(session, answer_id)
    assert (answer.status, answer.answer) == (MessageStatus.FAILED, None)
    assert answer.error is not None and "status 500" in answer.error
    assert stored(session, question_id).text == "Why?"


def test_an_answer_that_cannot_be_stored_fails(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    # Postgres JSONB refuses a NUL character.
    model = FakeModel(always({"answer": [{"text": "It\u0000 reads.", "sources": [1]}]}))

    _, answer_id = ask(sessions, clients(model), article.id, "Why?", NOW)

    assert stored(session, answer_id).status is MessageStatus.FAILED


def test_a_slow_model_fails_within_the_timeout(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    timeout = LLMError("conversation: gave up after 1 attempts: Request timed out.")
    model = FakeModel(always(timeout))

    _, answer_id = ask(sessions, clients(model), article.id, "Why?", NOW)

    assert stored(session, answer_id).status is MessageStatus.FAILED
    assert model.bounds == [ANSWER_TIMEOUT] or model.bounds[0] <= ANSWER_TIMEOUT


def test_an_unusable_answer_is_asked_again_while_there_is_time(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    model = FakeModel(lambda _p, n: {} if n == 1 else VALID)

    _, answer_id = ask(sessions, clients(model), article.id, "Why?", NOW)

    answer = stored(session, answer_id)
    assert answer.status is MessageStatus.DONE
    assert answer.usage["calls"] == 2
    assert len(model.bounds) == 2 and model.bounds[1] <= model.bounds[0]


def test_no_second_try_when_the_time_is_up(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    model = FakeModel(lambda _p, n: {} if n == 1 else VALID)
    ticks = iter([0.0, 44.0, 44.0, 44.0])

    _, answer_id = ask(sessions, clients(model, clock=lambda: next(ticks)), article.id, "Why?", NOW)

    answer = stored(session, answer_id)
    assert answer.status is MessageStatus.FAILED
    assert answer.usage["calls"] == 1
    assert len(model.bounds) == 1


def test_ask_is_refused_without_content(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = make.article()
    session.commit()
    with pytest.raises(NoContentError):
        ask(sessions, clients(), article.id, "Why?", NOW)
    assert ConversationRepository(session).for_article(article.id) is None
    assert can_ask(session, article.id, clients(), NOW)[0] is False


def test_ask_is_refused_over_budget(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    make.run(NOW, cost=0.02)
    session.commit()
    budget = BudgetSettings(daily_usd=Decimal("0.01"), monthly_usd=None)

    with pytest.raises(BudgetReachedError, match="daily LLM budget"):
        ask(sessions, clients(budget=budget), article.id, "Why?", NOW)

    assert message_count(session) == 0
    allowed, reason = can_ask(session, article.id, clients(budget=budget), NOW)
    assert not allowed and reason is not None and reason.startswith("daily LLM budget")
    assert can_ask(session, article.id, clients(), NOW) == (True, None)


def test_ask_is_refused_while_an_answer_is_in_progress(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    repository = ConversationRepository(session)
    repository.add_question(repository.get_or_create(article.id).id, "Why?", NOW)
    session.commit()

    with pytest.raises(AnswerBusyError):
        ask(sessions, clients(), article.id, "And?", NOW)

    assert message_count(session) == 2


def test_ask_about_an_unknown_article(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(NotFoundError):
        ask(sessions, clients(), 404, "Why?", NOW)


def test_answer_again_fills_the_same_row(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    failing = FakeModel(always(LLMError("boom")))
    _, answer_id = ask(sessions, clients(failing), article.id, "Why?", NOW)

    answer_again(sessions, clients(), answer_id, NOW)

    answer = stored(session, answer_id)
    assert (answer.status, answer.answer, answer.error) == (MessageStatus.DONE, VALID, None)
    assert answer.usage["calls"] == 2  # the failed call was paid for too
    assert message_count(session) == 2


def test_only_a_failed_latest_answer_is_answered_again(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    _, answer_id = ask(sessions, clients(), article.id, "Why?", NOW)
    with pytest.raises(ConflictError):
        answer_again(sessions, clients(), answer_id, NOW)
    with pytest.raises(NotFoundError):
        answer_again(sessions, clients(), 404, NOW)
