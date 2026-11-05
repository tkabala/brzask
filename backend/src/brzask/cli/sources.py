"""`brzask sources ...`"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from brzask.cli import common
from brzask.cli.common import ACTOR, errors_as_messages, local, table, unit_of_work
from brzask.clients.feed_finder import with_scheme
from brzask.db.models import SourceStatus
from brzask.services import opml, sources
from brzask.services.source_stats import source_survival

app = typer.Typer(no_args_is_help=True, help="List, add, mute, enable, import and export sources.")

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


@app.command("import")
def import_command(
    file: Annotated[
        Path,
        typer.Argument(
            exists=True, dir_okay=False, readable=True, help="OPML file from a feed reader."
        ),
    ],
    active: Annotated[
        bool,
        typer.Option("--active", help="Follow the new feeds now instead of leaving them pending."),
    ] = False,
) -> None:
    """Add the feeds of an OPML file; each is checked first, known ones are left alone."""
    with common.errors_as_messages():
        outlines = opml.parse_opml(file.read_bytes())
    typer.echo(f"Checking {len(outlines)} feeds...")
    finder = common.get_feed_finder()
    try:
        with common.errors_as_messages():
            report = opml.import_outlines(
                common.get_sessions(), finder, outlines, actor=ACTOR, active=active
            )
    finally:
        finder.close()
    for added in report.added:
        typer.echo(f"Added {added.name} (#{added.id}, {added.status.value}): {added.url}")
    for known in report.known:
        typer.echo(f"Known {known.url}: {known.name} ({known.status.value})")
    for failed in report.failed:
        typer.echo(f"Failed {failed.url}: {failed.reason}")
    typer.echo(
        f"{len(report.added)} added, {len(report.known)} already sources, "
        f"{len(report.failed)} without a feed."
    )
    if report.added and not active:
        typer.echo("New feeds are pending: approve them on the Sources page or with `enable`.")


@app.command()
def export(
    status: Annotated[
        list[SourceStatus] | None,
        typer.Option(
            "--status", "-s", help="Sources with this status; repeatable. Default: active."
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write here instead of stdout."),
    ] = None,
) -> None:
    """Write sources as an OPML file, for a feed reader or another brzask."""
    with unit_of_work() as session:
        data = opml.render_opml(
            sources.list_sources(session, *(status or [SourceStatus.ACTIVE])), datetime.now(UTC)
        )
    if output is None:
        typer.echo(data.decode(), nl=False)
    else:
        output.write_bytes(data)


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
