"""`brzask export` and `brzask import`."""

import contextlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, BinaryIO

import typer

from brzask import __version__
from brzask.cli import common
from brzask.cli.common import errors_as_messages, table
from brzask.config import get_settings
from brzask.services.archive import ArchiveError, Counts, export_archive, import_archive

STDIO = "-"


def export_command(
    path: Annotated[
        str | None,
        typer.Argument(
            help="File to write, '-' for standard output; default brzask-<date>.jsonl.gz.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Write every source, interest, article, vector, run and token to a portable archive.

    Runs alongside the worker and the API: the archive is one consistent snapshot.
    """
    with errors_as_messages():
        if path == STDIO:
            counts = _export(sys.stdout.buffer)
            sys.stdout.buffer.flush()
            _print_counts(counts, err=True)
            return
        target = Path(
            path or f"brzask-{datetime.now(get_settings().scheduler.timezone):%F}.jsonl.gz"
        )
        if target.exists():
            raise ArchiveError(f"{target} already exists")
        # A failed export leaves no file that looks complete.
        partial = target.with_name(target.name + ".partial")
        try:
            with partial.open("xb") as out:
                counts = _export(out)
            partial.replace(target)
        finally:
            with contextlib.suppress(FileNotFoundError):
                partial.unlink()
    _print_counts(counts, err=True)
    typer.echo(f"Wrote {target}", err=True)


def _export(out: BinaryIO) -> Counts:
    with common.get_snapshot_sessions().begin() as session:
        return export_archive(session, out, version=__version__)


def import_command(
    path: Annotated[str, typer.Argument(help="Archive to read, '-' for standard input.")],
) -> None:
    """Load an archive into an empty database at the latest migration, all or nothing."""
    with errors_as_messages():
        if path == STDIO:
            counts = import_archive(common.get_sessions(), sys.stdin.buffer)
        else:
            try:
                with Path(path).open("rb") as archive:
                    counts = import_archive(common.get_sessions(), archive)
            except OSError as error:
                raise ArchiveError(f"cannot read {path}: {error.strerror}") from error
    _print_counts(counts)
    typer.echo("Login sessions are not part of an archive: sign in again.")


def _print_counts(counts: Counts, *, err: bool = False) -> None:
    table(("TABLE", "ROWS"), list(counts.items()), err=err)
