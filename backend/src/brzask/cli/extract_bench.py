"""`brzask extract-bench`: every extractor on the same sample of stored links."""

import json
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, cast, get_args

import typer

from brzask.cli import common
from brzask.cli.common import table
from brzask.clients.extractors import build_chain
from brzask.clients.extractors.adapters import FEED_MIN_CHARS, PAGE_TIMEOUT
from brzask.clients.extractors.robots import RobotsPolicy
from brzask.clients.feeds import FeedFetcher
from brzask.clients.http import new_client
from brzask.config import get_settings
from brzask.config.settings import Extractor as ExtractorName
from brzask.config.settings import ExtractorSettings
from brzask.services.extract_bench import (
    BenchAttempt,
    FeedCheck,
    by_site,
    check_feed_threshold,
    load_sample,
    report,
    run_bench,
    summarize,
    with_feed_content,
)

# Jina Reader serves 20 requests a minute without a key (its documented limit).
JINA_KEYLESS_INTERVAL = 3.0


def extract_bench_command(
    extractors: Annotated[
        str | None,
        typer.Option(
            "--extractors",
            help="Comma-separated extractors to compare; default: feed, trafilatura, jina "
            "and the configured ones.",
        ),
    ] = None,
    sample: Annotated[int, typer.Option("--sample", min=1, help="Links to try.")] = 60,
    per_site: Annotated[
        int, typer.Option("--per-site", min=1, help="At most this many links from one site.")
    ] = 3,
    days: Annotated[
        int, typer.Option("--days", min=1, help="Sample links first seen in this many days.")
    ] = 10,
    seed: Annotated[int, typer.Option("--seed", help="Seed of the random sample.")] = 1,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Pages fetched at once.")] = 4,
    json_file: Annotated[
        Path | None, typer.Option("--json", help="Also write every attempt to this file.")
    ] = None,
) -> None:
    """Compare extractors: usable text, length, latency and cost, in total and per site.

    Fetches real pages (and calls hosted readers); writes nothing to the database.
    """
    settings = get_settings().extractors
    names = _extractor_names(extractors, settings)
    try:
        bench_settings = ExtractorSettings.model_validate(
            {**settings.model_dump(), "extractors": names}
        )
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--extractors") from error

    since = datetime.now(UTC) - timedelta(days=days)
    items = load_sample(common.get_read_only_sessions(), since, sample, per_site, seed)
    if not items:
        typer.echo("No stored links in that period.")
        return
    typer.echo(
        f"{len(items)} links from {len({i.host for i in items})} sites; "
        f"extractors: {', '.join(names)}",
        err=True,
    )
    with ExitStack() as stack:
        feeds = FeedFetcher()
        stack.callback(feeds.close)
        client = new_client(PAGE_TIMEOUT)
        stack.callback(client.close)
        items = with_feed_content(items, feeds)
        chain = build_chain(bench_settings, client)
        intervals = {"jina": JINA_KEYLESS_INTERVAL} if settings.jina_api_key is None else {}
        attempts = run_bench(items, chain.extractors, RobotsPolicy(client), workers, intervals)

    feed_check = check_feed_threshold(items, attempts, FEED_MIN_CHARS)
    _print(attempts, feed_check)
    if json_file is not None:
        data = report(items, attempts, feed_check)
        json_file.write_text(json.dumps(data, indent=2) + "\n")
        typer.echo(f"Written to {json_file}")


def _extractor_names(option: str | None, settings: ExtractorSettings) -> list[ExtractorName]:
    if option is None:
        defaults: list[ExtractorName] = ["feed", "trafilatura", "jina"]
        return [*defaults, *(n for n in settings.extractors if n not in defaults)]
    names = [name.strip() for name in option.split(",") if name.strip()]
    known = set(get_args(ExtractorName))
    unknown = [name for name in names if name not in known]
    if unknown or not names:
        raise typer.BadParameter(
            f"unknown extractor {', '.join(unknown)}" if unknown else "no extractor given",
            param_hint="--extractors",
        )
    return [cast(ExtractorName, name) for name in dict.fromkeys(names)]


def _print(attempts: list[BenchAttempt], feed_check: FeedCheck) -> None:
    rows = summarize(attempts)
    table(
        (
            "EXTRACTOR",
            "TRIED",
            "USABLE",
            "SHORT",
            "BLOCKED",
            "EMPTY",
            "FAILED",
            "SKIPPED",
            "MEDIAN CHARS",
            "MEDIAN WORDS",
            "MEDIAN MS",
            "P90 MS",
            "UNDER HALF",
            "ONLY ONE",
            "TOKENS",
        ),
        [
            (
                row.extractor,
                row.tried,
                f"{row.usable} ({row.usable / row.tried:.0%})" if row.tried else "0",
                row.too_short,
                row.blocked,
                row.empty,
                row.failed,
                row.skipped,
                row.median_chars,
                row.median_words,
                row.median_ms,
                row.p90_ms,
                row.shorter_than_best,
                row.only_usable,
                row.tokens or "",
            )
            for row in rows
        ],
    )
    typer.echo("")
    names = [row.extractor for row in rows]
    table(
        ("SITE", *(name.upper() for name in names)),
        [
            (host, *(_cell(row.get(name)) for name in names))
            for host, row in by_site(attempts).items()
        ],
    )
    typer.echo("")
    check = feed_check
    typer.echo(
        f"Feed content on {check.with_content} links, {check.compared} with a usable page. "
        f"Accepted (>= {FEED_MIN_CHARS} chars): {check.accepted_full} as long as the page, "
        f"{check.accepted_teaser} teasers. Rejected: {check.rejected_teaser} teasers, "
        f"{check.rejected_full} as long as the page."
    )
    flagged = sum(row.long_with_block_phrase for row in rows)
    if flagged:
        typer.echo(f"{flagged} usable texts contain a block phrase (longer than a block page).")


def _cell(counts: tuple[int, int] | None) -> str:
    return f"{counts[0]}/{counts[1]}" if counts else "-"
