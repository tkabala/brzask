"""Portable archive of an instance: every durable table as gzip'd JSON Lines.

An archive does not depend on the Postgres version, pgvector or the schema
version it came from: a newer brzask imports an older archive. One JSON
object per line: a header naming the format and the schema revision, one
line per row (`{"table": ..., "row": {...}}`, tables in foreign-key order,
rows by primary key), and a trailer with the number of rows per table. A
file cut short has no trailer, so it is never mistaken for a whole one.
"""

import gzip
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, BinaryIO

from sqlalchemy import Date, DateTime, Enum, Table, Uuid, select
from sqlalchemy.orm import Session

from brzask.db import migrations
from brzask.db.base import Base
from brzask.services.errors import ServiceError

FORMAT = "brzask-export"
FORMAT_VERSION = 1

# In foreign-key order, so rows can be inserted as they are read.
TABLES: tuple[Table, ...] = tuple(
    Base.metadata.tables[name]
    for name in (
        "sources",
        "interests",
        "articles",
        "article_embeddings",
        "runs",
        "settings",
        "change_log",
        "api_tokens",
    )
)
# Login sessions last days and only sign a browser in; after a restore everyone
# signs in again instead of an archive carrying them around.
EXCLUDED = frozenset({"login_sessions"})

Counts = dict[str, int]

# Rows fetched from the database at a time while exporting.
EXPORT_BATCH = 500


class ArchiveError(ServiceError):
    pass


def encode_row(table: Table, row: Mapping[str, Any]) -> dict[str, Any]:
    """`row` as plain JSON values: timestamps and dates in ISO 8601, UUIDs as text."""
    return {name: _encode(value) for name, value in row.items()}


def _encode(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def decode_row(table: Table, row: Mapping[str, Any]) -> dict[str, Any]:
    """`row` read from an archive, with values of the column types; only the columns given.

    Only the column type decides: text inside a JSON column stays text, even
    when it looks like a date.
    """
    decoded = {}
    for name, value in row.items():
        column = table.columns.get(name)
        if column is None:
            raise ArchiveError(f"{table.name}: unknown column {name}")
        decoded[name] = None if value is None else _decode(column.type, value)
    return decoded


def _decode(kind: Any, value: Any) -> Any:
    if isinstance(kind, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(kind, Date):
        return date.fromisoformat(value)
    if isinstance(kind, Uuid):
        return uuid.UUID(value)
    if isinstance(kind, Enum) and kind.enum_class is not None:
        return kind.enum_class(value)
    return value


def header(version: str, revision: str, exported_at: datetime) -> dict[str, Any]:
    """The first line of an archive."""
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "brzask": version,
        "revision": revision,
        "exported_at": exported_at.isoformat(),
    }


def check_header(line: Mapping[str, Any]) -> str:
    """The schema revision an archive was written at; `ArchiveError` for anything else."""
    if line.get("format") != FORMAT:
        raise ArchiveError("not a brzask archive")
    if line.get("format_version") != FORMAT_VERSION:
        raise ArchiveError(
            f"archive format version {line.get('format_version')} is not supported;"
            f" this brzask reads version {FORMAT_VERSION}"
        )
    revision = line.get("revision")
    if not isinstance(revision, str) or not revision:
        raise ArchiveError("the archive does not name its schema revision")
    return revision


def export_archive(session: Session, out: BinaryIO, *, version: str) -> Counts:
    """Write every exported table to `out`; the number of rows per table.

    The caller owns the transaction: a repeatable-read one gives a consistent
    snapshot while the worker and the API keep writing.
    """
    connection = session.connection()
    if not migrations.is_current(connection):
        raise ArchiveError("the database is not at the latest migration; run brzask migrate first")
    revision = migrations.head_revision()
    if revision is None:
        raise ArchiveError("brzask has no migrations")
    counts: Counts = {}
    # mtime=0: two exports of the same data differ only in the header line.
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as archive:
        _write(archive, header(version, revision, datetime.now(UTC)))
        for table in TABLES:
            counts[table.name] = 0
            rows = session.execute(
                select(table).order_by(*table.primary_key.columns),
                execution_options={"yield_per": EXPORT_BATCH},
            ).mappings()
            for row in rows:
                _write(archive, {"table": table.name, "row": encode_row(table, row)})
                counts[table.name] += 1
        _write(archive, {"end": {"counts": counts}})
    return counts


def _write(archive: gzip.GzipFile, line: Mapping[str, Any]) -> None:
    archive.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")).encode())
    archive.write(b"\n")
