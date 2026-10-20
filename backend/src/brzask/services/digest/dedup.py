"""Deduplication of the top candidates by embedding similarity.

Two passes. Cross-day: a candidate too close to an article shown in the last
days is a repeat. Same-day: of two candidates telling the same story, the
better ranked one stays. A candidate without an embedding cannot be compared
and is never dropped.

Thresholds depend on the embedding model: cosine values of one model mean
nothing for another, so each model has its own, measured on its vectors.
"""

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import timedelta

from brzask.log import get_logger
from brzask.repositories import ArticleRepository
from brzask.services.digest.pool import Candidate
from brzask.services.runs import RunContext

log = get_logger(__name__)

# Shown articles a candidate is compared with.
CROSS_DAY_WINDOW = timedelta(days=7)
# Candidates left for the selection of the 7. The cross-day pass never goes
# below it; the same-day pass picks its threshold by it.
MIN_SURVIVORS = 9


@dataclass(frozen=True, slots=True)
class Thresholds:
    cross_day: float
    # Tried in order, most aggressive first; the first that keeps MIN_SURVIVORS wins,
    # else the last one.
    same_day: tuple[float, ...]


THRESHOLDS: dict[str, Thresholds] = {
    # Measured on daily digests: every real repeat of a shown article had cosine
    # >= 0.962 and distinct but similar articles <= 0.959. Same-day duplicates sit
    # lower (0.80-0.88), as two outlets word one story differently.
    "gemini-embedding-001": Thresholds(cross_day=0.96, same_day=(0.80, 0.83, 0.86, 0.90, 0.93)),
}
# Used for models nothing was measured on, with a warning; validate with `brzask replay`.
DEFAULT_MODEL = "gemini-embedding-001"


def thresholds_for(model: str) -> tuple[Thresholds, bool]:
    """The model's thresholds, and whether they were measured on that model.

    Models are matched without their provider prefix
    (`google/gemini-embedding-001` is `gemini-embedding-001`).
    """
    name = model.rsplit("/", 1)[-1]
    if name in THRESHOLDS:
        return THRESHOLDS[name], True
    return THRESHOLDS[DEFAULT_MODEL], False


@dataclass(frozen=True, slots=True)
class Drop:
    link: str
    reason: str  # "cross_day" or "same_day"
    similarity: float
    duplicate_of: str | None = None  # the candidate kept instead, for same-day drops


@dataclass(frozen=True, slots=True)
class Deduplicated:
    survivors: list[Candidate]
    drops: list[Drop]
    same_day_threshold: float


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return _dot(_unit(a), _unit(b))


def _unit(vector: Sequence[float]) -> list[float]:
    """`vector` scaled to length 1; a zero vector stays zero (cosine 0 with anything)."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else [0.0] * len(vector)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def deduplicate(
    candidates: Sequence[Candidate], shown: Sequence[Sequence[float]], thresholds: Thresholds
) -> Deduplicated:
    """Survivors in their original order.

    `candidates` are in ranking order; a better rank wins a same-day pair.
    """
    cross_day = _cross_day(candidates, shown, thresholds.cross_day)
    dropped = {drop.link for drop in cross_day}
    remaining = [c for c in candidates if c.link not in dropped]

    same_day: list[Drop] = []
    threshold = thresholds.same_day[-1]
    for threshold in thresholds.same_day:
        same_day = _same_day(remaining, threshold)
        if len(remaining) - len(same_day) >= MIN_SURVIVORS:
            break
    dropped |= {drop.link for drop in same_day}
    return Deduplicated(
        survivors=[c for c in candidates if c.link not in dropped],
        drops=[*cross_day, *same_day],
        same_day_threshold=threshold,
    )


def _cross_day(
    candidates: Sequence[Candidate], shown: Sequence[Sequence[float]], threshold: float
) -> list[Drop]:
    """Repeats of shown articles, without going below MIN_SURVIVORS.

    The closest repeats go first and, among equally close ones, the worst
    ranked, so the survivor floor keeps the most defensible candidates.
    """
    hits: list[tuple[float, float, Candidate]] = []
    # Normalized once: each candidate is compared with every shown vector.
    shown_units = [_unit(vector) for vector in shown]
    for candidate in candidates:
        if candidate.embedding is None or not shown_units:
            continue
        unit = _unit(candidate.embedding)
        best = max(_dot(unit, vector) for vector in shown_units)
        if best >= threshold:
            hits.append((best, _rank(candidate), candidate))
    hits.sort(key=lambda hit: (-hit[0], -hit[1]))
    room = max(len(candidates) - MIN_SURVIVORS, 0)
    return [Drop(c.link, "cross_day", round(best, 4)) for best, _, c in hits[:room]]


def _same_day(candidates: Sequence[Candidate], threshold: float) -> list[Drop]:
    """Greedy, in ranking order: each kept candidate drops the later ones too close to it."""
    kept: list[Candidate] = []
    drops: list[Drop] = []
    for candidate in sorted(candidates, key=_rank):
        if candidate.embedding is not None:
            match = _closest(candidate.embedding, kept, threshold)
            if match is not None:
                similarity, original = match
                drops.append(Drop(candidate.link, "same_day", round(similarity, 4), original.link))
                continue
        kept.append(candidate)
    return drops


def _closest(
    vector: Sequence[float], kept: Sequence[Candidate], threshold: float
) -> tuple[float, Candidate] | None:
    matches = [
        (cosine(vector, other.embedding), other) for other in kept if other.embedding is not None
    ]
    best = max(matches, key=lambda match: match[0], default=None)
    return best if best is not None and best[0] >= threshold else None


def _rank(candidate: Candidate) -> float:
    """Unranked candidates count as the worst."""
    return candidate.rank if candidate.rank is not None else math.inf


def deduplicate_candidates(
    context: RunContext,
    candidates: Sequence[Candidate],
    model: str,
    thresholds: Thresholds | None = None,
) -> list[Candidate]:
    """Survivors of both passes, compared with articles shown by vectors of `model`.

    Articles shown in the window before the run's start count, so a replayed
    day compares with what had been shown by then. `thresholds` replaces the
    model's own (to try others with `brzask replay`).
    """
    measured = True
    if thresholds is None:
        thresholds, measured = thresholds_for(model)
    if not measured:
        log.warning(
            "no deduplication thresholds measured for this embedding model; using defaults",
            model=model,
            default_model=DEFAULT_MODEL,
        )
    with context.sessions.begin() as session:
        shown = ArticleRepository(session).shown_embeddings(
            context.started_at - CROSS_DAY_WINDOW, model, before=context.started_at
        )
    with context.stage("deduplication"):
        result = deduplicate(candidates, shown, thresholds)
    context.stats["deduplication"] = {
        "candidates": len(candidates),
        "survivors": len(result.survivors),
        "shown_compared": len(shown),
        "cross_day_dropped": sum(drop.reason == "cross_day" for drop in result.drops),
        "same_day_dropped": sum(drop.reason == "same_day" for drop in result.drops),
        "same_day_threshold": result.same_day_threshold,
        "thresholds_measured": measured,
        "drops": [asdict(drop) for drop in result.drops],
    }
    log.info(
        "candidates deduplicated",
        **{k: v for k, v in context.stats["deduplication"].items() if k != "drops"},
    )
    return result.survivors
