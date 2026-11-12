"""`brzask tokens ...`"""

from datetime import UTC, datetime
from typing import Annotated

import typer

from brzask.cli.common import ACTOR, errors_as_messages, local, table, unit_of_work
from brzask.config import get_settings
from brzask.db.models import TokenScope
from brzask.services import tokens

app = typer.Typer(no_args_is_help=True, help="Create, list and revoke API tokens.")

TokenName = Annotated[str, typer.Argument(help="Token name, e.g. the script that uses it.")]


@app.command()
def create(
    name: TokenName,
    scope: Annotated[
        TokenScope,
        typer.Option(
            "--scope",
            "-s",
            help=(
                "read: only reading; write: also changes; propose: changes over MCP wait "
                "for your approval; feed: only the digest feed, in its URL."
            ),
        ),
    ] = TokenScope.READ,
) -> None:
    """Create a token; it is shown once, here."""
    with errors_as_messages(), unit_of_work() as session:
        token, value = tokens.create_token(session, name, scope, actor=ACTOR)
        scope_name = token.scope.value
    typer.echo(value)
    server = get_settings().server.public_url or "<your server>/"
    use = (
        f"Subscribe to {server}feed?token=<token>"
        if scope is TokenScope.FEED
        else "Send it as 'Authorization: Bearer <token>'"
    )
    typer.echo(f"Token {name!r} ({scope_name}). {use}; it cannot be shown again.", err=True)


@app.command("list")
def list_command() -> None:
    """List tokens, revoked ones included."""
    with unit_of_work() as session:
        rows = [
            (
                t.name,
                t.scope.value,
                f"{t.prefix}…",
                local(t.created_at),
                local(t.last_used_at) if t.last_used_at else "never",
                local(t.revoked_at) if t.revoked_at else "",
            )
            for t in tokens.list_tokens(session)
        ]
    if not rows:
        typer.echo("No tokens.")
        return
    table(("NAME", "SCOPE", "STARTS WITH", "CREATED", "LAST USED", "REVOKED"), rows)


@app.command()
def revoke(name: TokenName) -> None:
    """Stop a token from working, at once."""
    with errors_as_messages(), unit_of_work() as session:
        revoked = tokens.revoke_token(session, name, datetime.now(UTC), actor=ACTOR)
    typer.echo(f"Revoked {name}." if revoked else f"{name} was already revoked.")
