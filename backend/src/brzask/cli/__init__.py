"""Command-line entry point. Commands are thin: they parse input and call services."""

from datetime import UTC, datetime
from typing import Annotated

import typer
from pydantic import ValidationError

from brzask import __version__
from brzask.cli import common, interests, sources
from brzask.cli.common import (
    ACTOR,
    configuration_problems,
    errors_as_messages,
    local,
    parse_moment,
    table,
    unit_of_work,
)
from brzask.config import get_settings
from brzask.db import migrations
from brzask.db.models import RunKind, RunStatus
from brzask.log import configure_logging
from brzask.services import pause as pausing
from brzask.services.runs import run_pipeline
from brzask.services.status import get_status
from brzask.telemetry import setup_telemetry
from brzask.worker import run_worker

app = typer.Typer(no_args_is_help=True, help="Self-hosted daily news digest.")
app.add_typer(sources.app, name="sources")
app.add_typer(interests.app, name="interests")


def run_cli() -> None:
    """The `brzask` command: an invalid setting is reported by name, not as a traceback."""
    try:
        app()
    except ValidationError as error:
        typer.secho("Error: invalid configuration", fg=typer.colors.RED, err=True)
        for problem in configuration_problems(error):
            typer.secho(f"  {problem}", fg=typer.colors.RED, err=True)
        raise SystemExit(1) from error


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"brzask {__version__}")
        raise typer.Exit


@app.callback()
def main(
    context: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = None,
) -> None:
    """Self-hosted daily news digest."""
    settings = get_settings()
    configure_logging(settings.logging.level, settings.logging.format)
    component = "worker" if context.invoked_subcommand == "worker" else "cli"
    setup_telemetry(settings.telemetry, component=component)


@app.command()
def migrate() -> None:
    """Create or upgrade the database schema. Safe to run repeatedly."""
    migrations.migrate()


@app.command()
def worker() -> None:
    """Run the pipelines on their schedule (DIGEST_AT, REVIEW_AT, ...) until stopped."""
    run_worker(get_settings().scheduler, common.get_sessions())


@app.command()
def run(
    pipeline: Annotated[RunKind, typer.Argument(help="Pipeline to run.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Compute everything, write nothing but the run.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Run even when paused or already done today.")
    ] = False,
) -> None:
    """Run a pipeline now, as the worker would."""
    with errors_as_messages():
        finished = run_pipeline(common.get_sessions(), pipeline, dry_run=dry_run, force=force)
    reason = finished.stats.get("reason")
    suffix = f": {reason}" if finished.status is RunStatus.SKIPPED and reason else ""
    typer.echo(f"{pipeline.value} {finished.status.value}{suffix} (run {finished.id})")


@app.command()
def status() -> None:
    """Show article and source counts, the pause and the last run of each pipeline."""
    with unit_of_work() as session:
        current = get_status(session, datetime.now(UTC))
    articles = current.articles
    typer.echo(
        f"Articles: {articles.total} stored, {articles.shown} shown, {articles.opened} opened"
    )
    typer.echo(
        "Sources: "
        + ", ".join(f"{count} {state.value}" for state, count in current.sources.items())
    )
    typer.echo(f"Last digest: {current.last_digest or '-'}")
    if current.paused_until:
        typer.echo(f"Paused until {local(current.paused_until)}")
    typer.echo("")
    table(
        ("PIPELINE", "LAST RUN", "STATUS", "ERROR"),
        [
            (kind.value, local(run.started_at), run.status.value, run.error or "")
            if run
            else (kind.value, "never", "", "")
            for kind, run in current.last_runs.items()
        ],
    )


@app.command()
def pause(
    until: Annotated[
        str,
        typer.Option(
            "--until",
            help="Resume on this day (YYYY-MM-DD) or at this time (YYYY-MM-DDTHH:MM), "
            "in the configured time zone.",
        ),
    ],
) -> None:
    """Pause the daily digest, e.g. for a holiday."""
    end = parse_moment(until)
    with unit_of_work() as session:
        pausing.pause(session, end, datetime.now(UTC), actor=ACTOR)
    typer.echo(f"Paused until {local(end)}.")


@app.command()
def resume() -> None:
    """End a pause now."""
    with unit_of_work() as session:
        resumed = pausing.resume(session, datetime.now(UTC), actor=ACTOR)
    typer.echo("Resumed." if resumed else "The digest was not paused.")
