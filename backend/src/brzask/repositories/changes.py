"""The change log: who changed what, why, and whether it was applied."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brzask.db.models import Change, ChangeStatus


@dataclass(frozen=True)
class RecordedChange:
    """A copy of what `record` was asked to log, kept apart from the session."""

    actor: str
    action: str
    entity_type: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None


_captured: ContextVar[list[RecordedChange] | None] = ContextVar("brzask_captured", default=None)


@dataclass
class Filling:
    proposal: Change
    filled: bool = False  # set once the change was written into the proposal


_filling: ContextVar[Filling | None] = ContextVar("brzask_filling", default=None)


@contextmanager
def capturing() -> Iterator[list[RecordedChange]]:
    """Collect a copy of every change recorded in the block.

    A proposal runs the real write and rolls it back; the copy is what
    survives the rollback.
    """
    captured: list[RecordedChange] = []
    reset = _captured.set(captured)
    try:
        yield captured
    finally:
        _captured.reset(reset)


@contextmanager
def filling(proposal: Change) -> Iterator[Filling]:
    """Write the one change recorded in the block into `proposal` instead of a new row.

    An approved proposal stays a single row in the log, so history and
    rollback see one change. The caller sets its status.
    """
    target = Filling(proposal)
    reset = _filling.set(target)
    try:
        yield target
    finally:
        _filling.reset(reset)


class ChangeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, change_id: int) -> Change | None:
        return self.session.get(Change, change_id)

    def get_for_update(self, change_id: int) -> Change | None:
        """The change, locked until the transaction ends."""
        return self.session.get(Change, change_id, with_for_update=True)

    def record(
        self,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str | None,
        status: ChangeStatus,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> Change:
        captured = _captured.get()
        if captured is not None:
            captured.append(
                RecordedChange(actor, action, entity_type, entity_id, before, after, reason)
            )
        target = _filling.get()
        if target is not None:
            return self._fill(target, action, entity_id, before, after, reason)
        change = Change(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            reason=reason,
            status=status,
        )
        self.session.add(change)
        self.session.flush()
        return change

    def _fill(
        self,
        target: Filling,
        action: str,
        entity_id: str | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str | None,
    ) -> Change:
        proposal = target.proposal
        if target.filled:
            raise RuntimeError(f"change {proposal.id} would be filled twice")
        if action != proposal.action:
            raise RuntimeError(f"change {proposal.id} is {proposal.action}, not {action}")
        proposal.entity_id = entity_id
        proposal.before = before
        proposal.after = after
        if reason is not None:
            proposal.reason = reason
        target.filled = True
        self.session.flush()
        return proposal

    def count(self, status: ChangeStatus) -> int:
        return self.session.scalar(select(func.count()).where(Change.status == status)) or 0

    def set_status(self, change: Change, status: ChangeStatus, decided_at: datetime) -> None:
        change.status = status
        change.decided_at = decided_at
        self.session.flush()

    def find(
        self,
        *,
        limit: int,
        status: ChangeStatus | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> Sequence[Change]:
        """Newest changes first, optionally for one status or one entity."""
        query = select(Change).order_by(Change.created_at.desc(), Change.id.desc()).limit(limit)
        if status is not None:
            query = query.where(Change.status == status)
        if entity_type is not None:
            query = query.where(Change.entity_type == entity_type)
        if entity_id is not None:
            query = query.where(Change.entity_id == entity_id)
        return self.session.scalars(query).all()
