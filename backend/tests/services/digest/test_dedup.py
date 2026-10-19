import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from brzask.db.models import EMBEDDING_DIMENSIONS, RunKind
from brzask.services.digest.dedup import (
    DEFAULT_MODEL,
    MIN_SURVIVORS,
    THRESHOLDS,
    Drop,
    Thresholds,
    cosine,
    deduplicate,
    deduplicate_candidates,
    thresholds_for,
)
from brzask.services.digest.pool import Candidate
from brzask.services.runs import RunContext
from tests.factories import TEST_MODEL, Factories

NOW = datetime(2026, 10, 18, 7, tzinfo=UTC)
GEMINI = THRESHOLDS["gemini-embedding-001"]


def axis(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[index] = 1.0
    return vector


def near(similarity: float, to: int, other: int) -> list[float]:
    """A unit vector at `similarity` from `axis(to)`, leaning towards `axis(other)`.

    Two vectors `near(a, to, x)` and `near(b, to, y)` with x != y have similarity a * b.
    """
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[to] = similarity
    vector[other] = math.sqrt(1 - similarity * similarity)
    return vector


def candidate(rank: int, embedding: list[float] | None, **fields: Any) -> Candidate:
    return Candidate(
        link=f"https://news.example/{rank}",
        title=f"Article {rank}",
        source_id=rank,
        source_name=f"Source {rank}",
        release=False,
        snippet=None,
        published_at=NOW,
        rank=rank,
        embedding=embedding,
        **fields,
    )


def distinct(first_rank: int, count: int) -> list[Candidate]:
    """Candidates unlike each other and anything else (each on its own axis from 100 on)."""
    return [candidate(rank, axis(100 + rank)) for rank in range(first_rank, first_rank + count)]


def ranks(candidates: list[Candidate]) -> list[int | None]:
    return [c.rank for c in candidates]


def test_cosine() -> None:
    assert cosine(axis(0), axis(0)) == pytest.approx(1.0)
    assert cosine(axis(0), axis(1)) == 0.0
    assert cosine(near(0.9, 0, 1), axis(0)) == pytest.approx(0.9)
    assert cosine([0.0] * 3, [1.0, 0.0, 0.0]) == 0.0


# --- Cross-day ---------------------------------------------------------------------------


def test_a_repeat_of_a_shown_article_is_dropped_at_the_measured_boundary() -> None:
    repeat = candidate(1, near(0.962, 0, 1))
    similar = candidate(2, near(0.959, 0, 2))
    candidates = [repeat, similar, *distinct(3, 10)]

    result = deduplicate(candidates, [axis(0)], GEMINI)

    assert result.drops == [Drop(repeat.link, "cross_day", 0.962)]
    assert ranks(result.survivors) == list(range(2, 13))


def test_the_cross_day_pass_never_goes_below_the_minimum() -> None:
    # Twelve repeats: only three may go. The closest first, then the worst ranked.
    candidates = [candidate(rank, near(0.97, 0, rank)) for rank in range(1, 11)]
    candidates.append(candidate(11, near(0.99, 0, 11)))
    candidates.append(candidate(12, near(0.98, 0, 12)))

    result = deduplicate(candidates, [axis(0)], Thresholds(0.96, (0.999,)))

    assert len(result.survivors) == MIN_SURVIVORS
    assert [drop.link.rsplit("/", 1)[-1] for drop in result.drops] == ["11", "12", "10"]


def test_no_cross_day_drops_when_the_pool_is_already_small() -> None:
    candidates = [candidate(rank, near(0.99, 0, rank)) for rank in range(1, 6)]

    result = deduplicate(candidates, [axis(0)], Thresholds(0.96, (0.999,)))

    assert result.drops == []


def test_nothing_shown_means_no_cross_day_drops() -> None:
    candidates = [candidate(1, axis(0)), *distinct(2, 10)]

    assert deduplicate(candidates, [], GEMINI).drops == []


# --- Same day -----------------------------------------------------------------------------


def test_of_two_candidates_on_one_story_the_better_ranked_stays() -> None:
    # Similarity 0.85 between them: a duplicate at the most aggressive threshold.
    better = candidate(3, near(math.sqrt(0.85), 0, 1))
    worse = candidate(2, near(math.sqrt(0.85), 0, 2))
    candidates = [*distinct(4, 10), worse, better]

    result = deduplicate(candidates, [], GEMINI)

    assert result.same_day_threshold == 0.80
    assert result.drops == [Drop(better.link, "same_day", 0.85, worse.link)]
    assert better not in result.survivors


def test_the_threshold_backs_off_until_enough_survive() -> None:
    # Ten candidates in pairs at 0.84 (duplicates at 0.80 and 0.83, not at 0.86),
    # plus two distinct ones: 0.80 would leave 7, 0.86 leaves all 12.
    pairs = []
    for pair in range(5):
        first, second = 2 * pair + 1, 2 * pair + 2
        pairs.append(candidate(first, near(math.sqrt(0.84), 10 + pair, 20 + first)))
        pairs.append(candidate(second, near(math.sqrt(0.84), 10 + pair, 20 + second)))
    candidates = [*pairs, *distinct(11, 2)]

    result = deduplicate(candidates, [], GEMINI)

    assert result.same_day_threshold == 0.86
    assert result.drops == []
    assert len(result.survivors) == 12


def test_a_day_full_of_duplicates_keeps_the_most_lenient_threshold() -> None:
    candidates = [candidate(rank, axis(0)) for rank in range(1, 13)]

    result = deduplicate(candidates, [], GEMINI)

    assert result.same_day_threshold == GEMINI.same_day[-1]
    assert ranks(result.survivors) == [1]
    assert {drop.duplicate_of for drop in result.drops} == {candidates[0].link}


def test_candidates_without_an_embedding_are_never_dropped() -> None:
    candidates = [candidate(rank, None) for rank in range(1, 4)]
    candidates += [candidate(rank, axis(0)) for rank in range(4, 7)]

    result = deduplicate(candidates, [axis(0)], GEMINI)

    assert ranks(result.survivors) == [1, 2, 3, 4]


# --- Thresholds per model --------------------------------------------------------------------


@pytest.mark.parametrize("model", ["google/gemini-embedding-001", "gemini-embedding-001"])
def test_thresholds_match_the_model_without_its_provider(model: str) -> None:
    assert thresholds_for(model) == (GEMINI, True)


def test_an_unmeasured_model_gets_the_default_thresholds() -> None:
    assert thresholds_for("nomic-embed-text") == (THRESHOLDS[DEFAULT_MODEL], False)


# --- The stage ----------------------------------------------------------------------------


def test_the_stage_compares_with_recent_articles_of_the_same_model(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    today = NOW.date()
    make.article(embedding=axis(0), digest_date=today - timedelta(days=2))
    make.article(  # other model: never compared
        embedding=axis(1), embedding_model="other/model", digest_date=today - timedelta(days=1)
    )
    make.article(  # too old to compare
        embedding=axis(2),
        first_seen_at=NOW - timedelta(days=8),
        digest_date=today - timedelta(days=8),
    )
    candidates = [
        candidate(1, axis(0)),
        candidate(2, axis(1)),
        candidate(3, axis(2)),
        *distinct(4, 9),
    ]
    run = RunContext(run_id=uuid.uuid4(), kind=RunKind.DIGEST, started_at=NOW, sessions=sessions)

    survivors = deduplicate_candidates(run, candidates, TEST_MODEL)

    assert ranks(survivors) == list(range(2, 13))
    stats = run.stats["deduplication"]
    assert {key: value for key, value in stats.items() if key != "drops"} == {
        "candidates": 12,
        "survivors": 11,
        "shown_compared": 1,
        "cross_day_dropped": 1,
        "same_day_dropped": 0,
        "same_day_threshold": 0.80,
        "thresholds_measured": False,
    }
    assert stats["drops"] == [
        {
            "link": candidates[0].link,
            "reason": "cross_day",
            "similarity": 1.0,
            "duplicate_of": None,
        }
    ]
    assert "deduplication" in run.timings
