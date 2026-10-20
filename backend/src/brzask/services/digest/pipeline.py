"""The digest pipeline: pool → ranking → extraction → deduplication → selection."""

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import tzinfo

from brzask import prompts
from brzask.clients.embeddings import Embedder
from brzask.clients.extractors import build_chain
from brzask.clients.extractors.adapters import PAGE_TIMEOUT
from brzask.clients.feeds import FeedFetcher
from brzask.clients.http import new_client
from brzask.clients.judge import Judge, build_judge
from brzask.clients.llm import LLMClient
from brzask.config import get_settings
from brzask.log import get_logger
from brzask.prompts import Language
from brzask.repositories import ArticleRepository
from brzask.repositories.articles import DigestEntry
from brzask.services.digest.dedup import deduplicate_candidates
from brzask.services.digest.extraction import DocumentEmbedder, TextExtractor, extract_and_embed
from brzask.services.digest.pool import FeedReader, gather_candidates
from brzask.services.digest.ranking import ChatModel, rank_candidates
from brzask.services.digest.selection import Pick, select_digest
from brzask.services.embeddings import active_model
from brzask.services.pause import paused_until
from brzask.services.runs import RunContext, SkipRunError

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DigestClients:
    feeds: FeedReader
    llm: ChatModel
    extractor: TextExtractor
    embedder: DocumentEmbedder
    language: Language
    timezone: tzinfo  # the digest date is the local date when the run starts
    judge: Judge | None = None  # ranks by composite score instead of the LLM when set
    dedup_judge: Judge | None = None  # decides same-day grey-zone pairs when set


def build_digest(context: RunContext, clients: DigestClients) -> None:
    """Build today's digest, skipping when paused or when it exists (unless forced).

    A forced run on a day that has a digest appends to it, numbering on from
    the last position. A dry run computes everything and writes nothing.
    """
    now = context.started_at
    day = now.astimezone(clients.timezone).date()
    context.stats["date"] = day.isoformat()
    with context.sessions.begin() as session:
        pause = paused_until(session, now)
        existing = ArticleRepository(session).last_digest_position(day)
    if pause is not None and not context.force:
        raise SkipRunError(f"paused until {pause.isoformat()}")
    if existing is not None and not context.force:
        raise SkipRunError("today's digest already exists")

    pool = gather_candidates(context, clients.feeds)
    if not pool:
        raise SkipRunError("no candidates")
    top = rank_candidates(context, pool, clients.llm, judge=clients.judge)
    extracted = extract_and_embed(context, top, clients.extractor, clients.embedder)
    survivors = deduplicate_candidates(
        context, extracted, clients.embedder.model, judge=clients.dedup_judge
    )
    picks = select_digest(context, survivors, clients.llm, clients.language)

    if not context.dry_run:
        with context.sessions.begin() as session:
            articles = ArticleRepository(session)
            # Read again inside the writing transaction: a forced run appends.
            offset = articles.last_digest_position(day) or 0
            articles.mark_shown(day, [_entry(pick, offset) for pick in picks], shown_at=now)


def run_digest(context: RunContext) -> None:
    """The digest with clients built from the settings, embedding with the active model."""
    settings = get_settings()
    with context.sessions.begin() as session:
        model = active_model(session, settings.embedding.model)
    if model != settings.embedding.model:
        log.warning(
            "EMBEDDING_MODEL differs from the active model; using the active one "
            "(brzask reembed switches models)",
            configured=settings.embedding.model,
            active=model,
        )
    with ExitStack() as stack:
        feeds = FeedFetcher()
        stack.callback(feeds.close)
        pages = new_client(PAGE_TIMEOUT)
        stack.callback(pages.close)
        llm = LLMClient.from_settings(settings.llm)
        stack.callback(llm.client.close)
        embedder = Embedder.from_settings(settings, model)
        stack.callback(embedder.client.close)
        digest = settings.digest
        judge = None
        if "judge" in (digest.ranking, digest.deduplication):
            judge = build_judge(settings)
            stack.callback(judge.close)
        build_digest(
            context,
            DigestClients(
                feeds=feeds,
                llm=llm,
                extractor=build_chain(settings.extractors, pages),
                embedder=embedder,
                language=prompts.language(settings.digest.language),
                timezone=settings.scheduler.timezone,
                judge=judge if digest.ranking == "judge" else None,
                dedup_judge=judge if digest.deduplication == "judge" else None,
            ),
        )


def _entry(pick: Pick, offset: int) -> DigestEntry:
    if pick.candidate.article_id is None:  # every candidate is stored outside a dry run
        raise RuntimeError(f"{pick.candidate.link} was picked but never stored")
    return DigestEntry(
        article_id=pick.candidate.article_id,
        position=offset + pick.position,
        title=pick.title,
        summary=pick.summary,
        why_it_matters=pick.why_it_matters,
        topic=pick.topic,
    )
