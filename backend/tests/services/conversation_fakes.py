"""Fakes and helpers shared by the conversation tests."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from brzask import prompts
from brzask.db.models import Article, ArticleContent, ContentKind
from brzask.services.conversation.ask import Clients
from tests.factories import Factories
from tests.services.test_briefs import FakeLLM

NOW = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
VALID = {
    "answer": [{"text": "It reads ahead.", "sources": [1]}],
    "enough": True,
    "suggestions": ["How do I turn it on?"],
}


class FakeModel:
    """A model whose `bounded` copies answer with `answers(prompt, call number)`."""

    def __init__(self, answers: Callable[[str, int], Any]) -> None:
        self.llm = FakeLLM(answers)
        self.bounds: list[float] = []

    def bounded(self, seconds: float) -> FakeLLM:
        self.bounds.append(seconds)
        return self.llm


def always(value: Any) -> Callable[[str, int], Any]:
    return lambda _prompt, _n: value


def clients(model: FakeModel | None = None, **fields: Any) -> Clients:
    values: dict[str, Any] = {
        "llm": model or FakeModel(always(VALID)),
        "language": prompts.language("en"),
        "budget": None,
        "timezone": UTC,
    }
    values.update(fields)
    return Clients(**values)


def readable(session: Session, make: Factories, **fields: Any) -> Article:
    """A digest article with stored text, committed."""
    values: dict[str, Any] = {"title": "Postgres 18", "digest_date": date(2026, 11, 23)}
    article = make.article(**{**values, **fields})
    session.add(
        ArticleContent(
            article_id=article.id, text="Postgres 18 reads ahead.", kind=ContentKind.PAGE
        )
    )
    session.commit()
    return article
