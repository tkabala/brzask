"""What every extractor shares: its input, its output and the rule for usable text."""

import re
from dataclasses import dataclass
from typing import Protocol

# Shorter than this is a teaser, an error page or a cookie banner, not an article.
MIN_CHARS = 200

# Anti-bot and error pages served with HTTP 200 instead of the article; Reddit,
# for one, answers fetchers with "You've been blocked by network security".
BLOCK_PHRASES = re.compile(
    r"blocked by network security|access denied|are you a human|"
    r"enable javascript and cookies|captcha",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ExtractionInput:
    url: str
    snippet: str | None = None  # the feed summary: the final fallback
    feed_content: str | None = None  # full content the feed carried, if any


@dataclass(frozen=True, slots=True)
class Extracted:
    text: str  # Markdown where the extractor produces it, plain text otherwise
    title: str | None = None
    author: str | None = None
    published: str | None = None  # as the page states it; not parsed


class ExtractionError(Exception):
    """The extractor could not get the page (network, HTTP status, unsupported content)."""


class Extractor(Protocol):
    name: str
    fetches_page: bool  # False only for extractors that read what the feed already gave

    def extract(self, item: ExtractionInput) -> Extracted | None:
        """The page text, None when there is none; raises ExtractionError on failures."""
        ...


def unusable_reason(text: str | None) -> str | None:
    """Why `text` cannot stand in for the article, or None when it can."""
    stripped = (text or "").strip()
    if len(stripped) < MIN_CHARS:
        return "too_short"
    if BLOCK_PHRASES.search(stripped):
        return "blocked"
    return None
