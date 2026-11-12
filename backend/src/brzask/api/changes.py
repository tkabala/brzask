"""Changes an agent proposed, waiting for the owner to approve or reject them."""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from brzask.api import problems
from brzask.api.auth import Actor
from brzask.api.deps import DbSession, Id
from brzask.db.models import Change, ChangeStatus
from brzask.services import proposals

router = APIRouter(prefix="/changes", tags=["changes"])


class ChangeOut(BaseModel):
    id: int
    created_at: datetime
    actor: str = Field(description="Who made or proposed it, e.g. 'agent:<token name>'.")
    action: str = Field(description="e.g. 'source.mute', 'interest.update'.")
    entity_type: str
    entity_id: str | None = Field(description="Empty for an addition not yet approved.")
    entity: str | None = Field(description="The source's name or the interest's topic.")
    before: dict[str, Any] | None = Field(description="The fields it changes, as they were.")
    after: dict[str, Any] | None = Field(description="The fields it changes, as it sets them.")
    reason: str | None
    status: ChangeStatus
    decided_at: datetime | None

    @classmethod
    def of(cls, session: Session, change: Change) -> "ChangeOut":
        return cls(
            id=change.id,
            created_at=change.created_at,
            actor=change.actor,
            action=change.action,
            entity_type=change.entity_type,
            entity_id=change.entity_id,
            entity=proposals.entity_label(session, change),
            before=change.before,
            after=change.after,
            reason=change.reason,
            status=change.status,
            decided_at=change.decided_at,
        )


@router.get("", summary="Changes waiting for approval")
def list_changes(
    session: DbSession,
    status: Annotated[
        Literal["proposed"], Query(description="Only proposed changes can be listed here.")
    ] = "proposed",
) -> list[ChangeOut]:
    """Oldest first; an agent with a propose token makes them."""
    return [ChangeOut.of(session, change) for change in proposals.list_proposals(session)]


@router.post(
    "/{change_id}/approve",
    summary="Apply a proposed change",
    responses=problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
)
def approve_change(session: DbSession, _actor: Actor, change_id: Id) -> ChangeOut:
    """Refused when what it changes was edited since it was proposed."""
    change = proposals.approve(session, change_id, datetime.now(UTC))
    return ChangeOut.of(session, change)


@router.post(
    "/{change_id}/reject",
    summary="Turn a proposed change down",
    responses=problems.responses(HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
)
def reject_change(session: DbSession, _actor: Actor, change_id: Id) -> ChangeOut:
    change = proposals.reject(session, change_id, datetime.now(UTC))
    return ChangeOut.of(session, change)
