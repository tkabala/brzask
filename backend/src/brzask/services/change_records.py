"""Reading logged changes back: the values a change recorded, and whether they still hold.

Undoing and approving a change both act on what the log says, so both refuse
a record with gaps and a change whose fields were edited since.
"""

from typing import Any

from sqlalchemy.orm import Session

from brzask.db.models import Change
from brzask.repositories import ChangeRepository
from brzask.services.errors import ConflictError, NotFoundError
from brzask.services.refs import MAX_ID, as_id


def locked_change(session: Session, change_id: int) -> Change:
    """The change, locked until the transaction ends, so two decisions on it queue up."""
    change = ChangeRepository(session).get_for_update(change_id) if change_id <= MAX_ID else None
    if change is None:
        raise NotFoundError(f"no change {change_id}")
    return change


def logged(fields: dict[str, Any] | None) -> dict[str, Any]:
    """One side of a change that must have been logged; a gap reads as an incomplete record."""
    if fields is None:
        raise TypeError("nothing logged")
    return fields


def entity_id_of(change: Change) -> int:
    entity_id = as_id(change.entity_id or "")
    if entity_id is None:
        raise ValueError("no usable entity ID")
    return entity_id


def require_type(valid: bool) -> None:
    """Values logged long ago, or edited by hand, must fit the column they go back to."""
    if not valid:
        raise TypeError("a logged value has the wrong type")


def require_unchanged(change: Change, field: str, logged: object, current: object) -> None:
    if current != logged:
        raise ConflictError(
            f"change {change.id} is out of date: {field} is now {current!r}, not {logged!r}"
        )
