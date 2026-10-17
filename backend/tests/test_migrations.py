from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.pool import NullPool
from typer.testing import CliRunner

import brzask.db.models  # noqa: F401  (registers the tables)
from brzask.cli import app
from brzask.db.base import Base
from brzask.db.migrations import alembic_config, current_revision, migrate


@pytest.fixture
def engine(empty_database_url: str) -> Iterator[Engine]:
    engine = create_engine(empty_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


def head() -> str | None:
    return ScriptDirectory.from_config(alembic_config("postgresql://")).get_current_head()


def test_migrate_twice_creates_the_schema_once(empty_database_url: str, engine: Engine) -> None:
    migrate(empty_database_url)
    migrate(empty_database_url)

    assert current_revision(empty_database_url) == head()
    tables = set(inspect(engine).get_table_names())
    assert tables == set(Base.metadata.tables) | {"alembic_version"}
    with engine.connect() as connection:
        extensions = connection.execute(text("SELECT extname FROM pg_extension")).scalars()
        assert "vector" in set(extensions)


def test_migrations_match_the_models(empty_database_url: str, engine: Engine) -> None:
    migrate(empty_database_url)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], "models changed: run `alembic revision --autogenerate`"


def test_constraints_from_the_models_exist(empty_database_url: str, engine: Engine) -> None:
    migrate(empty_database_url)

    checks = {check["name"] for check in inspect(engine).get_check_constraints("articles")}
    assert {
        "ck_articles_article_state",
        "ck_articles_embedding_has_model",
        "ck_articles_digest_date_and_position",
        "ck_articles_only_shown_articles_in_digest",
    } <= checks
    with engine.connect() as connection:
        column_type = connection.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'articles'::regclass AND attname = 'embedding'"
            )
        ).scalar_one()
    assert column_type == "vector(768)"


def test_downgrade_and_upgrade_again(empty_database_url: str, engine: Engine) -> None:
    config = alembic_config(empty_database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    assert set(inspect(engine).get_table_names()) == {"alembic_version"}

    command.upgrade(config, "head")
    assert current_revision(empty_database_url) == head()


def test_cli_migrate_uses_the_database_settings(
    empty_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = make_url(empty_database_url)
    for key, value in {
        "DB_HOST": url.host,
        "DB_PORT": url.port,
        "DB_NAME": url.database,
        "DB_USER": url.username,
        "DB_PASSWORD": url.password,
    }.items():
        monkeypatch.setenv(key, str(value))

    result = CliRunner().invoke(app, ["migrate"])

    assert result.exit_code == 0, result.output
    assert current_revision(empty_database_url) == head()


def test_migrate_logs_only_meaningful_lines(
    empty_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        migrate(empty_database_url)

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("Running upgrade") for message in messages)
    assert not any(message.startswith(("Context impl", "Will assume")) for message in messages)
