from contextlib import nullcontext
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brzask.clients.llm import LLMError
from brzask.config.settings import BudgetSettings
from brzask.db.models import (
    ArticleBrief,
    BriefBasis,
    Conversation,
    DeepDiveStatus,
    MessageStatus,
)
from brzask.repositories import ConversationRepository
from tests.factories import Factories
from tests.services.conversation_fakes import NOW, VALID, FakeModel, always, readable

PROBLEM = "application/problem+json"


class FakeWorker:
    def __init__(self) -> None:
        self.submitted: list[int] = []

    def submit(self, message_id: int) -> None:
        self.submitted.append(message_id)

    def close(self, grace: float = 5.0) -> None:
        pass


@pytest.fixture
def model(app: FastAPI) -> FakeModel:
    fake = FakeModel(always(VALID))
    app.state.clients.conversation_model = lambda: nullcontext(fake)
    return fake


@pytest.fixture
def worker(app: FastAPI) -> FakeWorker:
    fake = FakeWorker()
    app.state.conversation_search = fake
    return fake


@pytest.fixture
def over_budget(monkeypatch: pytest.MonkeyPatch, session: Session, make: Factories) -> None:
    from brzask.api import conversations

    budget = BudgetSettings(daily_usd=Decimal("0.01"), monthly_usd=None)
    monkeypatch.setattr(conversations, "_limits", lambda: (budget, NOW.tzinfo))
    make.run(NOW, cost=0.02)
    session.commit()


def asked(client: TestClient, article_id: int, text: str = "Why?") -> dict[str, Any]:
    response = client.post(
        f"/api/v1/articles/{article_id}/conversation/messages", json={"text": text}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_an_article_without_a_conversation(
    client: TestClient, session: Session, make: Factories, model: FakeModel
) -> None:
    article = readable(session, make)

    body = client.get(f"/api/v1/articles/{article.id}/conversation").json()

    assert body == {
        "article": {"id": article.id, "title": "Postgres 18"},
        "messages": [],
        "sources": [],
        "can_ask": True,
        "reason": None,
        "web_search": False,
    }
    assert session.scalar(select(func.count()).select_from(Conversation)) == 0


def test_cannot_ask_without_content(client: TestClient, session: Session, make: Factories) -> None:
    article = make.article()
    session.commit()
    body = client.get(f"/api/v1/articles/{article.id}/conversation").json()
    assert (body["can_ask"], body["reason"]) == (
        False,
        "this article has no stored text to ask about",
    )
    response = client.post(
        f"/api/v1/articles/{article.id}/conversation/messages", json={"text": "Why?"}
    )
    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM


def test_cannot_ask_over_budget(
    client: TestClient, session: Session, make: Factories, over_budget: None
) -> None:
    article = readable(session, make)
    body = client.get(f"/api/v1/articles/{article.id}/conversation").json()
    assert body["can_ask"] is False and body["reason"].startswith("daily LLM budget")
    response = client.post(
        f"/api/v1/articles/{article.id}/conversation/messages", json={"text": "Why?"}
    )
    assert response.status_code == 409
    assert "daily LLM budget" in response.json()["detail"]


def test_ask(client: TestClient, session: Session, make: Factories, model: FakeModel) -> None:
    article = readable(session, make)

    body = asked(client, article.id, "  Why?  ")

    assert body["question"]["role"] == "user" and body["question"]["text"] == "Why?"
    answer = body["answer"]
    assert (answer["role"], answer["status"], answer["searched"], answer["text"]) == (
        "assistant",
        "done",
        False,
        None,
    )
    assert answer["answer"] == {
        "paragraphs": [{"text": "It reads ahead.", "sources": [1]}],
        "enough": True,
        "suggestions": ["How do I turn it on?"],
    }
    conversation = client.get(f"/api/v1/articles/{article.id}/conversation").json()
    assert [m["id"] for m in conversation["messages"]] == [body["question"]["id"], answer["id"]]
    assert conversation["sources"] == [
        {
            "n": 1,
            "url": article.link,
            "title": "Postgres 18",
            "origin": "article",
            "open_url": conversation["sources"][0]["open_url"],
        }
    ]


@pytest.mark.parametrize("text", ["", "   ", "x" * 1001])
def test_a_question_must_have_one_to_a_thousand_characters(
    client: TestClient, session: Session, make: Factories, model: FakeModel, text: str
) -> None:
    article = readable(session, make)
    response = client.post(
        f"/api/v1/articles/{article.id}/conversation/messages", json={"text": text}
    )
    assert response.status_code == 422


def test_ask_about_an_unknown_article(client: TestClient, model: FakeModel) -> None:
    response = client.post("/api/v1/articles/404/conversation/messages", json={"text": "Why?"})
    assert response.status_code == 404


def test_ask_while_an_answer_is_in_progress(
    client: TestClient, session: Session, make: Factories, model: FakeModel
) -> None:
    article = readable(session, make)
    repository = ConversationRepository(session)
    repository.add_question(repository.get_or_create(article.id).id, "Why?", NOW)
    session.commit()
    response = client.post(
        f"/api/v1/articles/{article.id}/conversation/messages", json={"text": "And?"}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "an answer is still being written"


def test_a_failing_model_is_a_failed_answer_not_an_error(
    client: TestClient, session: Session, make: Factories, model: FakeModel
) -> None:
    article = readable(session, make)
    model.llm.answers = always(LLMError("conversation: gave up after 1 attempts: timed out"))
    body = asked(client, article.id)
    assert body["answer"]["status"] == "failed"
    assert "timed out" in body["answer"]["error"]

    model.llm.answers = always(VALID)
    retried = client.post(f"/api/v1/conversation-messages/{body['answer']['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "done"
    again = client.post(f"/api/v1/conversation-messages/{body['answer']['id']}/retry")
    assert again.status_code == 409


def test_retry_only_the_latest_answer(
    client: TestClient, session: Session, make: Factories, model: FakeModel
) -> None:
    article = readable(session, make)
    model.llm.answers = always(LLMError("boom"))
    first = asked(client, article.id)["answer"]["id"]
    asked(client, article.id, "And?")
    assert client.post(f"/api/v1/conversation-messages/{first}/retry").status_code == 409
    assert client.post("/api/v1/conversation-messages/404/retry").status_code == 404


def test_search(
    client: TestClient, session: Session, make: Factories, model: FakeModel, worker: FakeWorker
) -> None:
    article = readable(session, make)
    first = asked(client, article.id)["answer"]["id"]
    latest = asked(client, article.id, "And?")["answer"]["id"]

    assert client.post(f"/api/v1/conversation-messages/{first}/search").status_code == 409
    response = client.post(f"/api/v1/conversation-messages/{latest}/search")
    assert response.status_code == 202
    assert response.json()["status"] == "searching"
    assert worker.submitted == [latest]
    assert client.post(f"/api/v1/conversation-messages/{latest}/search").status_code == 409
    response = client.post(
        f"/api/v1/articles/{article.id}/conversation/messages", json={"text": "More?"}
    )
    assert response.status_code == 409


def test_search_over_budget(
    client: TestClient,
    session: Session,
    make: Factories,
    model: FakeModel,
    worker: FakeWorker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = readable(session, make)
    latest = asked(client, article.id)["answer"]["id"]
    from brzask.api import conversations

    budget = BudgetSettings(daily_usd=Decimal("0.0001"), monthly_usd=None)
    monkeypatch.setattr(conversations, "_limits", lambda: (budget, NOW.tzinfo))
    response = client.post(f"/api/v1/conversation-messages/{latest}/search")
    assert response.status_code == 409
    assert worker.submitted == []


def test_markdown(client: TestClient, session: Session, make: Factories, model: FakeModel) -> None:
    article = readable(session, make)
    assert client.get(f"/api/v1/articles/{article.id}/conversation/markdown").status_code == 404
    asked(client, article.id)

    response = client.get(f"/api/v1/articles/{article.id}/conversation/markdown")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"].endswith('-postgres-18-conversation.md"')
    assert "**Why?**" in response.text and "It reads ahead. [1]" in response.text


def test_question_counts_on_the_brief_and_the_deep_dive(
    client: TestClient, session: Session, make: Factories, model: FakeModel
) -> None:
    article = readable(session, make)
    session.add(
        ArticleBrief(
            article_id=article.id,
            gist="G.",
            points=["a", "b", "c"],
            caveats=[],
            chapters=[],
            basis=BriefBasis.FULL_TEXT,
            model="m",
        )
    )
    dive = make.deep_dive(article, status=DeepDiveStatus.DONE, sources=[])
    session.commit()
    assert client.get(f"/api/v1/articles/{article.id}/brief").json()["conversation_questions"] == 0
    asked(client, article.id)
    asked(client, article.id, "And?")

    assert client.get(f"/api/v1/articles/{article.id}/brief").json()["conversation_questions"] == 2
    assert client.get(f"/api/v1/deep-dives/{dive.id}").json()["conversation_questions"] == 2


def test_a_searching_answer_reads_as_searching(
    client: TestClient, session: Session, make: Factories, model: FakeModel, worker: FakeWorker
) -> None:
    article = readable(session, make)
    latest = asked(client, article.id)["answer"]["id"]
    client.post(f"/api/v1/conversation-messages/{latest}/search")
    messages = client.get(f"/api/v1/articles/{article.id}/conversation").json()["messages"]
    assert messages[-1]["status"] == MessageStatus.SEARCHING.value
    assert messages[-1]["answer"]["paragraphs"][0]["text"] == "It reads ahead."


@pytest.mark.parametrize("auth_settings", ["password"], indirect=True)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/articles/1/conversation"),
        ("post", "/api/v1/articles/1/conversation/messages"),
        ("post", "/api/v1/conversation-messages/1/retry"),
        ("post", "/api/v1/conversation-messages/1/search"),
        ("get", "/api/v1/articles/1/conversation/markdown"),
    ],
)
def test_every_endpoint_needs_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json={"text": "Why?"}).status_code == 401
