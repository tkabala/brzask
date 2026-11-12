from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brzask.db.models import Change, ChangeStatus, Interest, Source, SourceStatus
from brzask.repositories import ChangeRepository
from brzask.services import proposals
from brzask.services.errors import ConflictError, NotFoundError, ServiceError
from brzask.services.interests import add_interest, edit_interest
from brzask.services.pause import pause, paused_until, resume
from brzask.services.rollback import rollback_change
from brzask.services.sources import add_source, change_status, rename_source, set_note
from tests.factories import Factories

NOW = datetime(2026, 11, 12, 7, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)
FUTURE = NOW + timedelta(days=3)
AGENT = "agent:claude"


def rows(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Change)) or 0


def count(session: Session, model: type[Source] | type[Interest]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def proposed(session: Session, write: Any) -> Change:
    change = proposals.propose(session, write)
    assert change is not None
    return change


# --- proposing ---------------------------------------------------------------------


def test_proposing_a_mute_changes_nothing(session: Session, make: Factories) -> None:
    source = make.source(note="fine")

    change = proposed(
        session,
        lambda: change_status(session, source, SourceStatus.MUTED, actor=AGENT, reason="noisy"),
    )

    session.refresh(source)
    assert (source.status, source.note) == (SourceStatus.ACTIVE, "fine")
    assert (change.status, change.actor, change.action) == (
        ChangeStatus.PROPOSED,
        AGENT,
        "source.mute",
    )
    assert (change.entity_id, change.before, change.after, change.reason) == (
        str(source.id),
        {"status": "active", "note": "fine"},
        {"status": "muted"},
        "noisy",
    )
    assert change.decided_at is None
    assert rows(session) == 1


@pytest.mark.parametrize(
    ("action", "write"),
    [
        ("source.rename", lambda s, src: rename_source(s, src, "Better", actor=AGENT)),
        ("source.note", lambda s, src: set_note(s, src, "keep it", actor=AGENT)),
    ],
)
def test_proposing_a_source_edit_changes_nothing(
    session: Session, make: Factories, action: str, write: Any
) -> None:
    source = make.source("Plain", note=None)

    change = proposed(session, lambda: write(session, source))

    session.refresh(source)
    assert (source.name, source.note) == ("Plain", None)
    assert change.action == action


def test_proposing_an_addition_adds_no_source(session: Session) -> None:
    change = proposed(
        session,
        lambda: add_source(
            session, "https://a.example/feed", actor=AGENT, title="A", site_url="https://a.example/"
        ),
    )

    assert count(session, Source) == 0
    assert (change.action, change.entity_id) == ("source.add", None)
    assert change.after == {
        "name": "A",
        "url": "https://a.example/feed",
        "kind": "feed",
        "site_url": "https://a.example/",
    }


def test_proposing_interests_changes_nothing(session: Session, make: Factories) -> None:
    interest = make.interest("Rust", notes="")

    added = proposed(
        session, lambda: add_interest(session, "Go", actor=AGENT, keywords=["go"], notes="n")
    )
    edited = proposed(
        session, lambda: edit_interest(session, str(interest.id), actor=AGENT, notes="no hype")
    )

    session.refresh(interest)
    assert interest.notes == ""
    assert count(session, Interest) == 1
    assert (added.action, added.entity_id) == ("interest.add", None)
    assert (edited.before, edited.after) == ({"notes": ""}, {"notes": "no hype"})


def test_proposing_a_pause_and_a_resume_changes_nothing(session: Session) -> None:
    proposed(session, lambda: pause(session, FUTURE, NOW, actor=AGENT))
    assert paused_until(session, NOW) is None

    pause(session, FUTURE, NOW, actor="user")
    change = proposed(session, lambda: resume(session, NOW, actor=AGENT))

    assert paused_until(session, NOW) == FUTURE
    assert change.action == "digest.resume"


def test_a_write_that_changes_nothing_proposes_nothing(session: Session, make: Factories) -> None:
    source = make.source(status=SourceStatus.MUTED)

    change = proposals.propose(
        session, lambda: change_status(session, source, SourceStatus.MUTED, actor=AGENT)
    )

    assert change is None
    assert rows(session) == 0


def test_an_invalid_write_raises_and_stores_nothing(session: Session, make: Factories) -> None:
    make.source("Taken")
    source = make.source("Other")

    with pytest.raises(ConflictError, match="already exists"):
        proposals.propose(session, lambda: rename_source(session, source, "taken", actor=AGENT))

    assert rows(session) == 0


# --- approving ---------------------------------------------------------------------


def test_approving_a_mute_applies_it_into_the_same_row(session: Session, make: Factories) -> None:
    source = make.source(note="fine")
    change = proposed(
        session,
        lambda: change_status(session, source, SourceStatus.MUTED, actor=AGENT, reason="noisy"),
    )

    approved = proposals.approve(session, change.id, LATER)

    assert approved is change
    assert (source.status, source.note) == (SourceStatus.MUTED, "noisy")
    assert (change.status, change.decided_at, change.actor) == (ChangeStatus.APPLIED, LATER, AGENT)
    assert rows(session) == 1


def test_approving_an_enable_resets_fetch_health(session: Session, make: Factories) -> None:
    source = make.source(status=SourceStatus.MUTED, fetch_failures=4, fetch_error="HTTP 500")
    change = proposed(
        session, lambda: change_status(session, source, SourceStatus.ACTIVE, actor=AGENT)
    )

    proposals.approve(session, change.id, LATER)

    assert (source.status, source.fetch_failures, source.fetch_error) == (
        SourceStatus.ACTIVE,
        0,
        None,
    )


def test_approving_a_reject(session: Session, make: Factories) -> None:
    source = make.source(status=SourceStatus.PENDING)
    change = proposed(
        session,
        lambda: change_status(session, source, SourceStatus.REJECTED, actor=AGENT, reason="off"),
    )

    proposals.approve(session, change.id, LATER)

    assert source.status is SourceStatus.REJECTED


def test_approving_a_rename_and_a_note(session: Session, make: Factories) -> None:
    source = make.source("Plain")
    renamed = proposed(session, lambda: rename_source(session, source, "Better", actor=AGENT))
    noted = proposed(session, lambda: set_note(session, source, "keep it", actor=AGENT))

    proposals.approve(session, renamed.id, LATER)
    proposals.approve(session, noted.id, LATER)

    assert (source.name, source.note) == ("Better", "keep it")
    assert (renamed.status, noted.status) == (ChangeStatus.APPLIED, ChangeStatus.APPLIED)


def test_approving_an_addition_adds_the_source(session: Session) -> None:
    change = proposed(
        session,
        lambda: add_source(
            session, "https://a.example/feed", actor=AGENT, title="A", site_url="https://a.example/"
        ),
    )

    proposals.approve(session, change.id, LATER)

    source = session.scalars(select(Source)).one()
    assert (source.name, source.url, source.site_url, source.status) == (
        "A",
        "https://a.example/feed",
        "https://a.example/",
        SourceStatus.ACTIVE,
    )
    assert (change.entity_id, change.status) == (str(source.id), ChangeStatus.APPLIED)
    assert rows(session) == 1


def test_approving_interest_changes(session: Session, make: Factories) -> None:
    interest = make.interest("Rust", notes="")
    added = proposed(
        session, lambda: add_interest(session, "Go", actor=AGENT, keywords=["go"], notes="n")
    )
    edited = proposed(
        session, lambda: edit_interest(session, str(interest.id), actor=AGENT, notes="no hype")
    )

    proposals.approve(session, added.id, LATER)
    proposals.approve(session, edited.id, LATER)

    go = session.scalars(select(Interest).where(Interest.topic == "Go")).one()
    assert (go.keywords, go.notes) == (["go"], "n")
    assert added.entity_id == str(go.id)
    assert interest.notes == "no hype"


def test_approving_a_pause_and_a_resume(session: Session) -> None:
    paused = proposed(session, lambda: pause(session, FUTURE, NOW, actor=AGENT))

    proposals.approve(session, paused.id, LATER)
    assert paused_until(session, LATER) == FUTURE

    resumed = proposed(session, lambda: resume(session, LATER, actor=AGENT))
    proposals.approve(session, resumed.id, LATER)
    assert paused_until(session, LATER) is None


def test_rolling_back_an_approved_change(session: Session, make: Factories) -> None:
    source = make.source()
    change = proposed(
        session, lambda: change_status(session, source, SourceStatus.MUTED, actor=AGENT)
    )
    proposals.approve(session, change.id, LATER)

    rollback_change(session, change.id, LATER, actor="user")

    assert source.status is SourceStatus.ACTIVE
    assert change.status is ChangeStatus.REVERTED


# --- refusals ----------------------------------------------------------------------


def test_approving_a_mute_after_the_status_changed(session: Session, make: Factories) -> None:
    source = make.source()
    change = proposed(
        session, lambda: change_status(session, source, SourceStatus.MUTED, actor=AGENT)
    )
    change_status(session, source, SourceStatus.REJECTED, actor="user")

    with pytest.raises(ConflictError, match="out of date: status is now 'rejected'"):
        proposals.approve(session, change.id, LATER)

    assert change.status is ChangeStatus.PROPOSED
    assert source.status is SourceStatus.REJECTED


@pytest.mark.parametrize(
    ("write", "edit", "field"),
    [
        (
            lambda s, src: rename_source(s, src, "Better", actor=AGENT),
            lambda s, src: rename_source(s, src, "Mine", actor="user"),
            "name",
        ),
        (
            lambda s, src: set_note(s, src, "agent", actor=AGENT),
            lambda s, src: set_note(s, src, "mine", actor="user"),
            "note",
        ),
        (
            lambda s, src: change_status(s, src, SourceStatus.MUTED, actor=AGENT),
            lambda s, src: set_note(s, src, "mine", actor="user"),
            "note",
        ),
    ],
)
def test_approving_after_a_field_changed(
    session: Session, make: Factories, write: Any, edit: Any, field: str
) -> None:
    source = make.source("Plain")
    change = proposed(session, lambda: write(session, source))
    edit(session, source)

    with pytest.raises(ConflictError, match=f"out of date: {field} is now"):
        proposals.approve(session, change.id, LATER)

    assert change.status is ChangeStatus.PROPOSED


def test_approving_an_interest_edit_after_it_changed(session: Session, make: Factories) -> None:
    interest = make.interest("Rust", notes="")
    change = proposed(
        session, lambda: edit_interest(session, str(interest.id), actor=AGENT, notes="agent")
    )
    edit_interest(session, str(interest.id), actor="user", notes="mine")

    with pytest.raises(ConflictError, match="out of date: notes is now 'mine'"):
        proposals.approve(session, change.id, LATER)

    assert interest.notes == "mine"


def test_approving_a_pause_after_another_was_set(session: Session) -> None:
    change = proposed(session, lambda: pause(session, FUTURE, NOW, actor=AGENT))
    pause(session, FUTURE + timedelta(days=1), NOW, actor="user")

    with pytest.raises(ConflictError, match="out of date: the pause end is now"):
        proposals.approve(session, change.id, LATER)


def test_approving_a_resume_when_no_longer_paused(session: Session) -> None:
    pause(session, FUTURE, NOW, actor="user")
    change = proposed(session, lambda: resume(session, NOW, actor=AGENT))
    resume(session, NOW, actor="user")

    with pytest.raises(ConflictError, match="out of date"):
        proposals.approve(session, change.id, LATER)


def test_approving_a_pause_that_already_ended(session: Session) -> None:
    change = proposed(session, lambda: pause(session, FUTURE, NOW, actor=AGENT))

    with pytest.raises(ServiceError, match="not in the future"):
        proposals.approve(session, change.id, FUTURE + timedelta(hours=1))

    assert change.status is ChangeStatus.PROPOSED


def test_a_second_proposal_on_the_same_source_goes_stale(session: Session, make: Factories) -> None:
    source = make.source()
    mute = proposed(
        session, lambda: change_status(session, source, SourceStatus.MUTED, actor=AGENT)
    )
    reject = proposed(
        session, lambda: change_status(session, source, SourceStatus.REJECTED, actor=AGENT)
    )

    proposals.approve(session, mute.id, LATER)

    with pytest.raises(ConflictError, match="out of date: status is now 'muted'"):
        proposals.approve(session, reject.id, LATER)


def test_approving_an_addition_whose_url_was_taken(session: Session, make: Factories) -> None:
    change = proposed(session, lambda: add_source(session, "https://a.example/feed", actor=AGENT))
    make.source("Found", url="https://a.example/feed")

    with pytest.raises(ConflictError, match="already a source"):
        proposals.approve(session, change.id, LATER)

    assert (change.status, change.entity_id) == (ChangeStatus.PROPOSED, None)


def test_approving_an_interest_whose_topic_was_taken(session: Session, make: Factories) -> None:
    change = proposed(session, lambda: add_interest(session, "Go", actor=AGENT))
    make.interest("go")

    with pytest.raises(ConflictError, match="already exists"):
        proposals.approve(session, change.id, LATER)


def test_deciding_twice_is_refused(session: Session, make: Factories) -> None:
    source = make.source()
    approved = proposed(
        session, lambda: change_status(session, source, SourceStatus.MUTED, actor=AGENT)
    )
    rejected = proposed(session, lambda: set_note(session, source, "x", actor=AGENT))
    proposals.approve(session, approved.id, LATER)
    proposals.reject(session, rejected.id, LATER)

    with pytest.raises(ConflictError, match=f"change {approved.id} is applied"):
        proposals.approve(session, approved.id, LATER)
    with pytest.raises(ConflictError, match=f"change {approved.id} is applied"):
        proposals.reject(session, approved.id, LATER)
    with pytest.raises(ConflictError, match=f"change {rejected.id} is rejected"):
        proposals.approve(session, rejected.id, LATER)


def test_rejecting(session: Session, make: Factories) -> None:
    source = make.source()
    change = proposed(
        session, lambda: change_status(session, source, SourceStatus.MUTED, actor=AGENT)
    )

    rejected = proposals.reject(session, change.id, LATER)

    assert rejected is change
    assert (change.status, change.decided_at) == (ChangeStatus.REJECTED, LATER)
    assert source.status is SourceStatus.ACTIVE


def test_unknown_change(session: Session) -> None:
    with pytest.raises(NotFoundError, match="no change 99"):
        proposals.approve(session, 99, LATER)
    with pytest.raises(NotFoundError, match="no change 99"):
        proposals.reject(session, 99, LATER)
    with pytest.raises(NotFoundError):
        proposals.approve(session, 2**70, LATER)


def proposal(session: Session, action: str, **fields: Any) -> Change:
    fields.setdefault("entity_type", "source")
    fields.setdefault("entity_id", "1")
    return ChangeRepository(session).record(
        actor=AGENT, action=action, status=ChangeStatus.PROPOSED, **fields
    )


def test_an_action_without_an_approval_is_refused(session: Session, make: Factories) -> None:
    source = make.source()
    change = proposal(
        session, "source.move", entity_id=str(source.id), after={"url": "https://b.example/"}
    )

    with pytest.raises(ServiceError, match=r"\(source\.move\) cannot be approved"):
        proposals.approve(session, change.id, LATER)


def test_an_incomplete_record_is_refused(session: Session, make: Factories) -> None:
    source = make.source()
    change = proposal(session, "source.rename", entity_id=str(source.id), before={}, after={})

    with pytest.raises(ServiceError, match="its record is incomplete"):
        proposals.approve(session, change.id, LATER)


def test_a_change_with_nothing_left_to_do_is_refused(session: Session, make: Factories) -> None:
    source = make.source("Same")
    change = proposal(
        session,
        "source.rename",
        entity_id=str(source.id),
        before={"name": "Same"},
        after={"name": "Same"},
    )

    with pytest.raises(ConflictError, match="nothing left to change"):
        proposals.approve(session, change.id, LATER)


# --- listing -----------------------------------------------------------------------


def test_listing_proposals(session: Session, make: Factories) -> None:
    source = make.source("Plain")
    first = proposed(session, lambda: rename_source(session, source, "Better", actor=AGENT))
    second = proposed(session, lambda: set_note(session, source, "x", actor=AGENT))
    change_status(session, source, SourceStatus.MUTED, actor="user")

    assert [change.id for change in proposals.list_proposals(session)] == [first.id, second.id]


def test_entity_label(session: Session, make: Factories) -> None:
    source = make.source("Plain")
    interest = make.interest("Rust")
    renamed = proposed(session, lambda: rename_source(session, source, "Better", actor=AGENT))
    edited = proposed(
        session, lambda: edit_interest(session, str(interest.id), actor=AGENT, notes="x")
    )
    added = proposed(
        session, lambda: add_source(session, "https://a.example/feed", actor=AGENT, name="A")
    )
    new_interest = proposed(session, lambda: add_interest(session, "Go", actor=AGENT))
    paused = proposed(session, lambda: pause(session, FUTURE, NOW, actor=AGENT))

    assert [
        proposals.entity_label(session, change)
        for change in (renamed, edited, added, new_interest, paused)
    ] == ["Plain", "Rust", "A", "Go", None]
