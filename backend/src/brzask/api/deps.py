"""Dependencies shared by routers."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Path, Request
from sqlalchemy.orm import Session, sessionmaker

from brzask.api.clients import ApiClients
from brzask.services.refs import MAX_ID

# Who changes are recorded as when no user name or token says more.
ACTOR = "user"


def get_session(request: Request) -> Iterator[Session]:
    """One transaction per request, committed when the route returns without an error."""
    sessions: sessionmaker[Session] = request.app.state.sessions
    with sessions.begin() as session:
        yield session


def get_sessions(request: Request) -> sessionmaker[Session]:
    """For routes that must not hold a transaction open, e.g. while fetching a site."""
    sessions: sessionmaker[Session] = request.app.state.sessions
    return sessions


def get_clients(request: Request) -> ApiClients:
    clients: ApiClients = request.app.state.clients
    return clients


DbSession = Annotated[Session, Depends(get_session)]
Sessions = Annotated[sessionmaker[Session], Depends(get_sessions)]
Clients = Annotated[ApiClients, Depends(get_clients)]

# The largest ID the API takes: within Postgres bigints, so a larger number is no
# ID rather than a database error, and exact in JavaScript (2**53 - 1), which
# reads the document and the IDs as doubles.
MAX_API_ID = min(MAX_ID, 2**53 - 1)

Id = Annotated[int, Path(ge=1, le=MAX_API_ID)]

# Postgres text cannot hold NUL characters; the schema says so instead of the
# database failing on them.
NO_NUL = r"^[^\x00]*$"
