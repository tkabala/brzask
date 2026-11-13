"""Undoing one change from the change log.

Each undoable action has its own entry in `_UNDO`, because undoing is not always
writing `before` back: an added source is muted, not deleted. An action with no
entry is refused, so a new action stays irreversible until its undo is defined.
"""

from collections.abc import Callable, Sequence
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
from brzask.services.change_records import (
    entity_id_of,
    locked_change,
    logged,
    require_type,
    require_unchanged,
)
from brzask.services.errors import ConflictError, ServiceError
from brzask.services.pause import PAUSE_KEY, paused_until

_SUFFIX = ".rollback"


@dataclass(frozen=True, slots=True)
class Undone:
    """The fields an undo touched, as they were just before it and as it left them."""

    before: dict[str, Any]
    after: dict[str, Any]


type Undo = Callable[[Session, Change, datetime], Undone]


def list_changes(
    session: Session,
    *,
    limit: int,
    status: ChangeStatus | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> Sequence[Change]:
    """Newest changes first, optionally for one status or one entity."""
    return ChangeRepository(session).find(
        limit=limit, status=status, entity_type=entity_type, entity_id=entity_id
    )


def split_entity(value: str) -> tuple[str, str] | None:
    """`source:12` as ("source", "12"); None when either part is missing."""
    entity_type, _, entity_id = value.partition(":")
    return (entity_type, entity_id) if entity_type and entity_id else None


def describe_change(change: Change, width: int = 60) -> str:
    """What a change did, on one line of at most `width` characters."""
    before, after = change.before or {}, change.after or {}
    # A status change logs the old note only; the new one is its reason.
    fields = [name for name in dict.fromkeys([*before, *after]) if name != "note" or name in after]
    parts = [
        f"{field}: {_shown(before.get(field))} → {_shown(after.get(field))}"
        # Stored objects lose their key order; a long note must not hide the rest.
        for field in sorted(fields, key=lambda name: name in {"note", "notes"})
    ]
    return one_line(", ".join(parts), width)


def one_line(text: str, width: int = 60) -> str:
    """`text` with its whitespace collapsed, cut to `width` characters."""
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _shown(value: object) -> str:
    return "-" if value is None else str(value)


def rollback_change(
    session: Session, change_id: int, now: datetime, *, actor: str, reason: str | None = None
) -> Change:
    """Undo an applied change and mark it reverted; returns the change the undo recorded.

    Refused, with nothing written, when a field the change set has changed since.
    """
    changes = ChangeRepository(session)
    change = locked_change(session, change_id)
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


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _locked_source(session: Session, change: Change) -> Source:
    source = SourceRepository(session).get_for_update(entity_id_of(change))
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
    before, after = logged(change.before), logged(change.after)
    require_unchanged(change, "status", after["status"], source.status.value)
    # A status change sets the note to its reason; a note edited since is kept.
    require_unchanged(change, "note", change.reason, source.note)
    note = before.get("note")
    require_type(note is None or isinstance(note, str))
    return _set_status(session, source, SourceStatus(before["status"]), note)


def _undo_rename(session: Session, change: Change, _now: datetime) -> Undone:
    source = _locked_source(session, change)
    after = logged(change.after)
    require_unchanged(change, "name", after["name"], source.name)
    name = logged(change.before)["name"]
    require_type(_is_text(name))
    taken = SourceRepository(session).get_by_name(name)
    if taken is not None and taken.id != source.id:
        raise ConflictError(f"a source named {name!r} already exists; rename it first")
    undone = Undone(before={"name": source.name}, after={"name": name})
    source.name = name
    session.flush()
    return undone


def _undo_note(session: Session, change: Change, _now: datetime) -> Undone:
    source = _locked_source(session, change)
    require_unchanged(change, "note", logged(change.after)["note"], source.note)
    note = logged(change.before)["note"]
    require_type(note is None or _is_text(note))
    undone = Undone(before={"note": source.note}, after={"note": note})
    source.note = note
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
    status = logged(change.after).get("status", SourceStatus.ACTIVE.value)
    require_unchanged(change, "status", status, source.status.value)
    return _set_status(
        session, source, _AFTER_ADDITION[status], f"rolled back (change {change.id})"
    )


_INTEREST_FIELDS: dict[str, Callable[[object], bool]] = {
    "topic": _is_text,
    "keywords": lambda value: (
        isinstance(value, list) and all(isinstance(keyword, str) for keyword in value)
    ),
    "notes": lambda value: isinstance(value, str),
    "active": lambda value: isinstance(value, bool),
}


def _locked_interest(session: Session, change: Change) -> Interest:
    interest = InterestRepository(session).get_for_update(entity_id_of(change))
    if interest is None:
        raise ConflictError(f"the interest of change {change.id} no longer exists")
    return interest


def _undo_interest_addition(session: Session, change: Change, _now: datetime) -> Undone:
    interest = _locked_interest(session, change)
    edited = [
        field for field, value in logged(change.after).items() if getattr(interest, field) != value
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
    restored = logged(change.before)
    for field, value in restored.items():
        require_type(_INTEREST_FIELDS[field](value))
    for field, value in logged(change.after).items():
        require_unchanged(change, field, value, getattr(interest, field))
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
    until = datetime.fromisoformat(logged(change.after)["until"])
    current = paused_until(session, now)
    if current is None:
        raise ConflictError(f"change {change.id} is out of date: that pause is no longer in effect")
    # Compared as moments: one moment has many spellings across UTC offsets.
    require_unchanged(change, "the pause end", until, current)
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
    until = datetime.fromisoformat(logged(change.before)["until"])
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
    "source.note": _undo_note,
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
