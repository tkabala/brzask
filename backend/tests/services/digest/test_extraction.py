import threading
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.embeddings import EmbeddingError
from brzask.clients.extractors import SNIPPET, ExtractionInput, ExtractionResult
from brzask.db.models import Article
from brzask.services.digest.extraction import STORED_CHARS, TEXT_CHARS, extract_and_embed
from brzask.services.digest.pool import Candidate
from tests.factories import TEST_MODEL, Factories
from tests.services.digest.fakes import NOW, FakeEmbedder, FakeExtractor, context


def candidate(link: str, **fields: Any) -> Candidate:
    defaults: dict[str, Any] = {"snippet": None, "published_at": NOW, "rank": 1}
    return Candidate(
        link=link,
        title=link,
        source_id=1,
        source_name="Source",
        release=False,
        **(defaults | fields),
    )


def test_texts_are_cut_embedded_as_documents_and_stored(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    long_text = "word " * 2000
    full = make.article()
    teaser = make.article(snippet="A short teaser")
    nothing = make.article()
    candidates = [
        candidate(full.link, article_id=full.id, content="Feed text"),
        candidate(teaser.link, article_id=teaser.id, snippet="A short teaser"),
        candidate(nothing.link, article_id=nothing.id),
    ]
    extractor = FakeExtractor({full.link: long_text})
    embedder = FakeEmbedder()
    run = context(sessions)

    result = extract_and_embed(run, candidates, extractor, embedder)

    first, second, third = result
    assert extractor.inputs[0] == ExtractionInput(full.link, None, "Feed text")
    assert first.text == long_text.strip()[:TEXT_CHARS].strip()
    assert (first.extracted_by, second.extracted_by, third.extracted_by) == (
        "trafilatura",
        SNIPPET,
        None,
    )
    assert second.text == "A short teaser"
    assert (third.text, third.embedding) == (None, None)
    assert embedder.calls == [([first.text, "A short teaser"], "document")]
    assert first.embedding == embedder.vectors[first.text or ""]
    assert [c.rank for c in result] == [1, 1, 1]

    session.expire_all()
    stored = session.get_one(Article, full.id)
    assert stored.extracted_text == (first.text or "")[:STORED_CHARS]
    assert len(stored.extracted_text or "") == STORED_CHARS
    assert (stored.extracted_by, stored.embedding_model) == ("trafilatura", TEST_MODEL)
    assert list(stored.embedding or []) == pytest.approx(first.embedding)
    empty = session.get_one(Article, nothing.id)
    assert (empty.extracted_text, empty.embedding, empty.embedding_model) == (None, None, None)

    assert run.stats["extraction"] == {
        "candidates": 3,
        "by": {"trafilatura": 1, SNIPPET: 1, "none": 1},
        "embedded": 2,
    }
    assert {"extraction", "embedding"} <= run.timings.keys()


def test_pages_are_extracted_in_parallel(sessions: sessionmaker[Session]) -> None:
    candidates = [candidate(f"https://news.example/{n}", snippet="Snippet") for n in range(15)]
    started = threading.Barrier(2, timeout=5)

    class SlowExtractor(FakeExtractor):
        def extract(self, item: ExtractionInput) -> ExtractionResult:
            if item.url.endswith(("/0", "/1")):
                started.wait()  # both first pages must be in flight at once
            return super().extract(item)

    extractor = SlowExtractor({})

    extract_and_embed(context(sessions, dry_run=True), candidates, extractor, FakeEmbedder())

    assert len(extractor.threads) > 1


def test_a_dry_run_stores_nothing(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    article = make.article()
    candidates = [
        candidate(article.link, article_id=article.id),
        candidate("https://news.example/fresh"),  # no article ID in a dry run
    ]
    extractor = FakeExtractor(
        {article.link: "text " * 100, "https://news.example/fresh": "x" * 300}
    )

    result = extract_and_embed(
        context(sessions, dry_run=True), candidates, extractor, FakeEmbedder()
    )

    assert all(c.embedding is not None for c in result)
    session.expire_all()
    assert session.get_one(Article, article.id).extracted_text is None


def test_no_text_means_no_embedding_call(sessions: sessionmaker[Session]) -> None:
    embedder = FakeEmbedder()
    run = context(sessions, dry_run=True)

    result = extract_and_embed(
        run, [candidate("https://news.example/x")], FakeExtractor({}), embedder
    )

    assert result[0].embedding is None
    assert embedder.calls == []
    assert extract_and_embed(run, [], FakeExtractor({}), embedder) == []


def test_an_embedding_failure_fails_the_stage(sessions: sessionmaker[Session]) -> None:
    candidates = [candidate("https://news.example/x", snippet="Snippet")]

    with pytest.raises(EmbeddingError):
        extract_and_embed(
            context(sessions, dry_run=True),
            candidates,
            FakeExtractor({}),
            FakeEmbedder(EmbeddingError("down")),
        )
