from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.feed_finder import FoundFeed
from brzask.clients.feeds import FeedEntry
from brzask.clients.judge import JudgeError, Judgement, ScoreAnswer, Text
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.clients.web_search import SearchResult, WebSearchError
from brzask.db.models import Source, SourceOrigin, SourceStatus
from brzask.repositories import ChangeRepository
from brzask.services import discovery
from brzask.services.discovery import (
    ACTOR,
    RECENT_WINDOW,
    SAMPLE_ITEMS,
    Proposal,
    discover_sources,
    judge_feed,
    judge_state,
    name_mismatch,
    run_discovery,
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


def test_a_feed_that_dates_nothing_has_unknown_activity_and_an_empty_one_none() -> None:
    undated = tuple(
        FeedEntry(f"https://x.example/{n}", f"Post {n}", None, None, None) for n in range(3)
    )
    empty = FoundFeed("https://y.example/feed", "Empty", "https://y.example", ())

    candidate = to_candidate(
        proposal("https://x.example/"), feed("https://x.example/feed", items=undated), NOW
    )

    assert candidate.recent_count is None
    assert to_candidate(proposal("https://y.example/"), empty, NOW).recent_count == 0


@pytest.mark.parametrize(
    ("fit", "substance", "status"),
    [
        (3, 2, SourceStatus.ACTIVE),
        (2, 1.5, SourceStatus.ACTIVE),
        (1.99, 2, SourceStatus.PENDING),
        (3, 1.49, SourceStatus.PENDING),
        (3, 0, SourceStatus.PENDING),  # relevant, but a person decides about the noise
        (1, 0, SourceStatus.PENDING),
        (0.99, 2, SourceStatus.REJECTED),
    ],
)
def test_status_for_scores(fit: float, substance: float, status: SourceStatus) -> None:
    assert status_for(fit, substance) is status


def test_the_judge_reads_what_the_feed_publishes() -> None:
    candidate = to_candidate(
        proposal("https://x.example/", "AI Engineer"),
        feed("https://x.example/feed", "Street photography"),
        NOW,
    )
    interests = [{"topic": "Rust", "keywords": [], "notes": "skip: crypto"}]

    state = judge_state(candidate, interests)

    assert state["reader"] == {"interests": interests}
    assert state["feed"] == {
        "url": "https://x.example/feed",
        "title": "Street photography",
        "proposed_as": "AI Engineer",
        "title_differs_from_proposed_name": True,
        "suggested_because": None,
        "items": 3,
        f"items_in_last_{RECENT_WINDOW.days}_days": 3,
        "latest": "2026-10-17",
        "recent_items": [
            {"title": f"Post {n}", "date": f"2026-10-{17 - n}", "summary": f"About {n}"}
            for n in range(3)
        ],
    }


def test_a_verdict_names_the_scores_and_a_failed_judge_leaves_the_feed_pending() -> None:
    candidate = to_candidate(proposal("https://x.example/"), feed("https://x.example/feed"), NOW)

    verdict = judge_feed(candidate, FakeJudge({"https://x.example/feed": (2.5, 1.75)}), [])
    unjudged = judge_feed(candidate, FakeJudge({}), [])

    assert (verdict.status, verdict.scores, verdict.reason) == (
        SourceStatus.ACTIVE,
        {"interest_fit": 2.5, "substance": 1.75},
        "interest fit 2.5/3, substance 1.75/2",
    )
    assert (unjudged.status, unjudged.scores) == (SourceStatus.PENDING, None)


# --- The pipeline --------------------------------------------------------------------------


class FakeSearch:
    name = "llm-online"

    def __init__(self, results: dict[str, list[SearchResult] | Exception]) -> None:
        self.results = results  # by a word of the query
        self.queries: list[str] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

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
    """Scores feeds by URL as (interest fit, substance); unlisted feeds fail."""

    model = "test/judge"

    def __init__(self, scores: dict[str, tuple[float, float]]) -> None:
        self.scores = scores
        self.states: list[Any] = []

    def ask(
        self,
        state: Text,
        questions: Any,
        *,
        purpose: str,
        meter: UsageMeter | None = None,
    ) -> Judgement:
        assert isinstance(state, dict)
        self.states.append(state)
        url = state["feed"]["url"]
        if url not in self.scores:
            raise JudgeError(f"{purpose}: no answer for {url}")
        values = dict(zip(questions, self.scores[url], strict=True))
        answers = {name: ScoreAnswer(value, (1.0,), 1.0) for name, value in values.items()}
        return Judgement(answers, CallUsage(self.model, purpose, 1, 0, None, 1))

    def close(self) -> None:
        pass


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
                result("https://mirror.example/"),  # the rejected source's feed, in another case
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
            "https://mirror.example/": feed("HTTPS://Rejected.example/feed", "Mirror"),
            "https://unjudged.example/": feed("https://unjudged.example/feed", "Unjudged"),
        }
    )
    return search, finder


SCORES = {
    "https://great.example/feed": (2.5, 2.0),
    "https://meh.example/feed": (1.5, 1.0),
    "https://spam.example/feed": (0.2, 0.1),
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
    assert great.note == "discovery judge: interest fit 2.5/3, substance 2/2"
    assert stored(session, "https://meh.example/feed").status is SourceStatus.PENDING
    assert stored(session, "https://spam.example/feed").status is SourceStatus.REJECTED
    unjudged = stored(session, "https://unjudged.example/feed")
    assert unjudged.status is SourceStatus.PENDING
    assert unjudged.note == "discovery judge: no usable verdict from the judge"
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


def test_a_judge_that_answers_nothing_fails_the_run_and_stores_nothing(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    search, finder = setup(make)

    with pytest.raises(JudgeError, match="no verdict"):
        discover_sources(context(sessions), search, finder, FakeJudge({}))

    assert (
        session.scalars(select(Source).where(Source.origin == SourceOrigin.DISCOVERY)).all() == []
    )


def test_a_dry_run_judges_but_stores_nothing(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    search, finder = setup(make)
    judge = FakeJudge(SCORES)
    run = context(sessions, dry_run=True)

    discover_sources(run, search, finder, judge)

    assert judge.states
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


def test_run_discovery_closes_the_web_search_when_the_run_fails(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    search = FakeSearch({})
    monkeypatch.setattr(discovery, "build_web_search", lambda settings: search)

    def fail(*args: Any) -> None:
        raise RuntimeError("judge down")

    monkeypatch.setattr(discovery, "discover_sources", fail)

    with pytest.raises(RuntimeError, match="judge down"):
        run_discovery(context(sessions))

    assert search.closed
