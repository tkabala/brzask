"""Outside services the API calls, built once per process and replaceable in tests."""

import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field

from brzask.clients.embeddings import Embedder
from brzask.clients.feed_finder import FeedFinder
from brzask.clients.feeds import FeedFetcher
from brzask.clients.llm import LLMClient
from brzask.config import get_settings
from brzask.services.conversation.ask import BoundedModel
from brzask.services.search import QueryEmbedder
from brzask.services.sources import SiteFeedFinder


@contextmanager
def _feed_finder() -> Iterator[SiteFeedFinder]:
    finder = FeedFinder(FeedFetcher.from_settings(get_settings().fetch))
    try:
        yield finder
    finally:
        finder.close()


@contextmanager
def _conversation_model() -> Iterator[LLMClient]:
    llm = LLMClient.from_settings(get_settings().llm)
    try:
        yield llm
    finally:
        llm.client.close()


def _embedder(model: str) -> QueryEmbedder:
    return Embedder.from_settings(get_settings(), model)


@dataclass
class ApiClients:
    feed_finder: Callable[[], AbstractContextManager[SiteFeedFinder]] = _feed_finder
    """A finder for one request; its connections close afterwards."""
    new_embedder: Callable[[str], QueryEmbedder] = _embedder
    conversation_model: Callable[[], AbstractContextManager[BoundedModel]] = _conversation_model
    """The chat model answering one question; its connections close afterwards."""
    _embedders: dict[str, QueryEmbedder] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def embedder(self, model: str) -> QueryEmbedder:
        """One embedder per model for the whole process; its HTTP client is thread-safe."""
        with self._lock:
            if model not in self._embedders:
                self._embedders[model] = self.new_embedder(model)
            return self._embedders[model]
