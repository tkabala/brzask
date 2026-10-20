"""Moving stored vectors to another embedding model."""

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from brzask.db.models import Change, RunKind
from brzask.repositories import EmbeddingRepository
from brzask.services import embeddings as embedding_service
from brzask.services.embeddings import active_model, reembed, switch_model
from brzask.services.errors import ServiceError
from brzask.services.runs import pipeline_lock
from tests.factories import TEST_MODEL, Factories, unit_vector
from tests.services.digest.fakes import FakeEmbedder

NEW = "new/embedding"


class NewEmbedder(FakeEmbedder):
    model = NEW


@pytest.fixture
def history(make: Factories) -> list[int]:
    """Five articles embedded with TEST_MODEL, one of them without stored text."""
    ids = [make.article(extracted_text=f"Text {n}", embedding=unit_vector(1)).id for n in range(4)]
    make.article(extracted_text=None, embedding=unit_vector(1))
    return ids


def test_the_configured_model_is_active_until_a_switch(session: Session) -> None:
    assert active_model(session, TEST_MODEL) == TEST_MODEL

    assert switch_model(session, NEW, TEST_MODEL, actor="user") is True
    assert switch_model(session, NEW, TEST_MODEL, actor="user") is False

    assert active_model(session, TEST_MODEL) == NEW
    (change,) = session.scalars(select(Change)).all()
    assert (change.action, change.before, change.after) == (
        "embedding.switch",
        {"model": TEST_MODEL},
        {"model": NEW},
    )


def test_reembed_embeds_in_batches_then_switches(
    sessions: sessionmaker[Session],
    session: Session,
    history: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embedding_service, "BATCH", 3)
    embedder = NewEmbedder()
    progress: list[tuple[int, int]] = []

    result = reembed(
        sessions, embedder, TEST_MODEL, actor="user", progress=lambda *p: progress.append(p)
    )

    assert (result.embedded, result.without_text, result.switched, result.active) == (
        4,
        1,
        True,
        NEW,
    )
    assert [len(texts) for texts, _ in embedder.calls] == [3, 1]
    assert {kind for _, kind in embedder.calls} == {"document"}
    assert progress == [(3, 1), (4, 0)]
    vectors = EmbeddingRepository(session).of_articles(history, NEW)
    assert vectors.keys() == set(history)
    assert active_model(session, TEST_MODEL) == NEW
    # The old vectors stay: switching back costs nothing.
    assert EmbeddingRepository(session).counts_by_model() == {TEST_MODEL: 5, NEW: 4}


def test_reembed_continues_where_it_stopped(
    sessions: sessionmaker[Session], make: Factories, history: list[int]
) -> None:
    EmbeddingRepository(make.session).add(NEW, {history[0]: unit_vector(0, 1)})
    embedder = NewEmbedder()

    result = reembed(sessions, embedder, TEST_MODEL, switch=False, actor="user")

    assert result.embedded == 3
    assert (result.switched, result.active) == (False, TEST_MODEL)
    assert sorted(embedder.calls[0][0]) == ["Text 1", "Text 2", "Text 3"]


def test_reembed_does_not_switch_while_a_digest_runs(
    sessions: sessionmaker[Session],
    session: Session,
    db_engine: Engine,
    history: list[int],
) -> None:
    with pipeline_lock(db_engine, RunKind.DIGEST) as acquired:
        assert acquired
        with pytest.raises(ServiceError, match="a digest is running; 4 vectors are stored"):
            reembed(sessions, NewEmbedder(), TEST_MODEL, actor="user")

    assert active_model(session, TEST_MODEL) == TEST_MODEL
    # Run again later: nothing left to embed, only the switch.
    embedder = NewEmbedder()
    result = reembed(sessions, embedder, TEST_MODEL, actor="user")
    assert (result.embedded, result.switched) == (0, True)
    assert embedder.calls == []
