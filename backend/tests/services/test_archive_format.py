import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import Table

from brzask.db.base import Base
from brzask.db.models import ArticleState, RunKind, RunStatus, SourceKind
from brzask.services.archive import (
    EXCLUDED,
    FORMAT,
    FORMAT_VERSION,
    TABLES,
    ArchiveError,
    check_header,
    decode_row,
    encode_row,
    header,
)


def table(name: str) -> Table:
    return Base.metadata.tables[name]


def through_json(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    return decode_row(table, json.loads(json.dumps(encode_row(table, row))))


def test_every_model_table_is_exported_or_excluded() -> None:
    exported = {t.name for t in TABLES}
    assert exported | EXCLUDED == set(Base.metadata.tables)
    assert not exported & EXCLUDED


def test_tables_come_after_the_tables_they_point_to() -> None:
    position = {t.name: i for i, t in enumerate(TABLES)}
    for t in TABLES:
        for key in t.foreign_keys:
            assert position[key.column.table.name] < position[t.name], (t.name, key)


def test_article_values_round_trip() -> None:
    row = {
        "id": 7,
        "link": "https://news.example/a",
        "first_seen_at": datetime(2026, 11, 6, 5, 0, tzinfo=UTC),
        "digest_date": date(2026, 11, 6),
        "state": ArticleState.SHOWN,
        "opened_at": None,
    }
    assert through_json(table("articles"), row) == row


def test_a_uuid_that_is_no_text_is_an_archive_error() -> None:
    with pytest.raises(ArchiveError, match=r"runs\.id"):
        decode_row(table("runs"), {"id": 123})


def test_vectors_round_trip_exactly() -> None:
    vector = [0.12345679, -1e-7, 3.4028235e38] + [0.0] * 765
    row = {"article_id": 1, "model": "m", "embedding": vector}
    assert through_json(table("article_embeddings"), row) == row


def test_run_values_round_trip_and_json_stays_as_it_was() -> None:
    row = {
        "id": uuid.UUID("0b6f8f2e-6f0a-4b8e-9a52-3d1c1f8a7e10"),
        "kind": RunKind.DIGEST,
        "status": RunStatus.OK,
        "stats": {"usage": {"cost_usd": 0.0042}, "at": "2026-11-06"},
        "started_at": datetime(2026, 11, 6, 5, 0, tzinfo=UTC),
    }
    decoded = through_json(table("runs"), row)
    assert decoded == row
    assert decoded["stats"]["at"] == "2026-11-06"


def test_arrays_and_enums_round_trip() -> None:
    interest = {"id": 1, "topic": "AI", "keywords": ["llm", "agents"], "active": True}
    assert through_json(table("interests"), interest) == interest
    source = {"id": 1, "kind": SourceKind.FEED}
    assert through_json(table("sources"), source)["kind"] is SourceKind.FEED


def test_encoded_values_are_plain_json() -> None:
    encoded = encode_row(
        table("articles"),
        {
            "first_seen_at": datetime(2026, 11, 6, 5, 0, tzinfo=UTC),
            "digest_date": date(2026, 11, 6),
        },
    )
    assert encoded == {"first_seen_at": "2026-11-06T05:00:00+00:00", "digest_date": "2026-11-06"}


def test_an_unknown_column_is_an_error() -> None:
    with pytest.raises(ArchiveError, match="sources: unknown column colour"):
        decode_row(table("sources"), {"id": 1, "colour": "red"})


def test_missing_columns_are_left_out() -> None:
    assert decode_row(table("sources"), {"id": 1}) == {"id": 1}


def test_header_names_the_format_and_revision() -> None:
    line = header("0.1.17", "abc123", datetime(2026, 11, 6, 5, 0, tzinfo=UTC))
    assert line == {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "brzask": "0.1.17",
        "revision": "abc123",
        "exported_at": "2026-11-06T05:00:00+00:00",
    }
    assert check_header(json.loads(json.dumps(line))) == "abc123"


@pytest.mark.parametrize(
    "line",
    [
        {"format": "something-else", "format_version": 1, "revision": "abc"},
        {"format": FORMAT, "format_version": 2, "revision": "abc"},
        {"format": FORMAT, "format_version": 1},
        {"table": "sources", "row": {}},
    ],
)
def test_a_header_from_elsewhere_is_refused(line: dict[str, Any]) -> None:
    with pytest.raises(ArchiveError):
        check_header(line)
