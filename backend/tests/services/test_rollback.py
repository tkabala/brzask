from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from brzask.db.models import Change, ChangeStatus, SourceStatus
from brzask.repositories import ChangeRepository
from brzask.services.errors import ConflictError, NotFoundError, ServiceError
from brzask.services.rollback import rollback_change
from brzask.services.sources import change_status, enable_source, mute_source, rename_source
from tests.factories import Factories

NOW = datetime(2026, 11, 8, 7, tzinfo=UTC)


def last_change(session: Session) -> Change:
    return ChangeRepository(session).find(limit=1)[0]


def record(session: Session, action: str, **fields: Any) -> Change:
    """A change written directly, for actions or shapes the services don't produce here."""
    fields.setdefault("status", ChangeStatus.APPLIED)
    fields.setdefault("entity_type", "source")
    fields.setdefault("entity_id", "1")
    return ChangeRepository(session).record(actor="user", action=action, **fields)


def change_count(session: Session) -> int:
    return len(ChangeRepository(session).find(limit=100))


# --- source status ---------------------------------------------------------------


def test_rolling_back_a_mute(session: Session, make: Factories) -> None:
    source = make.source(note="was fine", fetch_failures=3, fetch_error="HTTP 500")
    mute_source(session, str(source.id), actor="user", reason="noisy")
    original = last_change(session)

    new = rollback_change(session, original.id, NOW, actor="user", reason="too eager")

    assert (source.status, source.note) == (SourceStatus.ACTIVE, "was fine")
    assert (source.fetch_failures, source.fetch_error) == (0, None)
    assert (original.status, original.decided_at) == (ChangeStatus.REVERTED, NOW)
    assert (new.action, new.entity_type, new.entity_id) == (
        "source.mute.rollback",
        "source",
        str(source.id),
    )
    assert new.before == {"status": "muted", "note": "noisy"}
    assert new.after == {"status": "active", "note": "was fine"}
    assert new.reason == f"rollback of change {original.id}: too eager"
    assert (new.status, new.decided_at) == (ChangeStatus.APPLIED, None)
    assert new.actor == "user"


def test_a_reason_is_optional(session: Session, make: Factories) -> None:
    source = make.source()
    mute_source(session, str(source.id), actor="user")
    original = last_change(session)

    new = rollback_change(session, original.id, NOW, actor="user")

    assert new.reason == f"rollback of change {original.id}"


@pytest.mark.parametrize(
    ("start", "target", "action"),
    [
        (SourceStatus.MUTED, SourceStatus.ACTIVE, "source.enable"),
        (SourceStatus.ACTIVE, SourceStatus.DEAD, "source.dead"),
        (SourceStatus.ACTIVE, SourceStatus.REJECTED, "source.reject"),
    ],
)
def test_rolling_back_other_status_changes(
    session: Session,
    make: Factories,
    start: SourceStatus,
    target: SourceStatus,
    action: str,
) -> None:
    source = make.source(status=start, note="earlier")
    change_status(session, source, target, actor="user", reason="now")
    original = last_change(session)
    assert original.action == action

    rollback_change(session, original.id, NOW, actor="user")

    assert (source.status, source.note) == (start, "earlier")


def test_row_without_a_note_clears_it(session: Session, make: Factories) -> None:
    source = make.source()
    mute_source(session, str(source.id), actor="user", reason="noisy")
    original = last_change(session)
    original.before = {"status": "active"}
    session.flush()

    rollback_change(session, original.id, NOW, actor="user")

    assert (source.status, source.note) == (SourceStatus.ACTIVE, None)


def test_stale_status_is_refused(session: Session, make: Factories) -> None:
    source = make.source()
    mute_source(session, str(source.id), actor="user")
    original = last_change(session)
    enable_source(session, str(source.id), actor="user")
    count = change_count(session)

    with pytest.raises(ConflictError, match="status"):
        rollback_change(session, original.id, NOW, actor="user")

    assert original.status is ChangeStatus.APPLIED
    assert change_count(session) == count


# --- rename ----------------------------------------------------------------------


def test_rolling_back_a_rename(session: Session, make: Factories) -> None:
    source = make.source("Old")
    rename_source(session, source, "New", actor="user")
    original = last_change(session)

    new = rollback_change(session, original.id, NOW, actor="user")

    assert source.name == "Old"
    assert (new.before, new.after) == ({"name": "New"}, {"name": "Old"})


def test_rename_refused_when_the_name_is_taken(session: Session, make: Factories) -> None:
    source = make.source("Old")
    rename_source(session, source, "New", actor="user")
    original = last_change(session)
    make.source("old")

    with pytest.raises(ConflictError, match="already exists"):
        rollback_change(session, original.id, NOW, actor="user")

    assert source.name == "New"


def test_case_only_rename_rolls_back(session: Session, make: Factories) -> None:
    source = make.source("feed")
    rename_source(session, source, "FEED", actor="user")
    original = last_change(session)

    rollback_change(session, original.id, NOW, actor="user")

    assert source.name == "feed"


def test_later_change_to_another_field_does_not_block(session: Session, make: Factories) -> None:
    source = make.source("Old")
    rename_source(session, source, "New", actor="user")
    original = last_change(session)
    mute_source(session, str(source.id), actor="user")

    rollback_change(session, original.id, NOW, actor="user")

    assert (source.name, source.status) == ("Old", SourceStatus.MUTED)


# --- refusals --------------------------------------------------------------------


def test_second_rollback_is_refused(session: Session, make: Factories) -> None:
    source = make.source()
    mute_source(session, str(source.id), actor="user")
    original = last_change(session)
    rollback_change(session, original.id, NOW, actor="user")

    with pytest.raises(ConflictError, match="reverted"):
        rollback_change(session, original.id, NOW, actor="user")


def test_a_rollback_cannot_be_rolled_back(session: Session, make: Factories) -> None:
    source = make.source()
    mute_source(session, str(source.id), actor="user")
    new = rollback_change(session, last_change(session).id, NOW, actor="user")

    with pytest.raises(ServiceError, match="make the change again"):
        rollback_change(session, new.id, NOW, actor="user")


def test_proposed_change_is_refused(session: Session, make: Factories) -> None:
    source = make.source()
    change = record(
        session,
        "source.mute",
        entity_id=str(source.id),
        status=ChangeStatus.PROPOSED,
        before={"status": "active"},
        after={"status": "muted"},
    )

    with pytest.raises(ConflictError, match="proposed"):
        rollback_change(session, change.id, NOW, actor="user")


def test_unknown_change(session: Session) -> None:
    with pytest.raises(NotFoundError, match="no change 123456"):
        rollback_change(session, 123456, NOW, actor="user")


def test_id_beyond_bigint(session: Session) -> None:
    with pytest.raises(NotFoundError, match="no change"):
        rollback_change(session, 2**70, NOW, actor="user")


def test_deleted_source_is_refused(session: Session, make: Factories) -> None:
    source = make.source()
    mute_source(session, str(source.id), actor="user")
    original = last_change(session)
    session.delete(source)
    session.flush()

    with pytest.raises(ConflictError, match="no longer exists"):
        rollback_change(session, original.id, NOW, actor="user")


@pytest.mark.parametrize(
    "broken",
    [{"before": None}, {"before": {"note": "x"}}, {"entity_id": "abc"}, {"entity_id": None}],
)
def test_incomplete_record_is_refused(
    session: Session, make: Factories, broken: dict[str, Any]
) -> None:
    source = make.source()
    mute_source(session, str(source.id), actor="user")
    original = last_change(session)
    for field, value in broken.items():
        setattr(original, field, value)
    session.flush()

    with pytest.raises(ServiceError, match="incomplete"):
        rollback_change(session, original.id, NOW, actor="user")


@pytest.mark.parametrize(
    ("action", "message"),
    [
        ("source.move", "redirect"),
        ("token.create", "brzask tokens"),
        ("token.revoke", "brzask tokens"),
        ("embedding.switch", "brzask reembed"),
        ("other.thing", "cannot be rolled back"),
    ],
)
def test_refused_actions(session: Session, action: str, message: str) -> None:
    change = record(session, action, before={"a": 1}, after={"a": 2})

    with pytest.raises(ServiceError, match=message):
        rollback_change(session, change.id, NOW, actor="user")

    assert change.status is ChangeStatus.APPLIED
