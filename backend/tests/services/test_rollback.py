from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.orm import Session

from brzask.clients.feed_finder import FoundFeed
from brzask.db.models import Change, ChangeStatus, SourceOrigin, SourceStatus
from brzask.repositories import ChangeRepository, SettingRepository, SourceRepository
from brzask.services.errors import ConflictError, NotFoundError, ServiceError
from brzask.services.interests import add_interest, edit_interest
from brzask.services.pause import PAUSE_KEY, pause, paused_until, resume
from brzask.services.rollback import describe_change, list_changes, one_line, rollback_change
from brzask.services.sources import (
    add_source,
    change_status,
    enable_source,
    mute_source,
    propose_source,
    rename_source,
    set_note,
)
from tests.factories import Factories

NOW = datetime(2026, 11, 8, 7, tzinfo=UTC)
FUTURE = NOW + timedelta(days=3)
LATER = NOW + timedelta(days=9)


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


# --- added sources ---------------------------------------------------------------

URL = "https://a.example/feed.xml"


def propose(session: Session, status: SourceStatus) -> Any:
    return propose_source(
        session,
        FoundFeed(url=URL, title="A", site_url="https://a.example"),
        status=status,
        origin=SourceOrigin.DISCOVERY,
        actor="pipeline:discovery",
    )


def test_rolling_back_an_added_source_mutes_it(session: Session) -> None:
    source = add_source(session, URL, actor="user", name="A")
    original = last_change(session)

    new = rollback_change(session, original.id, NOW, actor="user")

    assert source.status is SourceStatus.MUTED
    assert source.note == f"rolled back (change {original.id})"
    assert new.action == "source.add.rollback"
    assert new.before is not None and new.after is not None
    assert (new.before["status"], new.after["status"]) == ("active", "muted")


def test_rolling_back_a_discovered_active_source_mutes_it(session: Session) -> None:
    source = propose(session, SourceStatus.ACTIVE)
    original = last_change(session)
    assert original.action == "source.add"

    rollback_change(session, original.id, NOW, actor="user")

    assert source.status is SourceStatus.MUTED


def test_rolling_back_a_proposal_rejects_it(session: Session) -> None:
    source = propose(session, SourceStatus.PENDING)
    original = last_change(session)

    rollback_change(session, original.id, NOW, actor="user")

    assert source.status is SourceStatus.REJECTED
    assert SourceRepository(session).get_by_url(URL) is source


def test_rename_does_not_block_undoing_an_add(session: Session) -> None:
    source = add_source(session, URL, actor="user", name="A")
    original = last_change(session)
    rename_source(session, source, "B", actor="user")

    rollback_change(session, original.id, NOW, actor="user")

    assert (source.name, source.status) == ("B", SourceStatus.MUTED)


def test_muted_since_add_is_refused(session: Session) -> None:
    source = add_source(session, URL, actor="user", name="A")
    original = last_change(session)
    mute_source(session, str(source.id), actor="user")

    with pytest.raises(ConflictError, match="status"):
        rollback_change(session, original.id, NOW, actor="user")


def test_source_created_rejected_is_refused(session: Session) -> None:
    propose(session, SourceStatus.REJECTED)
    original = last_change(session)

    with pytest.raises(ServiceError, match="sources enable"):
        rollback_change(session, original.id, NOW, actor="user")

    assert original.status is ChangeStatus.APPLIED


# --- interests -------------------------------------------------------------------


def test_rolling_back_an_added_interest_deactivates_it(session: Session) -> None:
    interest = add_interest(session, "Postgres", actor="user", keywords=["pg"], notes="want: x")
    original = last_change(session)

    new = rollback_change(session, original.id, NOW, actor="user")

    assert interest.active is False
    assert (new.before, new.after) == ({"active": True}, {"active": False})


def test_edited_interest_add_is_refused(session: Session) -> None:
    interest = add_interest(session, "Postgres", actor="user")
    original = last_change(session)
    edit_interest(session, str(interest.id), actor="user", notes="changed")

    with pytest.raises(ConflictError, match="deactivat"):
        rollback_change(session, original.id, NOW, actor="user")

    assert interest.active is True


def test_rolling_back_an_interest_update(session: Session) -> None:
    interest = add_interest(session, "Postgres", actor="user", keywords=["pg"], notes="old")
    edit_interest(session, str(interest.id), actor="user", keywords=["sql"], notes="new")
    original = last_change(session)

    new = rollback_change(session, original.id, NOW, actor="user")

    assert (interest.keywords, interest.notes) == (["pg"], "old")
    assert new.before == {"keywords": ["sql"], "notes": "new"}
    assert new.after == {"keywords": ["pg"], "notes": "old"}


def test_stale_interest_update_is_refused(session: Session) -> None:
    interest = add_interest(session, "Postgres", actor="user", notes="old")
    edit_interest(session, str(interest.id), actor="user", notes="new")
    original = last_change(session)
    edit_interest(session, str(interest.id), actor="user", notes="newer")

    with pytest.raises(ConflictError, match="notes"):
        rollback_change(session, original.id, NOW, actor="user")

    assert interest.notes == "newer"


def test_topic_taken_is_refused(session: Session) -> None:
    interest = add_interest(session, "Old", actor="user")
    edit_interest(session, str(interest.id), actor="user", topic="New")
    original = last_change(session)
    add_interest(session, "old", actor="user")

    with pytest.raises(ConflictError, match="already exists"):
        rollback_change(session, original.id, NOW, actor="user")

    assert interest.topic == "New"


def test_case_only_topic_rolls_back(session: Session) -> None:
    interest = add_interest(session, "rust", actor="user")
    edit_interest(session, str(interest.id), actor="user", topic="Rust")
    original = last_change(session)

    rollback_change(session, original.id, NOW, actor="user")

    assert interest.topic == "rust"


def test_deleted_interest_is_refused(session: Session) -> None:
    interest = add_interest(session, "Postgres", actor="user")
    edit_interest(session, str(interest.id), actor="user", notes="new")
    original = last_change(session)
    session.delete(interest)
    session.flush()

    with pytest.raises(ConflictError, match="no longer exists"):
        rollback_change(session, original.id, NOW, actor="user")


def test_unknown_field_is_an_incomplete_record(session: Session) -> None:
    interest = add_interest(session, "Postgres", actor="user")
    edit_interest(session, str(interest.id), actor="user", notes="new")
    original = last_change(session)
    original.after = {"nonsense": 1}
    session.flush()

    with pytest.raises(ServiceError, match="incomplete"):
        rollback_change(session, original.id, NOW, actor="user")


# --- pause and resume ------------------------------------------------------------


def test_rolling_back_a_pause_removes_it(session: Session) -> None:
    pause(session, FUTURE, NOW, actor="user")
    original = last_change(session)

    new = rollback_change(session, original.id, NOW, actor="user")

    assert paused_until(session, NOW) is None
    assert (new.entity_type, new.entity_id) == ("setting", PAUSE_KEY)
    assert new.before == {"until": FUTURE.isoformat()}
    assert new.after == {"until": None}


def test_rolling_back_a_second_pause_restores_the_first(session: Session) -> None:
    pause(session, FUTURE, NOW, actor="user")
    pause(session, LATER, NOW, actor="user")
    original = last_change(session)

    rollback_change(session, original.id, NOW, actor="user")

    assert paused_until(session, NOW) == FUTURE


def test_rolling_back_a_pause_whose_previous_pause_ended(session: Session) -> None:
    pause(session, FUTURE, NOW, actor="user")
    pause(session, LATER, NOW, actor="user")
    original = last_change(session)
    afterwards = FUTURE + timedelta(days=1)

    rollback_change(session, original.id, afterwards, actor="user")

    assert paused_until(session, afterwards) is None


def test_pause_replaced_since_is_refused(session: Session) -> None:
    pause(session, FUTURE, NOW, actor="user")
    original = last_change(session)
    pause(session, LATER, NOW, actor="user")

    with pytest.raises(ConflictError, match="out of date"):
        rollback_change(session, original.id, NOW, actor="user")

    assert paused_until(session, NOW) == LATER


def test_pause_no_longer_in_effect_is_refused(session: Session) -> None:
    pause(session, FUTURE, NOW, actor="user")
    original = last_change(session)
    resume(session, NOW, actor="user")

    with pytest.raises(ConflictError, match="no longer in effect"):
        rollback_change(session, original.id, NOW, actor="user")


def test_same_moment_in_another_offset_is_not_stale(session: Session) -> None:
    pause(session, FUTURE, NOW, actor="user")
    original = last_change(session)
    respelled = FUTURE.astimezone(timezone(timedelta(hours=1))).isoformat()
    SettingRepository(session).put(PAUSE_KEY, {"until": respelled})

    rollback_change(session, original.id, NOW, actor="user")

    assert paused_until(session, NOW) is None


def test_rolling_back_a_resume_restores_the_pause(session: Session) -> None:
    pause(session, FUTURE, NOW, actor="user")
    resume(session, NOW, actor="user")
    original = last_change(session)

    new = rollback_change(session, original.id, NOW, actor="user")

    assert paused_until(session, NOW) == FUTURE
    assert (new.before, new.after) == ({"until": None}, {"until": FUTURE.isoformat()})


def test_resume_refused_when_that_pause_has_ended(session: Session) -> None:
    pause(session, FUTURE, NOW, actor="user")
    resume(session, NOW, actor="user")
    original = last_change(session)

    with pytest.raises(ConflictError, match="ended"):
        rollback_change(session, original.id, FUTURE + timedelta(days=1), actor="user")

    assert paused_until(session, NOW) is None


def test_resume_refused_when_a_new_pause_runs(session: Session) -> None:
    pause(session, FUTURE, NOW, actor="user")
    resume(session, NOW, actor="user")
    original = last_change(session)
    pause(session, LATER, NOW, actor="user")

    with pytest.raises(ConflictError, match="out of date"):
        rollback_change(session, original.id, NOW, actor="user")

    assert paused_until(session, NOW) == LATER


def test_malformed_until_is_refused(session: Session) -> None:
    change = record(
        session, "digest.pause", entity_type="setting", entity_id=PAUSE_KEY, after={"until": "soon"}
    )

    with pytest.raises(ServiceError, match="incomplete"):
        rollback_change(session, change.id, NOW, actor="user")


# --- listing ---------------------------------------------------------------------


def test_describe_is_one_shortened_line() -> None:
    change = Change(before={"notes": "a\nb " + "x" * 200}, after={"notes": "c"})

    text = describe_change(change)

    assert "\n" not in text
    assert len(text) <= 60
    assert text.endswith("…")


def test_describe_with_nothing_before() -> None:
    assert describe_change(Change(before=None, after={"name": "A"})) == "name: - → A"


def test_describe_a_field_set_to_nothing() -> None:
    change = Change(before={"until": "x", "note": None}, after={"until": None})

    assert describe_change(change) == "until: x → -"


def test_list_changes_filters(session: Session, make: Factories) -> None:
    first, second = make.source(), make.source()
    mute_source(session, str(first.id), actor="user")
    original = last_change(session)
    mute_source(session, str(second.id), actor="user")
    rollback_change(session, original.id, NOW, actor="user")

    assert [c.id for c in list_changes(session, limit=1, status=ChangeStatus.REVERTED)] == [
        original.id
    ]
    only_first = list_changes(session, limit=10, entity_type="source", entity_id=str(first.id))
    assert [c.action for c in only_first] == ["source.mute.rollback", "source.mute"]


def test_describe_shows_a_long_note_last() -> None:
    change = Change(
        before={"note": "x" * 100, "status": "muted"}, after={"note": "y", "status": "active"}
    )

    assert describe_change(change).startswith("status: muted → active")


def test_describe_shows_long_interest_notes_last() -> None:
    change = Change(before=None, after={"notes": "n" * 100, "topic": "Rust"})

    assert describe_change(change).startswith("topic: - → Rust")


def test_a_note_only_logged_before_is_not_shown_as_cleared() -> None:
    change = Change(before={"status": "active", "note": "x"}, after={"status": "muted"})

    assert describe_change(change) == "status: active → muted"


def test_one_line_collapses_and_shortens() -> None:
    assert one_line("a\n  b") == "a b"
    assert one_line("x" * 80, 10) == "x" * 9 + "…"


# --- malformed records -----------------------------------------------------------

TOO_BIG = "99999999999999999999"


@pytest.mark.parametrize(
    "before",
    [{"name": 5}, {"name": {"a": 1}}, {"name": None}, {"name": ["a"]}, {"name": ""}],
)
def test_rename_with_a_malformed_name_is_refused(
    session: Session, make: Factories, before: dict[str, Any]
) -> None:
    source = make.source("Old")
    rename_source(session, source, "New", actor="user")
    original = last_change(session)
    original.before = before
    session.flush()

    with pytest.raises(ServiceError, match="incomplete"):
        rollback_change(session, original.id, NOW, actor="user")

    assert source.name == "New"


def test_status_with_a_malformed_note_is_refused(session: Session, make: Factories) -> None:
    source = make.source()
    mute_source(session, str(source.id), actor="user")
    original = last_change(session)
    original.before = {"status": "active", "note": ["x"]}
    session.flush()

    with pytest.raises(ServiceError, match="incomplete"):
        rollback_change(session, original.id, NOW, actor="user")

    assert source.status is SourceStatus.MUTED


def test_source_id_beyond_bigint_is_refused(session: Session, make: Factories) -> None:
    mute_source(session, str(make.source().id), actor="user")
    original = last_change(session)
    original.entity_id = TOO_BIG
    session.flush()

    with pytest.raises(ServiceError, match="incomplete"):
        rollback_change(session, original.id, NOW, actor="user")


def test_interest_id_beyond_bigint_is_refused(session: Session) -> None:
    interest = add_interest(session, "Postgres", actor="user")
    edit_interest(session, str(interest.id), actor="user", notes="new")
    original = last_change(session)
    original.entity_id = TOO_BIG
    session.flush()

    with pytest.raises(ServiceError, match="incomplete"):
        rollback_change(session, original.id, NOW, actor="user")


@pytest.mark.parametrize(
    "before",
    [
        {"topic": 5},
        {"topic": None},
        {"topic": ""},
        {"keywords": "pg"},
        {"keywords": [1]},
        {"notes": None},
        {"active": "yes"},
        {"id": 7},
    ],
)
def test_interest_update_with_malformed_values_is_refused(
    session: Session, before: dict[str, Any]
) -> None:
    interest = add_interest(session, "Postgres", actor="user")
    edit_interest(session, str(interest.id), actor="user", notes="new")
    original = last_change(session)
    original.before = before
    session.flush()

    with pytest.raises(ServiceError, match="incomplete"):
        rollback_change(session, original.id, NOW, actor="user")

    assert (interest.topic, interest.notes) == ("Postgres", "new")


# --- note ------------------------------------------------------------------------


def test_rolling_back_a_note(session: Session, make: Factories) -> None:
    source = make.source("Blog")
    set_note(session, source, "first", actor="user")
    set_note(session, source, "second", actor="user")
    original = last_change(session)

    new = rollback_change(session, original.id, NOW, actor="user")

    assert source.note == "first"
    assert (new.action, new.before, new.after) == (
        "source.note.rollback",
        {"note": "second"},
        {"note": "first"},
    )


def test_note_rollback_refused_after_another_note(session: Session, make: Factories) -> None:
    source = make.source("Blog")
    set_note(session, source, "first", actor="user")
    original = last_change(session)
    set_note(session, source, "second", actor="user")

    with pytest.raises(ConflictError, match="note is now 'second'"):
        rollback_change(session, original.id, NOW, actor="user")
