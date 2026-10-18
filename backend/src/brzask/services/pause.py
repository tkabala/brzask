"""Pausing the daily digest, e.g. for a holiday."""

from datetime import datetime

from sqlalchemy.orm import Session

from brzask.db.models import ChangeStatus
from brzask.repositories import ChangeRepository, SettingRepository
from brzask.services.errors import ServiceError

PAUSE_KEY = "pause"


def paused_until(session: Session, now: datetime) -> datetime | None:
    """End of the current pause, or None when the digest is not paused."""
    value = SettingRepository(session).get(PAUSE_KEY)
    if value is None:
        return None
    until = datetime.fromisoformat(value["until"])
    return until if until > now else None


def pause(session: Session, until: datetime, now: datetime, *, actor: str) -> None:
    """No digest is built before `until`."""
    if until.tzinfo is None:
        raise ServiceError("the end of a pause needs a time zone")
    if until <= now:
        raise ServiceError(f"{until.isoformat()} is not in the future")
    before = paused_until(session, now)
    SettingRepository(session).put(PAUSE_KEY, {"until": until.isoformat()})
    ChangeRepository(session).record(
        actor=actor,
        action="digest.pause",
        entity_type="setting",
        entity_id=PAUSE_KEY,
        status=ChangeStatus.APPLIED,
        before={"until": before.isoformat()} if before else None,
        after={"until": until.isoformat()},
    )


def resume(session: Session, now: datetime, *, actor: str) -> bool:
    """End a pause now. False when the digest was not paused."""
    before = paused_until(session, now)
    SettingRepository(session).delete(PAUSE_KEY)
    if before is None:
        return False
    ChangeRepository(session).record(
        actor=actor,
        action="digest.resume",
        entity_type="setting",
        entity_id=PAUSE_KEY,
        status=ChangeStatus.APPLIED,
        before={"until": before.isoformat()},
    )
    return True
