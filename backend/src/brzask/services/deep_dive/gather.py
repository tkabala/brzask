"""The gather and read stages: candidates from the archive and the web, then their text."""

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from brzask.clients.embeddings import EmbeddingError
from brzask.clients.extractors.base import ExtractionInput
from brzask.clients.extractors.chain import SNIPPET
from brzask.clients.usage import UsageMeter
from brzask.clients.web_search import SearchResult, WebSearch, WebSearchError
from brzask.db.models import Article, ArticleContent, ArticleState
from brzask.log import get_logger
from brzask.repositories import ArticleRepository
from brzask.services.briefs import BRIEF_INPUT_CHARS, clip
from brzask.services.deep_dive.plan import Queries
from brzask.services.digest.extraction import TextExtractor
from brzask.services.search import QueryEmbedder, search_articles
from brzask.urls import is_http_url, item_key

log = get_logger(__name__)

# Measured on five real dives (2026-11-23). Archive articles kept: 4 of 25
# archive sources were cited, 3 of them in one dive; three leave room for that.
ARCHIVE_SOURCES = 3
WEB_RESULTS = 5  # results asked of each web query
# Web results read: each dive had 23-29 candidates and cited at least 4 of the 8.
WEB_PAGES = 8
# Characters of each archive or web source the writer reads: the write call
# took 18k-72k input tokens with 12 sources.
SOURCE_CHARS = 12_000
READ_WORKERS = 5

Origin = Literal["article", "archive", "web"]


@dataclass(frozen=True, slots=True)
class Source:
    n: int
    url: str
    title: str
    origin: Origin
    article_id: int | None
    text: str


def round_robin(lists: Sequence[Sequence[SearchResult]]) -> list[SearchResult]:
    """The first result of each list, then the second of each, and so on."""
    merged: list[SearchResult] = []
    for depth in range(max((len(items) for items in lists), default=0)):
        merged.extend(items[depth] for items in lists if depth < len(items))
    return merged


def web_candidates(
    queries: Queries, search: WebSearch, article_link: str, meter: UsageMeter | None
) -> tuple[list[SearchResult], bool]:
    """Web results for the background and practice queries, and whether any search answered.

    Results come in round-robin order across queries; anything that is not an
    http(s) URL, the article itself and repeats are dropped (compared by
    `item_key`). A failing search is logged and the others go on.
    """
    lists: list[list[SearchResult]] = []
    answered = False
    for query in [*queries.background, *queries.practice]:
        try:
            lists.append(search.search(query, limit=WEB_RESULTS, meter=meter))
        except WebSearchError as error:
            log.warning("deep dive search failed", search=search.name, error=str(error))
            continue
        answered = True
    seen = {item_key(article_link)}
    found: list[SearchResult] = []
    for result in round_robin(lists):
        url = result.url.strip()
        key = item_key(url)
        if not is_http_url(url) or key in seen:
            continue
        seen.add(key)
        found.append(SearchResult(url, result.title, result.snippet))
    return found, answered


def archive_candidates(
    session: Session, embedder: QueryEmbedder, queries: Sequence[str], article_id: int
) -> list[Article]:
    """Stored articles matching the archive queries, shown ones first.

    Each query is searched by meaning (articles with vectors); only a query
    that finds nothing that way is searched by text (titles and summaries):
    for a new subject a text match is rarely about it, and it filled every
    slot with unrelated articles in the real checks. The article itself is
    never one.
    """
    repository = ArticleRepository(session)
    found: dict[int, Article] = {}
    for query in queries:
        try:
            similar = [
                match.article
                for match in search_articles(session, embedder, query, ARCHIVE_SOURCES + 1)
            ]
        except EmbeddingError as error:
            log.warning("deep dive archive search failed", error=str(error))
            similar = []
        similar = [article for article in similar if article.id != article_id]
        # One more than kept, so the article itself never leaves a slot empty.
        text = [] if similar else repository.search_text(query, ARCHIVE_SOURCES + 1)
        for article in [*similar, *text]:
            if article.id != article_id:
                found.setdefault(article.id, article)
    ordered = sorted(found.values(), key=lambda article: article.state is not ArticleState.SHOWN)
    return ordered[:ARCHIVE_SOURCES]


def clip_source(text: str, limit: int = SOURCE_CHARS) -> str:
    """`text` cut to `limit` characters at a paragraph (see `briefs.clip`)."""
    return clip(text.strip(), limit)[0]


def read_sources(
    article: Article,
    content: ArticleContent,
    archive: Sequence[Article],
    contents: Mapping[int, str],
    web: Sequence[SearchResult],
    extractor: TextExtractor,
) -> list[Source]:
    """The numbered sources: the article, archive articles with text, readable web pages.

    Archive articles read their stored full text, else their extracted text,
    else are left out. The first `WEB_PAGES` web results are extracted; a page
    no extractor could read (only its search snippet left) is left out.
    """
    sources = [
        _source(
            1,
            article.link,
            article.digest_title or article.title,
            "article",
            article.id,
            clip(content.text.strip(), BRIEF_INPUT_CHARS)[0],
        )
    ]
    for item in archive:
        text = contents.get(item.id) or item.extracted_text
        if text and text.strip():
            sources.append(
                _source(
                    len(sources) + 1,
                    item.link,
                    item.digest_title or item.title,
                    "archive",
                    item.id,
                    clip_source(text),
                )
            )
    pages = list(web[:WEB_PAGES])
    with ThreadPoolExecutor(READ_WORKERS) as pool:
        texts = list(pool.map(lambda result: _read(extractor, result), pages))
    for result, text in zip(pages, texts, strict=True):
        if text:
            sources.append(
                _source(len(sources) + 1, result.url, result.title, "web", None, clip_source(text))
            )
    return sources


def _read(extractor: TextExtractor, result: SearchResult) -> str | None:
    try:
        extracted = extractor.extract(
            ExtractionInput(url=result.url, snippet=result.snippet, title=result.title)
        )
    except Exception as error:
        # One page's failure, whatever it is, must not cost the others theirs.
        log.warning("deep dive page not read", url=result.url, error=type(error).__name__)
        return None
    if extracted.extracted_by in (None, SNIPPET) or not extracted.text:
        return None
    return extracted.text


def _source(
    n: int, url: str, title: str, origin: Origin, article_id: int | None, text: str
) -> Source:
    return Source(n, url, title.strip() or url, origin, article_id, text)
