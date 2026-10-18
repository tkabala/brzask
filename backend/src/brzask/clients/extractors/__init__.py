"""Article text extraction: a chain of extractors with one rule for usable text.

`EXTRACTORS` sets the order (e.g. `feed,trafilatura,jina`). Each extractor
either returns text that passes `unusable_reason` or the next one is tried;
the feed snippet is the final fallback. Pages are fetched only where
robots.txt allows it, and some sites have their own rules (see `rules`).
"""

import httpx2

from brzask.clients.extractors.adapters import (
    PAGE_TIMEOUT,
    Crawl4AIExtractor,
    FeedExtractor,
    FirecrawlExtractor,
    JinaExtractor,
    TrafilaturaExtractor,
)
from brzask.clients.extractors.base import (
    Extracted,
    ExtractionError,
    ExtractionInput,
    Extractor,
    unusable_reason,
)
from brzask.clients.extractors.chain import (
    SNIPPET,
    Attempt,
    ExtractionResult,
    ExtractorChain,
    Outcome,
)
from brzask.clients.extractors.robots import RobotsPolicy
from brzask.clients.http import new_client
from brzask.config.settings import ExtractorSettings

__all__ = [
    "SNIPPET",
    "Attempt",
    "Extracted",
    "ExtractionError",
    "ExtractionInput",
    "ExtractionResult",
    "Extractor",
    "ExtractorChain",
    "Outcome",
    "build_chain",
    "unusable_reason",
]


def build_chain(settings: ExtractorSettings, client: httpx2.Client | None = None) -> ExtractorChain:
    """The chain configured by `EXTRACTORS`, sharing one HTTP client."""
    client = client or new_client(PAGE_TIMEOUT)

    jina_key = settings.jina_api_key.get_secret_value() if settings.jina_api_key else None
    firecrawl_key = (
        settings.firecrawl_api_key.get_secret_value() if settings.firecrawl_api_key else None
    )
    extractors: list[Extractor] = []
    for name in settings.extractors:
        match name:
            case "feed":
                extractors.append(FeedExtractor())
            case "trafilatura":
                extractors.append(TrafilaturaExtractor(client))
            case "jina":
                extractors.append(JinaExtractor(client, jina_key))
            case "firecrawl":
                extractors.append(
                    FirecrawlExtractor(client, str(settings.firecrawl_base_url), firecrawl_key)
                )
            case "crawl4ai":
                assert settings.crawl4ai_base_url is not None  # noqa: S101  (settings validate it)
                extractors.append(Crawl4AIExtractor(client, str(settings.crawl4ai_base_url)))
    return ExtractorChain(extractors, RobotsPolicy(client))
