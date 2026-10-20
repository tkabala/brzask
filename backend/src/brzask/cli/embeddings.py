"""`brzask reembed`: move the stored vectors to another embedding model."""

from typing import Annotated

import typer

from brzask.cli import common
from brzask.cli.common import ACTOR, errors_as_messages
from brzask.clients.usage import UsageMeter
from brzask.config import get_settings
from brzask.services.embeddings import reembed


def reembed_command(
    model: Annotated[str, typer.Option("--model", help="Embedding model to move to.")],
    switch: Annotated[
        bool,
        typer.Option(
            "--switch/--no-switch",
            help="Make the model the active one once every vector is computed. "
            "--no-switch only computes them, e.g. to check thresholds with replay first.",
        ),
    ] = True,
) -> None:
    """Embed every embedded article again with another model, then switch to it.

    Safe to stop and run again: computed vectors are kept. Digests keep using
    the active model until the switch.
    """
    settings = get_settings()
    meter = UsageMeter()

    def progress(done: int, remaining: int) -> None:
        typer.echo(f"{done} embedded, {remaining} to go", err=True)

    with errors_as_messages(), common.embedder(settings, model) as embedder:
        result = reembed(
            common.get_sessions(),
            embedder,
            settings.embedding.model,
            switch=switch,
            actor=ACTOR,
            meter=meter,
            progress=progress,
        )
    cost = meter.summary()["cost_usd"] if meter.calls else None
    typer.echo(
        f"{result.embedded} articles embedded with {result.model}"
        + (f" (${cost:.4f})" if cost is not None else "")
        + "."
    )
    if result.without_text:
        typer.echo(f"{result.without_text} embedded articles have no stored text and were skipped.")
    if result.switched:
        typer.echo(f"Active model is now {result.model}.")
        if result.model != settings.embedding.model:
            typer.echo(
                f"Set EMBEDDING_MODEL={result.model} so the configuration matches; "
                "until then every digest logs a warning."
            )
    elif result.active == result.model:
        typer.echo(f"{result.model} was already the active model.")
    else:
        typer.echo(f"Active model is still {result.active}.")
