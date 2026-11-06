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
import zlib
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime
from typing import IO, Any

from sqlalchemy import Date, DateTime, Enum, Integer, Table, Uuid, exists, func, insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from brzask.db import migrations
from brzask.db.base import Base
from brzask.db.models import RunKind
from brzask.services.errors import ServiceError
from brzask.services.runs import pipeline_lock, session_bind

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

# Rows fetched from the database, or inserted into it, at a time.
BATCH = 500


class ArchiveError(ServiceError):
    pass


def encode_row(table: Table, row: Mapping[Any, Any]) -> dict[str, Any]:
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
        try:
            decoded[name] = None if value is None else _decode(column.type, value)
        # AttributeError: uuid.UUID given something other than text.
        except (ValueError, TypeError, AttributeError) as error:
            raise ArchiveError(f"{table.name}.{name}: {error}") from error
    return decoded


def _decode(kind: Any, value: Any) -> Any:
    # bool is an int in Python; neither belongs in an integer column.
    if isinstance(kind, Integer) and (not isinstance(value, int) or isinstance(value, bool)):
        raise TypeError(f"expected an integer, got {value!r}")
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


def export_archive(session: Session, out: IO[bytes], *, version: str) -> Counts:
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
                execution_options={"yield_per": BATCH},
            ).mappings()
            for row in rows:
                _write(archive, {"table": table.name, "row": encode_row(table, row)})
                counts[table.name] += 1
        _write(archive, {"end": {"counts": counts}})
    return counts


def _write(archive: gzip.GzipFile, line: Mapping[str, Any]) -> None:
    archive.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")).encode())
    archive.write(b"\n")


def import_archive(sessions: sessionmaker[Session], source: IO[bytes]) -> Counts:
    """Load an archive into an empty database at the latest migration, all or nothing.

    Rows keep their IDs; the ID sequences continue after the highest one. The
    digest lock is held throughout, so a worker that is still running cannot
    start a digest halfway.
    """
    with pipeline_lock(session_bind(sessions), RunKind.DIGEST) as acquired:
        if not acquired:
            raise ArchiveError("a pipeline is running; stop the worker first")
        with sessions.begin() as session:
            return _load(session, _lines(source))


def _load(session: Session, lines: Iterator[tuple[int, Any]]) -> Counts:
    if not migrations.is_current(session.connection()):
        raise ArchiveError("the database is not at the latest migration; run brzask migrate first")
    number, first = next(lines, (1, None))
    if not isinstance(first, dict):
        raise ArchiveError("the archive is empty or has no header")
    revision = check_header(first)
    if revision not in migrations.known_revisions():
        raise ArchiveError(
            f"the archive comes from a newer brzask (schema revision {revision}); upgrade first"
        )
    filled = [t.name for t in TABLES if session.scalar(select(exists().select_from(t)))]
    if filled:
        raise ArchiveError(f"the database is not empty: {', '.join(filled)}")

    by_name = {t.name: t for t in TABLES}
    position = 0
    counts: Counts = dict.fromkeys(by_name, 0)
    batch: list[dict[str, Any]] = []
    batch_table: Table | None = None

    def flush() -> None:
        if batch_table is not None and batch:
            session.execute(insert(batch_table), batch)
        batch.clear()

    try:
        for number, line in lines:
            if not isinstance(line, dict):
                raise ArchiveError(f"line {number}: not a JSON object")
            if "end" in line:
                flush()
                _check_trailer(line, counts)
                break
            name = line.get("table")
            table = by_name.get(name) if isinstance(name, str) else None
            if table is None or not isinstance(line.get("row"), dict):
                raise ArchiveError(f"line {number}: unknown table {name!r}")
            if TABLES.index(table) < position:
                raise ArchiveError(f"line {number}: rows of {table.name} out of order")
            position = TABLES.index(table)
            try:
                row = decode_row(table, line["row"])
            except ArchiveError as error:
                raise ArchiveError(f"line {number}: {error}") from error
            # One INSERT takes rows with the same columns; an older archive
            # may leave columns out.
            if table is not batch_table or (batch and batch[0].keys() != row.keys()):
                flush()
                batch_table = table
            batch.append(row)
            counts[table.name] += 1
            if len(batch) >= BATCH:
                flush()
        else:
            raise ArchiveError("the archive ends without its trailer: the file is incomplete")
        for number, _ in lines:
            raise ArchiveError(f"line {number}: data after the trailer")
        session.flush()
    except DBAPIError as error:
        # The database's own reason, without the statement and its parameters.
        raise ArchiveError(f"the archive does not fit the database: {error.orig}") from error
    _continue_ids(session, counts)
    return counts


def _lines(source: IO[bytes]) -> Iterator[tuple[int, Any]]:
    """(line number, parsed JSON) for each line; `ArchiveError` for a damaged file."""
    number = 0
    try:
        with gzip.GzipFile(fileobj=source, mode="rb") as archive:
            for number, raw in enumerate(archive, start=1):
                yield number, json.loads(raw)
    except (OSError, EOFError, zlib.error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArchiveError(f"line {number + 1}: the archive is damaged ({error})") from error


def _check_trailer(line: Mapping[str, Any], counts: Counts) -> None:
    expected = line["end"].get("counts") if isinstance(line["end"], dict) else None
    if not isinstance(expected, dict):
        raise ArchiveError("the trailer has no row counts")
    # An archive from an older schema may not know every table; its rows must
    # still all be there.
    read = {name: n for name, n in counts.items() if n or name in expected}
    if read != expected:
        wrong = ", ".join(
            f"{name} {read.get(name, 0)} of {expected.get(name, 0)}"
            for name in sorted(read.keys() | expected.keys(), key=str)
            if read.get(name, 0) != expected.get(name, 0)
        )
        raise ArchiveError(f"the archive is incomplete: rows read {wrong}")


def _continue_ids(session: Session, counts: Counts) -> None:
    """Move each ID sequence past the highest restored ID."""
    for table in TABLES:
        column = table.columns.get("id")
        if column is None or column.identity is None or not counts[table.name]:
            continue
        session.execute(
            select(
                func.setval(
                    func.pg_get_serial_sequence(table.name, "id"),
                    select(func.max(column)).scalar_subquery(),
                )
            )
        )
