"""Digests: today's, any day's, and the archive of days."""

import re
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Path
from pydantic import BaseModel, BeforeValidator, Field

from brzask.api import problems
from brzask.api.articles import ArticleOut
from brzask.api.auth import Auth, AuthConfig
from brzask.api.deps import DbSession
from brzask.api.pagination import DEFAULT_LIMIT, CursorParam, Limit, Page, decode_cursor, page
from brzask.config import get_settings
from brzask.repositories.articles import DigestDay
from brzask.services import digests

router = APIRouter(prefix="/digests", tags=["digests"])


def _iso_day(value: object) -> object:
    # Pydantic would also read a number as a day (seconds since 1970).
    if isinstance(value, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("expected a date as YYYY-MM-DD")
    return value


Day = Annotated[date, BeforeValidator(_iso_day), Path(description="YYYY-MM-DD.")]


class DigestOut(BaseModel):
    date: date
    articles: list[ArticleOut] = Field(description="In digest order; empty when there is none.")


class DigestDayOut(BaseModel):
    date: date
    articles: int
    opened: int


def _digest(session: DbSession, links: Auth, day: date) -> DigestOut:
    return DigestOut(
        date=day, articles=[ArticleOut.of(a, links) for a in digests.digest_for(session, day)]
    )


def _parse_day(values: list[str]) -> date:
    [day] = values
    return date.fromisoformat(day)


def _day_key(day: DigestDay) -> list[str]:
    return [day.day.isoformat()]


@router.get(
    "",
    summary="List days with a digest",
    responses=problems.responses(HTTPStatus.BAD_REQUEST),
)
def list_digests(
    session: DbSession, limit: Limit = DEFAULT_LIMIT, cursor: CursorParam = None
) -> Page[DigestDayOut]:
    """Newest first, with how many articles each day had and how many were opened."""
    before = decode_cursor(cursor, _parse_day)
    items, next_cursor = page(digests.digest_days(session, limit + 1, before), limit, _day_key)
    return Page(
        items=[DigestDayOut(date=d.day, articles=d.articles, opened=d.opened) for d in items],
        next_cursor=next_cursor,
    )


@router.get("/today", summary="Today's digest")
def get_today_digest(session: DbSession, config: AuthConfig) -> DigestOut:
    """Today in the configured time zone (TZ); empty until the digest has run."""
    today = datetime.now(UTC).astimezone(get_settings().scheduler.timezone).date()
    return _digest(session, config, today)


@router.get("/{day}", summary="A day's digest")
def get_digest(session: DbSession, config: AuthConfig, day: Day) -> DigestOut:
    """Empty when that day had no digest."""
    return _digest(session, config, day)
