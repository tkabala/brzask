"""The active embedding model, and moving the stored vectors to another one.

Vectors of different models cannot be compared, so deduplication and search
use one model at a time: the active one. It is EMBEDDING_MODEL until
`brzask reembed` switches to another model, and from then on the one stored in
the database. Switching only happens once every embedded article has a vector
of the new model, so the digest never compares against a partial history.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.usage import UsageMeter
from brzask.db.models import ChangeStatus, RunKind
from brzask.log import get_logger
from brzask.repositories import ChangeRepository, EmbeddingRepository, SettingRepository
from brzask.services.digest.extraction import TEXT_CHARS, DocumentEmbedder
from brzask.services.errors import ServiceError
from brzask.services.runs import pipeline_lock, session_bind

log = get_logger(__name__)

ACTIVE_MODEL_KEY = "embedding_model"
# Articles embedded per call and per transaction; a run can stop at any batch
# and continue from there.
BATCH = 50


def active_model(session: Session, configured: str) -> str:
    """The model whose vectors are compared: the switched-to one, else `configured`."""
    value = SettingRepository(session).get(ACTIVE_MODEL_KEY)
    model = value.get("model") if value else None
    return model if isinstance(model, str) and model else configured


def switch_model(session: Session, model: str, configured: str, *, actor: str) -> bool:
    """Make `model` the active one; False when it already is."""
    before = active_model(session, configured)
    if before == model:
        return False
    SettingRepository(session).put(ACTIVE_MODEL_KEY, {"model": model})
    ChangeRepository(session).record(
        actor=actor,
        action="embedding.switch",
        entity_type="setting",
        entity_id=ACTIVE_MODEL_KEY,
        status=ChangeStatus.APPLIED,
        before={"model": before},
        after={"model": model},
    )
    return True


@dataclass(frozen=True, slots=True)
class Reembedded:
    model: str
    embedded: int  # vectors computed by this run
    without_text: int  # embedded articles with no stored text: they keep only their old vectors
    switched: bool  # the model became the active one in this run
    active: str  # the active model afterwards


def reembed(
    sessions: sessionmaker[Session],
    embedder: DocumentEmbedder,
    configured: str,
    *,
    switch: bool = True,
    actor: str,
    meter: UsageMeter | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Reembedded:
    """Embed every embedded article again with `embedder.model`, then switch to it.

    Runs alongside the worker: digests keep using the active model until the
    switch. The switch holds the digest's lock, embeds what digests added in
    the meantime and changes the active model in one go; when a digest is
    running, it fails and leaves the computed vectors for the next attempt.
    `progress` gets (embedded so far, still missing) after each batch.
    """
    model = embedder.model
    embedded = _embed_missing(sessions, embedder, meter, progress)
    if not switch:
        with sessions.begin() as session:
            return Reembedded(
                model,
                embedded,
                EmbeddingRepository(session).count_missing(model)[1],
                switched=False,
                active=active_model(session, configured),
            )

    with pipeline_lock(session_bind(sessions), RunKind.DIGEST) as acquired:
        if not acquired:
            raise ServiceError(
                f"a digest is running; {embedded} vectors are stored, run reembed again to switch"
            )
        embedded += _embed_missing(sessions, embedder, meter, progress)
        with sessions.begin() as session:
            without_text = EmbeddingRepository(session).count_missing(model)[1]
            switched = switch_model(session, model, configured, actor=actor)
    log.info(
        "embeddings moved to another model",
        model=model,
        embedded=embedded,
        without_text=without_text,
        switched=switched,
    )
    return Reembedded(model, embedded, without_text, switched, active=model)


def _embed_missing(
    sessions: sessionmaker[Session],
    embedder: DocumentEmbedder,
    meter: UsageMeter | None,
    progress: Callable[[int, int], None] | None,
) -> int:
    """Vectors for every article that has one of another model and stored text."""
    model = embedder.model
    done = 0
    # Counted once: a count per batch scans every article again. Articles a
    # running digest adds meanwhile are embedded too, so this only guides progress.
    remaining = 0
    if progress is not None:
        with sessions.begin() as session:
            remaining = EmbeddingRepository(session).count_missing(model)[0]
    while True:
        with sessions.begin() as session:
            batch = EmbeddingRepository(session).missing(model, BATCH)
        if not batch:
            return done
        # Outside a transaction: the call can take seconds.
        vectors = embedder.embed(
            [text[:TEXT_CHARS] for _, text in batch], "document", purpose="reembed", meter=meter
        )
        ids = [article_id for article_id, _ in batch]
        with sessions.begin() as session:
            EmbeddingRepository(session).add(model, dict(zip(ids, vectors, strict=True)))
        done += len(batch)
        remaining = max(0, remaining - len(batch))
        if progress is not None:
            progress(done, remaining)
