import pytest

from brzask.urls import feed_key, host_matches, host_of, is_http_url, item_key


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://www.Example.com/a", "example.com"),
        ("  http://old.reddit.com/r/x ", "old.reddit.com"),
        ("not a url", ""),
        ("https://[::1/broken", ""),
    ],
)
def test_host_of(url: str, host: str) -> None:
    assert host_of(url) == host


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/post", True),
        ("http://example.com", True),
        ("mailto:someone@example.com", False),
        ("https:///no-host", False),
        ("http://[oops/post", False),
        ("/relative", False),
    ],
)
def test_is_http_url(url: str, expected: bool) -> None:
    assert is_http_url(url) is expected


def test_host_matches_the_domain_and_its_subdomains() -> None:
    assert host_matches("reddit.com", "reddit.com")
    assert host_matches("old.reddit.com", "reddit.com")
    assert not host_matches("notreddit.com", "reddit.com")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            "https://github.com/NousResearch/hermes-agent/releases.atom",
            "https://github.com/nousresearch/hermes-agent/releases.atom",
        ),
        ("https://www.reddit.com/r/LocalLLaMA/.rss", "https://www.reddit.com/r/localllama/.rss"),
        ("HTTPS://Example.COM/feed", "https://example.com/feed"),
        (" https://example.com/feed ", "https://example.com/feed"),
    ],
)
def test_feed_keys_ignore_case_that_does_not_matter(first: str, second: str) -> None:
    assert feed_key(first) == feed_key(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCabc",
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCABC",
        ),
        ("https://example.com/Feed", "https://example.com/feed"),
        ("https://github.com/a/b/releases.atom?x=Y", "https://github.com/a/b/releases.atom?x=y"),
    ],
)
def test_feed_keys_keep_case_that_matters(first: str, second: str) -> None:
    assert feed_key(first) != feed_key(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # a mirror of release notes, tagged without the "v"
        (
            "https://github.com/anthropics/claude-code/releases/tag/v2.1.316",
            "https://github.com/someone/claude-code-update/releases/tag/2.1.316",
        ),
        # a fork's copy of a tag
        (
            "https://github.com/omacom/omarchy/releases/tag/v4.0.4",
            "https://github.com/someone/omarchy/releases/tag/V4.0.4/",
        ),
        # one blog under two feed URLs
        ("https://www.latent.space/p/claude-mods", "https://latent.space/p/claude-mods/"),
        ("http://example.com/a?id=1", "https://example.com/a?id=1"),
    ],
)
def test_item_keys_match_one_item_under_two_links(first: str, second: str) -> None:
    assert item_key(first) == item_key(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://example.com/a?id=1", "https://example.com/a?id=2"),
        ("https://example.com/a", "https://other.example/a"),
        # a tag page that is not a release of one repository
        ("https://github.com/a/b/releases/tag/v1/notes", "https://github.com/c/d/releases/tag/v1"),
    ],
)
def test_item_keys_tell_items_apart(first: str, second: str) -> None:
    assert item_key(first) != item_key(second)


def test_an_item_key_of_a_malformed_link_is_the_link() -> None:
    assert item_key(" http://[oops ") == "http://[oops"
