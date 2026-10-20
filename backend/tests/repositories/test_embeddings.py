from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from brzask.repositories import ArticleRepository, EmbeddingRepository
from tests.factories import TEST_MODEL, Factories, unit_vector

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)
OTHER = "other/embedding"


def test_add_replaces_a_vector_of_the_same_model(session: Session, make: Factories) -> None:
    article = make.article(embedding=unit_vector(1, 0))
    embeddings = EmbeddingRepository(session)

    embeddings.add(TEST_MODEL, {article.id: unit_vector(0, 1)})
    embeddings.add(OTHER, {article.id: unit_vector(1, 1)})

    assert embeddings.of_articles([article.id], TEST_MODEL)[article.id] == pytest.approx(
        unit_vector(0, 1)
    )
    assert embeddings.counts_by_model() == {TEST_MODEL: 1, OTHER: 1}
    assert embeddings.of_articles([], TEST_MODEL) == {}


def test_missing_is_what_a_model_has_to_embed(session: Session, make: Factories) -> None:
    old = make.article(extracted_text="Old text", embedding=unit_vector(1))
    done = make.article(extracted_text="Done", embedding=unit_vector(1))
    make.embedding(done, unit_vector(0, 1), OTHER)
    make.article(extracted_text="Never embedded")
    make.article(extracted_text=None, embedding=unit_vector(1))  # cannot be embedded again
    make.article(extracted_text="", embedding=unit_vector(1))
    embeddings = EmbeddingRepository(session)

    assert embeddings.missing(OTHER, limit=10) == [(old.id, "Old text")]
    assert embeddings.count_missing(OTHER) == (1, 2)
    assert embeddings.missing(TEST_MODEL, limit=10) == []  # `done` has a TEST_MODEL vector


def test_similarity_queries_never_mix_models(session: Session, make: Factories) -> None:
    today = date(2026, 10, 18)
    shown = make.article(
        title="Shown", digest_date=today, shown_at=NOW - timedelta(days=1), embedding=unit_vector(1)
    )
    make.embedding(shown, unit_vector(0, 1), OTHER)
    plain = make.article(title="Plain", embedding=unit_vector(1, 1))
    articles = ArticleRepository(session)

    test_vectors = articles.shown_embeddings(NOW - timedelta(days=7), TEST_MODEL)
    other_vectors = articles.shown_embeddings(NOW - timedelta(days=7), OTHER)
    similar = articles.search_similar(unit_vector(0, 1), OTHER, limit=10)

    assert test_vectors == [pytest.approx(unit_vector(1))]
    assert other_vectors == [pytest.approx(unit_vector(0, 1))]
    assert [(s.article.title, round(s.similarity, 3)) for s in similar] == [("Shown", 1.0)]
    nearest = articles.search_similar(unit_vector(0, 1), TEST_MODEL, limit=10)
    assert [s.article.id for s in nearest] == [plain.id, shown.id]
