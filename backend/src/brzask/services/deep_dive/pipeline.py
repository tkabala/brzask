"""The deep dive run: plan, gather, read, write, for one queued dive."""

from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import Any

from brzask import prompts
from brzask.clients.embeddings import Embedder
from brzask.clients.extractors import build_chain
from brzask.clients.extractors.adapters import PAGE_TIMEOUT
from brzask.clients.http import new_client, public_client
from brzask.clients.llm import LLMClient
from brzask.clients.web_search import WebSearch, build_web_search
from brzask.config import get_settings
from brzask.config.settings import BudgetSettings
from brzask.prompts import Language
from brzask.repositories import BriefRepository, ContentRepository, DeepDiveRepository
from brzask.services.budget import check_budget
from brzask.services.deep_dive.gather import (
    Source,
    archive_candidates,
    read_sources,
    web_candidates,
)
from brzask.services.deep_dive.plan import plan_queries
from brzask.services.deep_dive.report import write_report
from brzask.services.digest.extraction import TextExtractor
from brzask.services.digest.ranking import ChatModel, interest_context
from brzask.services.embeddings import active_model
from brzask.services.errors import ServiceError
from brzask.services.runs import Pipeline, RunContext, SkipRunError
from brzask.services.search import QueryEmbedder

ERROR_CHARS = 300


@dataclass(frozen=True, slots=True)
class DeepDiveClients:
    llm: ChatModel
    model: str  # the LLM the report is recorded as written by
    embedder: QueryEmbedder
    extractor: TextExtractor
    search: WebSearch | None  # None: WEB_SEARCH is not configured
    language: Language
    budget: BudgetSettings | None
    timezone: tzinfo


def build_deep_dive(context: RunContext, clients: DeepDiveClients, dive_id: int) -> None:
    """Write dive `dive_id` and store it; on any error store the dive as failed and re-raise.

    A reached spending limit fails the dive with the limit's reason and skips
    the run.
    """
    with context.sessions.begin() as session:
        repository = DeepDiveRepository(session)
        if repository.get(dive_id) is None:
            raise SkipRunError(f"no deep dive {dive_id}")
        context.stats["deep_dive"] = {"dive_id": dive_id}
        budget = (
            check_budget(session, context.started_at, clients.budget, clients.timezone)
            if clients.budget is not None
            else None
        )
        if budget is not None and budget.reason is not None:
            repository.fail(dive_id, budget.reason, datetime.now(UTC))
        else:
            repository.start(dive_id, context.run_id)
    if budget is not None and budget.reason is not None:
        raise SkipRunError(budget.reason)
    try:
        _write(context, clients, dive_id)
    except Exception as error:
        message = f"{type(error).__name__}: {error}"[:ERROR_CHARS]
        with context.sessions.begin() as session:
            DeepDiveRepository(session).fail(dive_id, message, datetime.now(UTC))
        raise


def _write(context: RunContext, clients: DeepDiveClients, dive_id: int) -> None:
    stats: dict[str, Any] = context.stats["deep_dive"]
    with context.sessions() as session:
        dive = DeepDiveRepository(session).get(dive_id)
        assert dive is not None  # noqa: S101  (checked by the caller)
        article, focus = dive.article, dive.focus
        content = ContentRepository(session).get(article.id)
        if content is None:
            raise ServiceError("the article has no stored text to go deeper from")
        brief = BriefRepository(session).get(article.id)
        interests = interest_context(session)

    with context.stage("plan"):
        queries = plan_queries(
            clients.llm, article, brief, content, interests, focus, clients.language, context.usage
        )
    stats["queries"] = {
        "background": queries.background,
        "practice": queries.practice,
        "archive": queries.archive,
    }

    with context.stage("gather"):
        web, searched = (
            web_candidates(queries, clients.search, article.link, context.usage)
            if clients.search is not None
            else ([], False)
        )
        with context.sessions() as session:
            archive = archive_candidates(session, clients.embedder, queries.archive, article.id)
            contents = {
                item.id: stored.text
                for item in archive
                if (stored := ContentRepository(session).get(item.id)) is not None
            }
    stats["web_results"] = len(web)

    with context.stage("read"):
        sources = read_sources(article, content, archive, contents, web, clients.extractor)
    stats["archive_sources"] = sum(s.origin == "archive" for s in sources)
    stats["web_pages_read"] = sum(s.origin == "web" for s in sources)
    stats["sources"] = len(sources)
    stats["thin"] = len(sources) == 1

    with context.stage("write"):
        report = write_report(
            clients.llm, article, sources, interests, focus, clients.language, context.usage
        )
    with context.sessions.begin() as session:
        DeepDiveRepository(session).finish(
            dive_id,
            report=report.as_json(),
            sources=_stored(sources),
            thin=len(sources) == 1,
            searched_web=searched,
            model=clients.model,
            at=datetime.now(UTC),
        )


def _stored(sources: Sequence[Source]) -> list[dict[str, Any]]:
    return [
        {"n": s.n, "url": s.url, "title": s.title, "origin": s.origin, "article_id": s.article_id}
        for s in sources
    ]


def deep_dive_pipeline(dive_id: int) -> Pipeline:
    """The run of dive `dive_id`, with clients built from the settings."""

    def pipeline(context: RunContext) -> None:
        settings = get_settings()
        with context.sessions.begin() as session:
            model = active_model(session, settings.embedding.model)
        with ExitStack() as stack:
            proxy = settings.fetch.proxy_target()
            pages = public_client(
                PAGE_TIMEOUT, settings.fetch.allowed_private_networks, proxy=proxy
            )
            stack.callback(pages.close)
            services = new_client(PAGE_TIMEOUT)
            stack.callback(services.close)
            llm = LLMClient.from_settings(settings.llm)
            stack.callback(llm.client.close)
            embedder = Embedder.from_settings(settings, model)
            stack.callback(embedder.client.close)
            search = build_web_search(settings)
            if search is not None:
                stack.callback(search.close)
            build_deep_dive(
                context,
                DeepDiveClients(
                    llm=llm,
                    model=settings.llm.model,
                    embedder=embedder,
                    extractor=build_chain(settings.extractors, pages, services, proxy),
                    search=search,
                    language=prompts.language(settings.digest.language),
                    budget=settings.budget,
                    timezone=settings.scheduler.timezone,
                ),
                dive_id,
            )

    return pipeline
