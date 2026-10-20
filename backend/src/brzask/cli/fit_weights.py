"""`brzask fit-weights`: composite weights learned from a judge-bench report."""

import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from brzask.cli.common import table
from brzask.services.digest import scoring
from brzask.services.weights import L2, evaluate, examples_from_bench


def fit_weights_command(
    report_file: Annotated[
        Path, typer.Argument(help="JSON written by `brzask judge-bench --json`.")
    ],
    model: Annotated[
        str | None,
        typer.Option("--model", help="Whose scores to fit, if the report has several."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option(
            "--until",
            help="Fit only on days up to this date (YYYY-MM-DD), to replay the later ones.",
        ),
    ] = None,
    l2: Annotated[float, typer.Option("--l2", min=0, help="Penalty on the weights.")] = L2,
) -> None:
    """Fit composite weights to what the reader opened and compare them with the
    hand-set ones, each day scored by weights fitted on the other days.

    Prints a `[ranking.weights]` block for `brzask replay --config`.
    """
    try:
        examples = examples_from_bench(json.loads(report_file.read_text()), model)
        last = date.fromisoformat(until) if until else None
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise typer.BadParameter(str(error)) from error
    if last is not None:
        examples = [example for example in examples if example.day <= last]
    if not any(example.opened for example in examples):
        raise typer.BadParameter("no opened article to learn from")

    result = evaluate(examples, l2=l2)
    table(
        ("DIMENSION", "HAND", "LEARNED"),
        [
            (name, f"{scoring.WEIGHTS[name]:g}", f"{result.learned[name]:g}")
            for name in scoring.DIMENSIONS
        ],
    )
    typer.echo("")
    typer.echo(
        f"Leave-one-day-out AUC over {result.days} days, {result.examples} articles, "
        f"{result.opened} opened: learned {_auc(result.learned_auc)}, "
        f"hand {_auc(result.hand_auc)} (0.5 is chance)."
    )
    typer.echo("")
    typer.echo("[ranking.weights]")
    for name in scoring.DIMENSIONS:
        typer.echo(f"{name} = {result.learned[name]:g}")


def _auc(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "-"
