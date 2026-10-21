"""Liveness and readiness probes, outside the versioned API."""

from http import HTTPStatus
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from brzask.api import problems
from brzask.api.problems import ProblemError
from brzask.db.migrations import is_current
from brzask.log import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/healthz", summary="The process is up")
def healthz() -> Health:
    """Answers as long as the process serves requests; touches nothing else."""
    return Health()


@router.get(
    "/readyz",
    summary="The process can serve the API",
    responses=problems.responses(HTTPStatus.SERVICE_UNAVAILABLE),
)
def readyz(request: Request) -> Health:
    """The database answers and its schema is at the latest migration."""
    sessions: sessionmaker[Session] = request.app.state.sessions
    try:
        with sessions() as session:
            current = is_current(session.connection())
    except SQLAlchemyError as error:
        log.warning("not ready: database unreachable", error=str(error))
        raise ProblemError(
            HTTPStatus.SERVICE_UNAVAILABLE, "The database is unreachable."
        ) from error
    if not current:
        raise ProblemError(
            HTTPStatus.SERVICE_UNAVAILABLE, "The database schema is not migrated; run migrate."
        )
    return Health()
