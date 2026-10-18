"""`brzask interests ...`"""

from typing import Annotated

import typer

from brzask.cli.common import ACTOR, table, unit_of_work
from brzask.services import interests

app = typer.Typer(no_args_is_help=True, help="List, add and edit interests.")

KEYWORDS_HELP = "Comma-separated keywords; they can only widen the topic."
NOTES_HELP = "Reader notes, e.g. 'want: ..., skip: ...'; they override keywords."


def _split(keywords: str) -> list[str]:
    return keywords.split(",")


@app.command("list")
def list_command(
    active_only: Annotated[bool, typer.Option("--active", help="Only active interests.")] = False,
) -> None:
    """List interests in the order they were added."""
    with unit_of_work() as session:
        rows = [
            (i.id, i.topic, "yes" if i.active else "no", ", ".join(i.keywords), i.notes)
            for i in interests.list_interests(session, active_only=active_only)
        ]
    if not rows:
        typer.echo("No interests.")
        return
    table(("ID", "TOPIC", "ACTIVE", "KEYWORDS", "NOTES"), rows)


@app.command()
def add(
    topic: Annotated[str, typer.Argument(help="Topic name, e.g. 'Postgres'.")],
    keywords: Annotated[str, typer.Option("--keywords", "-k", help=KEYWORDS_HELP)] = "",
    notes: Annotated[str, typer.Option("--notes", "-n", help=NOTES_HELP)] = "",
) -> None:
    """Add an interest."""
    with unit_of_work() as session:
        interest = interests.add_interest(
            session, topic, actor=ACTOR, keywords=_split(keywords), notes=notes
        )
        message = f"Added {interest.topic} (#{interest.id})."
    typer.echo(message)


@app.command()
def edit(
    interest: Annotated[str, typer.Argument(help="Interest ID or topic.")],
    topic: Annotated[str | None, typer.Option("--topic", "-t", help="New topic name.")] = None,
    keywords: Annotated[
        str | None, typer.Option("--keywords", "-k", help=f"{KEYWORDS_HELP} Replaces the list.")
    ] = None,
    notes: Annotated[
        str | None, typer.Option("--notes", "-n", help=f"{NOTES_HELP} Replaces the notes.")
    ] = None,
    active: Annotated[
        bool | None, typer.Option("--active/--inactive", help="Use the interest or not.")
    ] = None,
) -> None:
    """Change an interest; options left out stay as they are."""
    with unit_of_work() as session:
        edited = interests.edit_interest(
            session,
            interest,
            actor=ACTOR,
            topic=topic,
            keywords=None if keywords is None else _split(keywords),
            notes=notes,
            active=active,
        )
        message = f"Saved {edited.topic} (#{edited.id})."
    typer.echo(message)
