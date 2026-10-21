import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from brzask.db.models import RunKind, RunStatus, SourceStatus
from brzask.repositories import RunRepository
from tests.factories import Factories


def test_status(client: TestClient, make: Factories, session: Session) -> None:
    make.source(status=SourceStatus.PENDING)
    make.article(digest_date=datetime(2026, 10, 20).date())
    runs = RunRepository(session)
    run = runs.start(uuid.uuid4(), RunKind.DIGEST, datetime(2026, 10, 20, 7, tzinfo=UTC))
    runs.finish(run, RunStatus.OK, datetime(2026, 10, 20, 7, 5, tzinfo=UTC))

    body = client.get("/api/v1/status").json()

    assert body["articles"] == {"total": 1, "shown": 1, "opened": 0}
    assert body["sources"]["pending"] == 1
    assert body["sources"]["active"] == 0
    assert body["last_digest"] == "2026-10-20"
    assert body["paused_until"] is None
    assert body["last_runs"]["digest"]["id"] == str(run.id)
    assert body["last_runs"]["discovery"] is None


def test_pause_and_resume(client: TestClient) -> None:
    until = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)

    assert client.get("/api/v1/pause").json() == {"until": None}
    response = client.put("/api/v1/pause", json={"until": until.isoformat()})
    assert response.status_code == 200
    assert datetime.fromisoformat(client.get("/api/v1/pause").json()["until"]) == until
    assert client.get("/api/v1/status").json()["paused_until"] is not None

    assert client.delete("/api/v1/pause").status_code == 204
    assert client.get("/api/v1/pause").json() == {"until": None}
    assert client.delete("/api/v1/pause").status_code == 204  # not paused: still fine


def test_pause_needs_a_future_time_with_a_zone(client: TestClient) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)

    assert client.put("/api/v1/pause", json={"until": past.isoformat()}).status_code == 400
    assert client.put("/api/v1/pause", json={"until": "2099-01-01T00:00:00"}).status_code == 422
