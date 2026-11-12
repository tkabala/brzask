"""Changes that wait for the owner: proposing, approving and rejecting them.

A proposal runs the real write inside a savepoint, keeps the change it would
log and rolls everything else back, so it is validated and described exactly
as the write itself. Approving checks that what the proposal saw still holds,
then runs the write again with its log entry going into the proposal's row:
one change, one row, which history and rollback treat like any other.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.db.models import Change, ChangeStatus, Interest, Source, SourceStatus
from brzask.repositories import ChangeRepository, InterestRepository, SourceRepository
from brzask.repositories.changes import capturing, filling
from brzask.services import interests, sources
from brzask.services import pause as pausing
from brzask.services.change_records import entity_id_of, logged, require_type, require_unchanged
from brzask.services.errors import ConflictError, NotFoundError, ServiceError
from brzask.services.refs import MAX_ID

# Additions have no entity until they are approved.
_ADDITIONS = frozenset({"source.add", "interest.add"})


def propose(session: Session, write: Callable[[], object]) -> Change | None:
    """Record what `write` would change, as a proposal, without changing it.

    None when the write would change nothing. Errors of the write propagate
    and nothing is stored.
    """
    with capturing() as captured:
        savepoint = session.begin_nested()
        try:
            write()
        finally:
            savepoint.rollback()
    if not captured:
        return None
    if len(captured) > 1:
        raise RuntimeError(f"one write logged {len(captured)} changes")
    [change] = captured
    return ChangeRepository(session).record(
        actor=change.actor,
        action=change.action,
        entity_type=change.entity_type,
        entity_id=None if change.action in _ADDITIONS else change.entity_id,
        status=ChangeStatus.PROPOSED,
        before=change.before,
        after=change.after,
        reason=change.reason,
    )


def list_proposals(session: Session) -> Sequence[Change]:
    """Changes waiting for a decision, oldest first."""
    query = (
        select(Change)
        .where(Change.status == ChangeStatus.PROPOSED)
        .order_by(Change.created_at, Change.id)
    )
    return session.scalars(query).all()


def count_proposals(session: Session) -> int:
    return ChangeRepository(session).count(ChangeStatus.PROPOSED)


def entity_label(session: Session, change: Change) -> str | None:
    """The source's name or the interest's topic the change is about, when known."""
    if change.entity_type == "source":
        if change.entity_id is None:
            return _text((change.after or {}).get("name"))
        source = session.get(Source, _id(change.entity_id))
        return source.name if source else None
    if change.entity_type == "interest":
        if change.entity_id is None:
            return _text((change.after or {}).get("topic"))
        interest = session.get(Interest, _id(change.entity_id))
        return interest.topic if interest else None
    return None


def approve(session: Session, change_id: int, now: datetime) -> Change:
    """Apply a proposed change; refused, with nothing written, when it is out of date."""
    change = _proposal(session, change_id, "approved")
    apply = _APPLY.get(change.action)
    if apply is None:
        raise ServiceError(f"change {change.id} ({change.action}) cannot be approved")
    with filling(change) as target:
        try:
            apply(session, change, now)
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise ServiceError(
                f"change {change.id} cannot be approved: its record is incomplete"
            ) from error
    if not target.filled:
        raise ConflictError(f"change {change.id} has nothing left to change")
    ChangeRepository(session).set_status(change, ChangeStatus.APPLIED, now)
    return change


def reject(session: Session, change_id: int, now: datetime) -> Change:
    """Turn a proposed change down; nothing else is touched."""
    change = _proposal(session, change_id, "rejected")
    ChangeRepository(session).set_status(change, ChangeStatus.REJECTED, now)
    return change


def _proposal(session: Session, change_id: int, decision: str) -> Change:
    change = ChangeRepository(session).get_for_update(change_id) if change_id <= MAX_ID else None
    if change is None:
        raise NotFoundError(f"no change {change_id}")
    if change.status is not ChangeStatus.PROPOSED:
        raise ConflictError(
            f"change {change.id} is {change.status.value}; only a proposed change can be {decision}"
        )
    return change


def _id(value: str) -> int:
    return int(value) if value.isdigit() and int(value) <= MAX_ID else 0


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _require_current(change: Change, current: dict[str, Any]) -> None:
    """Every field the proposal saw must still hold the value it saw."""
    for field, seen in (change.before or {}).items():
        require_unchanged(change, field, seen, current[field])


def _locked_source(session: Session, change: Change) -> Source:
    source = SourceRepository(session).get_for_update(entity_id_of(change))
    if source is None:
        raise ConflictError(f"the source of change {change.id} no longer exists")
    _require_current(
        change, {"status": source.status.value, "note": source.note, "name": source.name}
    )
    return source


def _apply_status(session: Session, change: Change, _now: datetime) -> None:
    source = _locked_source(session, change)
    status = SourceStatus(logged(change.after)["status"])
    sources.change_status(session, source, status, actor=change.actor, reason=change.reason)


def _apply_rename(session: Session, change: Change, _now: datetime) -> None:
    source = _locked_source(session, change)
    name = logged(change.after)["name"]
    require_type(isinstance(name, str))
    sources.rename_source(session, source, name, actor=change.actor)


def _apply_note(session: Session, change: Change, _now: datetime) -> None:
    source = _locked_source(session, change)
    note = logged(change.after)["note"]
    require_type(note is None or isinstance(note, str))
    sources.set_note(session, source, note, actor=change.actor)


def _apply_source_addition(session: Session, change: Change, _now: datetime) -> None:
    after = logged(change.after)
    url, name, site_url = after["url"], after["name"], after.get("site_url")
    require_type(isinstance(url, str) and isinstance(name, str))
    require_type(site_url is None or isinstance(site_url, str))
    sources.add_source(session, url, actor=change.actor, name=name, site_url=site_url)


def _apply_interest_addition(session: Session, change: Change, _now: datetime) -> None:
    after = logged(change.after)
    topic, keywords, notes = after["topic"], after["keywords"], after["notes"]
    require_type(isinstance(topic, str) and isinstance(notes, str))
    require_type(isinstance(keywords, list) and all(isinstance(k, str) for k in keywords))
    interests.add_interest(session, topic, actor=change.actor, keywords=keywords, notes=notes)


_INTEREST_FIELDS = ("topic", "keywords", "notes", "active")


def _apply_interest_update(session: Session, change: Change, _now: datetime) -> None:
    interest = InterestRepository(session).get_for_update(entity_id_of(change))
    if interest is None:
        raise ConflictError(f"the interest of change {change.id} no longer exists")
    _require_current(
        change,
        {
            "topic": interest.topic,
            "keywords": list(interest.keywords),
            "notes": interest.notes,
            "active": interest.active,
        },
    )
    after = logged(change.after)
    fields = {field: after[field] for field in _INTEREST_FIELDS if field in after}
    interests.edit_interest(session, str(interest.id), actor=change.actor, **fields)


def _require_pause(session: Session, change: Change, now: datetime) -> None:
    """The pause must be the one the proposal saw (compared as moments)."""
    seen = (change.before or {}).get("until")
    expected = datetime.fromisoformat(seen) if seen is not None else None
    current = pausing.paused_until(session, now)
    if current == expected:
        return
    if current is None:
        state = "the digest is no longer paused"
    else:
        state = f"the pause end is now {current.isoformat()}"
    raise ConflictError(f"change {change.id} is out of date: {state}")


def _apply_pause(session: Session, change: Change, now: datetime) -> None:
    _require_pause(session, change, now)
    until = datetime.fromisoformat(logged(change.after)["until"])
    pausing.pause(session, until, now, actor=change.actor)


def _apply_resume(session: Session, change: Change, now: datetime) -> None:
    _require_pause(session, change, now)
    pausing.resume(session, now, actor=change.actor)


# Only these actions can be approved; another action stays refused until its
# approval is defined here.
_APPLY: dict[str, Callable[[Session, Change, datetime], None]] = {
    "source.mute": _apply_status,
    "source.enable": _apply_status,
    "source.reject": _apply_status,
    "source.rename": _apply_rename,
    "source.note": _apply_note,
    "source.add": _apply_source_addition,
    "interest.add": _apply_interest_addition,
    "interest.update": _apply_interest_update,
    "digest.pause": _apply_pause,
    "digest.resume": _apply_resume,
}
