"""Command-line entry point."""

from typing import Annotated

import typer

from brzask import __version__
from brzask.config import get_settings
from brzask.log import configure_logging

app = typer.Typer(no_args_is_help=True, help="Self-hosted daily news digest.")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"brzask {__version__}")
        raise typer.Exit


@app.callback()
def main(
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
    log_settings = get_settings().logging
    configure_logging(log_settings.level, log_settings.format)
