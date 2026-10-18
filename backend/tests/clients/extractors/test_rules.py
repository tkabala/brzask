import pytest

from brzask.clients.extractors.rules import FEED_ONLY, rule_for
from brzask.urls import host_matches, host_of


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://www.Reddit.com/r/x/comments/1", "reddit.com"),
        ("https://old.reddit.com/r/x", "old.reddit.com"),
        ("http://example.com:8080/a", "example.com"),
        ("not a url", ""),
    ],
)
def test_host_of(url: str, host: str) -> None:
    assert host_of(url) == host


def test_host_matches_domain_and_subdomains_only() -> None:
    assert host_matches("reddit.com", "reddit.com")
    assert host_matches("old.reddit.com", "reddit.com")
    assert not host_matches("notreddit.com", "reddit.com")
    assert not host_matches("reddit.com.evil.example", "reddit.com")


@pytest.mark.parametrize(
    "host", ["reddit.com", "old.reddit.com", "youtube.com", "m.youtube.com", "youtu.be"]
)
def test_feed_only_sites(host: str) -> None:
    rule = rule_for(host)

    assert rule is not None
    assert rule.only == FEED_ONLY


def test_other_sites_have_no_rule() -> None:
    assert rule_for("blog.example.com") is None
