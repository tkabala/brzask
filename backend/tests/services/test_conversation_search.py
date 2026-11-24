import threading
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.llm import LLMError
from brzask.clients.web_search import SearchResult
from brzask.db.models import (
    ArticleContent,
    ContentKind,
    ConversationMessage,
    ConversationSourceOrigin,
    MessageStatus,
)
from brzask.repositories import ConversationRepository
from brzask.repositories.conversations import NewSource
from brzask.services.conversation.ask import ask
from brzask.services.conversation.search import (
    NOTHING_NEW,
    NOTHING_USED,
    SearchClients,
    SearchWorker,
    parse_search_queries,
    search_round,
    start_search,
)
from brzask.services.deep_dive.plan import Queries
from brzask.services.errors import ConflictError
from tests.factories import Factories
from tests.services.conversation_fakes import NOW, VALID, FakeModel, always, clients, readable
from tests.services.deep_dive_fakes import FakeSearch
from tests.services.digest.fakes import FakeEmbedder, FakeExtractor

DOCS = "https://docs.example/io"
QUERIES = {"web": ["io_uring postgres"], "archive": ["postgres"]}
REWRITTEN = {"answer": [{"text": "Use io_uring.", "sources": [1, 2]}], "enough": True}


def search_clients(model: FakeModel, **fields: Any) -> SearchClients:
    values: dict[str, Any] = {
        "llm": model,
        "embedder": FakeEmbedder(),
        "extractor": FakeExtractor({DOCS: "Set io_method = io_uring."}),
        "search": FakeSearch({"io_uring postgres": [SearchResult(DOCS, "io docs", "s")]}),
        "language": clients().language,
    }
    values.update(fields)
    return SearchClients(**values)


def answered(sessions: sessionmaker[Session], session: Session, make: Factories) -> int:
    """An article's conversation with one done answer, now searching."""
    article = readable(session, make)
    _, answer_id = ask(sessions, clients(), article.id, "How do I enable it?", NOW)
    start_search(session, answer_id, None, clients().timezone, NOW)
    session.commit()
    return answer_id


def stored(session: Session, message_id: int) -> ConversationMessage:
    session.expire_all()
    message = ConversationRepository(session).message(message_id)
    assert message is not None
    return message


def by_call(*answers: Any) -> Callable[[str, int], Any]:
    return lambda _prompt, n: answers[n - 1]


def test_parse_search_queries() -> None:
    value = {"web": ["a", " A ", "b", "c"], "archive": ["x", "y"]}
    assert parse_search_queries(value, "Q?") == Queries(["a", "b"], [], ["x"])
    assert parse_search_queries({"web": [], "archive": []}, " Q? ") == Queries(["Q?"], [], ["Q?"])
    assert parse_search_queries("text", "Q?") == Queries(["Q?"], [], ["Q?"])
    assert parse_search_queries({"archive": ["x"]}, "Q?") == Queries([], [], ["x"])


def test_search_round_adds_sources_and_rewrites_the_answer(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    answer_id = answered(sessions, session, make)
    model = FakeModel(by_call(QUERIES, REWRITTEN))

    search_round(sessions, search_clients(model), answer_id, NOW)

    answer = stored(session, answer_id)
    assert (answer.status, answer.searched, answer.note) == (MessageStatus.DONE, True, None)
    assert answer.answer is not None
    assert answer.answer["answer"] == [{"text": "Use io_uring.", "sources": [1, 2]}]
    sources = ConversationRepository(session).sources(answer.conversation_id)
    assert [(s.n, s.url, s.origin, s.text) for s in sources][1:] == [
        (2, DOCS, ConversationSourceOrigin.WEB, "Set io_method = io_uring.")
    ]
    assert model.llm.purposes == ["conversation_search", "conversation"]
    assert "How do I enable it?" in model.llm.prompts[0]
    assert "Set io_method = io_uring." in model.llm.prompts[1]
    assert "just found sources 2." in model.llm.prompts[1]


def test_a_rewrite_citing_no_new_source_says_so(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    answer_id = answered(sessions, session, make)
    old_only = {"answer": [{"text": "Still only the article.", "sources": [1]}], "enough": False}

    search_round(sessions, search_clients(FakeModel(by_call(QUERIES, old_only))), answer_id, NOW)

    answer = stored(session, answer_id)
    assert (answer.status, answer.searched, answer.note) == (
        MessageStatus.DONE,
        True,
        NOTHING_USED,
    )
    assert answer.answer is not None
    assert answer.answer["answer"][0]["text"] == "Still only the article."


def test_search_usage_is_added_to_the_row(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    answer_id = answered(sessions, session, make)
    search_round(sessions, search_clients(FakeModel(by_call(QUERIES, REWRITTEN))), answer_id, NOW)
    usage = stored(session, answer_id).usage
    assert usage["calls"] == 3
    assert set(usage["by_purpose"]) == {"conversation", "conversation_search"}


def test_search_that_finds_only_known_urls_keeps_the_answer(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    answer_id = answered(sessions, session, make)
    conversation_id = stored(session, answer_id).conversation_id
    ConversationRepository(session).add_sources(
        conversation_id,
        [NewSource(DOCS, "io docs", ConversationSourceOrigin.WEB, text="Already read.")],
    )
    session.commit()
    model = FakeModel(by_call(QUERIES, REWRITTEN))

    search_round(sessions, search_clients(model), answer_id, NOW)

    answer = stored(session, answer_id)
    assert (answer.status, answer.answer, answer.note, answer.searched) == (
        MessageStatus.DONE,
        VALID,
        NOTHING_NEW,
        False,
    )
    assert model.llm.purposes == ["conversation_search"]
    assert answer.usage["calls"] == 2


def test_a_known_url_without_text_gains_it_and_counts_as_new(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    answer_id = answered(sessions, session, make)
    conversation_id = stored(session, answer_id).conversation_id
    ConversationRepository(session).add_sources(
        conversation_id, [NewSource(DOCS, "io docs", ConversationSourceOrigin.REPORT)]
    )
    session.commit()

    search_round(sessions, search_clients(FakeModel(by_call(QUERIES, REWRITTEN))), answer_id, NOW)

    sources = ConversationRepository(session).sources(conversation_id)
    assert [(s.n, s.origin, s.text) for s in sources][1:] == [
        (2, ConversationSourceOrigin.REPORT, "Set io_method = io_uring.")
    ]
    assert stored(session, answer_id).searched is True


def test_search_failure_keeps_the_answer(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    answer_id = answered(sessions, session, make)
    model = FakeModel(by_call(QUERIES, LLMError("conversation: status 500")))

    search_round(sessions, search_clients(model), answer_id, NOW)

    answer = stored(session, answer_id)
    assert (answer.status, answer.answer, answer.searched) == (MessageStatus.DONE, VALID, False)
    assert answer.note is not None and "status 500" in answer.note


def test_a_failed_answer_searched_without_result_stays_failed(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    failing = FakeModel(always(LLMError("boom")))
    _, answer_id = ask(sessions, clients(failing), article.id, "Why?", NOW)
    start_search(session, answer_id, None, clients().timezone, NOW)
    session.commit()

    search_round(sessions, search_clients(FakeModel(always({})), search=None), answer_id, NOW)

    answer = stored(session, answer_id)
    assert (answer.status, answer.error) == (MessageStatus.FAILED, NOTHING_NEW)


def test_a_failing_query_call_searches_for_the_question(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    answer_id = answered(sessions, session, make)
    search = FakeSearch({"How do I enable it?": [SearchResult(DOCS, "io docs", "s")]})
    model = FakeModel(by_call(LLMError("down"), REWRITTEN))

    search_round(sessions, search_clients(model, search=search), answer_id, NOW)

    assert search.calls == [("How do I enable it?", 5)]
    assert stored(session, answer_id).searched is True


def test_search_without_web_search_uses_the_archive(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    answer_id = answered(sessions, session, make)
    older = make.article(title="postgres tuning notes", link="https://old.example/tuning")
    session.add(ArticleContent(article_id=older.id, text="Tune it.", kind=ContentKind.PAGE))
    session.commit()

    search_round(
        sessions,
        search_clients(FakeModel(by_call(QUERIES, REWRITTEN)), search=None),
        answer_id,
        NOW,
    )

    conversation_id = stored(session, answer_id).conversation_id
    sources = ConversationRepository(session).sources(conversation_id)
    assert [(s.url, s.origin, s.article_id, s.text) for s in sources][1:] == [
        ("https://old.example/tuning", ConversationSourceOrigin.ARCHIVE, older.id, "Tune it.")
    ]


def test_start_search_only_on_the_latest_finished_answer(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = readable(session, make)
    _, first = ask(sessions, clients(), article.id, "Why?", NOW)
    _, second = ask(sessions, clients(), article.id, "And?", NOW)
    with pytest.raises(ConflictError):
        start_search(session, first, None, clients().timezone, NOW)
    start_search(session, second, None, clients().timezone, NOW)
    with pytest.raises(ConflictError):
        start_search(session, second, None, clients().timezone, NOW)
    assert stored(session, second).status is MessageStatus.SEARCHING


def test_the_worker_runs_rounds_in_order_and_survives_a_failure(
    sessions: sessionmaker[Session],
) -> None:
    done: list[int] = []
    finished = threading.Event()

    def round_(_sessions: Any, _clients: Any, message_id: int, _now: Any) -> None:
        if message_id == 1:
            raise RuntimeError("boom")
        done.append(message_id)
        if message_id == 3:
            finished.set()

    worker = SearchWorker(sessions, lambda _sessions: nullcontext(None), round_=round_)  # type: ignore[arg-type]
    for message_id in (1, 2, 3):
        worker.submit(message_id)
    assert finished.wait(5)
    worker.close()
    assert done == [2, 3]


def test_the_worker_keeps_the_answer_when_its_clients_cannot_be_built(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    answer_id = answered(sessions, session, make)

    def broken(_sessions: Any) -> Any:
        raise RuntimeError("no embedding model")

    worker = SearchWorker(sessions, broken)
    worker.submit(answer_id)
    worker.close()

    message = stored(session, answer_id)
    assert message.status is MessageStatus.DONE
    assert message.note == "no embedding model"
    assert message.answer is not None
