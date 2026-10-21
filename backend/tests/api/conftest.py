from contextlib import nullcontext
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from brzask.api.app import create_app
from brzask.api.clients import ApiClients
from brzask.api.metrics import prometheus_reader
from brzask.clients.embeddings import EmbeddingKind
from brzask.clients.feed_finder import FoundFeed
from brzask.clients.retry import APIError
from brzask.config.settings import AuthSettings
from brzask.services.auth import hash_password
from tests.factories import unit_vector


@dataclass
class FakeEmbedder:
    """Answers each text with its vector in `vectors`, or a fixed one."""

    model: str
    vectors: dict[str, list[float]]
    calls: list[tuple[list[str], EmbeddingKind]] = field(default_factory=list)
    fail: bool = False

    def embed(
        self, texts: list[str], kind: EmbeddingKind, *, purpose: str = "embedding"
    ) -> list[list[float]]:
        self.calls.append((texts, kind))
        if self.fail:
            raise APIError("embedding API failed: 503 Service Unavailable")
        return [self.vectors.get(text, unit_vector(1)) for text in texts]


@dataclass
class FakeFeedFinder:
    """Knows the feeds in `feeds`, by any page URL."""

    feeds: dict[str, FoundFeed] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)

    def find(self, url: str) -> FoundFeed | None:
        self.asked.append(url)
        return self.feeds.get(url)


@pytest.fixture
def embedders() -> dict[str, FakeEmbedder]:
    """The embedders the app made, by model."""
    return {}


@pytest.fixture
def query_vectors() -> dict[str, list[float]]:
    return {}


@pytest.fixture
def feed_finder() -> FakeFeedFinder:
    return FakeFeedFinder()


PASSWORD = "correct horse battery staple"
SECRET = "s" * 32


@pytest.fixture(scope="session")
def password_hash() -> str:
    return hash_password(PASSWORD)


@pytest.fixture
def auth_settings() -> AuthSettings:
    """No login, so tests of the endpoints need none; auth tests switch to password."""
    return AuthSettings(mode="none")


@pytest.fixture
def password_auth(password_hash: str) -> AuthSettings:
    return AuthSettings(
        mode="password",
        password_hash=SecretStr(password_hash),
        session_secret=SecretStr(SECRET),
    )


@pytest.fixture
def app(
    sessions: sessionmaker[Session],
    embedders: dict[str, FakeEmbedder],
    query_vectors: dict[str, list[float]],
    feed_finder: FakeFeedFinder,
    auth_settings: AuthSettings,
) -> FastAPI:
    """The API on the test database, with its own metrics and fake outside services."""

    def new_embedder(model: str) -> FakeEmbedder:
        embedders[model] = FakeEmbedder(model, query_vectors)
        return embedders[model]

    reader, registry = prometheus_reader()
    return create_app(
        sessions,
        metrics_registry=registry,
        meter_provider=MeterProvider(metric_readers=[reader]),
        clients=ApiClients(feed_finder=lambda: nullcontext(feed_finder), new_embedder=new_embedder),
        auth_settings=auth_settings,
    )


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # Unexpected errors are answered with a problem, as in production.
    return TestClient(app, raise_server_exceptions=False)
