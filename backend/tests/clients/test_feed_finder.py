from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest

from brzask.clients.feed_finder import (
    FeedFinder,
    alternate_feeds,
    common_feed_urls,
    youtube_channel_id,
)
from brzask.clients.feeds import FeedFetcher

FEEDS = Path(__file__).parent.parent / "fixtures" / "feeds"
RSS = (FEEDS / "rss2.xml").read_bytes()
ATOM = (FEEDS / "atom.xml").read_bytes()
CHANNEL_ID = "UC" + "a1B2c3D4e5F6g7H8i9J0k-"  # 24 characters, like a real channel ID


def feed(body: bytes = RSS) -> httpx2.Response:
    return httpx2.Response(200, content=body, headers={"Content-Type": "application/xml"})


def page(html: str) -> httpx2.Response:
    return httpx2.Response(200, text=html, headers={"Content-Type": "text/html; charset=utf-8"})


class Web:
    """A fake web: full URL -> response; anything else is a 404. Records requested URLs."""

    def __init__(self, routes: dict[str, httpx2.Response]) -> None:
        self.routes = routes
        self.requested: list[str] = []
        self.headers: dict[str, httpx2.Headers] = {}

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        self.requested.append(url)
        self.headers[url] = request.headers
        return self.routes.get(url, httpx2.Response(404))

    def finder(self) -> FeedFinder:
        fetcher = FeedFetcher(now=lambda: datetime(2026, 10, 18, tzinfo=UTC))
        fetcher.client = httpx2.Client(
            transport=httpx2.MockTransport(self.handle), follow_redirects=True
        )
        return FeedFinder(fetcher)


BLOG = """<!doctype html><html><head>
<link rel="alternate" type="application/rss+xml"
      title="Example &raquo; Comments Feed" href="/comments/feed/">
<link rel="alternate" type="application/rss+xml" title="Example &raquo; Feed" href="/feed/">
<link rel="stylesheet" href="/style.css">
</head><body>Hello</body></html>"""


# --- Pure helpers --------------------------------------------------------------


def test_alternate_feeds_resolve_and_put_comment_feeds_last() -> None:
    assert alternate_feeds(BLOG, "https://blog.example.com/2026/10/post") == [
        "https://blog.example.com/feed/",
        "https://blog.example.com/comments/feed/",
    ]


def test_alternate_feeds_ignore_other_links() -> None:
    html = """<link rel="alternate" hreflang="de" href="/de/">
    <link rel="alternate" type="application/json" href="/feed.json">
    <LINK REL="Alternate" TYPE="application/atom+xml; charset=utf-8" HREF="atom.xml">
    <link rel="alternate" type="application/rss+xml" href="javascript:void(0)">
    <link rel="alternate" type="application/rss+xml" href="http://[oops/feed">"""

    assert alternate_feeds(html, "https://site.example/blog/") == [
        "https://site.example/blog/atom.xml"
    ]


def test_common_feed_urls_try_the_page_directory_then_the_root() -> None:
    urls = common_feed_urls("https://site.example/blog/post-1?ref=x")

    assert urls[:2] == ["https://site.example/blog/feed", "https://site.example/blog/rss.xml"]
    assert "https://site.example/index.xml" in urls
    assert len(urls) == 10
    assert common_feed_urls("https://site.example/")[0] == "https://site.example/feed"
    assert len(common_feed_urls("https://site.example/")) == 5


OTHER_CHANNEL = "UC" + "z" * 22


def test_the_channel_owner_wins_over_recommended_channels() -> None:
    channel_page = (
        f'{{"channelId":"{OTHER_CHANNEL}"}} ... '
        f'<link rel="canonical" href="https://www.youtube.com/channel/{CHANNEL_ID}">'
    )
    assert youtube_channel_id(channel_page) == CHANNEL_ID
    data = f'"channelId":"{OTHER_CHANNEL}","externalId":"{CHANNEL_ID}"'
    assert youtube_channel_id(data) == CHANNEL_ID
    video = f'"channelId":"{OTHER_CHANNEL}"<meta itemprop="channelId" content="{CHANNEL_ID}">'
    assert youtube_channel_id(video) == CHANNEL_ID


def test_youtube_channel_id_from_a_page() -> None:
    assert youtube_channel_id(f'..."channelId":"{CHANNEL_ID}",...') == CHANNEL_ID
    canonical = f'<link rel="canonical" href="https://www.youtube.com/channel/{CHANNEL_ID}">'
    assert youtube_channel_id(canonical) == CHANNEL_ID
    assert youtube_channel_id("<html>consent page</html>") is None


# --- Sites ---------------------------------------------------------------------


def test_a_feed_url_is_returned_as_it_is() -> None:
    web = Web({"https://blog.example.com/feed.xml": feed()})

    found = web.finder().find("https://blog.example.com/feed.xml")

    assert found is not None
    assert (found.url, found.title, found.site_url) == (
        "https://blog.example.com/feed.xml",
        "Example & Co. Blog",
        "https://blog.example.com/",
    )


def test_alternate_link_on_the_page() -> None:
    web = Web(
        {
            "https://blog.example.com/2026/10/post": page(BLOG),
            "https://blog.example.com/feed/": feed(),
        }
    )

    found = web.finder().find("blog.example.com/2026/10/post")  # no scheme: https assumed

    assert found is not None
    assert found.url == "https://blog.example.com/feed/"
    assert "https://blog.example.com/comments/feed/" not in web.requested


def test_a_broken_alternate_falls_back_to_the_next_one() -> None:
    html = BLOG.replace("/comments/feed/", "/feed-v2/").replace("Comments Feed", "Feed v2")
    web = Web(
        {
            "https://blog.example.com/": page(html),
            "https://blog.example.com/feed/": page("<html>moved</html>"),
            "https://blog.example.com/feed-v2/": feed(ATOM),
        }
    )

    found = web.finder().find("https://blog.example.com/")

    assert found is not None
    assert found.url == "https://blog.example.com/feed-v2/"


@pytest.mark.parametrize(
    "feed_url",
    [
        "https://site.example/feed",
        "https://site.example/rss.xml",
        "https://site.example/atom.xml",
        "https://site.example/index.xml",
        "https://site.example/feed.xml",
    ],
)
def test_common_paths_at_the_root(feed_url: str) -> None:
    web = Web({"https://site.example/": page("<html>no links</html>"), feed_url: feed()})

    found = web.finder().find("https://site.example/")

    assert found is not None
    assert found.url == feed_url


def test_common_paths_under_the_page_directory_first() -> None:
    web = Web(
        {
            "https://site.example/blog/": page("<html>no links</html>"),
            "https://site.example/blog/index.xml": feed(),
            "https://site.example/feed": feed(ATOM),
        }
    )

    found = web.finder().find("https://site.example/blog/")

    assert found is not None
    assert found.url == "https://site.example/blog/index.xml"


COMMENTS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Komentarze do: Post</title>
<item><title>By Ann</title><link>https://site.example/blog/post/#comment-2</link></item>
<item><title>By Bob</title><link>https://site.example/blog/post/#comment-1</link></item>
</channel></rss>"""


def test_a_feed_of_comments_on_one_post_is_not_the_sites_feed() -> None:
    web = Web(
        {
            "https://site.example/blog/post/": page("<html>no links</html>"),
            "https://site.example/blog/post/feed": feed(COMMENTS),
            "https://site.example/feed": feed(ATOM),
        }
    )

    found = web.finder().find("https://site.example/blog/post/")

    assert found is not None
    assert found.url == "https://site.example/feed"
    assert found.entries


def test_redirects_are_followed_before_looking_for_feeds() -> None:
    web = Web(
        {
            "https://old.example/": httpx2.Response(
                301, headers={"Location": "https://new.example/"}
            ),
            "https://new.example/": page(
                '<link rel="alternate" type="application/atom+xml" href="/atom">'
            ),
            "https://new.example/atom": feed(ATOM),
        }
    )

    found = web.finder().find("https://old.example/")

    assert found is not None
    assert (found.url, found.site_url) == ("https://new.example/atom", "https://new.example/")


def test_no_feed_anywhere() -> None:
    web = Web({"https://site.example/": page("<html>nothing</html>")})

    assert web.finder().find("https://site.example/") is None


def test_unreachable_site_still_tries_the_common_paths() -> None:
    web = Web({"https://site.example/rss.xml": feed()})

    found = web.finder().find("https://site.example/")

    assert found is not None
    assert found.url == "https://site.example/rss.xml"


@pytest.mark.parametrize("url", ["   ", "https://[::1/blog"])
def test_not_a_url(url: str) -> None:
    assert Web({}).finder().find(url) is None


# --- GitHub --------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/astral-sh/uv",
        "https://github.com/astral-sh/uv/",
        "https://github.com/astral-sh/uv.git",
        "https://github.com/astral-sh/uv/releases",
        "https://github.com/astral-sh/uv/issues/123",
        "github.com/astral-sh/uv",
        "https://github.com/astral-sh/uv/releases.atom",
    ],
)
def test_github_repositories_resolve_to_release_notes(url: str) -> None:
    web = Web({"https://github.com/astral-sh/uv/releases.atom": feed(ATOM)})

    found = web.finder().find(url)

    assert found is not None
    assert found.url == "https://github.com/astral-sh/uv/releases.atom"
    assert found.site_url == "https://github.com/astral-sh/uv"
    assert web.requested == ["https://github.com/astral-sh/uv/releases.atom"]  # no HTML fetched


@pytest.mark.parametrize(
    "url", ["https://github.com/astral-sh", "https://github.com/topics/rust", "https://github.com/"]
)
def test_github_pages_that_are_not_repositories(url: str) -> None:
    web = Web({})

    assert web.finder().find(url) is None
    assert web.requested == []


def test_github_subdomains_are_ordinary_sites() -> None:
    web = Web(
        {"https://gist.github.com/someone": page(BLOG), "https://gist.github.com/feed/": feed()}
    )

    found = web.finder().find("https://gist.github.com/someone")

    assert found is not None
    assert found.url == "https://gist.github.com/feed/"


def test_a_missing_repository() -> None:
    assert Web({}).finder().find("https://github.com/nobody/nothing") is None


# --- YouTube -------------------------------------------------------------------

YOUTUBE_FEED = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"


def test_youtube_channel_url_needs_no_page() -> None:
    web = Web({YOUTUBE_FEED: feed(ATOM)})

    found = web.finder().find(f"https://www.youtube.com/channel/{CHANNEL_ID}/videos")

    assert found is not None
    assert found.url == YOUTUBE_FEED
    assert found.site_url == f"https://www.youtube.com/channel/{CHANNEL_ID}"
    assert web.requested == [YOUTUBE_FEED]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/@example",
        "https://m.youtube.com/c/Example",
        "https://www.youtube.com/user/example",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_youtube_handles_and_videos_read_the_channel_id(url: str) -> None:
    html = f'<html><script>var data = {{"channelId":"{CHANNEL_ID}"}};</script></html>'
    web = Web({url: page(html), YOUTUBE_FEED: feed(ATOM)})

    found = web.finder().find(url)

    assert found is not None
    assert found.url == YOUTUBE_FEED
    assert web.headers[url]["Cookie"] == "SOCS=CAI"


def test_youtube_consent_page_without_an_id() -> None:
    url = "https://www.youtube.com/@example"

    assert (
        Web({url: page("<html>Before you continue to YouTube</html>")}).finder().find(url) is None
    )


def test_youtube_feed_url_is_checked_and_kept() -> None:
    web = Web({YOUTUBE_FEED: feed(ATOM)})

    found = web.finder().find(YOUTUBE_FEED)

    assert found is not None
    assert found.url == YOUTUBE_FEED
