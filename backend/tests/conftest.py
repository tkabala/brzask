from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from brzask.config import get_settings

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


@pytest.fixture
def empty_database_url(postgres: PostgresContainer) -> Iterator[str]:
    """URL of a new, empty database on the test server, dropped after the test."""
    server_url = postgres.get_connection_url()
    name = f"test_{uuid4().hex[:12]}"
    admin = create_engine(server_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    yield make_url(server_url).set(database=name).render_as_string(hide_password=False)
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()
