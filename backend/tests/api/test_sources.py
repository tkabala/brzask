from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.clients.feed_finder import FoundFeed
from brzask.db.models import Change, SourceKind, SourceStatus
from tests.api.conftest import FakeFeedFinder
from tests.factories import Factories

NOW = datetime.now(UTC)


def test_lists_sources_by_name_with_health_and_activity(
    client: TestClient, make: Factories
) -> None:
    beta = make.source(
        "Beta",
        fetch_failures=3,
        fetch_error="HTTP 503",
        failing_since=NOW - timedelta(days=2),
    )
    alpha = make.source("Alpha")
    make.article(alpha, opened_at=NOW)
    make.article(alpha, first_seen_at=NOW - timedelta(days=40))  # outside the window

    items = client.get("/api/v1/sources").json()["items"]

    assert [item["name"] for item in items] == ["Alpha", "Beta"]
    assert items[0]["activity"] == {"articles": 1, "ranked": 0, "shown": 0, "opened": 1}
    health = items[1]["health"]
    assert (health["fetch_failures"], health["fetch_error"]) == (3, "HTTP 503")
    assert items[1]["id"] == beta.id


def test_filters_pending_decisions(client: TestClient, make: Factories) -> None:
    make.source("Active")
    pending = make.source("Proposed", status=SourceStatus.PENDING, note="fit 3/3")

    items = client.get("/api/v1/sources", params={"status": "pending"}).json()["items"]

    assert [(item["id"], item["note"]) for item in items] == [(pending.id, "fit 3/3")]


def test_pages_by_name(client: TestClient, make: Factories) -> None:
    for name in ("c", "a", "b"):
        make.source(name)

    first = client.get("/api/v1/sources", params={"limit": "2"}).json()
    rest = client.get(
        "/api/v1/sources", params={"limit": "2", "cursor": first["next_cursor"]}
    ).json()

    assert [s["name"] for s in first["items"] + rest["items"]] == ["a", "b", "c"]
    assert rest["next_cursor"] is None


def test_get_source(client: TestClient, make: Factories) -> None:
    source = make.source("One")

    assert client.get(f"/api/v1/sources/{source.id}").json()["name"] == "One"
    assert client.get("/api/v1/sources/999999").status_code == 404


def test_adds_a_source_from_any_page(
    client: TestClient, feed_finder: FakeFeedFinder, session: Session
) -> None:
    feed_finder.feeds["blog.example/post/1"] = FoundFeed(
        url="https://blog.example/feed.xml", title="A Blog", site_url="https://blog.example/"
    )

    response = client.post("/api/v1/sources", json={"url": "blog.example/post/1"})

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["url"], body["status"], body["origin"]) == (
        "A Blog",
        "https://blog.example/feed.xml",
        "active",
        "manual",
    )
    assert body["kind"] == SourceKind.FEED
    actions = session.scalars(select(Change.action)).all()
    assert actions == ["source.add"]


def test_adding_without_a_feed_is_not_found(
    client: TestClient, feed_finder: FakeFeedFinder
) -> None:
    response = client.post("/api/v1/sources", json={"url": "https://nofeed.example/"})

    assert response.status_code == 404
    assert "no RSS or Atom feed" in response.json()["detail"]


def test_adding_a_known_url_conflicts_before_fetching_it(
    client: TestClient, make: Factories, feed_finder: FakeFeedFinder
) -> None:
    make.source(url="https://known.example/feed.xml", status=SourceStatus.REJECTED)

    response = client.post("/api/v1/sources", json={"url": "https://known.example/feed.xml"})

    assert response.status_code == 409
    assert "rejected" in response.json()["detail"]
    assert feed_finder.asked == []


def test_approves_a_pending_source_with_a_reason(
    client: TestClient, make: Factories, session: Session
) -> None:
    source = make.source(status=SourceStatus.PENDING)

    response = client.patch(
        f"/api/v1/sources/{source.id}", json={"status": "active", "reason": "looks good"}
    )

    assert response.json()["status"] == "active"
    change = session.scalars(select(Change)).one()
    assert (change.action, change.reason) == ("source.enable", "looks good")


def test_rejects_mutes_and_renames(client: TestClient, make: Factories) -> None:
    source = make.source("Old")
    url = f"/api/v1/sources/{source.id}"

    assert client.patch(url, json={"status": "muted"}).json()["status"] == "muted"
    assert client.patch(url, json={"status": "rejected"}).json()["status"] == "rejected"
    assert client.patch(url, json={"name": " New "}).json()["name"] == "New"


def test_cannot_mark_a_source_dead_or_pending_by_hand(client: TestClient, make: Factories) -> None:
    source = make.source()

    for status in ("dead", "pending"):
        response = client.patch(f"/api/v1/sources/{source.id}", json={"status": status})
        assert response.status_code == 422


def test_rename_conflicts_and_rejects_numbers(client: TestClient, make: Factories) -> None:
    make.source("Taken")
    source = make.source("Mine")
    url = f"/api/v1/sources/{source.id}"

    assert client.patch(url, json={"name": "taken"}).status_code == 409
    assert client.patch(url, json={"name": "42"}).status_code == 400
    assert client.patch(url, json={"name": "   "}).status_code == 400
