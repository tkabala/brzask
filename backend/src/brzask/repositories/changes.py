"""The change log: who changed what, why, and whether it was applied."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.db.models import Change, ChangeStatus


class ChangeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, change_id: int) -> Change | None:
        return self.session.get(Change, change_id)

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
