"""Applying database migrations."""

import logging
from functools import lru_cache

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, create_engine
from sqlalchemy.pool import NullPool

from brzask.config import get_settings
from brzask.log import get_logger

log = get_logger(__name__)

SCRIPT_LOCATION = "brzask:migrations"


class _AlembicSetupFilter(logging.Filter):
    """Drops the setup lines Alembic logs on every connection; keeps 'Running upgrade ...'."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not message.startswith(("Context impl", "Will assume"))


logging.getLogger("alembic.runtime.migration").addFilter(_AlembicSetupFilter())


def alembic_config(url: str | None = None) -> Config:
    """Alembic configuration for the packaged migrations.

    The URL is passed as an attribute rather than an ini option, so passwords
    with '%' need no escaping.
    """
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    config.attributes["url"] = url or get_settings().database.url
    return config


def current_revision(url: str) -> str | None:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def is_current(connection: Connection) -> bool:
    """Whether the database behind `connection` is at the latest revision."""
    return MigrationContext.configure(connection).get_current_revision() == head_revision()


@lru_cache(maxsize=1)
def head_revision() -> str | None:
    """The latest revision among the packaged migrations."""
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    return ScriptDirectory.from_config(config).get_current_head()


def migrate(url: str | None = None) -> None:
    """Upgrade the database to the latest revision. Safe to run repeatedly."""
    config = alembic_config(url)
    database_url: str = config.attributes["url"]
    before = current_revision(database_url)
    command.upgrade(config, "head")
    after = current_revision(database_url)
    if before == after:
        log.info("database is up to date", revision=after)
    else:
        log.info("database migrated", from_revision=before, to_revision=after)
