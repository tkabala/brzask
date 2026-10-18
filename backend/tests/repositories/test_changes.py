from datetime import UTC, datetime

from sqlalchemy.orm import Session

from brzask.db.models import ChangeStatus
from brzask.repositories import ChangeRepository

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)


def record(changes: ChangeRepository, entity_id: str, status: ChangeStatus) -> None:
    changes.record(
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
