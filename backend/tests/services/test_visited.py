from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.feed_finder import FoundFeed
from brzask.db.models import Article, ChangeStatus, Source, SourceOrigin, SourceStatus
from brzask.repositories import ChangeRepository
from brzask.services.visited import (
    ACTOR,
    known_hosts,
    known_sites,
    new_hosts,
    propose_visited,
    related,
    site_of,
)
from tests.factories import Factories
from tests.services.digest.fakes import NOW, context


def opened(*links: str) -> list[Article]:
    return [Article(link=link, title=f"Title {n}") for n, link in enumerate(links)]


@pytest.mark.parametrize(
    ("host", "known", "expected"),
    [
        ("example.com", "example.com", True),
        ("blog.example.com", "example.com", True),
        ("example.com", "blog.example.com", True),
        ("notexample.com", "example.com", False),
        ("example.com.evil.net", "example.com", False),
    ],
)
def test_related_hosts(host: str, known: str, expected: bool) -> None:
    assert related(host, known) is expected


def test_known_hosts_drop_www_and_empty_values() -> None:
    assert known_hosts(["https://www.example.com/feed", None, "not a url", "http://b.org"]) == {
        "example.com",
        "b.org",
    }


def test_new_hosts_keep_one_entry_per_unknown_host_newest_first() -> None:
    articles = opened(
        "https://www.newsite.dev/latest",
        "https://newsite.dev/older",
        "https://lobste.rs/s/abc",
        "https://docs.known.org/page",
        "http://[broken",
        "https://other.net/x",
    )

    found = new_hosts(articles, {"lobste.rs", "known.org", ""})

    assert [(h.host, h.link, h.title) for h in found] == [
        ("newsite.dev", "https://www.newsite.dev/latest", "Title 0"),
        ("other.net", "https://other.net/x", "Title 5"),
    ]


@pytest.mark.parametrize(
    ("url", "site"),
    [
        ("https://www.example.com/post?id=1", "example.com"),
        ("https://github.com/owner/repo/releases/tag/v1", "github.com/owner/repo"),
        ("https://github.com/owner/repo/releases.atom", "github.com/owner/repo"),
        ("https://www.youtube.com/watch?v=abc", "youtube.com/watch?v=abc"),
        ("https://youtu.be/abc", "youtu.be/abc"),
        ("http://[broken", ""),
    ],
)
def test_site_of(url: str, site: str) -> None:
    assert site_of(url) == site


def test_new_hosts_tell_github_repositories_and_youtube_videos_apart() -> None:
    sources = ["https://github.com/known/repo/releases.atom", "https://youtube.com/feeds/x"]
    articles = opened(
        "https://github.com/known/repo/issues/1",
        "https://github.com/other/tool",
        "https://github.com/other/tool/releases",
        "https://www.youtube.com/watch?v=one",
        "https://www.youtube.com/watch?v=two",
    )

    found = new_hosts(articles, known_sites(sources))

    assert [h.host for h in found] == [
        "github.com/other/tool",
        "youtube.com/watch?v=one",
        "youtube.com/watch?v=two",
    ]


def test_new_hosts_skip_links_to_the_site_of_their_own_source() -> None:
    channel = Source(url="https://www.youtube.com/feeds/videos.xml?channel_id=UC1")
    aggregator = Source(url="https://news.ycombinator.com/rss")
    own = Article(link="https://www.youtube.com/watch?v=own", title="Own", source=channel)
    linked = Article(link="https://youtube.com/watch?v=hn", title="Linked", source=aggregator)

    found = new_hosts([own, linked], known_sites([channel.url, aggregator.url]))

    assert [h.link for h in found] == ["https://youtube.com/watch?v=hn"]


class FakeFinder:
    def __init__(self, feeds: dict[str, FoundFeed]) -> None:
        self.feeds = feeds
        self.asked: list[str] = []

    def find(self, url: str) -> FoundFeed | None:
        self.asked.append(url)
        return self.feeds.get(url)


def test_propose_visited_adds_pending_sources_for_new_sites(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    aggregator = make.source(url="https://lobste.rs/rss", site_url="https://lobste.rs")
    make.source(url="https://feeds.example/blog", site_url="https://blog.known.org")
    make.source(url="https://gone.example/feed.xml", status=SourceStatus.REJECTED)
    make.article(aggregator, link="https://lobste.rs/s/1", opened_at=NOW - timedelta(days=1))
    make.article(aggregator, link="https://known.org/post", opened_at=NOW - timedelta(days=2))
    make.article(
        link="https://newsite.dev/a", title="A good post", opened_at=NOW - timedelta(days=3)
    )
    make.article(link="https://nofeed.net/a", opened_at=NOW - timedelta(days=4))
    make.article(link="https://rejected.net/a", opened_at=NOW - timedelta(days=5))
    make.article(link="https://too-old.net/a", opened_at=NOW - timedelta(days=31))
    make.article(link="https://unopened.net/a")
    finder = FakeFinder(
        {
            "https://newsite.dev/a": FoundFeed(
                "https://newsite.dev/feed", "New Site", "https://newsite.dev"
            ),
            # Found, but the URL is a known (rejected) source.
            "https://rejected.net/a": FoundFeed(
                "https://gone.example/feed.xml", "Gone", "https://rejected.net"
            ),
        }
    )
    run = context(sessions)

    propose_visited(run, finder)

    assert finder.asked == [
        "https://newsite.dev/a",
        "https://nofeed.net/a",
        "https://rejected.net/a",
    ]
    added = session.scalars(select(Source).where(Source.url == "https://newsite.dev/feed")).one()
    assert (added.name, added.status, added.origin) == (
        "New Site",
        SourceStatus.PENDING,
        SourceOrigin.VISITED,
    )
    assert (added.site_url, added.origin_detail) == ("https://newsite.dev", "https://newsite.dev/a")
    assert added.note == 'You opened "A good post" from this site; it is not a source yet.'
    (change,) = ChangeRepository(session).find(
        limit=5, entity_type="source", entity_id=str(added.id)
    )
    assert (change.actor, change.action, change.status) == (
        ACTOR,
        "source.propose",
        ChangeStatus.APPLIED,
    )
    assert run.stats == {
        "opened": 5,
        "new_hosts": ["newsite.dev", "nofeed.net", "rejected.net"],
        "proposed": [
            {"host": "newsite.dev", "url": "https://newsite.dev/feed", "name": "New Site"}
        ],
        "without_feed": ["nofeed.net"],
    }


def test_a_dry_run_proposes_without_writing(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    make.article(link="https://newsite.dev/a", opened_at=NOW - timedelta(days=1))
    finder = FakeFinder(
        {
            "https://newsite.dev/a": FoundFeed(
                "https://newsite.dev/feed", None, "https://newsite.dev"
            )
        }
    )
    run = context(sessions, dry_run=True)

    propose_visited(run, finder)

    assert run.stats["proposed"] == [{"host": "newsite.dev", "url": "https://newsite.dev/feed"}]
    assert session.scalars(select(Source)).all() == []


def test_two_videos_of_one_channel_propose_it_once(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    make.article(link="https://youtube.com/watch?v=1", opened_at=NOW - timedelta(days=1))
    make.article(link="https://youtube.com/watch?v=2", opened_at=NOW - timedelta(days=2))
    channel = FoundFeed(
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC1", "Channel", "https://youtube.com"
    )
    finder = FakeFinder(
        {"https://youtube.com/watch?v=1": channel, "https://youtube.com/watch?v=2": channel}
    )
    run = context(sessions, dry_run=True)

    propose_visited(run, finder)

    assert run.stats["proposed"] == [{"host": "youtube.com/watch?v=1", "url": channel.url}]
