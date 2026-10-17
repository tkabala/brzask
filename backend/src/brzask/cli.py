"""Command-line entry point."""

from typing import Annotated

import typer

from brzask import __version__

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
