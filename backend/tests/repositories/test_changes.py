from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brzask.db.models import Change, ChangeStatus
from brzask.repositories import ChangeRepository
from brzask.repositories.changes import RecordedChange, capturing, filling

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)


def record(changes: ChangeRepository, entity_id: str, status: ChangeStatus) -> Change:
    return changes.record(
        actor="pipeline:review",
        action="source.mute",
        entity_type="source",
        entity_id=entity_id,
        status=status,
    )


def test_record_stores_before_after_and_reason(session: Session) -> None:
    changes = ChangeRepository(session)

    change = changes.record(
        actor="user",
        action="interest.update",
        entity_type="interest",
        entity_id="3",
        status=ChangeStatus.APPLIED,
        before={"notes": ""},
        after={"notes": "skip: funding rounds"},
        reason="too many funding stories",
    )
    session.expire_all()

    stored = changes.get(change.id)
    assert stored is not None
    assert (stored.before, stored.after) == ({"notes": ""}, {"notes": "skip: funding rounds"})
    assert stored.reason == "too many funding stories"
    assert stored.created_at is not None
    assert stored.decided_at is None


def test_set_status_records_the_decision_time(session: Session) -> None:
    changes = ChangeRepository(session)
    change = changes.record(
        actor="token:agent",
        action="source.add",
        entity_type="source",
        entity_id=None,
        status=ChangeStatus.PROPOSED,
    )

    changes.set_status(change, ChangeStatus.REJECTED, NOW)

    assert (change.status, change.decided_at) == (ChangeStatus.REJECTED, NOW)


def test_find_newest_first_with_filters(session: Session) -> None:
    changes = ChangeRepository(session)
    record(changes, "1", ChangeStatus.APPLIED)
    record(changes, "2", ChangeStatus.PROPOSED)
    record(changes, "1", ChangeStatus.PROPOSED)

    assert [c.entity_id for c in changes.find(limit=10)] == ["1", "2", "1"]
    assert [c.entity_id for c in changes.find(limit=2)] == ["1", "2"]
    proposed = changes.find(limit=10, status=ChangeStatus.PROPOSED)
    assert [c.entity_id for c in proposed] == ["1", "2"]
    history = changes.find(limit=10, entity_type="source", entity_id="1")
    assert [c.status for c in history] == [ChangeStatus.PROPOSED, ChangeStatus.APPLIED]


def _rows(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Change)) or 0


def test_capturing_collects_recorded_changes(session: Session) -> None:
    changes = ChangeRepository(session)

    with capturing() as recorded:
        changes.record(
            actor="agent:claude",
            action="source.rename",
            entity_type="source",
            entity_id="4",
            status=ChangeStatus.APPLIED,
            before={"name": "a"},
            after={"name": "b"},
            reason="clearer",
        )
    record(changes, "5", ChangeStatus.APPLIED)  # after the block: not captured

    assert recorded == [
        RecordedChange(
            actor="agent:claude",
            action="source.rename",
            entity_type="source",
            entity_id="4",
            before={"name": "a"},
            after={"name": "b"},
            reason="clearer",
        )
    ]


def test_filling_writes_into_the_proposal_row(session: Session) -> None:
    changes = ChangeRepository(session)
    proposal = changes.record(
        actor="agent:claude",
        action="source.add",
        entity_type="source",
        entity_id=None,
        status=ChangeStatus.PROPOSED,
        after={"url": "https://a.example/feed"},
        reason="covers the topic",
    )
    rows = _rows(session)

    with filling(proposal) as target:
        filled = changes.record(
            actor="agent:claude",
            action="source.add",
            entity_type="source",
            entity_id="12",
            status=ChangeStatus.APPLIED,
            after={"url": "https://a.example/feed", "name": "a"},
        )

    assert filled is proposal
    assert target.filled
    assert _rows(session) == rows
    assert (proposal.entity_id, proposal.after) == (
        "12",
        {"url": "https://a.example/feed", "name": "a"},
    )
    assert proposal.reason == "covers the topic"  # kept when the service passes none
    assert proposal.status is ChangeStatus.PROPOSED  # the caller decides the status


def test_filling_refuses_another_action(session: Session) -> None:
    changes = ChangeRepository(session)
    proposal = changes.record(
        actor="agent:claude",
        action="source.rename",
        entity_type="source",
        entity_id="4",
        status=ChangeStatus.PROPOSED,
    )

    with filling(proposal), pytest.raises(RuntimeError, match=r"source\.mute"):
        record(changes, "4", ChangeStatus.APPLIED)


def test_filling_refuses_a_second_record(session: Session) -> None:
    changes = ChangeRepository(session)
    proposal = changes.record(
        actor="agent:claude",
        action="source.mute",
        entity_type="source",
        entity_id="4",
        status=ChangeStatus.PROPOSED,
    )

    with filling(proposal):
        record(changes, "4", ChangeStatus.APPLIED)
        with pytest.raises(RuntimeError, match="twice"):
            record(changes, "4", ChangeStatus.APPLIED)


def test_proposed_oldest_first(session: Session) -> None:
    changes = ChangeRepository(session)
    first = record(changes, "1", ChangeStatus.PROPOSED)
    second = record(changes, "2", ChangeStatus.PROPOSED)
    record(changes, "3", ChangeStatus.APPLIED)

    assert [change.id for change in changes.proposed()] == [first.id, second.id]
