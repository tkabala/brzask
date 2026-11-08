"""`brzask config ...`"""

from datetime import UTC, datetime
from typing import Annotated

import typer

from brzask.cli.common import ACTOR, local, table, unit_of_work
from brzask.db.models import ChangeStatus
from brzask.services import rollback

app = typer.Typer(no_args_is_help=True, help="See recorded changes and undo one.")


def _entity(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    entity_type, _, entity_id = value.partition(":")
    if not entity_type or not entity_id:
        raise typer.BadParameter("expected <type>:<id>, e.g. source:12")
    return entity_type, entity_id


@app.command()
def history(
    entity: Annotated[
        str | None,
        typer.Option(help="Only this entity, as <type>:<id>: source:12, setting:pause."),
    ] = None,
    status: Annotated[
        ChangeStatus | None, typer.Option(help="Only changes in this status.")
    ] = None,
    limit: Annotated[int, typer.Option(min=1, help="How many changes to show.")] = 50,
) -> None:
    """List changes to sources, interests and settings, newest first."""
    entity_type, entity_id = _entity(entity)
    with unit_of_work() as session:
        rows = [
            (
                change.id,
                local(change.created_at),
                change.actor,
                change.action,
                f"{change.entity_type}:{change.entity_id}"
                if change.entity_id
                else change.entity_type,
                change.status.value,
                rollback.describe_change(change),
                " ".join((change.reason or "").split()),
            )
            for change in rollback.list_changes(
                session, limit=limit, status=status, entity_type=entity_type, entity_id=entity_id
            )
        ]
    if not rows:
        typer.echo("No changes.")
        return
    table(("ID", "WHEN", "ACTOR", "ACTION", "ENTITY", "STATUS", "CHANGE", "REASON"), rows)


@app.command("rollback")
def rollback_command(
    change_id: Annotated[int, typer.Argument(help="ID from `brzask config history`.")],
    reason: Annotated[
        str | None, typer.Option("--reason", "-r", help="Why, kept in the change log.")
    ] = None,
) -> None:
    """Undo one change; refused if what it set has changed since."""
    with unit_of_work() as session:
        new = rollback.rollback_change(
            session, change_id, datetime.now(UTC), actor=ACTOR, reason=reason
        )
        original = new.action.removesuffix(".rollback")
        message = (
            f"Rolled back change {change_id} ({original} on {new.entity_type} {new.entity_id}); "
            f"this is change {new.id}."
        )
    typer.echo(message)
