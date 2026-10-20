"""Deduplication of the top candidates by embedding similarity.

Two passes. Cross-day: a candidate too close to an article shown in the last
days is a repeat. Same-day: of two candidates telling the same story, the
better ranked one stays. A candidate without an embedding cannot be compared
and is never dropped.

The same-day pass either picks a threshold by how many candidates it leaves
(the default), or, given a judge, asks it about the pairs in the grey zone,
from the lowest same-day threshold up to the cross-day one: there the
similarity of two articles about one event and of two articles that merely
share a topic overlap, and only reading them tells which it is. Pairs above
the zone are duplicates without asking.

Thresholds depend on the embedding model: cosine values of one model mean
nothing for another, so each model has its own, measured on its vectors.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

from brzask.clients.judge import Judge, JudgeError, Noul
from brzask.clients.usage import UsageMeter
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

# A grey-zone pair is the same event when the judge's yes is at least this likely.
# Not tuned: an even split is the judge saying it cannot tell, and then both stay.
SAME_EVENT_PROBABILITY = 0.5
# Characters of each article's text the judge reads; enough for the lead of a story.
JUDGE_TEXT_CHARS = 1000

SAME_EVENT = Noul(
    "Do these two articles report the same event?",
    true="The same news: one release, announcement, incident or finding, "
    "even from different outlets or in different words.",
    false="Different news, even on the same topic, from the same source or project, "
    "or about two versions or two products of one company.",
)

Pair = tuple[str, str]
"""Two candidates' links, in ranking order."""

SameEvent = Callable[[Sequence[tuple[Candidate, Candidate]]], Mapping[Pair, float]]
"""Asked about grey-zone pairs; the probability that each pair is one event."""


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
    same_event: float | None = None  # the judge's probability, for judged pairs


@dataclass(frozen=True, slots=True)
class Deduplicated:
    survivors: list[Candidate]
    drops: list[Drop]
    same_day_threshold: float | None  # None when a judge decided the grey zone
    judged_pairs: int = 0


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return _dot(_unit(a), _unit(b))


def _unit(vector: Sequence[float]) -> list[float]:
    """`vector` scaled to length 1; a zero vector stays zero (cosine 0 with anything)."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else [0.0] * len(vector)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def deduplicate(
    candidates: Sequence[Candidate],
    shown: Sequence[Sequence[float]],
    thresholds: Thresholds,
    same_event: SameEvent | None = None,
) -> Deduplicated:
    """Survivors in their original order.

    `candidates` are in ranking order; a better rank wins a same-day pair.
    With `same_event`, grey-zone pairs are asked about instead of picking a
    threshold; if asking fails, `JudgeError` propagates.
    """
    cross_day = _cross_day(candidates, shown, thresholds.cross_day)
    dropped = {drop.link for drop in cross_day}
    remaining = [c for c in candidates if c.link not in dropped]

    if same_event is not None:
        lower, upper = thresholds.same_day[0], thresholds.cross_day
        pairs = grey_pairs(remaining, lower, upper)
        probabilities = same_event(pairs) if pairs else {}
        judged = _same_day_judged(remaining, lower, upper, probabilities)
        dropped |= {drop.link for drop in judged}
        return Deduplicated(
            survivors=[c for c in candidates if c.link not in dropped],
            drops=[*cross_day, *judged],
            same_day_threshold=None,
            judged_pairs=len(pairs),
        )

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


def grey_pairs(
    candidates: Sequence[Candidate], lower: float, upper: float
) -> list[tuple[Candidate, Candidate]]:
    """Pairs with similarity in [lower, upper), the better ranked one first."""
    ordered = [c for c in sorted(candidates, key=_rank) if c.embedding is not None]
    return [
        (first, second)
        for index, first in enumerate(ordered)
        for second in ordered[index + 1 :]
        if lower <= _similarity(first, second) < upper
    ]


def _same_day_judged(
    candidates: Sequence[Candidate],
    lower: float,
    upper: float,
    same_event: Mapping[Pair, float],
) -> list[Drop]:
    """Greedy, in ranking order: a candidate goes when a kept one is above the
    zone, or in it and judged the same event; never below MIN_SURVIVORS.
    """
    kept: list[Candidate] = []
    drops: list[Drop] = []
    room = max(len(candidates) - MIN_SURVIVORS, 0)
    for candidate in sorted(candidates, key=_rank):
        duplicates: list[tuple[float, Candidate, float | None]] = []
        comparable = candidate.embedding is not None and len(drops) < room
        for other in kept if comparable else []:
            if other.embedding is None:
                continue
            similarity = _similarity(other, candidate)
            probability = same_event.get((other.link, candidate.link))
            if similarity >= upper:
                duplicates.append((similarity, other, None))
            elif (
                similarity >= lower
                and probability is not None
                and probability >= SAME_EVENT_PROBABILITY
            ):
                duplicates.append((similarity, other, probability))
        if duplicates:
            similarity, original, probability = max(duplicates, key=lambda match: match[0])
            drops.append(
                Drop(
                    candidate.link,
                    "same_day",
                    round(similarity, 4),
                    original.link,
                    probability,
                )
            )
            continue
        kept.append(candidate)
    return drops


def judge_same_event(judge: Judge, meter: UsageMeter | None = None) -> SameEvent:
    """Asks `judge` about all pairs in one call, the articles in the state."""

    def ask(pairs: Sequence[tuple[Candidate, Candidate]]) -> dict[Pair, float]:
        articles: dict[str, dict[str, Any]] = {}
        names: dict[str, str] = {}
        for candidate in (c for pair in pairs for c in pair):
            if candidate.link not in names:
                names[candidate.link] = f"a{len(names) + 1}"
                articles[names[candidate.link]] = _judge_article(candidate)
        questions = {
            f"pair{index}": Noul(
                f"Do `articles.{names[first.link]}` and `articles.{names[second.link]}` "
                "report the same event?",
                true=SAME_EVENT.true,
                false=SAME_EVENT.false,
            )
            for index, (first, second) in enumerate(pairs)
        }
        judgement = judge.ask(
            {"articles": articles}, questions, purpose="deduplication", meter=meter
        )
        return {
            (first.link, second.link): judgement.noul(f"pair{index}").probability
            for index, (first, second) in enumerate(pairs)
        }

    return ask


def _judge_article(candidate: Candidate) -> dict[str, Any]:
    return {
        "source": candidate.source_name,
        "title": candidate.title,
        "text": (candidate.text or candidate.snippet or "")[:JUDGE_TEXT_CHARS],
    }


def _similarity(a: Candidate, b: Candidate) -> float:
    if a.embedding is None or b.embedding is None:
        raise ValueError("both candidates need an embedding")
    return cosine(a.embedding, b.embedding)


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
    judge: Judge | None = None,
) -> list[Candidate]:
    """Survivors of both passes, compared with articles shown by vectors of `model`.

    Articles shown in the window before the run's start count, so a replayed
    day compares with what had been shown by then. `thresholds` replaces the
    model's own (to try others with `brzask replay`). With a `judge`, it
    decides the grey zone; if it fails, the threshold decides, with a warning.
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
    method = "threshold"
    with context.stage("deduplication"):
        if judge is not None:
            try:
                result = deduplicate(
                    candidates, shown, thresholds, judge_same_event(judge, context.usage)
                )
                method = "judge"
            except JudgeError as error:
                log.warning("same-event judge failed; using the threshold", error=str(error))
                result = deduplicate(candidates, shown, thresholds)
                method = "threshold (judge failed)"
        else:
            result = deduplicate(candidates, shown, thresholds)
    context.stats["deduplication"] = {
        "same_day_method": method,
        "candidates": len(candidates),
        "survivors": len(result.survivors),
        "shown_compared": len(shown),
        "cross_day_dropped": sum(drop.reason == "cross_day" for drop in result.drops),
        "same_day_dropped": sum(drop.reason == "same_day" for drop in result.drops),
        "same_day_threshold": result.same_day_threshold,
        "judged_pairs": result.judged_pairs,
        "thresholds_measured": measured,
        "drops": [asdict(drop) for drop in result.drops],
    }
    log.info(
        "candidates deduplicated",
        **{k: v for k, v in context.stats["deduplication"].items() if k != "drops"},
    )
    return result.survivors
