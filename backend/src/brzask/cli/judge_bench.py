"""`brzask judge-bench`: judges scoring the same shown articles, measured by opens."""

import json
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from brzask.cli import common
from brzask.cli.common import table
from brzask.clients.judge import Judge, LLMJudge, SystemOneJudge
from brzask.clients.llm import LLMClient
from brzask.config import get_settings
from brzask.config.settings import Settings
from brzask.services.digest import scoring
from brzask.services.judge_bench import BenchResult, report, score_shown

# Names `--model` takes besides a System One model ID.
LLM = "llm"


def judge_bench_command(
    models: Annotated[
        list[str] | None,
        typer.Option(
            "--model",
            help="A System One model (e.g. typesafe/jev-1.13, liquid/d1) or `llm` for "
            "LLM_MODEL as the judge; repeat to compare. Default: the configured judge.",
        ),
    ] = None,
    days: Annotated[
        int, typer.Option("--days", min=1, help="Score the digests of this many past days.")
    ] = 30,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Calls at once.")] = 8,
    json_file: Annotated[
        Path | None,
        typer.Option("--json", help="Also write every article's scores to this file."),
    ] = None,
) -> None:
    """Score every shown article with each judge and report how well the scores
    tell opened articles from the rest (AUC; 0.5 is chance).

    Calls the judge once per shown article and model; writes nothing to the database.
    """
    settings = get_settings()
    today = datetime.now(UTC).astimezone(settings.scheduler.timezone).date()
    since = today - timedelta(days=days - 1)
    sessions = common.get_read_only_sessions()

    results: list[BenchResult] = []
    with ExitStack() as stack, common.errors_as_messages():
        names: list[str | None] = list(models) if models else [None]
        for name in names:
            judge = _judge(settings, name)
            stack.callback(judge.close)
            results.append(score_shown(sessions, judge, since, workers))

    _print(results)
    if json_file is not None:
        json_file.write_text(json.dumps(report(results), indent=2) + "\n")
        typer.echo(f"Written to {json_file}")


def _judge(settings: Settings, name: str | None) -> Judge:
    if name == LLM:
        # LLM_MODEL where it is served: JUDGE_BASE_URL and JUDGE_API_KEY may point elsewhere.
        return LLMJudge(LLMClient.from_settings(settings.llm))
    if name is None and settings.judge.backend == "llm":
        return LLMJudge.from_settings(settings)
    return SystemOneJudge.from_settings(settings, name)


def _print(results: list[BenchResult]) -> None:
    if not any(result.rows for result in results):
        typer.echo("No shown articles in that period.")
        return
    dimensions = list(scoring.DIMENSIONS)
    rows = []
    for result in results:
        aucs = result.aucs()
        usage = result.usage
        calls = usage.get("calls") or 0
        cost = usage.get("cost_usd")
        rows.append(
            (
                result.model,
                f"{sum(row.opened for row in result.rows)}/{len(result.rows)}",
                result.failed,
                _auc(aucs["composite"]),
                *(_auc(aucs[name]) for name in dimensions),
                f"${cost:.4f}" if cost is not None else "-",
                f"{usage.get('duration_ms', 0) // calls} ms" if calls else "-",
            )
        )
    table(
        (
            "MODEL",
            "OPENED",
            "FAILED",
            "AUC COMPOSITE",
            *(f"AUC {name.upper()}" for name in dimensions),
            "COST",
            "PER CALL",
        ),
        rows,
    )


def _auc(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "-"
