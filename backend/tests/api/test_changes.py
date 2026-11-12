"""Proposed changes: listed, approved and rejected through the API."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from brzask.db.models import Change, ChangeStatus, SourceStatus
from brzask.services import proposals
from brzask.services.sources import change_status, rename_source
from tests.factories import Factories

AGENT = "agent:claude"


def propose_mute(session: Session, make: Factories, name: str = "Blog") -> Change:
    source = make.source(name, note="fine")
    change = proposals.propose(
        session,
        lambda: change_status(session, source, SourceStatus.MUTED, actor=AGENT, reason="noisy"),
    )
    assert change is not None
    session.commit()
    return change


def test_lists_waiting_proposals_oldest_first(
    client: TestClient, session: Session, make: Factories
) -> None:
    first = propose_mute(session, make, "Blog")
    second = propose_mute(session, make, "News")
    change_status(session, make.source("Other"), SourceStatus.MUTED, actor="user")
    session.commit()

    body = client.get("/api/v1/changes").json()

    assert [c["id"] for c in body] == [first.id, second.id]
    assert body[0] == {
        "id": first.id,
        "created_at": body[0]["created_at"],
        "actor": AGENT,
        "action": "source.mute",
        "entity_type": "source",
        "entity_id": first.entity_id,
        "entity": "Blog",
        "before": {"status": "active", "note": "fine"},
        "after": {"status": "muted"},
        "reason": "noisy",
        "status": "proposed",
        "decided_at": None,
    }


def test_only_proposed_changes_can_be_listed(client: TestClient) -> None:
    assert client.get("/api/v1/changes", params={"status": "applied"}).status_code == 422


def test_approving_applies_the_change(
    client: TestClient, session: Session, make: Factories
) -> None:
    change = propose_mute(session, make)

    response = client.post(f"/api/v1/changes/{change.id}/approve")

    assert response.status_code == 200, response.json()
    assert (response.json()["status"], response.json()["entity"]) == ("applied", "Blog")
    assert response.json()["decided_at"] is not None
    session.expire_all()
    assert client.get("/api/v1/changes").json() == []
    assert session.get(Change, change.id).status is ChangeStatus.APPLIED  # type: ignore[union-attr]


def test_rejecting_leaves_the_source_alone(
    client: TestClient, session: Session, make: Factories
) -> None:
    change = propose_mute(session, make)

    response = client.post(f"/api/v1/changes/{change.id}/reject")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    sources = client.get("/api/v1/sources", params={"status": "active"}).json()
    assert "Blog" in str(sources)


def test_refusals(client: TestClient, session: Session, make: Factories) -> None:
    change = propose_mute(session, make)
    plain = make.source("Plain")
    stale = proposals.propose(session, lambda: rename_source(session, plain, "Better", actor=AGENT))
    assert stale is not None
    rename_source(session, plain, "Mine", actor="user")
    session.commit()

    unknown = client.post("/api/v1/changes/999999/approve")
    out_of_date = client.post(f"/api/v1/changes/{stale.id}/approve")
    client.post(f"/api/v1/changes/{change.id}/approve")
    twice = client.post(f"/api/v1/changes/{change.id}/reject")

    assert unknown.status_code == 404
    assert out_of_date.status_code == 409
    assert "out of date: name is now 'Mine'" in out_of_date.json()["detail"]
    assert twice.status_code == 409
    assert "is applied" in twice.json()["detail"]
