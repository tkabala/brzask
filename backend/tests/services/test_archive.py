import gzip
import io
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from brzask.db.migrations import head_revision
from brzask.db.models import (
    ApiToken,
    Change,
    ChangeStatus,
    LoginSession,
    Setting,
    SourceStatus,
    TokenScope,
)
from brzask.services.archive import FORMAT, TABLES, export_archive
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
