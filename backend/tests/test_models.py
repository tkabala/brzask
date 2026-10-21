from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.schema import CreateTable

from brzask.db.base import Base
from brzask.db.models import EMBEDDING_DIMENSIONS, Article, Source, SourceStatus

# SQLAlchemy's dialect constructors are not annotated.
POSTGRES = PGDialect()  # type: ignore[no-untyped-call]


def ddl(table_name: str) -> str:
    table = Base.metadata.tables[table_name]
    return str(CreateTable(table).compile(dialect=POSTGRES))


def test_all_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "sources",
        "interests",
        "articles",
        "article_embeddings",
        "runs",
        "settings",
        "change_log",
        "api_tokens",
        "login_sessions",
    }


def test_every_table_compiles_for_postgres() -> None:
    for name in Base.metadata.tables:
        assert f"CREATE TABLE {name}" in ddl(name)


def test_articles_join_sources_by_id() -> None:
    [foreign_key] = Article.__table__.c.source_id.foreign_keys

    assert foreign_key.target_fullname == "sources.id"
    assert foreign_key.ondelete == "SET NULL"


def test_embedding_column_has_fixed_width() -> None:
    assert f"embedding VECTOR({EMBEDDING_DIMENSIONS}) NOT NULL" in ddl("article_embeddings")


def test_statuses_are_text_with_check_constraints() -> None:
    sql = ddl("sources")

    assert "status VARCHAR" in sql or "status TEXT" in sql
    assert "CONSTRAINT ck_sources_source_status CHECK" in sql
    for status in SourceStatus:
        assert f"'{status.value}'" in sql


def test_constraint_names_follow_the_convention() -> None:
    sql = ddl("articles")

    assert "CONSTRAINT pk_articles PRIMARY KEY" in sql
    assert "CONSTRAINT uq_articles_link UNIQUE" in sql
    assert "CONSTRAINT uq_articles_digest_date_digest_position UNIQUE" in sql
    assert "CONSTRAINT fk_articles_source_id_sources FOREIGN KEY" in sql
    embeddings = ddl("article_embeddings")
    assert "CONSTRAINT pk_article_embeddings PRIMARY KEY (article_id, model)" in embeddings
    assert "CONSTRAINT fk_article_embeddings_article_id_articles FOREIGN KEY" in embeddings


def test_enum_values_are_stored_not_member_names() -> None:
    sql = ddl("sources")

    assert "'active'" in sql
    assert "'ACTIVE'" not in sql
    assert Source.__table__.c.status.type.length is None  # type: ignore[attr-defined]
