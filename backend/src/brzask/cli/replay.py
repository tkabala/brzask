"""`brzask replay`: past digests chosen again and scored by opens."""

import json
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from brzask import prompts
from brzask.cli import common
from brzask.cli.common import table
from brzask.config import get_settings
from brzask.services.embeddings import active_model
from brzask.services.replay import (
    DayReplay,
    ReplayClients,
    ReplayConfig,
    ReplaySummary,
    replay,
    report,
    summarize,
)


def replay_command(
    days: Annotated[
        int, typer.Option("--days", min=1, help="Replay the digests of this many past days.")
    ] = 30,
    config_file: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="TOML file with the values to try: llm_model, [pool], [ranking], "
            "[deduplication], [selection].",
        ),
    ] = None,
    prompt_dir: Annotated[
        Path | None,
        typer.Option(
            "--prompt-dir", help="Directory with changed prompts (e.g. ranking.md) to try."
        ),
    ] = None,
    json_file: Annotated[
        Path | None, typer.Option("--json", help="Also write every day and pick to this file.")
    ] = None,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Days replayed at once.")] = 4,
) -> None:
    """Choose past digests again and compare the picks with what was opened.

    Calls the LLM twice per day; writes nothing to the database.
    """
    try:
        config = ReplayConfig.load(config_file) if config_file else ReplayConfig()
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--config") from error

    settings = get_settings()
    llm_settings = settings.llm
    if config.llm_model:
        llm_settings = llm_settings.model_copy(update={"model": config.llm_model})
    today = datetime.now(UTC).astimezone(settings.scheduler.timezone).date()
    since = today - timedelta(days=days - 1)

    with ExitStack() as stack:
        if prompt_dir is not None:
            try:
                stack.enter_context(prompts.overridden(prompt_dir))
            except ValueError as error:
                raise typer.BadParameter(str(error), param_hint="--prompt-dir") from error
        sessions = common.get_read_only_sessions()
        with sessions.begin() as session:
            embedding_model = config.embedding_model or active_model(
                session, settings.embedding.model
            )
        clients = ReplayClients(
            llm=stack.enter_context(common.llm_client(llm_settings)),
            llm_model=llm_settings.model,
            embedding_model=embedding_model,
            language=prompts.language(settings.digest.language),
        )
        with common.errors_as_messages():
            results = replay(sessions, clients, since, config, workers)

    _print(results, summarize(results))
    if json_file is not None:
        json_file.write_text(json.dumps(report(results, clients, config), indent=2) + "\n")
        typer.echo(f"Written to {json_file}")


def _print(days: list[DayReplay], summary: ReplaySummary) -> None:
    if not days:
        typer.echo("No digests in that period.")
        return
    table(
        ("DATE", "POOL", "OPENED IN POOL", "SHOWN: OPENED", "REPLAY: OPENED", "SAME", "ERROR"),
        [
            (
                day.day.isoformat(),
                day.pool,
                day.opened_in_pool,
                f"{day.shown_opened}/{day.shown}",
                f"{day.picked_opened}/{len(day.picks)}" if day.error is None else "-",
                day.same if day.error is None else "-",
                day.error or "",
            )
            for day in days
        ],
    )
    typer.echo("")
    typer.echo(
        f"Replay: opened {summary.picked_opened} of {summary.picked} picks "
        f"({_share(summary.picked_opened, summary.picked)}); "
        f"shown: opened {summary.shown_opened} of {summary.shown} "
        f"({_share(summary.shown_opened, summary.shown)}); "
        f"{summary.same} picks also shown; over {summary.days} days"
        + (f", {summary.failed} failed" if summary.failed else "")
        + "."
    )
    cost = summary.usage.get("cost_usd")
    typer.echo(
        f"{summary.usage['calls']} model calls"
        + (f", ${cost:.4f}" if cost is not None else "")
        + "."
    )


def _share(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "-"
