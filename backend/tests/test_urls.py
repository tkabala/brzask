import pytest

from brzask.urls import host_matches, host_of, is_http_url


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
