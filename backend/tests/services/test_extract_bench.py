"""The extraction benchmark, with fake extractors and feeds."""

import random
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.extractors import Extracted, ExtractionError, ExtractionInput, Outcome
from brzask.clients.feeds import FeedEntry, FeedResult, FetchStatus
from brzask.services.extract_bench import (
    BenchAttempt,
    BenchItem,
    by_site,
    check_feed_threshold,
    load_sample,
    report,
    run_bench,
    sample_items,
    summarize,
    with_feed_content,
    words,
)
from tests.factories import Factories
from tests.services.digest.fakes import NOW, FakeFeeds

ARTICLE = "A real article paragraph. " * 40  # 160 words


@dataclass
class Fake:
    """Returns `texts[url]` (default: ARTICLE), None for a missing text, or raises."""

    name: str
    texts: dict[str, str | Exception | None] = field(default_factory=dict)
    fetches_page: bool = True
    calls: list[str] = field(default_factory=list)

    def extract(self, item: ExtractionInput) -> Extracted | None:
        self.calls.append(item.url)
        text = self.texts.get(item.url, ARTICLE)
        if isinstance(text, Exception):
            raise text
        return Extracted(text, tokens=7) if text is not None else None


def item(url: str, feed_content: str | None = None) -> BenchItem:
    host = url.split("/")[2]
    return BenchItem(url, host, f"https://{host}/feed", "Snippet", feed_content)


def test_words_leave_out_link_targets_and_images() -> None:
    text = (
        "Read [the post](https://a.example/x?y=1) ![chart](https://a.example/c.png) "
        "at https://b.example/z now"
    )

    assert words(text) == 5  # Read, the, post, at, now


def test_sample_spreads_over_sites(session: Session, make: Factories) -> None:
    source = make.source()
    articles = [make.article(source, link=f"https://a.example/{n}") for n in range(5)]
    articles += [make.article(source, link=f"https://b.example/{n}") for n in range(2)]
    articles.append(make.article(None, link="https://c.example/1"))  # no source

    items = sample_items(articles, size=10, per_host=2, rng=random.Random(1))

    assert sorted(i.host for i in items) == ["a.example", "a.example", "b.example", "b.example"]
    assert {i.source_url for i in items} == {source.url}
    assert len(sample_items(articles, size=3, per_host=2, rng=random.Random(1))) == 3


def test_sample_takes_links_first_seen_in_the_window(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    source = make.source()
    recent = make.article(source, first_seen_at=NOW - timedelta(days=1))
    make.article(source, first_seen_at=NOW - timedelta(days=20))

    items = load_sample(sessions, NOW - timedelta(days=10), size=10, per_host=5, seed=1)

    assert [i.url for i in items] == [recent.link]


def test_feed_content_is_fetched_again() -> None:
    feeds = FakeFeeds(
        {
            "https://a.example/feed": FeedResult(
                "https://a.example/feed",
                FetchStatus.OK,
                [FeedEntry("https://a.example/1", "T", None, "Full text", None)],
            )
        }
    )

    items = with_feed_content([item("https://a.example/1"), item("https://a.example/2")], feeds)

    assert [i.feed_content for i in items] == ["Full text", None]
    assert len(feeds.requests) == 1  # one fetch per source


def test_every_extractor_tries_every_item() -> None:
    items = [item("https://a.example/1"), item("https://a.example/2"), item("https://b.example/1")]
    good = Fake("good")
    bad = Fake(
        "bad",
        {
            "https://a.example/1": "short",
            "https://a.example/2": ExtractionError("HTTP 500"),
            "https://b.example/1": None,
        },
    )

    attempts = run_bench(items, [good, bad], robots=None, workers=2)

    assert sorted(good.calls) == sorted(bad.calls) == sorted(i.url for i in items)
    outcomes = {(a.extractor, a.url): a.outcome for a in attempts}
    assert outcomes[("bad", "https://a.example/1")] is Outcome.TOO_SHORT
    assert outcomes[("bad", "https://a.example/2")] is Outcome.FAILED
    assert outcomes[("bad", "https://b.example/1")] is Outcome.EMPTY
    assert all(outcomes[("good", i.url)] is Outcome.USABLE for i in items)


def test_a_paced_extractor_runs_one_call_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [item("https://a.example/1"), item("https://a.example/2")]
    slept: list[float] = []
    monkeypatch.setattr("brzask.services.extract_bench.time.sleep", slept.append)

    run_bench(items, [Fake("jina")], robots=None, intervals={"jina": 3.0})

    assert slept == [3.0]  # between the two calls, not before the first


def test_site_rules_and_robots_count_as_skipped() -> None:
    @dataclass
    class Deny:
        def allowed(self, url: str) -> bool:
            return False

    items = [item("https://www.reddit.com/r/x/1"), item("https://a.example/1")]

    attempts = run_bench(items, [Fake("trafilatura")], robots=Deny())

    assert {a.outcome for a in attempts} == {Outcome.SKIPPED_RULE, Outcome.SKIPPED_ROBOTS}
    (row,) = summarize(attempts)
    assert (row.tried, row.skipped) == (0, 2)
    assert by_site(attempts) == {}


def attempt(
    extractor: str, url: str, outcome: Outcome = Outcome.USABLE, **fields: Any
) -> BenchAttempt:
    return BenchAttempt(url, url.split("/")[2], extractor, outcome, **fields)


def test_summary_per_extractor() -> None:
    attempts = [
        attempt("trafilatura", "https://a.example/1", chars=1000, words=100, duration_ms=100),
        attempt("trafilatura", "https://a.example/2", chars=300, words=40, duration_ms=300),
        attempt("trafilatura", "https://b.example/1", Outcome.BLOCKED, chars=250, duration_ms=50),
        attempt("jina", "https://a.example/1", chars=5000, words=110, duration_ms=2000, tokens=900),
        attempt("jina", "https://a.example/2", chars=4000, words=100, duration_ms=4000, tokens=800),
        attempt("jina", "https://b.example/1", chars=3000, words=300, block_phrase=True, tokens=5),
        attempt("jina", "https://c.example/1", Outcome.SKIPPED_ROBOTS),
    ]

    trafilatura, jina = summarize(attempts)

    assert (trafilatura.tried, trafilatura.usable, trafilatura.blocked) == (3, 2, 1)
    assert (trafilatura.median_chars, trafilatura.median_words) == (650, 70)
    assert (trafilatura.median_ms, trafilatura.p90_ms) == (100, 300)
    assert trafilatura.shorter_than_best == 1  # 40 words against jina's 100
    assert trafilatura.only_usable == 0
    assert (jina.tried, jina.usable, jina.skipped, jina.tokens) == (3, 3, 1, 1705)
    assert (jina.only_usable, jina.long_with_block_phrase) == (1, 1)
    assert by_site(attempts) == {
        "a.example": {"trafilatura": (2, 2), "jina": (2, 2)},
        "b.example": {"trafilatura": (0, 1), "jina": (1, 1)},
    }


def test_feed_threshold_check() -> None:
    full, teaser = "word " * 400, "word " * 50  # 1999 and 249 characters, stripped
    items = [
        item("https://a.example/1", full),  # accepted, page as long: right
        item("https://a.example/2", full),  # accepted, page far longer: a teaser let through
        item("https://a.example/3", teaser),  # rejected, page far longer: right
        item("https://a.example/4", teaser),  # rejected, page as long: full text thrown away
        item("https://a.example/5", teaser),  # no usable page: not compared
        item("https://a.example/6"),  # no feed content
    ]
    attempts = [
        attempt("trafilatura", "https://a.example/1", words=420),
        attempt("trafilatura", "https://a.example/2", words=2000),
        attempt("trafilatura", "https://a.example/3", words=900),
        attempt("trafilatura", "https://a.example/4", words=55),
        attempt("trafilatura", "https://a.example/5", Outcome.FAILED),
        attempt("feed", "https://a.example/3", words=5000),  # the feed is not a page
        attempt("jina", "https://a.example/1", words=3000),  # not the first usable page text
    ]

    check = check_feed_threshold(items, attempts, min_chars=1500)

    assert (check.with_content, check.compared) == (5, 4)
    assert (check.accepted_full, check.accepted_teaser) == (1, 1)
    assert (check.rejected_teaser, check.rejected_full) == (1, 1)
    assert check.pairs == [
        ("https://a.example/1", 1999, 400, 420),
        ("https://a.example/2", 1999, 400, 2000),
        ("https://a.example/3", 249, 50, 900),
        ("https://a.example/4", 249, 50, 55),
    ]


def test_report_is_plain_data() -> None:
    items = [item("https://a.example/1")]
    attempts = [attempt("trafilatura", "https://a.example/1", words=10)]

    data = report(items, attempts, check_feed_threshold(items, attempts, 1500))

    assert (data["items"], data["sites"]) == (1, 1)
    assert data["extractors"][0]["extractor"] == "trafilatura"
    assert data["attempts"][0]["outcome"] == "usable"
    assert data["sites_by_extractor"] == {"a.example": {"trafilatura": {"usable": 1, "tried": 1}}}
