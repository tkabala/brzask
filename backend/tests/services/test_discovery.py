from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.feed_finder import FoundFeed
from brzask.clients.feeds import FeedEntry
from brzask.clients.llm import Completion, InvalidJSONError
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.clients.web_search import SearchResult, WebSearchError
from brzask.db.models import Source, SourceOrigin, SourceStatus
from brzask.repositories import ChangeRepository
from brzask.services.discovery import (
    ACTOR,
    RECENT_WINDOW,
    SAMPLE_ITEMS,
    Proposal,
    discover_sources,
    judge_prompt,
    name_mismatch,
    parse_verdicts,
    search_query,
    status_for,
    to_candidate,
    unique_sites,
)
from brzask.services.runs import SkipRunError
from tests.factories import Factories
from tests.services.digest.fakes import NOW, context

DAY = timedelta(days=1)


def proposal(url: str, title: str = "", interest: str = "Rust") -> Proposal:
    return Proposal(url, title, "", interest)


def entries(count: int, newest_days_ago: int = 1) -> tuple[FeedEntry, ...]:
    return tuple(
        FeedEntry(
            f"https://x.example/{n}",
            f"Post {n}",
            f"About {n}",
            None,
            NOW - (newest_days_ago + n) * DAY,
        )
        for n in range(count)
    )


def feed(url: str, title: str | None = "A Blog", items: tuple[FeedEntry, ...] = ()) -> FoundFeed:
    return FoundFeed(url, title, url.rsplit("/", 1)[0], items or entries(3))


# --- Pure parts ------------------------------------------------------------------------


def test_search_query_for_an_online_llm_or_a_search_engine() -> None:
    interest = {"topic": "Rust", "keywords": ["cargo"], "notes": "skip: crypto"}

    assert search_query(interest, conversational=False) == "Rust cargo blog"
    request = search_query(interest, conversational=True)
    assert "staying up to date on Rust (cargo)" in request
    assert "crypto" not in request


def test_unique_sites_keep_one_page_per_site_and_skip_followed_sites() -> None:
    proposed = [
        proposal("https://blog.example/post-1"),
        proposal("https://www.blog.example/post-2"),
        proposal("https://followed.example/"),
        proposal("https://www.youtube.com/@first"),
        proposal("https://www.youtube.com/@second/videos"),
        proposal("https://youtube.com/@first"),
        proposal("https://github.com/a/one"),
        proposal("https://github.com/a/two/issues"),
        proposal("not a url"),
    ]

    kept = unique_sites(proposed, {"followed.example", "github.com", "youtube.com"})

    assert [p.url for p in kept] == [
        "https://blog.example/post-1",
        "https://www.youtube.com/@first",
        "https://www.youtube.com/@second/videos",
        "https://github.com/a/one",
        "https://github.com/a/two/issues",
    ]


@pytest.mark.parametrize(
    ("proposed", "title", "expected"),
    [
        ("AI Engineer", "Istanbul street photography", True),
        ("Claude Code Releases", "Release notes from anthropics/claude-code", False),
        ("Simon Willison", "Simon Willison's Weblog", False),
        ("AI", "Turkish photos", False),  # no word long enough to compare
        ("Some Blog", None, False),
    ],
)
def test_name_mismatch(proposed: str, title: str | None, expected: bool) -> None:
    assert name_mismatch(proposed, title) is expected


def test_candidates_sample_the_newest_items_and_count_recent_ones() -> None:
    old = entries(3, newest_days_ago=RECENT_WINDOW.days + 1)
    undated = (FeedEntry("https://x.example/u", "Undated", None, None, None),)
    items = (*old, *entries(SAMPLE_ITEMS + 2), *undated)

    candidate = to_candidate(
        proposal("https://x.example/"), feed("https://x.example/feed", items=items), NOW
    )

    assert len(candidate.sample) == SAMPLE_ITEMS
    assert candidate.sample[0].title == "Post 0"
    assert candidate.recent_count == SAMPLE_ITEMS
    assert candidate.latest == NOW - DAY


def test_inactive_feeds_have_no_recent_items() -> None:
    items = entries(4, newest_days_ago=RECENT_WINDOW.days + 1)

    candidate = to_candidate(
        proposal("https://x.example/"), feed("https://x.example/feed", items=items), NOW
    )

    assert candidate.recent_count == 0


@pytest.mark.parametrize(
    ("score", "status"),
    [
        (10, SourceStatus.ACTIVE),
        (7, SourceStatus.ACTIVE),
        (6.9, SourceStatus.PENDING),
        (4, SourceStatus.PENDING),
        (3.9, SourceStatus.REJECTED),
        (0, SourceStatus.REJECTED),
    ],
)
def test_status_for_score(score: float, status: SourceStatus) -> None:
    assert status_for(score) is status


def test_verdicts_are_matched_by_url_and_missing_ones_stay_pending() -> None:
    candidates = [
        to_candidate(proposal(f"https://{n}.example/"), feed(f"https://{n}.example/feed"), NOW)
        for n in range(5)
    ]
    answer = {
        "verdicts": [
            {"url": "https://0.example/feed", "score": 8, "reason": " Deep posts "},
            {"url": "https://1.example/feed", "score": 2, "reason": "Spam"},
            {"url": "https://2.example/feed", "score": True},
            {"url": "https://3.example/feed", "score": 11},
            {"url": "https://0.example/feed", "score": 1},  # a second verdict is ignored
            {"score": 9},
        ]
    }

    verdicts = parse_verdicts(answer, candidates)

    assert [(v.status, v.score, v.reason) for v in verdicts] == [
        (SourceStatus.ACTIVE, 8.0, "Deep posts"),
        (SourceStatus.REJECTED, 2.0, "Spam"),
        (SourceStatus.PENDING, None, "no usable verdict from the judge"),
        (SourceStatus.PENDING, None, "no usable verdict from the judge"),
        (SourceStatus.PENDING, None, "no usable verdict from the judge"),
    ]
    assert (
        parse_verdicts([{"url": "https://0.example/feed", "score": 5}], candidates[:1])[0].status
        is SourceStatus.PENDING
    )
    assert all(v.score is None for v in parse_verdicts("nonsense", candidates))


def test_judge_prompt_shows_what_the_feed_publishes() -> None:
    candidate = to_candidate(
        proposal("https://x.example/", "AI Engineer"),
        feed("https://x.example/feed", "Street photography"),
        NOW,
    )

    text = judge_prompt([candidate], [])

    assert "URL: https://x.example/feed" in text
    assert "Proposed as: AI Engineer" in text
    assert "Feed calls itself: Street photography (does NOT match" in text
    assert f"Items: 3, in the last {RECENT_WINDOW.days} days: 3, latest: 2026-10-17" in text
    assert "  - Post 0 (2026-10-17) | About 0" in text


# --- The pipeline --------------------------------------------------------------------------


class FakeSearch:
    name = "llm-online"

    def __init__(self, results: dict[str, list[SearchResult] | Exception]) -> None:
        self.results = results  # by a word of the query
        self.queries: list[str] = []

    def search(
        self, query: str, *, limit: int = 10, meter: UsageMeter | None = None
    ) -> list[SearchResult]:
        self.queries.append(query)
        for word, results in self.results.items():
            if word in query:
                if isinstance(results, Exception):
                    raise results
                return results
        return []


class FakeFinder:
    def __init__(self, feeds: dict[str, FoundFeed]) -> None:
        self.feeds = feeds

    def find(self, url: str) -> FoundFeed | None:
        return self.feeds.get(url)


class FakeJudge:
    def __init__(self, scores: dict[str, float] | Exception) -> None:
        self.scores = scores
        self.prompts: list[str] = []

    def complete_json(
        self, prompt: str, *, purpose: str, meter: UsageMeter | None = None
    ) -> tuple[Any, Completion]:
        self.prompts.append(prompt)
        if isinstance(self.scores, Exception):
            raise self.scores
        verdicts = [
            {"url": url, "score": score, "reason": f"judged {score}"}
            for url, score in self.scores.items()
            if f"URL: {url}\n" in prompt
        ]
        return {"verdicts": verdicts}, Completion("{}", CallUsage("m", purpose, 1, 1, None, 1))


def result(url: str, title: str = "") -> SearchResult:
    return SearchResult(url, title, "Found by search")


def setup(make: Factories) -> tuple[FakeSearch, FakeFinder]:
    make.interest("Rust", keywords=["cargo"])
    make.interest("Postgres")
    make.interest("Knitting", active=False)
    make.source(url="https://known.example/feed", site_url="https://known.example")
    make.source(url="https://rejected.example/feed", status=SourceStatus.REJECTED)
    search = FakeSearch(
        {
            "Rust": [
                result("https://great.example/", "Great Rust"),
                result("https://meh.example/", "Meh"),
                result("https://spam.example/", "Spam"),
                result("https://known.example/post"),  # a followed site
                result("https://stale.example/", "Stale"),
                result("https://nofeed.example/"),
            ],
            "Postgres": [
                result("https://great.example/other-post"),  # same site, other interest
                result("https://mirror.example/"),  # resolves to the rejected source's feed
                result("https://unjudged.example/", "Unjudged"),
            ],
        }
    )
    finder = FakeFinder(
        {
            "https://great.example/": feed("https://great.example/feed", "Great Rust"),
            "https://meh.example/": feed("https://meh.example/feed", "Meh"),
            "https://spam.example/": feed("https://spam.example/feed", "Spam"),
            "https://stale.example/": feed(
                "https://stale.example/feed", "Stale", entries(2, newest_days_ago=90)
            ),
            "https://mirror.example/": feed("https://rejected.example/feed", "Mirror"),
            "https://unjudged.example/": feed("https://unjudged.example/feed", "Unjudged"),
        }
    )
    return search, finder


SCORES = {
    "https://great.example/feed": 8.5,
    "https://meh.example/feed": 5,
    "https://spam.example/feed": 1,
}


def stored(session: Session, url: str) -> Source:
    return session.scalars(select(Source).where(Source.url == url)).one()


def test_discovery_stores_each_verdict(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    search, finder = setup(make)
    judge = FakeJudge(SCORES)
    run = context(sessions)

    discover_sources(run, search, finder, judge)

    assert len(search.queries) == 2
    great = stored(session, "https://great.example/feed")
    assert (great.status, great.origin, great.origin_detail) == (
        SourceStatus.ACTIVE,
        SourceOrigin.DISCOVERY,
        "llm-online: Rust",
    )
    assert great.note == "discovery judge 8.5/10: judged 8.5"
    assert stored(session, "https://meh.example/feed").status is SourceStatus.PENDING
    assert stored(session, "https://spam.example/feed").status is SourceStatus.REJECTED
    unjudged = stored(session, "https://unjudged.example/feed")
    assert unjudged.status is SourceStatus.PENDING
    assert unjudged.note == "discovery judge no score: no usable verdict from the judge"
    assert session.scalars(select(Source).where(Source.url.like("%stale%"))).all() == []
    assert "Knitting" not in search.queries[0] + search.queries[1]
    assert run.stats["proposed"] == 7
    assert run.stats["resolved"] == 5
    assert run.stats["inactive"] == ["https://stale.example/feed"]
    assert [entry["url"] for entry in run.stats["active"]] == ["https://great.example/feed"]
    assert run.stats["failed_searches"] == []
    assert {"search", "resolve", "judge"} <= run.timings.keys()


def test_a_failed_search_skips_only_its_interest(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    search, finder = setup(make)
    search.results["Postgres"] = WebSearchError("down")

    run = context(sessions)
    discover_sources(run, search, finder, FakeJudge(SCORES))

    assert run.stats["failed_searches"] == ["Postgres"]
    assert stored(session, "https://great.example/feed").status is SourceStatus.ACTIVE


def test_an_answer_that_is_not_json_leaves_everything_pending(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    search, finder = setup(make)

    discover_sources(context(sessions), search, finder, FakeJudge(InvalidJSONError("hmm")))

    assert stored(session, "https://great.example/feed").status is SourceStatus.PENDING
    assert stored(session, "https://spam.example/feed").status is SourceStatus.PENDING


def test_a_dry_run_judges_but_stores_nothing(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    search, finder = setup(make)
    judge = FakeJudge(SCORES)
    run = context(sessions, dry_run=True)

    discover_sources(run, search, finder, judge)

    assert judge.prompts
    assert [entry["url"] for entry in run.stats["active"]] == ["https://great.example/feed"]
    assert (
        session.scalars(select(Source).where(Source.origin == SourceOrigin.DISCOVERY)).all() == []
    )


def test_without_a_web_search_or_interests_discovery_is_skipped(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    with pytest.raises(SkipRunError, match="WEB_SEARCH"):
        discover_sources(context(sessions), None, FakeFinder({}), FakeJudge({}))
    with pytest.raises(SkipRunError, match="no active interests"):
        discover_sources(context(sessions), FakeSearch({}), FakeFinder({}), FakeJudge({}))


def test_changes_are_recorded_as_the_discovery_pipeline(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    search, finder = setup(make)
    discover_sources(context(sessions), search, finder, FakeJudge(SCORES))

    actions = {
        (c.actor, c.action) for c in ChangeRepository(session).find(limit=20) if c.actor == ACTOR
    }
    assert actions == {(ACTOR, "source.add"), (ACTOR, "source.propose"), (ACTOR, "source.reject")}
