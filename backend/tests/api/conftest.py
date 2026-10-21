import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from sqlalchemy.orm import Session, sessionmaker

from brzask.api.app import create_app
from brzask.api.metrics import prometheus_reader


@pytest.fixture
def app(sessions: sessionmaker[Session]) -> FastAPI:
    """The API on the test database, with its own metrics."""
    reader, registry = prometheus_reader()
    return create_app(
        sessions,
        metrics_registry=registry,
        meter_provider=MeterProvider(metric_readers=[reader]),
    )


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # Unexpected errors are answered with a problem, as in production.
    return TestClient(app, raise_server_exceptions=False)
