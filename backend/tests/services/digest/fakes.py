"""Fakes for the digest stages' clients, and a run context to pass them."""

import threading
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.embeddings import EmbeddingKind
from brzask.clients.extractors import SNIPPET, ExtractionInput, ExtractionResult
from brzask.clients.feeds import FeedEntry, FeedRequest, FeedResult
from brzask.clients.usage import UsageMeter
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
