"""Interests and the reader notes that steer them."""

from datetime import datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from brzask.api import problems
from brzask.api.deps import ACTOR, NO_NUL, DbSession, Id
from brzask.db.models import Interest
from brzask.services import interests

router = APIRouter(prefix="/interests", tags=["interests"])

Topic = Annotated[str, Field(min_length=1, max_length=200, pattern=NO_NUL)]
Keyword = Annotated[str, Field(max_length=200, pattern=NO_NUL)]
Notes = Annotated[
    str,
    Field(
        max_length=10_000,
        pattern=NO_NUL,
        description="Free text, e.g. 'want: ..., skip: ...'; takes priority over keywords.",
    ),
]
Keywords = Annotated[list[Keyword], Field(max_length=100, description="Can only widen the topic.")]


class InterestOut(BaseModel):
    id: int
    topic: str
    keywords: list[str]
    notes: str
    active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, interest: Interest) -> "InterestOut":
        return cls(
            id=interest.id,
            topic=interest.topic,
            keywords=list(interest.keywords),
            notes=interest.notes,
            active=interest.active,
            created_at=interest.created_at,
            updated_at=interest.updated_at,
        )


class NewInterest(BaseModel):
    topic: Topic
    keywords: Keywords = []
    notes: Notes = ""


class InterestChange(BaseModel):
    """Fields to change; the ones left out (or null) stay as they are."""

    topic: Topic | None = None
    keywords: Keywords | None = None
    notes: Notes | None = None
    active: bool | None = Field(None, description="Inactive interests are left out of prompts.")


@router.get("", summary="List interests")
def list_interests(
    session: DbSession,
    active_only: Annotated[bool, Query(description="Leave out inactive interests.")] = False,
) -> list[InterestOut]:
    """In the order they were added, as prompts list them. Not paginated: a reader has a handful."""
    return [
        InterestOut.of(interest)
        for interest in interests.list_interests(session, active_only=active_only)
    ]


@router.get(
    "/{interest_id}",
    summary="Get an interest",
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def get_interest(session: DbSession, interest_id: Id) -> InterestOut:
    return InterestOut.of(interests.find_interest(session, str(interest_id)))


@router.post(
    "",
    summary="Add an interest",
    status_code=status.HTTP_201_CREATED,
    responses=problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.CONFLICT),
)
def add_interest(session: DbSession, new: NewInterest) -> InterestOut:
    interest = interests.add_interest(
        session, new.topic, actor=ACTOR, keywords=new.keywords, notes=new.notes
    )
    return InterestOut.of(interest)


@router.patch(
    "/{interest_id}",
    summary="Change an interest or its notes",
    responses=problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
)
def change_interest(session: DbSession, interest_id: Id, change: InterestChange) -> InterestOut:
    """Interests are not deleted; an inactive one keeps its history."""
    interest = interests.edit_interest(
        session,
        str(interest_id),
        actor=ACTOR,
        topic=change.topic,
        keywords=change.keywords,
        notes=change.notes,
        active=change.active,
    )
    return InterestOut.of(interest)
