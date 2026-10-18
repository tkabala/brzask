"""Engine and session creation.

Repositories take a `Session` and never commit; the caller owns the unit of work:

    with factory.begin() as session:
        SourceRepository(session).add(...)
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from brzask.config import get_settings


def create_db_engine(url: str | None = None) -> Engine:
    """Engine for the configured database; `pool_pre_ping` survives database restarts."""
    return create_engine(url or get_settings().database.url, pool_pre_ping=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    # Objects stay readable after commit, so services can return what they wrote.
    return sessionmaker(engine, expire_on_commit=False)
