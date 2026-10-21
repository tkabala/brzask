"""Pipeline runs."""

import uuid
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from brzask.api import problems
from brzask.api.deps import DbSession
from brzask.api.pagination import (
    DEFAULT_LIMIT,
    CursorParam,
    Limit,
    Page,
    decode_cursor,
    page,
)
from brzask.db.models import Run, RunKind, RunStatus
from brzask.services import runs

router = APIRouter(prefix="/runs", tags=["runs"])


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: RunKind
    status: RunStatus
    dry_run: bool
    started_at: datetime
    finished_at: datetime | None
    stats: dict[str, Any]
    timings: dict[str, Any]
    error: str | None


def _key(run: Run) -> tuple[str, str]:
    return run.started_at.isoformat(), str(run.id)


def _parse_key(values: list[str]) -> tuple[datetime, uuid.UUID]:
    started_at, run_id = values
    return datetime.fromisoformat(started_at), uuid.UUID(run_id)


@router.get(
    "",
    summary="List pipeline runs",
    responses=problems.responses(HTTPStatus.BAD_REQUEST),
)
def list_runs(
    session: DbSession,
    kind: Annotated[RunKind | None, Query(description="Only runs of this pipeline.")] = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> Page[RunOut]:
    """Runs newest first, including ones still running."""
    after = decode_cursor(cursor, _parse_key)
    rows = runs.list_runs(session, limit + 1, kind=kind, after=after)
    items, next_cursor = page(rows, limit, _key)
    return Page(items=[RunOut.model_validate(run) for run in items], next_cursor=next_cursor)


@router.get(
    "/{run_id}",
    summary="Get a run",
    responses=problems.responses(HTTPStatus.NOT_FOUND),
)
def get_run(session: DbSession, run_id: uuid.UUID) -> RunOut:
    """With its stats (counts, costs) and stage timings."""
    return RunOut.model_validate(runs.get_run(session, run_id))
