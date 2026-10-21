from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.db.models import Change
from tests.factories import Factories


def test_lists_interests_in_the_order_added(client: TestClient, make: Factories) -> None:
    first = make.interest("Linux", keywords=["kernel"], notes="want: releases")
    make.interest("Old", active=False)

    every = client.get("/api/v1/interests").json()
    active = client.get("/api/v1/interests", params={"active_only": "true"}).json()

    assert [i["topic"] for i in every] == ["Linux", "Old"]
    assert [i["id"] for i in active] == [first.id]
    assert (active[0]["keywords"], active[0]["notes"]) == (["kernel"], "want: releases")


def test_adds_an_interest(client: TestClient, session: Session) -> None:
    response = client.post(
        "/api/v1/interests",
        json={"topic": " Postgres ", "keywords": ["pg", " pg ", ""], "notes": "skip: webinars"},
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["topic"], body["keywords"], body["notes"], body["active"]) == (
        "Postgres",
        ["pg"],
        "skip: webinars",
        True,
    )
    assert client.get(f"/api/v1/interests/{body['id']}").json()["topic"] == "Postgres"
    assert session.scalars(select(Change.action)).all() == ["interest.add"]


def test_duplicate_or_blank_topics_are_refused(client: TestClient, make: Factories) -> None:
    make.interest("Linux")

    assert client.post("/api/v1/interests", json={"topic": "linux"}).status_code == 409
    assert client.post("/api/v1/interests", json={"topic": "  "}).status_code == 400
    assert client.post("/api/v1/interests", json={"topic": ""}).status_code == 422


def test_changes_only_the_given_fields(client: TestClient, make: Factories) -> None:
    interest = make.interest("Linux", keywords=["kernel"], notes="old")

    body = client.patch(
        f"/api/v1/interests/{interest.id}", json={"notes": "want: LTS", "active": False}
    ).json()

    assert (body["topic"], body["keywords"], body["notes"], body["active"]) == (
        "Linux",
        ["kernel"],
        "want: LTS",
        False,
    )


def test_unknown_interest(client: TestClient) -> None:
    assert client.get("/api/v1/interests/999999").status_code == 404
    assert client.patch("/api/v1/interests/999999", json={}).status_code == 404
