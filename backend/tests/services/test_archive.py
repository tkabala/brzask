import gzip
import io
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from brzask.db.migrations import head_revision
from brzask.db.models import (
    ApiToken,
    Change,
    ChangeStatus,
    Interest,
    LoginSession,
    RunKind,
    Setting,
    Source,
    SourceStatus,
    TokenScope,
)
from brzask.services.archive import (
    FORMAT,
    TABLES,
    ArchiveError,
    export_archive,
    import_archive,
)
from brzask.services.runs import pipeline_lock
from tests.factories import Factories

NOW = datetime(2026, 11, 6, 5, 0, tzinfo=UTC)


def fill_every_table(session: Session, make: Factories) -> None:
    """At least one row in every table, the excluded login sessions included."""
    feed = make.source(name="Feed", note="ok", fetched_at=NOW)
    make.source(name="Muted", status=SourceStatus.MUTED, fetch_failures=3, failing_since=NOW)
    make.interest(topic="AI", keywords=["llm", "agents"], notes="want: evals")
    make.article(feed, first_seen_at=NOW, embedding=[0.25] * 768)
    make.article(
        feed,
        first_seen_at=NOW,
        digest_date=date(2026, 11, 6),
        opened_at=NOW + timedelta(hours=2),
        summary="A summary.",
        topic="AI",
        embedding=[0.5] * 768,
    )
    make.run(NOW, cost=0.0042)
    session.add_all(
        [
            Setting(key="embedding_model", value={"model": "test/model"}),
            Change(
                actor="user",
                action="source.mute",
                entity_type="source",
                entity_id="2",
                before={"status": "active"},
                after={"status": "muted"},
                status=ChangeStatus.APPLIED,
            ),
            ApiToken(name="reader", prefix="brz_abcd", token_hash="0" * 64, scope=TokenScope.READ),
            LoginSession(token_hash="1" * 64, expires_at=NOW + timedelta(days=30)),
        ]
    )
    session.flush()


def export_lines(session: Session) -> list[dict[str, Any]]:
    out = io.BytesIO()
    export_archive(session, out, version="0.1.17")
    return [json.loads(line) for line in gzip.decompress(out.getvalue()).splitlines()]


def test_export_writes_header_rows_and_trailer(session: Session, make: Factories) -> None:
    fill_every_table(session, make)

    lines = export_lines(session)

    first, *rows, last = lines
    assert first["format"] == FORMAT
    assert first["format_version"] == 1
    assert first["brzask"] == "0.1.17"
    assert first["revision"] == head_revision()
    order = [t.name for t in TABLES]
    tables = [row["table"] for row in rows]
    assert tables == sorted(tables, key=order.index)
    assert "login_sessions" not in tables
    counts = {name: tables.count(name) for name in order}
    assert last == {"end": {"counts": counts}}
    assert counts["sources"] == 2
    assert counts["article_embeddings"] == 2
    assert all(counts.values())


def test_export_counts_empty_tables_as_zero(session: Session, make: Factories) -> None:
    make.interest(topic="Only")

    *_, last = export_lines(session)

    assert last["end"]["counts"]["interests"] == 1
    assert last["end"]["counts"]["articles"] == 0


def test_rows_are_ordered_by_primary_key(session: Session, make: Factories) -> None:
    for n in range(5):
        make.source(name=f"S{n}")

    ids = [line["row"]["id"] for line in export_lines(session) if line.get("table") == "sources"]

    assert ids == sorted(ids)


def test_rows_hold_every_column_as_plain_json(session: Session, make: Factories) -> None:
    fill_every_table(session, make)
    run_id = session.scalars(select(TABLES[4].c.id)).one()

    rows = {line["table"]: line["row"] for line in export_lines(session) if "table" in line}

    assert set(rows["sources"]) == set(TABLES[0].columns.keys())
    assert uuid.UUID(rows["runs"]["id"]) == run_id
    assert rows["interests"]["keywords"] == ["llm", "agents"]
    assert datetime.fromisoformat(rows["articles"]["first_seen_at"]) == NOW
    assert len(rows["article_embeddings"]["embedding"]) == 768


def test_export_is_stable(session: Session, make: Factories) -> None:
    fill_every_table(session, make)

    first = export_lines(session)
    second = export_lines(session)

    assert first[1:] == second[1:]


def test_export_needs_the_latest_schema(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("brzask.services.archive.migrations.is_current", lambda connection: False)

    with pytest.raises(Exception, match="run brzask migrate first"):
        export_archive(session, io.BytesIO(), version="0.1.17")


# --- Import ----------------------------------------------------------------------


def snapshot(session: Session) -> dict[str, list[dict[str, Any]]]:
    return {
        table.name: [
            dict(row)
            for row in session.execute(
                select(table).order_by(*table.primary_key.columns)
            ).mappings()
        ]
        for table in TABLES
    }


def clear(session: Session) -> None:
    session.execute(delete(LoginSession))
    for table in reversed(TABLES):
        session.execute(delete(table))
    session.flush()


def archive_of(session: Session) -> bytes:
    out = io.BytesIO()
    export_archive(session, out, version="0.1.17")
    return out.getvalue()


def lines_to_archive(lines: list[dict[str, Any]]) -> bytes:
    return gzip.compress(b"".join(json.dumps(line).encode() + b"\n" for line in lines))


def assert_empty(session: Session) -> None:
    session.expire_all()
    assert all(not rows for rows in snapshot(session).values())


def test_round_trip(session: Session, sessions: sessionmaker[Session], make: Factories) -> None:
    fill_every_table(session, make)
    before = snapshot(session)
    data = archive_of(session)
    clear(session)

    counts = import_archive(sessions, io.BytesIO(data))

    session.expire_all()
    assert snapshot(session) == before
    assert counts == {name: len(rows) for name, rows in before.items()}
    assert session.scalar(select(func.count()).select_from(LoginSession)) == 0


def test_new_rows_get_ids_after_the_restored_ones(
    session: Session, sessions: sessionmaker[Session], make: Factories
) -> None:
    make.source(name="Template")
    lines = [json.loads(line) for line in gzip.decompress(archive_of(session)).splitlines()]
    header_line, source_line, *_ = lines
    rows = [
        {
            "table": "sources",
            "row": {
                **source_line["row"],
                "id": n,
                "name": f"S{n}",
                "url": f"https://s{n}.example/feed",
            },
        }
        for n in (1000, 1001)
    ]
    counts = {name: 0 for name in lines[-1]["end"]["counts"]} | {"sources": 2}
    clear(session)
    interest_before = make.interest(topic="Probe").id
    clear(session)

    import_archive(
        sessions, io.BytesIO(lines_to_archive([header_line, *rows, {"end": {"counts": counts}}]))
    )

    assert make.source(name="After").id == 1002
    assert (
        make.interest(topic="New").id == interest_before + 1
    )  # an empty table's sequence is left alone


def test_refuses_a_database_with_rows(
    session: Session, sessions: sessionmaker[Session], make: Factories
) -> None:
    make.interest(topic="AI")
    data = archive_of(session)

    with pytest.raises(ArchiveError, match="the database is not empty: interests"):
        import_archive(sessions, io.BytesIO(data))


def test_refuses_a_database_behind_the_latest_migration(
    session: Session, sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    data = archive_of(session)
    monkeypatch.setattr("brzask.services.archive.migrations.is_current", lambda connection: False)

    with pytest.raises(ArchiveError, match="run brzask migrate first"):
        import_archive(sessions, io.BytesIO(data))


def test_refuses_an_archive_from_a_newer_brzask(
    session: Session, sessions: sessionmaker[Session]
) -> None:
    first, *rest = [json.loads(line) for line in gzip.decompress(archive_of(session)).splitlines()]
    first["revision"] = "ffffffffffff"

    with pytest.raises(ArchiveError, match="newer brzask"):
        import_archive(sessions, io.BytesIO(lines_to_archive([first, *rest])))


def broken_archives(data: bytes) -> dict[str, bytes]:
    lines = [json.loads(line) for line in gzip.decompress(data).splitlines()]
    *body, trailer = lines
    wrong = json.loads(json.dumps(trailer))
    wrong["end"]["counts"]["sources"] += 1
    return {
        "without the trailer": lines_to_archive(body),
        "with a wrong count": lines_to_archive([*body, wrong]),
        "with lines after the trailer": lines_to_archive([*lines, body[1]]),
        "cut in the middle": data[: len(data) // 2],
        "not gzip": b"sources,articles\n",
        "with an unknown table": lines_to_archive(
            [body[0], {"table": "colours", "row": {}}, *body[1:], trailer]
        ),
        "with tables out of order": lines_to_archive([body[0], *reversed(body[1:]), trailer]),
    }


@pytest.mark.parametrize(
    "case",
    [
        "without the trailer",
        "with a wrong count",
        "with lines after the trailer",
        "cut in the middle",
        "not gzip",
        "with an unknown table",
        "with tables out of order",
    ],
)
def test_refuses_a_damaged_archive_and_writes_nothing(
    case: str, session: Session, sessions: sessionmaker[Session], make: Factories
) -> None:
    fill_every_table(session, make)
    data = broken_archives(archive_of(session))[case]
    clear(session)

    with pytest.raises(ArchiveError):
        import_archive(sessions, io.BytesIO(data))

    assert_empty(session)


def test_a_wrong_count_names_the_table(
    session: Session, sessions: sessionmaker[Session], make: Factories
) -> None:
    fill_every_table(session, make)
    data = broken_archives(archive_of(session))["with a wrong count"]
    clear(session)

    with pytest.raises(ArchiveError, match=r"rows read sources 2 of 3$"):
        import_archive(sessions, io.BytesIO(data))


def test_refuses_while_a_digest_runs(
    session: Session, sessions: sessionmaker[Session], make: Factories, db_engine: Engine
) -> None:
    make.interest(topic="AI")
    data = archive_of(session)
    clear(session)

    with pipeline_lock(db_engine, RunKind.DIGEST) as acquired:
        assert acquired
        with pytest.raises(ArchiveError, match="a pipeline is running"):
            import_archive(sessions, io.BytesIO(data))

    assert_empty(session)


def test_an_older_archive_without_a_column_gets_its_default(
    session: Session, sessions: sessionmaker[Session], make: Factories
) -> None:
    make.source(name="Old")
    make.source(name="Older")
    lines = [json.loads(line) for line in gzip.decompress(archive_of(session)).splitlines()]
    for line in lines:
        if line.get("table") == "sources":
            del line["row"]["kind"]
            del line["row"]["fetch_failures"]
    lines[2]["row"].pop("note")  # rows of one table need not share their columns
    clear(session)

    import_archive(sessions, io.BytesIO(lines_to_archive(lines)))

    assert [s.kind for s in session.scalars(select(Source))] == ["feed", "feed"]
    assert session.scalar(select(func.count()).select_from(Interest)) == 0


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("first_seen_at", "yesterday"),
        ("first_seen_at", 17),
        ("state", "forgotten"),
        ("id", "abc"),
    ],
)
def test_a_bad_value_names_its_line_and_column(
    column: str, value: Any, session: Session, sessions: sessionmaker[Session], make: Factories
) -> None:
    make.article(make.source(name="Feed"), first_seen_at=NOW)
    lines = [json.loads(line) for line in gzip.decompress(archive_of(session)).splitlines()]
    article = next(i for i, line in enumerate(lines) if line.get("table") == "articles")
    lines[article]["row"][column] = value
    clear(session)

    with pytest.raises(ArchiveError, match=rf"line {article + 1}: articles\.{column}"):
        import_archive(sessions, io.BytesIO(lines_to_archive(lines)))

    assert_empty(session)


def test_a_vector_of_the_wrong_size_is_a_message(
    session: Session, sessions: sessionmaker[Session], make: Factories
) -> None:
    make.article(make.source(name="Feed"), first_seen_at=NOW, embedding=[0.5] * 768)
    lines = [json.loads(line) for line in gzip.decompress(archive_of(session)).splitlines()]
    for line in lines:
        if line.get("table") == "article_embeddings":
            line["row"]["embedding"] = [0.5, 0.5, 0.5]
    clear(session)

    with pytest.raises(ArchiveError, match="does not fit the database"):
        import_archive(sessions, io.BytesIO(lines_to_archive(lines)))

    assert_empty(session)


def test_a_json_null_stays_a_json_null(session: Session, sessions: sessionmaker[Session]) -> None:
    """The app stores None in a JSON column as JSON null; a restore keeps it that way."""
    session.add(
        Change(
            actor="user",
            action="source.add",
            entity_type="source",
            before=None,
            after={"status": "active"},
            status=ChangeStatus.APPLIED,
        )
    )
    session.flush()
    json_null = select(func.count()).where(func.jsonb_typeof(Change.before) == "null")
    assert session.scalar(json_null) == 1
    data = archive_of(session)
    clear(session)

    import_archive(sessions, io.BytesIO(data))

    assert session.scalar(json_null) == 1
