from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from brzask.config import get_settings
from brzask.db.migrations import migrate
from brzask.db.session import create_db_engine
from tests.factories import Factories

POSTGRES_IMAGE = "pgvector/pgvector:pg17"


@pytest.fixture(autouse=True)
def fresh_settings() -> Iterator[None]:
    """Settings are cached per process; each test reads its own environment."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    """One Postgres + pgvector server for the whole test session."""
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        yield container


@contextmanager
def _new_database(postgres: PostgresContainer) -> Iterator[str]:
    """Create an empty database on the test server, yield its URL, drop it afterwards."""
    server_url = postgres.get_connection_url()
    name = f"test_{uuid4().hex[:12]}"
    admin = create_engine(server_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    yield make_url(server_url).set(database=name).render_as_string(hide_password=False)
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def empty_database_url(postgres: PostgresContainer) -> Iterator[str]:
    """URL of a new, empty database, dropped after the test (for migration tests)."""
    with _new_database(postgres) as url:
        yield url


@pytest.fixture(scope="session")
def db_engine(postgres: PostgresContainer) -> Iterator[Engine]:
    """Engine for one database migrated to head, shared by the whole session."""
    with _new_database(postgres) as url:
        migrate(url)
        engine = create_db_engine(url)
        yield engine
        engine.dispose()


@pytest.fixture
def connection(db_engine: Engine) -> Iterator[Connection]:
    """A connection inside a transaction that is rolled back after the test."""
    with db_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def sessions(connection: Connection) -> sessionmaker[Session]:
    """Session factory for code that opens its own transactions (CLI, pipeline runner).

    Commits become savepoints on the test's connection, so the test sees them
    and they are still rolled back afterwards.
    """
    return sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture
def session(sessions: sessionmaker[Session]) -> Iterator[Session]:
    """A session whose work is rolled back after the test.

    Commits inside the code under test become savepoints, so every test starts
    from the same empty, migrated schema.
    """
    with sessions() as session:
        yield session


@pytest.fixture
def make(session: Session) -> Factories:
    """Factories that add rows to the test session."""
    return Factories(session)
