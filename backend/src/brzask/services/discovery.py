"""Discovery: new sources from a web search per interest, vetted by an LLM judge.

For each active interest the web search proposes sites; each is resolved to a
feed (blog, YouTube channel, GitHub releases), feeds without recent items are
dropped, and the judge scores the rest on what they actually publish:

  >= 7      the source is enabled at once,
  4 - 6.9   it waits as `pending` for a person,
  < 4       it is stored as `rejected`, so the URL is never proposed again.

A missing verdict leaves the feed pending: nothing is enabled or rejected on
no evidence.
"""

import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from brzask import prompts
from brzask.clients.feed_finder import FeedFinder, FoundFeed
from brzask.clients.feeds import FeedEntry, FeedFetcher
from brzask.clients.llm import InvalidJSONError, LLMClient
from brzask.clients.web_search import WebSearch, WebSearchError, build_web_search
from brzask.config import get_settings
from brzask.db.models import SourceOrigin, SourceStatus
from brzask.log import get_logger
from brzask.repositories import SourceRepository
from brzask.services.digest.ranking import ChatModel, interest_context
from brzask.services.runs import RunContext, SkipRunError
from brzask.services.sources import propose_source
from brzask.services.visited import FindsFeeds
from brzask.urls import host_matches, host_of

log = get_logger(__name__)

ACTOR = "pipeline:discovery"

# Results asked of the web search per interest.
SEARCH_RESULTS = 10
# Newest feed items sampled, and how many of them the judge sees.
SAMPLE_ITEMS = 10
SAMPLE_IN_PROMPT = 8
# A feed with no item this recent is not worth judging.
RECENT_WINDOW = timedelta(days=60)
# Candidates per judge call, keeping each prompt a manageable size.
JUDGE_BATCH = 15
# Judge scores, out of 10.
ENABLE_AT = 7.0
PENDING_AT = 4.0
# Sites resolved to feeds at once.
WORKERS = 5

_WORD = re.compile(r"\w{4,}")


@dataclass(frozen=True, slots=True)
class Proposal:
    """A page the web search proposed for an interest."""

    url: str
    title: str
    reason: str
    interest: str


@dataclass(frozen=True, slots=True)
class Candidate:
    """A proposal resolved to a working feed, with what the judge needs."""

    proposal: Proposal
    feed: FoundFeed
    sample: list[FeedEntry]  # newest first
    recent_count: int
    latest: datetime | None
    name_mismatch: bool


@dataclass(frozen=True, slots=True)
class Verdict:
    candidate: Candidate
    status: SourceStatus
    score: float | None  # None when the judge gave no usable verdict
    reason: str


def search_query(interest: dict[str, Any], *, conversational: bool) -> str:
    return prompts.render(
        "discovery_search",
        topic=interest["topic"],
        keywords=interest["keywords"],
        conversational=conversational,
    ).strip()


def unique_sites(proposed: Iterable[Proposal], known_sites: set[str]) -> list[Proposal]:
    """The first proposal per site, skipping sites a source already follows.

    A site's article pages all lead to the same feed, so one is enough. On
    YouTube and GitHub each channel or repository is a feed of its own, so
    there the channel or repository path counts instead of the host.
    """
    seen: set[str] = set()
    unique: list[Proposal] = []
    for proposal in proposed:
        key = _site_key(proposal.url)
        if not key or key in seen or ("/" not in key and key in known_sites):
            continue
        seen.add(key)
        unique.append(proposal)
    return unique


def name_mismatch(proposed: str, feed_title: str | None) -> bool:
    """True when the feed's own title shares no word (4+ letters) with the proposed name.

    Web search names are sometimes simply wrong, so the judge is told; one
    shared word is enough ("Claude Code Releases" vs "anthropics/claude-code").
    """
    proposed_words = set(_WORD.findall(proposed.lower()))
    feed_words = set(_WORD.findall((feed_title or "").lower()))
    return bool(proposed_words and feed_words) and not proposed_words & feed_words


def to_candidate(proposal: Proposal, feed: FoundFeed, now: datetime) -> Candidate:
    oldest = datetime.min.replace(tzinfo=UTC)
    sample = sorted(feed.entries, key=lambda e: e.published_at or oldest, reverse=True)
    sample = sample[:SAMPLE_ITEMS]
    dates = [entry.published_at for entry in sample if entry.published_at is not None]
    return Candidate(
        proposal=proposal,
        feed=feed,
        sample=sample,
        recent_count=sum(date >= now - RECENT_WINDOW for date in dates),
        latest=max(dates, default=None),
        name_mismatch=name_mismatch(proposal.title, feed.title),
    )


def judge_prompt(candidates: Sequence[Candidate], interests: Sequence[dict[str, Any]]) -> str:
    return prompts.render(
        "discovery_judge",
        interests=interests,
        recent_days=RECENT_WINDOW.days,
        candidates=[
            {
                "url": c.feed.url,
                "proposed_as": c.proposal.title or c.proposal.url,
                "feed_title": c.feed.title,
                "name_mismatch": c.name_mismatch,
                "reason": c.proposal.reason or None,
                "item_count": len(c.feed.entries),
                "recent_count": c.recent_count,
                "latest": c.latest.date().isoformat() if c.latest else None,
                "sample": [
                    {
                        "title": entry.title,
                        "date": entry.published_at.date().isoformat() if entry.published_at else "",
                        "snippet": entry.summary or "",
                    }
                    for entry in c.sample[:SAMPLE_IN_PROMPT]
                ],
            }
            for c in candidates
        ],
    )


def status_for(score: float) -> SourceStatus:
    if score >= ENABLE_AT:
        return SourceStatus.ACTIVE
    if score >= PENDING_AT:
        return SourceStatus.PENDING
    return SourceStatus.REJECTED


def parse_verdicts(answer: Any, candidates: Sequence[Candidate]) -> list[Verdict]:
    """One verdict per candidate, matched by feed URL; pending where none is usable."""
    items = answer.get("verdicts") if isinstance(answer, dict) else answer
    by_url: dict[str, dict[str, Any]] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            by_url.setdefault(item["url"].strip(), item)
    verdicts: list[Verdict] = []
    for candidate in candidates:
        item = by_url.get(candidate.feed.url, {})
        score = item.get("score")
        reason = item.get("reason")
        reason = reason.strip() if isinstance(reason, str) else ""
        if isinstance(score, bool) or not isinstance(score, int | float) or not 0 <= score <= 10:
            verdicts.append(
                Verdict(candidate, SourceStatus.PENDING, None, "no usable verdict from the judge")
            )
        else:
            verdicts.append(Verdict(candidate, status_for(float(score)), float(score), reason))
    return verdicts


def discover_sources(
    context: RunContext,
    search: WebSearch | None,
    finder: FindsFeeds,
    llm: ChatModel,
) -> None:
    """Search, resolve, sample and judge; store verdicts outside a dry run."""
    if search is None:
        raise SkipRunError("no web search configured (WEB_SEARCH)")
    now = context.started_at
    with context.sessions.begin() as session:
        interests = interest_context(session)
        sources = SourceRepository(session).find()
        known_urls = {source.url for source in sources}
        known_sites = {host_of(url) for s in sources for url in (s.url, s.site_url) if url}
    if not interests:
        raise SkipRunError("no active interests")

    proposed: list[Proposal] = []
    failed_searches: list[str] = []
    with context.stage("search"):
        for interest in interests:
            query = search_query(interest, conversational=search.name == "llm-online")
            try:
                results = search.search(query, limit=SEARCH_RESULTS, meter=context.usage)
            except WebSearchError as error:
                # One interest's failed search must not cost the others.
                log.warning("web search failed", interest=interest["topic"], error=str(error))
                failed_searches.append(interest["topic"])
                continue
            proposed.extend(Proposal(r.url, r.title, r.snippet, interest["topic"]) for r in results)
    proposed = unique_sites(proposed, known_sites)

    with context.stage("resolve"), ThreadPoolExecutor(max_workers=WORKERS) as pool:
        found = list(pool.map(lambda p: finder.find(p.url), proposed))
    candidates: list[Candidate] = []
    feed_urls = set(known_urls)
    for proposal, feed in zip(proposed, found, strict=True):
        # The same feed can come back for two proposals, or be a source already.
        if feed is not None and feed.url not in feed_urls:
            feed_urls.add(feed.url)
            candidates.append(to_candidate(proposal, feed, now))
    active = [c for c in candidates if c.recent_count > 0]

    verdicts: list[Verdict] = []
    with context.stage("judge"):
        for start in range(0, len(active), JUDGE_BATCH):
            batch = active[start : start + JUDGE_BATCH]
            try:
                answer, _ = llm.complete_json(
                    judge_prompt(batch, interests), purpose="discovery", meter=context.usage
                )
            except InvalidJSONError as error:
                log.warning("judge answer is not JSON", answer=error.content[:500])
                answer = None
            verdicts.extend(parse_verdicts(answer, batch))

    if not context.dry_run:
        with context.sessions.begin() as session:
            for verdict in verdicts:
                _store(session, verdict, search.name)

    context.stats.update(
        {
            "interests": len(interests),
            "failed_searches": failed_searches,
            "proposed": len(proposed),
            "resolved": len(candidates),
            "inactive": [c.feed.url for c in candidates if c.recent_count == 0],
            "judged": len(verdicts),
            **{
                status.value: [
                    {"url": v.candidate.feed.url, "score": v.score}
                    for v in verdicts
                    if v.status is status
                ]
                for status in (SourceStatus.ACTIVE, SourceStatus.PENDING, SourceStatus.REJECTED)
            },
        }
    )
    log.info(
        "discovery finished",
        proposed=len(proposed),
        resolved=len(candidates),
        judged=len(verdicts),
    )


def run_discovery(context: RunContext) -> None:
    """Discovery with clients built from the settings."""
    settings = get_settings()
    finder = FeedFinder(FeedFetcher())
    llm = LLMClient.from_settings(settings.llm)
    try:
        discover_sources(context, build_web_search(settings), finder, llm)
    finally:
        finder.close()
        llm.client.close()


def _store(session: Session, verdict: Verdict, adapter: str) -> None:
    candidate = verdict.candidate
    score = f"{verdict.score:g}/10" if verdict.score is not None else "no score"
    note = f"discovery judge {score}"
    propose_source(
        session,
        candidate.feed,
        status=verdict.status,
        origin=SourceOrigin.DISCOVERY,
        actor=ACTOR,
        # Which search found it and for which interest, for source survival stats.
        origin_detail=f"{adapter}: {candidate.proposal.interest}",
        note=f"{note}: {verdict.reason}" if verdict.reason else note,
    )


def _site_key(url: str) -> str:
    """What identifies a proposal's feed: the host, or the channel/repository path."""
    host = host_of(url)
    if not host:
        return ""
    if host == "github.com" or host_matches(host, "youtube.com"):
        segments = [s for s in urlsplit(url).path.split("/") if s][:2]
        return "/".join([host, *segments])
    return host
