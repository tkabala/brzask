"""`brzask notify ...`"""

import typer

from brzask.config import get_settings
from brzask.services.notify import TEST_MESSAGE, notifier_from_settings

app = typer.Typer(no_args_is_help=True, help="Check notifications.")


@app.command()
def test() -> None:
    """Send a test notification to every NOTIFY_URLS target."""
    notifier = notifier_from_settings(get_settings().notifications)
    if notifier is None:
        typer.secho("Error: NOTIFY_URLS is not set", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if not notifier.send(TEST_MESSAGE):
        typer.secho("Error: notification not sent (see the log)", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.echo("Test notification sent.")
