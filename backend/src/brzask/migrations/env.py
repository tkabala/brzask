"""Alembic environment: runs migrations against the configured database."""

from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

import brzask.db.models  # noqa: F401  (registers the tables on Base.metadata)
from brzask.config import get_settings
from brzask.db.base import Base

# Any constant works; it only has to be the same for every migrate process.
MIGRATION_LOCK_ID = 0x62727A61736B  # "brzask"


def _render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    # Render pgvector columns as Vector(n), imported in script.py.mako.
    if type_ == "type" and isinstance(obj, Vector):
        return f"Vector({obj.dim})"
    return False


def _database_url() -> str:
    url = context.config.attributes.get("url")
    return url if isinstance(url, str) else get_settings().database.url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            render_item=_render_item,
        )
        with context.begin_transaction():
            # Two processes starting at once (e.g. api and worker) migrate one after another.
            connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATION_LOCK_ID})
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
