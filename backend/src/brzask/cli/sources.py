"""`brzask sources ...`"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from brzask.cli import common
from brzask.cli.common import ACTOR, errors_as_messages, local, table, unit_of_work
from brzask.clients.feed_finder import with_scheme
from brzask.db.models import SourceStatus
from brzask.services import sources
from brzask.services.source_stats import source_survival

app = typer.Typer(no_args_is_help=True, help="List, add, mute and enable sources.")

SourceRef = Annotated[str, typer.Argument(help="Source ID, feed URL or name.")]


@app.command("list")
def list_command(
    status: Annotated[
        list[SourceStatus] | None,
        typer.Option("--status", "-s", help="Only sources with this status; repeatable."),
    ] = None,
) -> None:
    """List sources by name."""
    with unit_of_work() as session:
        rows = [
            (s.id, s.name, s.status.value, s.kind.value, s.origin.value, local(s.created_at), s.url)
            for s in sources.list_sources(session, *(status or ()))
        ]
    if not rows:
        typer.echo("No sources.")
        return
    table(("ID", "NAME", "STATUS", "KIND", "ORIGIN", "ADDED", "URL"), rows)


@app.command()
def add(
    url: Annotated[
        str, typer.Argument(help="Feed URL, or any page of the site: its feed is looked up.")
    ],
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Display name; defaults to the feed's title."),
    ] = None,
) -> None:
    """Add a feed; it is read from the next digest on."""
    with unit_of_work() as session:
        # Before any request to the site, as the finder will read the URL.
        sources.ensure_unknown(session, with_scheme(url))
    finder = common.get_feed_finder()
    try:
        with errors_as_messages():
            found = sources.find_feed(finder, url)
    finally:
        finder.close()
    with unit_of_work() as session:
        source = sources.add_source(
            session, found.url, actor=ACTOR, name=name, title=found.title, site_url=found.site_url
        )
        message = f"Added {source.name} (#{source.id}, {source.kind.value}): {source.url}"
    typer.echo(message)


@app.command()
def mute(
    source: SourceRef,
    reason: Annotated[
        str | None, typer.Option("--reason", "-r", help="Why, kept in the change log.")
    ] = None,
) -> None:
    """Stop reading a source."""
    with unit_of_work() as session:
        changed = sources.mute_source(session, source, actor=ACTOR, reason=reason)
    typer.echo(f"Muted {source}." if changed else f"{source} is already muted.")


@app.command()
def enable(source: SourceRef) -> None:
    """Read a source again, whatever its status (muted, pending, rejected, dead)."""
    with unit_of_work() as session:
        changed = sources.enable_source(session, source, actor=ACTOR)
    typer.echo(f"Enabled {source}." if changed else f"{source} is already active.")


@app.command()
def stats(
    days: Annotated[
        int, typer.Option("--days", min=1, help="Judge sources added at least this long ago.")
    ] = 30,
) -> None:
    """Do added sources stay and get read? By origin and discovery's search adapter."""
    with unit_of_work() as session:
        rows = source_survival(session, datetime.now(UTC), timedelta(days=days))
    if not rows:
        typer.echo("No sources.")
        return
    table(
        (
            "ORIGIN",
            "ADAPTER",
            "ADDED",
            "ENABLED",
            f"{days}+ DAYS",
            "STILL ACTIVE",
            "SHOWN",
            "OPENED",
            "OPENS",
        ),
        [
            (
                row.origin.value,
                row.adapter or "-",
                row.added,
                row.enabled,
                row.old_enough,
                _share(row.still_active, row.old_enough),
                _share(row.shown, row.old_enough),
                _share(row.opened, row.old_enough),
                row.opens,
            )
            for row in rows
        ],
    )
    typer.echo("")
    typer.echo(
        f"STILL ACTIVE, SHOWN and OPENED count sources enabled at least {days} days ago: "
        "still read, with an article in a digest, with an article opened."
    )


def _share(part: int, whole: int) -> str:
    return f"{part} ({part / whole:.0%})" if whole else "-"
