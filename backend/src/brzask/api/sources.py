"""Sources: the feeds read every day, the ones proposed, and their health."""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from brzask.api import problems
from brzask.api.auth import Actor
from brzask.api.deps import NO_NUL, Clients, DbSession, Id, Sessions
from brzask.api.pagination import DEFAULT_LIMIT, CursorParam, Limit, Page, decode_cursor, page
from brzask.clients.feed_finder import with_scheme
from brzask.db.models import Source, SourceKind, SourceOrigin, SourceStatus
from brzask.repositories.sources import SourceStats
from brzask.services import sources
from brzask.services.refs import as_id

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceHealth(BaseModel):
    """How fetching the feed goes; the source review marks a long-failing source dead."""

    fetched_at: datetime | None = Field(description="Last successful fetch.")
    failing_since: datetime | None = Field(description="Start of the current failures.")
    permanent_failing_since: datetime | None = Field(
        description="Start of the current permanent errors (404, 410, 403, not a feed)."
    )
    failed_at: datetime | None = Field(description="Last failed fetch.")
    fetch_failures: int = Field(description="Failed fetches in a row.")
    fetch_error: str | None = Field(description="Error of the last failed fetch.")


class SourceActivity(BaseModel):
    """Articles first seen in the last 30 days."""

    articles: int
    ranked: int = Field(description="Near the top of a day's ranking.")
    shown: int = Field(description="In a digest.")
    opened: int


class SourceOut(BaseModel):
    id: int
    name: str
    url: str = Field(description="Feed URL.")
    site_url: str | None
    kind: SourceKind
    status: SourceStatus
    origin: SourceOrigin
    origin_detail: str | None = Field(description="What proposed it, e.g. a search adapter.")
    note: str | None = Field(description="Why it has its status, e.g. a judge's verdict.")
    created_at: datetime
    health: SourceHealth
    activity: SourceActivity

    @classmethod
    def of(cls, source: Source, stats: SourceStats | None) -> "SourceOut":
        return cls(
            id=source.id,
            name=source.name,
            url=source.url,
            site_url=source.site_url,
            kind=source.kind,
            status=source.status,
            origin=source.origin,
            origin_detail=source.origin_detail,
            note=source.note,
            created_at=source.created_at,
            health=SourceHealth(
                fetched_at=source.fetched_at,
                failing_since=source.failing_since,
                permanent_failing_since=source.permanent_failing_since,
                failed_at=source.failed_at,
                fetch_failures=source.fetch_failures,
                fetch_error=source.fetch_error,
            ),
            activity=SourceActivity(
                articles=stats.articles if stats else 0,
                ranked=stats.ranked if stats else 0,
                shown=stats.shown if stats else 0,
                opened=stats.opened if stats else 0,
            ),
        )


class NewSource(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2000,
        pattern=NO_NUL,
        description="The feed, or any page of the site: its feed is looked up.",
    )
    name: str | None = Field(
        None,
        max_length=200,
        pattern=NO_NUL,
        description="Display name; defaults to the feed's title.",
    )


Decision = Literal[SourceStatus.ACTIVE, SourceStatus.MUTED, SourceStatus.REJECTED]


class SourceChange(BaseModel):
    """Fields to change; the ones left out (or null) stay as they are."""

    name: str | None = Field(None, min_length=1, max_length=200, pattern=NO_NUL)
    status: Decision | None = Field(
        None,
        description="active reads it (also approves a pending one), muted stops reading it, "
        "rejected declines a pending one so it is not proposed again.",
    )
    reason: str | None = Field(
        None,
        max_length=1000,
        pattern=NO_NUL,
        description="Why, kept in the change log with a new status.",
    )


def _parse_key(values: list[str]) -> tuple[str, int]:
    name, source_id = values
    parsed = as_id(source_id)
    if parsed is None:
        raise ValueError(f"not a source ID: {source_id!r}")
    return name, parsed


def _key(source: Source) -> list[str]:
    return [source.name, str(source.id)]


def _out(session: DbSession, source: Source) -> SourceOut:
    stats = sources.recent_stats(session, datetime.now(UTC), [source.id])
    return SourceOut.of(source, stats.get(source.id))


@router.get(
    "",
    summary="List sources",
    responses=problems.responses(HTTPStatus.BAD_REQUEST),
)
def list_sources(
    session: DbSession,
    status: Annotated[
        list[SourceStatus] | None,
        Query(description="Only sources with one of these statuses, e.g. pending ones."),
    ] = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> Page[SourceOut]:
    """By name, with fetch health and what each published in the last 30 days."""
    after = decode_cursor(cursor, _parse_key)
    rows = sources.page_sources(session, limit + 1, status or (), after)
    items, next_cursor = page(rows, limit, _key)
    stats = sources.recent_stats(session, datetime.now(UTC), [source.id for source in items])
    return Page(
        items=[SourceOut.of(source, stats.get(source.id)) for source in items],
        next_cursor=next_cursor,
    )


@router.get(
    "/{source_id}",
    summary="Get a source",
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def get_source(session: DbSession, source_id: Id) -> SourceOut:
    return _out(session, sources.get_source(session, source_id))


@router.post(
    "",
    summary="Add a source",
    status_code=status.HTTP_201_CREATED,
    responses=problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
)
def add_source(sessions: Sessions, clients: Clients, actor: Actor, new: NewSource) -> SourceOut:
    """Looks up the feed of the page, then reads it from the next digest on.

    404 when the page has no RSS or Atom feed, 409 when it is already a source
    (whatever its status: enable a muted or rejected one instead).
    """
    with sessions.begin() as session:
        # Before any request to the site, as the finder will read the URL.
        sources.ensure_unknown(session, with_scheme(new.url))
    # No transaction is held while the site answers.
    with clients.feed_finder() as finder:
        found = sources.find_feed(finder, new.url)
    with sessions.begin() as session:
        source = sources.add_source(
            session,
            found.url,
            actor=actor,
            name=new.name,
            title=found.title,
            site_url=found.site_url,
        )
        return _out(session, source)


@router.patch(
    "/{source_id}",
    summary="Rename a source or change its status",
    responses=problems.responses(HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT),
)
def change_source(
    session: DbSession, actor: Actor, source_id: Id, change: SourceChange
) -> SourceOut:
    """Sources are never deleted: a muted or rejected one keeps its history and
    is not proposed again."""
    source = sources.get_source(session, source_id)
    if change.name is not None:
        sources.rename_source(session, source, change.name, actor=actor)
    if change.status is not None:
        sources.change_status(session, source, change.status, actor=actor, reason=change.reason)
    return _out(session, source)
