"""Command-line entry point. Commands are thin: they parse input and call services."""

from datetime import UTC, datetime
from typing import Annotated

import typer
import uvicorn
from pydantic import ValidationError

from brzask import __version__
from brzask.api.app import create_app
from brzask.api.metrics import prometheus_reader
from brzask.cli import common, interests, sources, tokens
from brzask.cli.common import (
    ACTOR,
    configuration_problems,
    errors_as_messages,
    local,
    parse_moment,
    table,
    unit_of_work,
)
from brzask.cli.embeddings import reembed_command
from brzask.cli.extract_bench import extract_bench_command
from brzask.cli.fit_weights import fit_weights_command
from brzask.cli.judge_bench import judge_bench_command
from brzask.cli.replay import replay_command
from brzask.config import get_settings
from brzask.db import migrations
from brzask.db.models import RunKind, RunStatus
from brzask.log import configure_logging
from brzask.services import auth
from brzask.services import pause as pausing
from brzask.services.demo import DIGEST_DAYS, seed_demo
from brzask.services.runs import run_pipeline
from brzask.services.status import get_status
from brzask.telemetry import setup_telemetry
from brzask.worker import run_worker

app = typer.Typer(no_args_is_help=True, help="Self-hosted daily news digest.")
app.add_typer(sources.app, name="sources")
app.add_typer(interests.app, name="interests")
app.add_typer(tokens.app, name="tokens")
app.command(name="replay")(replay_command)
app.command(name="extract-bench")(extract_bench_command)
app.command(name="judge-bench")(judge_bench_command)
app.command(name="fit-weights")(fit_weights_command)
app.command(name="reembed")(reembed_command)


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
    if context.invoked_subcommand == "api":
        return  # `api` sets up telemetry with its /metrics reader
    component = "worker" if context.invoked_subcommand == "worker" else "cli"
    setup_telemetry(settings.telemetry, component=component)


@app.command()
def migrate() -> None:
    """Create or upgrade the database schema. Safe to run repeatedly."""
    migrations.migrate()


@app.command()
def api(
    host: Annotated[str, typer.Option(help="Address to listen on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8000,
) -> None:
    """Serve the HTTP API until stopped."""
    reader, registry = prometheus_reader()
    setup_telemetry(get_settings().telemetry, component="api", metric_readers=[reader])
    application = create_app(common.get_sessions(), metrics_registry=registry)
    # log_config=None keeps the structured logging configured above. Proxy
    # headers stay untouched: the app checks the connection's own address
    # against TRUSTED_PROXIES, which uvicorn would replace with X-Forwarded-For.
    uvicorn.run(application, host=host, port=port, log_config=None, proxy_headers=False)


@app.command(name="hash-password")
def hash_password_command() -> None:
    """Print an argon2 hash of a password for AUTH_PASSWORD_HASH."""
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    if not password:
        raise typer.BadParameter("the password must not be empty")
    typer.echo(auth.hash_password(password))


@app.command(name="demo-data")
def demo_data() -> None:
    """Fill an empty database with a made-up instance to try brzask on."""
    zone = get_settings().scheduler.timezone
    with errors_as_messages(), unit_of_work() as session:
        added = seed_demo(session, datetime.now(zone).date(), zone)
    typer.echo(f"Added demo data: {added} articles in {len(DIGEST_DAYS)} digests.")


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
        current = get_status(session, datetime.now(UTC), get_settings().embedding.model)
    articles = current.articles
    typer.echo(
        f"Articles: {articles.total} stored, {articles.shown} shown, {articles.opened} opened"
    )
    typer.echo(
        "Sources: "
        + ", ".join(f"{count} {state.value}" for state, count in current.sources.items())
    )
    vectors = ", ".join(
        f"{count} {model}" + (" (active)" if model == current.embedding_model else "")
        for model, count in sorted(current.embeddings.items())
    )
    typer.echo(f"Embedding model: {current.embedding_model}")
    if vectors:
        typer.echo(f"Vectors: {vectors}")
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
