"""Article text and embeddings for the top of the ranking.

Only the top candidates are extracted: fetching pages is the slow part of a
run, and deduplication and selection only look at the top.
"""

from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Protocol

from brzask.clients.embeddings import EmbeddingKind
from brzask.clients.extractors import ExtractionInput, ExtractionResult
from brzask.clients.usage import UsageMeter
from brzask.log import get_logger
from brzask.repositories import ArticleRepository
from brzask.repositories.articles import Extraction
from brzask.services.digest.pool import Candidate
from brzask.services.runs import RunContext

log = get_logger(__name__)

# Characters of article text embedded and shown to the selection prompt; the
# start of an article says what it is about.
TEXT_CHARS = 4000
# Characters stored: the text that was embedded, so `brzask reembed` gives
# another model the same input.
STORED_CHARS = TEXT_CHARS
# Pages extracted at once for the top 15.
WORKERS = 5


class TextExtractor(Protocol):
    """Extracts one article (`ExtractorChain`); safe to call from several threads."""

    def extract(self, item: ExtractionInput) -> ExtractionResult: ...


class DocumentEmbedder(Protocol):
    """Embeds texts (`Embedder`); `model` is stored next to every vector."""

    model: str

    def embed(
        self,
        texts: Sequence[str],
        kind: EmbeddingKind,
        *,
        purpose: str = "embedding",
        meter: UsageMeter | None = None,
    ) -> list[list[float]]: ...


def extract_and_embed(
    context: RunContext,
    candidates: Sequence[Candidate],
    extractor: TextExtractor,
    embedder: DocumentEmbedder,
) -> list[Candidate]:
    """Each candidate with its text and embedding; stores both outside a dry run.

    A candidate with neither extracted text nor a snippet keeps no text and no
    embedding; deduplication never drops it.
    """
    if not candidates:
        return []
    with context.stage("extraction"), ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(extractor.extract, [_input(c) for c in candidates]))
    extracted = [
        replace(c, text=_text(result), extracted_by=result.extracted_by)
        for c, result in zip(candidates, results, strict=True)
    ]

    with_text = [c for c in extracted if c.text]
    vectors: list[list[float]] = []
    if with_text:
        with context.stage("embedding"):
            vectors = embedder.embed(
                [c.text or "" for c in with_text], "document", meter=context.usage
            )
    by_link = {c.link: vector for c, vector in zip(with_text, vectors, strict=True)}
    embedded = [replace(c, embedding=by_link.get(c.link)) for c in extracted]

    if not context.dry_run:
        with context.sessions.begin() as session:
            ArticleRepository(session).save_extractions(
                [
                    _extraction(c.article_id, c, embedder.model)
                    for c in embedded
                    if c.article_id is not None
                ]
            )

    context.stats["extraction"] = {
        "candidates": len(embedded),
        "by": dict(Counter(c.extracted_by or "none" for c in embedded)),
        "embedded": len(by_link),
    }
    log.info("top candidates extracted", **context.stats["extraction"])
    return embedded


def _input(candidate: Candidate) -> ExtractionInput:
    return ExtractionInput(
        candidate.link,
        snippet=candidate.snippet,
        feed_content=candidate.content,
        title=candidate.title,
    )


def _text(result: ExtractionResult) -> str | None:
    text = (result.text or "").strip()[:TEXT_CHARS].strip()
    return text or None


def _extraction(article_id: int, candidate: Candidate, model: str) -> Extraction:
    return Extraction(
        article_id=article_id,
        text=candidate.text[:STORED_CHARS] if candidate.text else None,
        extracted_by=candidate.extracted_by,
        embedding=candidate.embedding,
        embedding_model=model if candidate.embedding is not None else None,
    )
