import pytest

from brzask.clients.extractors import unusable_reason
from brzask.clients.extractors.base import MIN_CHARS

ARTICLE = "Postgres 18 brings asynchronous I/O. " * 10


def test_long_text_is_usable() -> None:
    assert unusable_reason(ARTICLE) is None


@pytest.mark.parametrize("text", [None, "", "   ", "x" * (MIN_CHARS - 1), " " * 50 + "x" * 150])
def test_short_text_is_not(text: str | None) -> None:
    assert unusable_reason(text) == "too_short"


def test_exactly_the_minimum_is_usable() -> None:
    assert unusable_reason("x" * MIN_CHARS) is None


@pytest.mark.parametrize(
    "page",
    [
        "You've been blocked by network security. To continue, log in to your Reddit account.",
        "Access Denied. You don't have permission to access this server.",
        "Are you a human? Please complete the check below.",
        "Please enable JavaScript and cookies to continue.",
        "Complete the CAPTCHA to proceed.",
    ],
)
def test_block_pages_are_not_usable(page: str) -> None:
    assert unusable_reason(page + " " + "padding " * 40) == "blocked"
