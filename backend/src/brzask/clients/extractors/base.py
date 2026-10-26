"""What every extractor shares: its input, its output and the rule for usable text."""

import re
from dataclasses import dataclass
from typing import Protocol

# Shorter than this is a teaser, an error page or a cookie banner, not an article.
MIN_CHARS = 200

# Anti-bot and error pages served with HTTP 200 instead of the article; Reddit,
# for one, answers fetchers with "You've been blocked by network security", the
# JetBrains blog (after a few dozen requests) with "verify that you're not a robot",
# VentureBeat's feeds (429) with a "Vercel Security Checkpoint: we're verifying
# your browser" page.
BLOCK_PHRASES = re.compile(
    r"blocked by network security|access denied|are you a human|not a robot|"
    r"enable javascript and cookies|captcha|verifying your browser",
    re.IGNORECASE,
)
# Block pages are a few hundred characters; an article about CAPTCHAs or access
# errors is far longer and must not be mistaken for one. Measured with
# extract-bench: 3 of 49 whole pages from a hosted reader (20k+ characters) had
# "reCAPTCHA" in their footer; this cap keeps them usable.
BLOCK_PAGE_MAX_CHARS = 2000


@dataclass(frozen=True, slots=True)
class ExtractionInput:
    url: str
    snippet: str | None = None  # the feed summary: the final fallback
    feed_content: str | None = None  # full content the feed carried, if any
    title: str | None = None  # the feed's title, to find where the article starts


@dataclass(frozen=True, slots=True)
class Extracted:
    text: str  # Markdown where the extractor produces it, plain text otherwise
    title: str | None = None
    author: str | None = None
    published: str | None = None  # as the page states it; not parsed
    tokens: int | None = None  # what a hosted reader billed for the page, when it says


class ExtractionError(Exception):
    """The extractor could not get the page (network, HTTP status, unsupported content)."""


class ExtractionBlockedError(ExtractionError):
    """The site refused the extractor with an anti-bot page, and the extractor said so."""


class Extractor(Protocol):
    name: str
    fetches_page: bool  # False only for extractors that read what the feed already gave

    def extract(self, item: ExtractionInput) -> Extracted | None:
        """The page text, None when there is none; raises ExtractionError on failures."""
        ...


# A Markdown ATX heading: its text without the hashes.
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
_MARKUP = re.compile(r"[*_`]")


def from_headline(text: str, *titles: str | None) -> str:
    """`text` from the heading that matches one of `titles`, else unchanged.

    Readers that render the whole page put the site's navigation, newsletter
    forms and cookie notices before the article; on InfoQ the headline comes
    after 12k characters of them, identical on every page. Only the start of
    the text is embedded, so two such articles looked like one.
    """
    wanted = {_normalized(title) for title in titles if title and title.strip()}
    for heading in _HEADING.finditer(text):
        if _normalized(heading.group(1)) in wanted:
            return text[heading.start() :]
    return text


def _normalized(title: str) -> str:
    return " ".join(_MARKUP.sub("", title).casefold().split())


def unusable_reason(text: str | None) -> str | None:
    """Why `text` cannot stand in for the article, or None when it can."""
    stripped = (text or "").strip()
    if len(stripped) < MIN_CHARS:
        return "too_short"
    if len(stripped) <= BLOCK_PAGE_MAX_CHARS and BLOCK_PHRASES.search(stripped):
        return "blocked"
    return None
