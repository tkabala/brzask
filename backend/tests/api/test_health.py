from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from brzask.api.app import create_app
from brzask.api.metrics import prometheus_reader
from brzask.db.session import create_db_engine, session_factory


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_on_a_migrated_database(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_not_ready_before_migrations(client: TestClient, connection: Connection) -> None:
    connection.execute(text("UPDATE alembic_version SET version_num = 'older'"))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert "not migrated" in response.json()["detail"]


def _app(sessions: sessionmaker[Session]) -> FastAPI:
    reader, registry = prometheus_reader()
    return create_app(
        sessions, metrics_registry=registry, meter_provider=MeterProvider(metric_readers=[reader])
    )


def test_not_ready_without_a_database() -> None:
    # Nothing listens on port 1; connecting fails at once.
    engine = create_db_engine("postgresql+psycopg://brzask:x@127.0.0.1:1/brzask")
    client = TestClient(_app(session_factory(engine)))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["detail"] == "The database is unreachable."
    # Liveness does not depend on the database.
    assert client.get("/healthz").status_code == 200
