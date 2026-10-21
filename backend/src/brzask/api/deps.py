"""Dependencies shared by routers."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker


def get_session(request: Request) -> Iterator[Session]:
    """One transaction per request, committed when the route returns without an error."""
    sessions: sessionmaker[Session] = request.app.state.sessions
    with sessions.begin() as session:
        yield session


DbSession = Annotated[Session, Depends(get_session)]
