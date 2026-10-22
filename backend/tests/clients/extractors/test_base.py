import pytest

from brzask.clients.extractors import unusable_reason
from brzask.clients.extractors.base import MIN_CHARS, from_headline

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
        "JavaScript is disabled\nIn order to continue, we need to verify that you're not a robot.",
    ],
)
def test_block_pages_are_not_usable(page: str) -> None:
    assert unusable_reason(page + " " + "padding " * 40) == "blocked"


def test_long_articles_mentioning_block_phrases_stay_usable() -> None:
    article = "How CAPTCHA solvers work and why access denied errors confuse users. " * 40

    assert unusable_reason(article) is None


# Site chrome a reader renders before the article, as on InfoQ.
CHROME = "## Software Architects' Newsletter\n\nEnter your e-mail address\n\n[Login](/login)\n\n"
TITLE = "Buildkite Adds Scoped Secrets and New Agentic CI Tools"


def test_the_text_starts_at_the_headline() -> None:
    text = f"{CHROME}# {TITLE}\n\n{ARTICLE}"

    assert from_headline(text, TITLE) == f"# {TITLE}\n\n{ARTICLE}"


@pytest.mark.parametrize(
    "heading",
    [
        f"## **{TITLE}**",
        f"###   {TITLE.upper()}  ##",
        "# Buildkite Adds Scoped Secrets\tand New  Agentic CI Tools",
    ],
)
def test_headings_match_ignoring_case_spacing_and_emphasis(heading: str) -> None:
    assert from_headline(f"{CHROME}{heading}\n\n{ARTICLE}", TITLE).startswith(heading)


def test_any_of_the_titles_can_match() -> None:
    text = f"{CHROME}# {TITLE}\n\n{ARTICLE}"

    assert from_headline(text, None, "Some feed title", TITLE).startswith(f"# {TITLE}")


@pytest.mark.parametrize("titles", [(), (None,), ("",), ("Another article",)])
def test_without_a_matching_heading_the_text_is_unchanged(titles: tuple[str | None, ...]) -> None:
    text = f"{CHROME}# {TITLE}\n\n{ARTICLE}"

    assert from_headline(text, *titles) == text


def test_the_title_in_running_text_is_not_a_headline() -> None:
    text = f"Related: {TITLE}\n\n{CHROME}{ARTICLE}"

    assert from_headline(text, TITLE) == text
