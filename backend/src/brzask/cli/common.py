"""Helpers shared by the CLI commands."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, time
from functools import lru_cache

import typer
from sqlalchemy.orm import Session, sessionmaker

from brzask.config import get_settings
from brzask.db.session import create_db_engine, session_factory
from brzask.services.errors import ServiceError

# Recorded as the actor in the change log for changes made from the command line.
ACTOR = "user"


@lru_cache(maxsize=1)
def get_sessions() -> sessionmaker[Session]:
    return session_factory(create_db_engine())


@contextmanager
def errors_as_messages() -> Iterator[None]:
    """Show a service error as one line on stderr and exit with status 1."""
    try:
        yield
    except ServiceError as error:
        typer.secho(f"Error: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from error


@contextmanager
def unit_of_work() -> Iterator[Session]:
    """A transaction committed when the command succeeds."""
    with errors_as_messages(), get_sessions().begin() as session:
        yield session


def local(moment: datetime | None) -> str:
    """A timestamp in the configured time zone, to the minute."""
    if moment is None:
        return "-"
    return moment.astimezone(get_settings().scheduler.timezone).strftime("%Y-%m-%d %H:%M")


def parse_moment(value: str) -> datetime:
    """A date (start of that day) or a date and time, in the configured time zone."""
    zone = get_settings().scheduler.timezone
    try:
        moment = (
            datetime.combine(date.fromisoformat(value), time())
            if len(value) == len("2026-01-01")
            else datetime.fromisoformat(value)
        )
    except ValueError as error:
        raise typer.BadParameter(
            f"expected YYYY-MM-DD or YYYY-MM-DDTHH:MM, got {value!r}"
        ) from error
    return moment if moment.tzinfo else moment.replace(tzinfo=zone)


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    """Print rows as left-aligned columns."""
    cells = [[str(cell) for cell in row] for row in [headers, *rows]]
    widths = [max(len(row[column]) for row in cells) for column in range(len(headers))]
    for row in cells:
        typer.echo(
            "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        )
