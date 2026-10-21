import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from brzask.db.models import RunKind, RunStatus
from brzask.repositories import RunRepository

NOW = datetime(2026, 10, 21, 7, tzinfo=UTC)


def add_runs(session: Session, count: int, kind: RunKind = RunKind.DIGEST) -> list[uuid.UUID]:
    runs = RunRepository(session)
    ids = []
    for minutes in range(count):
        run = runs.start(uuid.uuid4(), kind, NOW + timedelta(minutes=minutes))
        runs.finish(run, RunStatus.OK, NOW + timedelta(minutes=minutes, seconds=30))
        ids.append(run.id)
    session.commit()
    return ids


def test_lists_runs_newest_first(client: TestClient, session: Session) -> None:
    [first, second] = add_runs(session, 2)

    body = client.get("/api/v1/runs").json()

    assert [item["id"] for item in body["items"]] == [str(second), str(first)]
    assert body["next_cursor"] is None
    assert body["items"][0]["kind"] == "digest"
    assert body["items"][0]["status"] == "ok"


def test_pages_follow_the_cursor(client: TestClient, session: Session) -> None:
    ids = add_runs(session, 5)

    seen: list[str] = []
    cursor = None
    for _ in range(3):
        params = {"limit": "2"} | ({"cursor": cursor} if cursor else {})
        body = client.get("/api/v1/runs", params=params).json()
        seen += [item["id"] for item in body["items"]]
        cursor = body["next_cursor"]

    assert seen == [str(run_id) for run_id in reversed(ids)]
    assert cursor is None


def test_runs_started_at_the_same_moment_are_not_skipped(
    client: TestClient, session: Session
) -> None:
    runs = RunRepository(session)
    ids = {runs.start(uuid.uuid4(), RunKind.DIGEST, NOW).id for _ in range(3)}
    session.commit()

    first = client.get("/api/v1/runs", params={"limit": "2"}).json()
    rest = client.get("/api/v1/runs", params={"limit": "2", "cursor": first["next_cursor"]}).json()

    assert {item["id"] for item in first["items"] + rest["items"]} == {str(i) for i in ids}


def test_filters_by_kind(client: TestClient, session: Session) -> None:
    add_runs(session, 1)
    [review] = add_runs(session, 1, RunKind.REVIEW)

    body = client.get("/api/v1/runs", params={"kind": "review"}).json()

    assert [item["id"] for item in body["items"]] == [str(review)]


def test_bad_cursor_is_a_problem(client: TestClient) -> None:
    response = client.get("/api/v1/runs", params={"cursor": "garbage"})

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert "cursor" in response.json()["detail"]


def test_limit_out_of_range_is_a_validation_problem(client: TestClient) -> None:
    response = client.get("/api/v1/runs", params={"limit": "0"})

    assert response.status_code == 422
    assert response.json()["errors"][0]["location"] == ["query", "limit"]


def test_get_run(client: TestClient, session: Session) -> None:
    [run_id] = add_runs(session, 1)

    body = client.get(f"/api/v1/runs/{run_id}").json()

    assert (body["id"], body["status"]) == (str(run_id), "ok")
    assert client.get(f"/api/v1/runs/{uuid.uuid4()}").status_code == 404
