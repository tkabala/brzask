"""Helpers shared by the CLI commands."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache

import typer
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.embeddings import Embedder
from brzask.clients.feed_finder import FeedFinder
from brzask.clients.feeds import FeedFetcher
from brzask.clients.llm import LLMClient
from brzask.config import get_settings
from brzask.config.settings import GROUPS, LLMSettings, Settings, env_name
from brzask.db.session import create_db_engine, session_factory
from brzask.services.digest.extraction import DocumentEmbedder
from brzask.services.digest.ranking import ChatModel
from brzask.services.errors import ServiceError

# Recorded as the actor in the change log for changes made from the command line.
ACTOR = "user"


@lru_cache(maxsize=1)
def get_sessions() -> sessionmaker[Session]:
    return session_factory(create_db_engine())


@lru_cache(maxsize=1)
def get_read_only_sessions() -> sessionmaker[Session]:
    """Sessions whose transactions the database keeps read-only (`brzask replay`)."""
    return session_factory(create_db_engine().execution_options(postgresql_readonly=True))


@contextmanager
def embedder(settings: Settings, model: str) -> Iterator[DocumentEmbedder]:
    client = Embedder.from_settings(settings, model)
    try:
        yield client
    finally:
        client.client.close()


@contextmanager
def llm_client(settings: LLMSettings) -> Iterator[ChatModel]:
    client = LLMClient.from_settings(settings)
    try:
        yield client
    finally:
        client.client.close()


def get_feed_finder() -> FeedFinder:
    return FeedFinder(FeedFetcher())


@contextmanager
def errors_as_messages() -> Iterator[None]:
    """Show a service error as one line on stderr and exit with status 1."""
    try:
        yield
    except ServiceError as error:
        typer.secho(f"Error: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from error


def configuration_problems(error: ValidationError) -> list[str]:
    """One line per invalid setting, named by its environment variable."""
    group = next((group for group in GROUPS if group.__name__ == error.title), None)
    problems = []
    for problem in error.errors():
        field = str(problem["loc"][0]) if problem["loc"] else ""
        name = env_name(group, field) if group and field in group.model_fields else field
        problems.append(f"{name}: {problem['msg']}")
    return problems


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
        # A date alone parses as midnight.
        moment = datetime.fromisoformat(value)
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
