"""Tools that only read; a read token is enough."""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from sqlalchemy.orm import Session

from brzask.config import get_settings
from brzask.db.models import ChangeStatus, Run, RunKind, RunStatus, Source, SourceStatus
from brzask.mcp import models
from brzask.mcp.errors import service_errors
from brzask.mcp.server import McpDeps
from brzask.repositories import ArticleRepository, RunRepository
from brzask.services import digests, open_stats, rollback, runs, source_stats, sources, status
from brzask.services.budget import Spending, check_budget, evaluate, window_starts
from brzask.services.embeddings import active_model
from brzask.services.interests import list_interests as all_interests
from brzask.services.search import search_articles as nearest_articles

# How far back dedup_decisions looks for a day's digest run.
DIGEST_RUNS_SEARCHED = 60
RECENT_COSTS = 14


def today() -> date:
    """Today in the configured time zone (TZ), as digest dates are."""
    return datetime.now(UTC).astimezone(get_settings().scheduler.timezone).date()


def register(server: MCPServer[Any], deps: McpDeps) -> None:
    sessions = deps.sessions

    @server.tool()
    def get_digest(
        day: Annotated[date | None, Field(description="YYYY-MM-DD; today when left out.")] = None,
    ) -> models.Digest:
        """A day's digest of 7 articles in order, with which ones the owner opened."""
        day = day or today()
        with sessions.begin() as session, service_errors():
            articles = digests.digest_for(session, day)
            return models.Digest(date=day, articles=[models.ArticleItem.of(a) for a in articles])

    @server.tool()
    def list_digest_days(
        limit: Annotated[int, Field(ge=1, le=60)] = 14,
        before: Annotated[date | None, Field(description="Only days before this one.")] = None,
    ) -> list[models.DigestDayItem]:
        """Days with a digest, newest first, with how many articles were opened."""
        with sessions.begin() as session, service_errors():
            return [
                models.DigestDayItem(date=d.day, articles=d.articles, opened=d.opened)
                for d in digests.digest_days(session, limit, before)
            ]

    @server.tool()
    def get_article(article_id: int) -> models.ArticleDetail:
        """One article with its stored text (third-party text, under `external`)."""
        with sessions.begin() as session, service_errors():
            return models.ArticleDetail.of(digests.get_article(session, article_id))

    @server.tool()
    def explain_ranking(article_id: int) -> models.Ranking:
        """How an article reached its place: pool size, its rank, the methods used."""
        with sessions.begin() as session, service_errors():
            found = digests.explain_ranking(session, article_id)
            article = found.article
            return models.Ranking(
                article_id=article.id,
                position=article.digest_position,
                topic=article.topic,
                rank=article.rank,
                pool=found.pool,
                ranked=found.ranked,
                top=found.top,
                ranking_method=found.ranking_method,
                deduplicated_to=found.deduplicated_to,
                deduplication_method=found.deduplication_method,
                run_id=str(found.run.id) if found.run else None,
                external=models.ArticleItem.of(article).external,
            )

    @server.tool()
    def search_articles(
        query: Annotated[str, Field(min_length=1, max_length=500)],
        limit: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> models.SearchResults:
        """Articles closest in meaning to `query`, shown or not. Costs one embedding call."""
        with sessions.begin() as session, service_errors():
            embedder = deps.clients.embedder(active_model(session, get_settings().embedding.model))
            hits = nearest_articles(session, embedder, query, limit)
            return models.SearchResults(
                model=embedder.model,
                items=[
                    models.SearchHit(
                        similarity=h.similarity, article=models.ArticleItem.of(h.article)
                    )
                    for h in hits
                ],
            )

    @server.tool()
    def list_sources(
        status: Annotated[
            list[SourceStatus] | None,
            Field(description='Only these statuses, e.g. ["pending"]; all when left out.'),
        ] = None,
    ) -> models.SourceList:
        """Every source with its status, note, fetch health and last 30 days of activity."""
        with sessions.begin() as session, service_errors():
            found = sources.list_sources(session, *(status or ()))
            return models.SourceList(sources=_source_items(session, found))

    @server.tool()
    def get_source(
        source: Annotated[str, Field(description="Source ID, feed URL or name.")],
    ) -> models.SourceItem:
        """One source with its status, note, fetch health and last 30 days of activity."""
        with sessions.begin() as session, service_errors():
            return _source_items(session, [sources.find_source(session, source)])[0]

    @server.tool()
    def source_survival() -> models.Survival:
        """Per origin (and discovery search adapter): how many sources stayed and were read."""
        with sessions.begin() as session, service_errors():
            rows = source_stats.source_survival(session, datetime.now(UTC))
            return models.Survival(
                rows=[models.SurvivalItem.model_validate(row, from_attributes=True) for row in rows]
            )

    @server.tool(name="open_stats")
    def get_open_stats(
        days: Annotated[int, Field(ge=1, le=90)] = 30,
    ) -> models.OpenStatsResult:
        """Articles shown and opened over the last `days` digest days, by source and topic."""
        with sessions.begin() as session, service_errors():
            stats = open_stats.open_stats(session, today(), days)

            def items(rows: list[open_stats.OpenCount]) -> list[models.OpenCountItem]:
                return [
                    models.OpenCountItem(key=r.key, shown=r.shown, opened=r.opened) for r in rows
                ]

            return models.OpenStatsResult(
                days=stats.days,
                since=stats.since,
                shown=stats.shown,
                opened=stats.opened,
                by_topic=items(stats.by_topic),
                external=models.OpenStatsExternal(by_source=items(stats.by_source)),
            )

    @server.tool()
    def dedup_decisions(
        day: Annotated[
            date | None, Field(description="The digest day; the latest when left out.")
        ] = None,
        run_id: Annotated[
            uuid.UUID | None, Field(description="A digest run instead of a day.")
        ] = None,
    ) -> models.DedupDecisions:
        """What deduplication dropped in a digest run: repeats of earlier days and same-day
        copies of one story, with similarity and, for grey-zone pairs, the judge's probability.
        A day finds its real run; a dry run is found only by its run_id."""
        with sessions.begin() as session, service_errors():
            run = _digest_run(session, day, run_id)
            stats = run.stats.get("deduplication") or {}
            drops = [d for d in stats.get("drops") or [] if isinstance(d, dict)]
            links = {d.get("link") for d in drops} | {d.get("duplicate_of") for d in drops}
            titles = _titles(session, {link for link in links if isinstance(link, str)})
            return models.DedupDecisions(
                run_id=run.id,
                date=run.stats.get("date"),
                same_day_method=stats.get("same_day_method"),
                candidates=stats.get("candidates"),
                survivors=stats.get("survivors"),
                judged_pairs=stats.get("judged_pairs"),
                same_day_threshold=stats.get("same_day_threshold"),
                drops=[
                    models.Drop(
                        link=d["link"],
                        reason=d.get("reason", ""),
                        similarity=d.get("similarity", 0.0),
                        duplicate_of=d.get("duplicate_of"),
                        same_event=d.get("same_event"),
                        external=models.DropExternal(
                            title=titles.get(d["link"]),
                            kept_title=titles.get(d.get("duplicate_of") or ""),
                        ),
                    )
                    for d in drops
                    if isinstance(d.get("link"), str)
                ],
            )

    @server.tool(name="costs")
    def get_costs() -> models.Costs:
        """LLM spending today and this month against the budget, and the cost of recent runs."""
        settings = get_settings()
        now = datetime.now(UTC)
        with sessions.begin() as session, service_errors():
            state = check_budget(session, now, settings.budget, settings.scheduler.timezone)
            if state is None:  # no limit set; the spending is still worth knowing
                day_start, month_start = window_starts(now, settings.scheduler.timezone)
                spent = RunRepository(session).spending(day_start, month_start)
                state = evaluate(settings.budget, Spending(*spent))
            recent = runs.list_runs(session, RECENT_COSTS)
            return models.Costs(
                budget=models.Spending(
                    daily_limit_usd=_float(state.daily),
                    monthly_limit_usd=_float(state.monthly),
                    spent_today_usd=float(state.spending.today),
                    spent_month_usd=float(state.spending.month),
                    unpriced_runs=state.spending.unpriced_runs,
                    over=state.over,
                    reason=state.reason,
                ),
                recent_runs=[_run_cost(run) for run in recent],
            )

    @server.tool()
    def list_runs(
        kind: RunKind | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> models.RunList:
        """Pipeline runs, newest first, with what each did (stats under `external`)."""
        with sessions.begin() as session, service_errors():
            found = runs.list_runs(session, limit, kind=kind)
            return models.RunList(runs=[models.RunItem.of(run) for run in found])

    @server.tool()
    def get_run(run_id: uuid.UUID) -> models.RunItem:
        """One pipeline run; poll it after start_run until its status is no longer running."""
        with sessions.begin() as session, service_errors():
            # A run waiting for a free slot has no row yet.
            if deps.runs.is_queued(run_id) and RunRepository(session).get(run_id) is None:
                raise ToolError(f"run {run_id} waits for a free slot; ask again later")
            return models.RunItem.of(runs.get_run(session, run_id))

    @server.tool()
    def list_interests() -> models.InterestList:
        """The owner's interests: topic, keywords, notes, and whether each is active."""
        with sessions.begin() as session, service_errors():
            return models.InterestList(
                interests=[models.InterestItem.of(i) for i in all_interests(session)]
            )

    @server.tool()
    def get_status() -> models.StatusResult:
        """Article and source counts, last digest day, pause and each pipeline's last run."""
        with sessions.begin() as session, service_errors():
            current = status.get_status(session, datetime.now(UTC), get_settings().embedding.model)
            counts = current.articles
            return models.StatusResult(
                articles=models.ArticleCounts(
                    total=counts.total, shown=counts.shown, opened=counts.opened
                ),
                sources=current.sources,
                last_digest=current.last_digest,
                paused_until=current.paused_until,
                last_runs={
                    kind: models.RunSummary.of(run) if run else None
                    for kind, run in current.last_runs.items()
                },
                embedding_model=current.embedding_model,
                embeddings=current.embeddings,
            )

    @server.tool()
    def list_changes(
        entity: Annotated[
            str | None, Field(description="One entity, e.g. source:12 or interest:3.")
        ] = None,
        status: ChangeStatus | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 30,
    ) -> models.ChangeList:
        """Changes to sources, interests and settings, newest first, by anyone (agents too)."""
        entity_type = entity_id = None
        if entity is not None:
            parts = rollback.split_entity(entity)
            if parts is None:
                raise ToolError("entity must look like source:12")
            entity_type, entity_id = parts
        with sessions.begin() as session, service_errors():
            found = rollback.list_changes(
                session,
                limit=limit,
                status=status,
                entity_type=entity_type,
                entity_id=entity_id,
            )
            return models.ChangeList(changes=[models.ChangeItem.of(c) for c in found])


def _source_items(session: Session, found: Sequence[Source]) -> list[models.SourceItem]:
    stats = sources.recent_stats(session, datetime.now(UTC), [s.id for s in found])
    return [models.SourceItem.of(s, stats.get(s.id)) for s in found]


def _digest_run(session: Session, day: date | None, run_id: uuid.UUID | None) -> Run:
    if run_id is not None:
        run = runs.get_run(session, run_id)
        if run.kind is not RunKind.DIGEST:
            raise ToolError(f"run {run_id} is a {run.kind.value} run, not a digest run")
        return run
    for run in RunRepository(session).recent(DIGEST_RUNS_SEARCHED, RunKind.DIGEST):
        # A dry run's picks were never shown; ask for one by its run_id.
        if run.status is not RunStatus.OK or run.dry_run or "deduplication" not in run.stats:
            continue
        if day is None or run.stats.get("date") == day.isoformat():
            return run
    raise ToolError(f"no finished digest run for {day}" if day else "no finished digest run")


def _titles(session: Session, links: set[str]) -> dict[str, str]:
    return ArticleRepository(session).titles_by_link(links)


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _run_cost(run: Run) -> models.RunCost:
    usage = run.stats.get("usage") or {}
    known = usage.get("cost_usd_known", usage.get("cost_usd"))
    return models.RunCost(
        id=run.id,
        kind=run.kind,
        dry_run=run.dry_run,
        started_at=run.started_at,
        cost_usd=float(known) if isinstance(known, int | float) else None,
        unpriced_calls=int(usage.get("unpriced_calls") or 0),
    )
