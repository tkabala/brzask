"""What the instance holds, what ran last, and pausing the digest."""

from datetime import UTC, date, datetime
from http import HTTPStatus

from fastapi import APIRouter, status
from pydantic import AwareDatetime, BaseModel, Field

from brzask.api import problems
from brzask.api.deps import ACTOR, DbSession
from brzask.api.runs import RunOut
from brzask.config import get_settings
from brzask.db.models import RunKind, SourceStatus
from brzask.services import pause as pausing
from brzask.services.status import get_status

router = APIRouter(tags=["status"])


class ArticleCountsOut(BaseModel):
    total: int
    shown: int
    opened: int


class StatusOut(BaseModel):
    articles: ArticleCountsOut
    sources: dict[SourceStatus, int] = Field(description="Every status, zero included.")
    last_digest: date | None
    paused_until: datetime | None
    last_runs: dict[RunKind, RunOut | None] = Field(
        description="Every pipeline; null when it never ran."
    )
    embedding_model: str = Field(description="The model new vectors and queries use.")
    embeddings: dict[str, int] = Field(description="Stored vectors by model.")


class Pause(BaseModel):
    until: datetime | None = Field(description="No digest is built before this; null: not paused.")


class NewPause(BaseModel):
    until: AwareDatetime = Field(description="When the digest resumes; with a time zone.")


@router.get("/status", summary="Counts, the pause and the last runs")
def read_status(session: DbSession) -> StatusOut:
    current = get_status(session, datetime.now(UTC), get_settings().embedding.model)
    articles = current.articles
    return StatusOut(
        articles=ArticleCountsOut(
            total=articles.total, shown=articles.shown, opened=articles.opened
        ),
        sources=current.sources,
        last_digest=current.last_digest,
        paused_until=current.paused_until,
        last_runs={
            kind: RunOut.model_validate(run) if run else None
            for kind, run in current.last_runs.items()
        },
        embedding_model=current.embedding_model,
        embeddings=current.embeddings,
    )


@router.get("/pause", summary="Whether the digest is paused")
def get_pause(session: DbSession) -> Pause:
    return Pause(until=pausing.paused_until(session, datetime.now(UTC)))


@router.put(
    "/pause",
    summary="Pause the digest",
    responses=problems.responses(HTTPStatus.BAD_REQUEST),
)
def set_pause(session: DbSession, new: NewPause) -> Pause:
    """E.g. for a holiday; replaces a pause already set. 400 when `until` is not in the future."""
    pausing.pause(session, new.until, datetime.now(UTC), actor=ACTOR)
    return Pause(until=new.until)


@router.delete("/pause", summary="Resume the digest", status_code=status.HTTP_204_NO_CONTENT)
def delete_pause(session: DbSession) -> None:
    """Ends a pause now; nothing happens when the digest was not paused."""
    pausing.resume(session, datetime.now(UTC), actor=ACTOR)
