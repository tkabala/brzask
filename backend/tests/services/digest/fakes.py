"""Fakes for the digest stages' clients, and a run context to pass them."""

import threading
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.embeddings import EmbeddingKind
from brzask.clients.extractors import SNIPPET, ExtractionInput, ExtractionResult
from brzask.clients.feeds import FeedEntry, FeedRequest, FeedResult
from brzask.clients.judge import JudgeError, Judgement, Question, Score, ScoreAnswer, Text
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.db.models import EMBEDDING_DIMENSIONS, RunKind
from brzask.services.runs import RunContext
from tests.factories import TEST_MODEL

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)


def context(
    sessions: sessionmaker[Session], *, dry_run: bool = False, started_at: datetime = NOW
) -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        kind=RunKind.DIGEST,
        started_at=started_at,
        sessions=sessions,
        dry_run=dry_run,
    )


def entry(link: str, published_at: datetime | None = NOW) -> FeedEntry:
    return FeedEntry(link, link.rsplit("/", 1)[-1], "Summary", "Content", published_at)


class FakeFeeds:
    """Answers each feed URL with its result from `results`."""

    def __init__(self, results: dict[str, FeedResult]) -> None:
        self.results = results
        self.requests: list[FeedRequest] = []

    def fetch_all(self, requests: Sequence[FeedRequest]) -> list[FeedResult]:
        self.requests.extend(requests)
        return [self.results[request.url] for request in requests]


class FakeExtractor:
    """Returns `texts[url]` as extracted by trafilatura, else falls back to the snippet."""

    def __init__(self, texts: dict[str, str] | None = None) -> None:
        self.texts = texts or {}
        self.inputs: list[ExtractionInput] = []
        self.threads: set[int] = set()
        self._lock = threading.Lock()

    def extract(self, item: ExtractionInput) -> ExtractionResult:
        with self._lock:
            self.inputs.append(item)
            self.threads.add(threading.get_ident())
        if item.url in self.texts:
            return ExtractionResult(self.texts[item.url], "trafilatura")
        if item.snippet:
            return ExtractionResult(item.snippet, SNIPPET)
        return ExtractionResult(None, None)


class FakeEmbedder:
    """Gives each distinct text its own axis, so different texts are never similar."""

    model = TEST_MODEL

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], EmbeddingKind]] = []
        self.vectors: dict[str, list[float]] = {}
        self.error = error

    def embed(
        self,
        texts: Sequence[str],
        kind: EmbeddingKind,
        *,
        purpose: str = "embedding",
        meter: UsageMeter | None = None,
    ) -> list[list[float]]:
        self.calls.append((list(texts), kind))
        if self.error is not None:
            raise self.error
        for text in texts:
            if text not in self.vectors:
                vector = [0.0] * EMBEDDING_DIMENSIONS
                vector[len(self.vectors)] = 1.0
                self.vectors[text] = vector
        return [self.vectors[text] for text in texts]


class FakeJudge:
    """Answers every Score with a sure level: `levels[title][dimension]`, else 0.

    Articles whose title is in `fail` raise `JudgeError`; states are kept.
    """

    model = "test/judge"

    def __init__(
        self,
        levels: Mapping[str, Mapping[str, int]] | None = None,
        fail: set[str] | None = None,
    ) -> None:
        self.levels = levels or {}
        self.fail = fail or set()
        self.states: list[Any] = []
        self.closed = False
        self._lock = threading.Lock()

    def ask(
        self,
        state: Text,
        questions: Mapping[str, Question],
        *,
        purpose: str,
        meter: UsageMeter | None = None,
    ) -> Judgement:
        assert isinstance(state, dict)
        title = state["article"]["title"]
        with self._lock:
            self.states.append(state)
        if title in self.fail:
            raise JudgeError(f"{purpose}: failed for {title}")
        answers = {}
        for name, question in questions.items():
            assert isinstance(question, Score)
            level = self.levels.get(title, {}).get(name, 0)
            probabilities = tuple(float(i == level) for i in range(len(question.levels)))
            answers[name] = ScoreAnswer(float(level), probabilities, 1.0)
        usage = CallUsage(self.model, purpose, 500, 0, 0.00002, 1)
        if meter is not None:
            meter.add(usage)
        return Judgement(answers, usage)

    def close(self) -> None:
        self.closed = True
