"""Undoing one change from the change log.

Each undoable action has its own entry in `_UNDO`, because undoing is not always
writing `before` back: an added source is muted, not deleted. An action with no
entry is refused, so a new action stays irreversible until its undo is defined.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from brzask.db.models import Change, ChangeStatus, Interest, Source, SourceStatus
from brzask.repositories import (
    ChangeRepository,
    InterestRepository,
    SettingRepository,
    SourceRepository,
)
from brzask.services.errors import ConflictError, NotFoundError, ServiceError
from brzask.services.pause import PAUSE_KEY, paused_until
from brzask.services.refs import MAX_ID

_SUFFIX = ".rollback"


@dataclass(frozen=True, slots=True)
class Undone:
    """The fields an undo touched, as they were just before it and as it left them."""

    before: dict[str, Any]
    after: dict[str, Any]


type Undo = Callable[[Session, Change, datetime], Undone]


def rollback_change(
    session: Session, change_id: int, now: datetime, *, actor: str, reason: str | None = None
) -> Change:
    """Undo an applied change and mark it reverted; returns the change the undo recorded.

    Refused, with nothing written, when a field the change set has changed since.
    """
    changes = ChangeRepository(session)
    change = changes.get_for_update(change_id) if change_id <= MAX_ID else None
    if change is None:
        raise NotFoundError(f"no change {change_id}")
    if change.action.endswith(_SUFFIX):
        raise ServiceError(f"change {change.id} is a rollback; make the change again instead")
    if change.status is not ChangeStatus.APPLIED:
        raise ConflictError(
            f"change {change.id} is {change.status.value}; only an applied change can be undone"
        )
    undo = _UNDO.get(change.action)
    if undo is None:
        why = _REFUSED.get(change.action, "no undo is defined for it")
        raise ServiceError(f"change {change.id} ({change.action}) cannot be rolled back: {why}")
    try:
        undone = undo(session, change, now)
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ServiceError(
            f"change {change.id} cannot be rolled back: its record is incomplete"
        ) from error
    changes.set_status(change, ChangeStatus.REVERTED, now)
    return changes.record(
        actor=actor,
        action=change.action + _SUFFIX,
        entity_type=change.entity_type,
        entity_id=change.entity_id,
        status=ChangeStatus.APPLIED,
        before=undone.before,
        after=undone.after,
        reason=f"rollback of change {change.id}" + (f": {reason}" if reason else ""),
    )


def _logged(fields: dict[str, Any] | None) -> dict[str, Any]:
    """One side of a change that must have been logged; a gap reads as an incomplete record."""
    if fields is None:
        raise TypeError("nothing logged")
    return fields


def _require_unchanged(change: Change, field: str, logged: object, current: object) -> None:
    if current != logged:
        raise ConflictError(
            f"change {change.id} is out of date: {field} is now {current!r}, not {logged!r}"
        )


def _locked_source(session: Session, change: Change) -> Source:
    source = SourceRepository(session).get_for_update(int(change.entity_id or ""))
    if source is None:
        raise ConflictError(f"the source of change {change.id} no longer exists")
    return source


def _set_status(session: Session, source: Source, status: SourceStatus, note: str | None) -> Undone:
    """Set a source's status; becoming active forgets past failures, as enabling does."""
    before = {"status": source.status.value, "note": source.note}
    sources = SourceRepository(session)
    sources.set_status(source, status, note)
    if status is SourceStatus.ACTIVE:
        sources.reset_fetch_health(source)
    return Undone(before=before, after={"status": status.value, "note": note})


def _undo_status(session: Session, change: Change, _now: datetime) -> Undone:
    source = _locked_source(session, change)
    before, after = _logged(change.before), _logged(change.after)
    _require_unchanged(change, "status", after["status"], source.status.value)
    return _set_status(session, source, SourceStatus(before["status"]), before.get("note"))


def _undo_rename(session: Session, change: Change, _now: datetime) -> Undone:
    source = _locked_source(session, change)
    after = _logged(change.after)
    _require_unchanged(change, "name", after["name"], source.name)
    name = _logged(change.before)["name"]
    taken = SourceRepository(session).get_by_name(name)
    if taken is not None and taken.id != source.id:
        raise ConflictError(f"a source named {name!r} already exists; rename it first")
    undone = Undone(before={"name": source.name}, after={"name": name})
    source.name = name
    session.flush()
    return undone


def _undo_reject(session: Session, change: Change, now: datetime) -> Undone:
    if change.before is None:  # discovery stored the source as rejected from the start
        raise ServiceError(
            f"change {change.id} created a rejected source, so there is nothing to undo; "
            "`brzask sources enable` follows it"
        )
    return _undo_status(session, change, now)


# A source's row stays when its addition is undone: articles point to it, and a
# known URL is never proposed again. It was fetched if it was active, so it counts
# as once enabled; a pending one never was.
_AFTER_ADDITION = {"active": SourceStatus.MUTED, "pending": SourceStatus.REJECTED}


def _undo_addition(session: Session, change: Change, _now: datetime) -> Undone:
    source = _locked_source(session, change)
    # A source added by hand logs no status; it is always active.
    logged = _logged(change.after).get("status", SourceStatus.ACTIVE.value)
    _require_unchanged(change, "status", logged, source.status.value)
    return _set_status(
        session, source, _AFTER_ADDITION[logged], f"rolled back (change {change.id})"
    )


def _locked_interest(session: Session, change: Change) -> Interest:
    interest = InterestRepository(session).get_for_update(int(change.entity_id or ""))
    if interest is None:
        raise ConflictError(f"the interest of change {change.id} no longer exists")
    return interest


def _undo_interest_addition(session: Session, change: Change, _now: datetime) -> Undone:
    interest = _locked_interest(session, change)
    edited = [
        field for field, value in _logged(change.after).items() if getattr(interest, field) != value
    ]
    if edited:
        raise ConflictError(
            f"change {change.id} is out of date: {', '.join(edited)} changed since; "
            "deactivate the interest instead"
        )
    interest.active = False
    session.flush()
    return Undone(before={"active": True}, after={"active": False})


def _undo_interest_update(session: Session, change: Change, _now: datetime) -> Undone:
    interest = _locked_interest(session, change)
    restored = _logged(change.before)
    for field, value in _logged(change.after).items():
        _require_unchanged(change, field, value, getattr(interest, field))
    if "topic" in restored:
        taken = InterestRepository(session).get_by_topic(restored["topic"])
        if taken is not None and taken.id != interest.id:
            raise ConflictError(f"interest {restored['topic']!r} already exists; rename it first")
    undone = Undone(before={field: getattr(interest, field) for field in restored}, after=restored)
    for field, value in restored.items():
        setattr(interest, field, value)
    session.flush()
    return undone


def _undo_pause(session: Session, change: Change, now: datetime) -> Undone:
    logged = datetime.fromisoformat(_logged(change.after)["until"])
    current = paused_until(session, now)
    if current is None:
        raise ConflictError(f"change {change.id} is out of date: that pause is no longer in effect")
    # Compared as moments: one moment has many spellings across UTC offsets.
    _require_unchanged(change, "the pause end", logged, current)
    settings = SettingRepository(session)
    previous = datetime.fromisoformat(change.before["until"]) if change.before else None
    if previous is None or previous <= now:
        settings.delete(PAUSE_KEY)
        restored = None
    else:
        restored = previous.isoformat()
        settings.put(PAUSE_KEY, {"until": restored})
    return Undone(before={"until": current.isoformat()}, after={"until": restored})


def _undo_resume(session: Session, change: Change, now: datetime) -> Undone:
    until = datetime.fromisoformat(_logged(change.before)["until"])
    current = paused_until(session, now)
    if current is not None:
        raise ConflictError(
            f"change {change.id} is out of date: a pause until {current.isoformat()} is running"
        )
    if until <= now:
        raise ConflictError(f"change {change.id} cannot be undone: that pause has ended")
    SettingRepository(session).put(PAUSE_KEY, {"until": until.isoformat()})
    return Undone(before={"until": None}, after={"until": until.isoformat()})


_UNDO: dict[str, Undo] = {
    "source.mute": _undo_status,
    "source.enable": _undo_status,
    "source.dead": _undo_status,
    "source.reject": _undo_reject,
    "source.rename": _undo_rename,
    "source.add": _undo_addition,
    "source.propose": _undo_addition,
    "interest.add": _undo_interest_addition,
    "interest.update": _undo_interest_update,
    "digest.pause": _undo_pause,
    "digest.resume": _undo_resume,
}

_REFUSED = {
    "source.move": "the feed's permanent redirect would move it again on the next fetch",
    "token.create": "use `brzask tokens` to manage tokens",
    "token.revoke": "use `brzask tokens` to manage tokens",
    "embedding.switch": (
        "switching models needs the digest lock and complete vectors; use `brzask reembed`"
    ),
}
