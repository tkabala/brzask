"""Discovery: new sources from a web search per interest, vetted by a judge.

For each active interest the web search proposes sites; each is resolved to a
feed (blog, YouTube channel, GitHub releases), feeds without recent items are
dropped, and the judge scores the rest on what they actually publish: how
regularly it serves an interest, and how much of it is substance rather than
marketing. Code turns the two scores into a status:

  enabled at once     fit >= 2 of 3 and substance >= 1.5 of 2,
  rejected            fit < 1: it does not serve the interests (never proposed again),
  pending             anything else, such as a relevant feed full of sponsor
                      posts, for a person to decide.

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
from brzask.clients.judge import Judge, JudgeError, Score, build_judge
from brzask.clients.usage import UsageMeter
from brzask.clients.web_search import WebSearch, WebSearchError, build_web_search
from brzask.config import get_settings
from brzask.db.models import SourceOrigin, SourceStatus
from brzask.log import get_logger
from brzask.repositories import SourceRepository
from brzask.services.digest.ranking import interest_context
from brzask.services.runs import RunContext, SkipRunError
from brzask.services.sources import propose_source
from brzask.services.visited import FindsFeeds, known_hosts
from brzask.urls import feed_key, host_matches, host_of

log = get_logger(__name__)

ACTOR = "pipeline:discovery"

# Results asked of the web search per interest.
SEARCH_RESULTS = 10
# Newest feed items sampled, and how many of them the judge sees.
SAMPLE_ITEMS = 10
SAMPLE_IN_PROMPT = 8
# Characters of each sampled item's summary the judge sees.
SNIPPET_CHARS = 200
# A feed with no item this recent is not worth judging.
RECENT_WINDOW = timedelta(days=60)
# Sites resolved to feeds, and feeds judged, at once.
WORKERS = 5

QUESTIONS: dict[str, Score] = {
    "interest_fit": Score(
        "How regularly do the items in `feed.recent_items` serve the reader's interests "
        "(`reader.interests`)? An interest's notes are the reader's own words and outrank "
        "its keywords. Judge the feed by its items and its own title, never by the name it "
        "was proposed under (`feed.proposed_as`), which came from a web search and is "
        "sometimes wrong.",
        [
            "Never: its items serve none of the interests",
            "Now and then, among mostly unrelated items",
            "Often: a good share of its items serve an interest",
            "Mostly: the feed is focused on an interest",
        ],
    ),
    "substance": Score(
        "How much of `feed.recent_items` is substance (news, analysis, technical writing, "
        "release notes with real changes) rather than marketing, sponsor posts, SEO filler "
        "or announcements without content?",
        [
            "Mostly marketing, sponsor posts or filler",
            "Mixed",
            "Mostly substance",
        ],
    ),
}
# Scores (probability-weighted levels) a feed needs to be enabled without a person,
# and below which it is rejected. Compared on one real run of 16 feeds (2026-10-20)
# with a 0-10 LLM judge, Jev answering: the same four enabled, 12 of 16 statuses the
# same, and every difference a feed one of the two left pending, the other rejected.
ENABLE_FIT, ENABLE_SUBSTANCE = 2.0, 1.5
REJECT_FIT = 1.0

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
    scores: dict[str, float] | None  # by question; None when the judge gave no verdict
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


def judge_state(candidate: Candidate, interests: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """What the judge reads about one feed."""
    c = candidate
    return {
        "reader": {"interests": [dict(interest) for interest in interests]},
        "feed": {
            "url": c.feed.url,
            "title": c.feed.title,
            "proposed_as": c.proposal.title or c.proposal.url,
            "title_differs_from_proposed_name": c.name_mismatch,
            "suggested_because": c.proposal.reason or None,
            "items": len(c.feed.entries),
            f"items_in_last_{RECENT_WINDOW.days}_days": c.recent_count,
            "latest": c.latest.date().isoformat() if c.latest else None,
            "recent_items": [
                {
                    "title": entry.title,
                    "date": entry.published_at.date().isoformat() if entry.published_at else None,
                    "summary": (entry.summary or "")[:SNIPPET_CHARS],
                }
                for entry in c.sample[:SAMPLE_IN_PROMPT]
            ],
        },
    }


def status_for(fit: float, substance: float) -> SourceStatus:
    if fit >= ENABLE_FIT and substance >= ENABLE_SUBSTANCE:
        return SourceStatus.ACTIVE
    if fit < REJECT_FIT:
        return SourceStatus.REJECTED
    return SourceStatus.PENDING


def judge_feed(
    candidate: Candidate,
    judge: Judge,
    interests: Sequence[dict[str, Any]],
    meter: UsageMeter | None = None,
) -> Verdict:
    """The judge's verdict on one feed; pending when it cannot give one."""
    try:
        judgement = judge.ask(
            judge_state(candidate, interests), QUESTIONS, purpose="discovery", meter=meter
        )
    except JudgeError as error:
        log.warning("feed not judged", url=candidate.feed.url, error=str(error))
        return Verdict(candidate, SourceStatus.PENDING, None, "no usable verdict from the judge")
    scores = {name: round(judgement.score(name).score, 2) for name in QUESTIONS}
    fit, substance = scores["interest_fit"], scores["substance"]
    reason = f"interest fit {fit:g}/3, substance {substance:g}/2"
    return Verdict(candidate, status_for(fit, substance), scores, reason)


def discover_sources(
    context: RunContext,
    search: WebSearch | None,
    finder: FindsFeeds,
    judge: Judge,
) -> None:
    """Search, resolve, sample and judge; store verdicts outside a dry run."""
    if search is None:
        raise SkipRunError("no web search configured (WEB_SEARCH)")
    now = context.started_at
    with context.sessions.begin() as session:
        interests = interest_context(session)
        sources = SourceRepository(session).find()
        known_urls = {feed_key(source.url) for source in sources}
        known_sites = known_hosts([s.url for s in sources] + [s.site_url for s in sources])
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
        if feed is not None and feed_key(feed.url) not in feed_urls:
            feed_urls.add(feed_key(feed.url))
            candidates.append(to_candidate(proposal, feed, now))
    active = [c for c in candidates if c.recent_count > 0]

    with context.stage("judge"), ThreadPoolExecutor(max_workers=WORKERS) as pool:
        verdicts = list(pool.map(lambda c: judge_feed(c, judge, interests, context.usage), active))
    if verdicts and all(verdict.scores is None for verdict in verdicts):
        # An unusable judge would store every feed as pending, and pending feeds
        # are never proposed again; failing the run keeps them for the next one.
        raise JudgeError(f"no verdict for any of {len(verdicts)} feeds")

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
                    {"url": v.candidate.feed.url, "scores": v.scores}
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
    judge = build_judge(settings)
    search = build_web_search(settings)
    try:
        discover_sources(context, search, finder, judge)
    finally:
        finder.close()
        judge.close()
        if search is not None:
            search.close()


def _store(session: Session, verdict: Verdict, adapter: str) -> None:
    candidate = verdict.candidate
    propose_source(
        session,
        candidate.feed,
        status=verdict.status,
        origin=SourceOrigin.DISCOVERY,
        actor=ACTOR,
        # Which search found it and for which interest, for source survival stats.
        origin_detail=f"{adapter}: {candidate.proposal.interest}",
        note=f"discovery judge: {verdict.reason}",
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
