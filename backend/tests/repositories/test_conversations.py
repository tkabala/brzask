from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from brzask.db.models import (
    Article,
    Conversation,
    ConversationMessage,
    ConversationSource,
    ConversationSourceOrigin,
    MessageRole,
    MessageStatus,
)
from brzask.repositories import ConversationRepository
from brzask.repositories.conversations import (
    AnswerInProgressError,
    NewSource,
    NotLatestAnswerError,
)
from tests.factories import Factories

AT = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
ANSWER = {"answer": [{"text": "It is.", "sources": [1]}], "enough": True, "suggestions": []}
USAGE = {"calls": 1, "cost_usd": 0.001, "cost_usd_known": 0.001, "unpriced_calls": 0}


def asked(session: Session, make: Factories) -> tuple[ConversationRepository, int, int]:
    """A conversation with one question whose answer is being written."""
    repository = ConversationRepository(session)
    conversation = repository.get_or_create(make.article().id)
    _, answer = repository.add_question(conversation.id, "Why?", AT)
    return repository, conversation.id, answer.id


def test_get_or_create_makes_one_conversation_per_article(
    session: Session, make: Factories
) -> None:
    article = make.article()
    repository = ConversationRepository(session)
    assert repository.for_article(article.id) is None
    first = repository.get_or_create(article.id)
    assert repository.get_or_create(article.id).id == first.id
    assert repository.for_article(article.id) == first


def test_add_question_stores_a_question_and_an_answer_in_progress(
    session: Session, make: Factories
) -> None:
    repository, conversation_id, answer_id = asked(session, make)
    question, answer = repository.messages(conversation_id)
    assert (question.role, question.status, question.text) == (
        MessageRole.USER,
        MessageStatus.DONE,
        "Why?",
    )
    assert (answer.id, answer.role, answer.status, answer.answer) == (
        answer_id,
        MessageRole.ASSISTANT,
        MessageStatus.ANSWERING,
        None,
    )
    assert repository.latest_answer(conversation_id) == answer


def test_one_answer_in_progress(session: Session, make: Factories) -> None:
    repository, conversation_id, answer_id = asked(session, make)
    with pytest.raises(AnswerInProgressError):
        repository.add_question(conversation_id, "And?", AT)

    repository.finish(
        answer_id, answer=ANSWER, model="m", usage=USAGE, searched=False, note=None, at=AT
    )
    _, second = repository.add_question(conversation_id, "And?", AT + timedelta(minutes=1))
    assert repository.latest_answer(conversation_id) == second
    assert [m.text for m in repository.messages(conversation_id)] == ["Why?", None, "And?", None]


def test_a_search_in_progress_also_blocks_a_question(session: Session, make: Factories) -> None:
    repository, conversation_id, answer_id = asked(session, make)
    repository.finish(
        answer_id, answer=ANSWER, model="m", usage=USAGE, searched=False, note=None, at=AT
    )
    repository.begin(answer_id, MessageStatus.SEARCHING)
    with pytest.raises(AnswerInProgressError):
        repository.add_question(conversation_id, "And?", AT)
    with pytest.raises(AnswerInProgressError):
        repository.begin(answer_id, MessageStatus.SEARCHING)


def test_begin_sees_an_answer_another_request_put_in_progress(
    session: Session, make: Factories
) -> None:
    repository, _, answer_id = asked(session, make)
    repository.fail(answer_id, "timeout", None, AT)
    # Read before the other request commits, and held, as the services hold it.
    seen = repository.message(answer_id)
    assert seen is not None and seen.status is MessageStatus.FAILED
    # What a second request committing first leaves behind, unseen by this session's row.
    session.execute(
        update(ConversationMessage)
        .where(ConversationMessage.id == answer_id)
        .values(status=MessageStatus.ANSWERING)
        .execution_options(synchronize_session=False)
    )
    with pytest.raises(AnswerInProgressError):
        repository.begin(answer_id, MessageStatus.SEARCHING)


def test_begin_only_on_the_latest_answer(session: Session, make: Factories) -> None:
    repository, conversation_id, first = asked(session, make)
    repository.fail(first, "timeout", None, AT)
    _, second = repository.add_question(conversation_id, "And?", AT)
    repository.fail(second.id, "timeout", None, AT)

    with pytest.raises(NotLatestAnswerError):
        repository.begin(first, MessageStatus.ANSWERING)
    repository.begin(second.id, MessageStatus.ANSWERING)
    assert repository.message(second.id) is not None
    assert second.status is MessageStatus.ANSWERING


def test_begin_refuses_a_question_row(session: Session, make: Factories) -> None:
    repository, conversation_id, answer_id = asked(session, make)
    repository.fail(answer_id, "timeout", None, AT)
    question = repository.messages(conversation_id)[0]
    with pytest.raises(NotLatestAnswerError):
        repository.begin(question.id, MessageStatus.SEARCHING)


def test_finish_and_fail_record_the_outcome(session: Session, make: Factories) -> None:
    repository, _, answer_id = asked(session, make)
    repository.fail(answer_id, "timeout", USAGE, AT)
    failed = repository.message(answer_id)
    assert failed is not None
    assert (failed.status, failed.error, failed.usage, failed.finished_at) == (
        MessageStatus.FAILED,
        "timeout",
        USAGE,
        AT,
    )

    repository.begin(answer_id, MessageStatus.ANSWERING)
    repository.finish(
        answer_id, answer=ANSWER, model="m", usage=USAGE, searched=True, note=None, at=AT
    )
    done = repository.message(answer_id)
    assert done is not None
    assert (done.status, done.answer, done.model, done.searched, done.error) == (
        MessageStatus.DONE,
        ANSWER,
        "m",
        True,
        None,
    )


def test_keep_with_note_keeps_an_answer_done_and_fails_an_empty_one(
    session: Session, make: Factories
) -> None:
    repository, _, answer_id = asked(session, make)
    repository.keep_with_note(answer_id, "interrupted", None, AT)
    empty = repository.message(answer_id)
    assert empty is not None
    assert (empty.status, empty.error) == (MessageStatus.FAILED, "interrupted")

    repository.begin(answer_id, MessageStatus.ANSWERING)
    repository.finish(
        answer_id, answer=ANSWER, model="m", usage=USAGE, searched=False, note=None, at=AT
    )
    repository.begin(answer_id, MessageStatus.SEARCHING)
    repository.keep_with_note(answer_id, "The search found nothing new.", USAGE, AT)
    kept = repository.message(answer_id)
    assert kept is not None
    assert (kept.status, kept.answer, kept.note, kept.error, kept.usage) == (
        MessageStatus.DONE,
        ANSWER,
        "The search found nothing new.",
        None,
        USAGE,
    )


def test_add_sources_numbers_are_stable(session: Session, make: Factories) -> None:
    repository = ConversationRepository(session)
    conversation = repository.get_or_create(make.article().id)
    web = ConversationSourceOrigin.WEB
    added = repository.add_sources(
        conversation.id,
        [NewSource("https://a.example/", "A", web), NewSource("https://b.example/", "B", web)],
    )
    assert [(s.n, s.url, s.text) for s in added] == [
        (1, "https://a.example/", None),
        (2, "https://b.example/", None),
    ]
    repository.add_sources(
        conversation.id,
        [
            NewSource("https://b.example/", "B again", web, text="B's text"),
            NewSource("https://c.example/", "C", web, text="C's text"),
            NewSource("https://c.example/", "C twice", web, text="other"),
        ],
    )
    repository.add_sources(conversation.id, [NewSource("https://b.example/", "B", web, text="new")])

    assert [(s.n, s.url, s.title, s.text) for s in repository.sources(conversation.id)] == [
        (1, "https://a.example/", "A", None),
        (2, "https://b.example/", "B", "B's text"),
        (3, "https://c.example/", "C", "C's text"),
    ]


def test_add_sources_returns_what_changed(session: Session, make: Factories) -> None:
    repository = ConversationRepository(session)
    conversation = repository.get_or_create(make.article().id)
    web = ConversationSourceOrigin.WEB
    repository.add_sources(conversation.id, [NewSource("https://a.example/", "A", web)])
    changed = repository.add_sources(
        conversation.id,
        [
            NewSource("https://a.example/", "A", web),
            NewSource("https://a.example/", "A", web, text="now with text"),
            NewSource("https://b.example/", "B", web),
        ],
    )
    assert [s.n for s in changed] == [1, 2]


def test_settle_interrupted(session: Session, make: Factories) -> None:
    repository, _, answering = asked(session, make)
    other = ConversationRepository(session)
    conversation = other.get_or_create(make.article().id)
    _, searched = other.add_question(conversation.id, "What?", AT)
    other.finish(
        searched.id, answer=ANSWER, model="m", usage=USAGE, searched=False, note=None, at=AT
    )
    other.begin(searched.id, MessageStatus.SEARCHING)

    assert repository.settle_interrupted(AT) == 2
    first = repository.message(answering)
    second = repository.message(searched.id)
    assert first is not None and second is not None
    assert (first.status, first.error) == (MessageStatus.FAILED, "interrupted")
    assert (second.status, second.note, second.answer) == (
        MessageStatus.DONE,
        "interrupted",
        ANSWER,
    )
    assert repository.settle_interrupted(AT) == 0


def test_question_counts(session: Session, make: Factories) -> None:
    repository, conversation_id, answer_id = asked(session, make)
    repository.finish(
        answer_id, answer=ANSWER, model="m", usage=USAGE, searched=False, note=None, at=AT
    )
    repository.add_question(conversation_id, "And?", AT)
    conversation = session.get(Conversation, conversation_id)
    assert conversation is not None
    article_id = conversation.article_id
    quiet = make.article()
    assert repository.question_counts([article_id, quiet.id]) == {article_id: 2}
    assert repository.question_counts([]) == {}


def test_deleting_the_article_deletes_everything(session: Session, make: Factories) -> None:
    repository, conversation_id, _ = asked(session, make)
    repository.add_sources(
        conversation_id,
        [NewSource("https://a.example/", "A", ConversationSourceOrigin.ARTICLE)],
    )
    conversation = session.get(Conversation, conversation_id)
    assert conversation is not None
    article_id = conversation.article_id
    session.expunge_all()

    session.execute(delete(Article).where(Article.id == article_id))

    for model in (Conversation, ConversationMessage, ConversationSource):
        assert session.scalar(select(func.count()).select_from(model)) == 0
