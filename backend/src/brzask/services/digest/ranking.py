"""Ranking: the LLM orders the pool, and the top of its order goes on to extraction.

The model ranks candidates against each other instead of scoring each one
(see the ranking prompt for why). Candidates are numbered by their position in
the pool, since fresh entries have no article ID in a dry run.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy.orm import Session

from brzask import prompts
from brzask.clients.llm import Completion, InvalidJSONError
from brzask.clients.usage import UsageMeter
from brzask.log import get_logger
from brzask.repositories import ArticleRepository, InterestRepository
from brzask.repositories.articles import OpenedArticle
from brzask.services.digest.pool import Candidate
from brzask.services.runs import RunContext

log = get_logger(__name__)

# Positions asked of the model: more than TOP_N, leaving room for the per-source limit.
RANK_LIMIT = 40
# Candidates that go on to extraction, embeddings and deduplication.
TOP_N = 15
# A chatty source may take at most this many of the TOP_N places...
MAX_PER_SOURCE = 2
# ...unless that leaves fewer candidates than this, on a day with few sources.
MIN_CANDIDATES = 10
# Opens are rare (about 4 a week), so the preference window is wide.
OPENS_WINDOW = timedelta(days=90)
OPENS_LIMIT = 100
# Of those, the prompt lists the newest titles and the most opened topics and sources.
OPENED_TITLES = 15
OPENED_TALLY = 8


class ChatModel(Protocol):
    """Answers a prompt with JSON (`LLMClient`)."""

    def complete_json(
        self, prompt: str, *, purpose: str, meter: UsageMeter | None = None
    ) -> tuple[Any, Completion]: ...


def ranking_prompt(
    candidates: Sequence[Candidate],
    interests: Sequence[dict[str, Any]],
    opens: Sequence[OpenedArticle],
) -> str:
    """The ranking prompt; candidate `i` in the pool is listed with ID `i + 1`."""
    return prompts.render(
        "ranking",
        interests=interests,
        opened_titles=[opened.title for opened in opens[:OPENED_TITLES]],
        opened_topics=_tally(opened.topic for opened in opens),
        opened_sources=_tally(opened.source_name for opened in opens),
        candidates=[
            {
                "id": number,
                "source": candidate.source_name,
                "title": candidate.title,
                "snippet": candidate.snippet or "",
                "release": candidate.release,
            }
            for number, candidate in enumerate(candidates, start=1)
        ],
        rank_limit=min(RANK_LIMIT, len(candidates)),
    )


def parse_ranking(answer: Any, count: int) -> list[int]:
    """Pool positions (0-based), best first, from the model's `{"ranking": [id, ...]}`.

    IDs outside 1..`count`, repeated IDs and values that are not whole numbers
    are skipped; an answer of any other shape gives an empty ranking.
    """
    values = answer.get("ranking") if isinstance(answer, dict) else None
    if not isinstance(values, list):
        return []
    positions: dict[int, None] = {}  # ordered, without repeats
    for value in values:
        number = _whole_number(value)
        if number is not None and 1 <= number <= count:
            positions.setdefault(number - 1)
    return list(positions)


def select_top(candidates: Sequence[Candidate], ranking: Sequence[int]) -> list[Candidate]:
    """Up to TOP_N candidates in ranking order, each with its rank, at most MAX_PER_SOURCE each.

    One pass in ranking order: a source's third article is skipped and the
    next one taken. Candidates the model left out rank after the ranked ones,
    in pool order, and only top the list up to MIN_CANDIDATES; if the
    per-source limit still leaves fewer, it is lifted.
    """
    ranked = [
        replace(candidates[position], rank=rank) for rank, position in enumerate(ranking, start=1)
    ]
    left_out = set(range(len(candidates))) - set(ranking)
    unranked = [
        replace(candidates[position], rank=rank)
        for rank, position in enumerate(sorted(left_out), start=len(ranking) + 1)
    ]

    picked: list[Candidate] = []
    picked_links: set[str] = set()
    per_source: Counter[int] = Counter()

    def fill(group: Sequence[Candidate], limit: int, *, capped: bool) -> None:
        for candidate in group:
            if len(picked) >= limit:
                return
            if candidate.link in picked_links:
                continue
            if capped and per_source[candidate.source_id] >= MAX_PER_SOURCE:
                continue
            per_source[candidate.source_id] += 1
            picked_links.add(candidate.link)
            picked.append(candidate)

    fill(ranked, TOP_N, capped=True)
    fill(unranked, MIN_CANDIDATES, capped=True)
    fill([*ranked, *unranked], MIN_CANDIDATES, capped=False)
    return sorted(picked, key=lambda candidate: candidate.rank or 0)


def rank_candidates(
    context: RunContext, candidates: Sequence[Candidate], llm: ChatModel
) -> list[Candidate]:
    """The top of the LLM's ranking of the pool; stores the ranks outside a dry run.

    An answer that is not a usable ranking is logged and the pool order is used
    instead: a bad answer must not cost the day's digest.
    """
    if not candidates:
        return []
    since = context.started_at - OPENS_WINDOW
    with context.sessions.begin() as session:
        interests = interest_context(session)
        opens = ArticleRepository(session).recent_opens(since, OPENS_LIMIT)

    prompt = ranking_prompt(candidates, interests, opens)
    with context.stage("ranking"):
        try:
            answer, _ = llm.complete_json(prompt, purpose="ranking", meter=context.usage)
        except InvalidJSONError as error:
            log.warning("ranking answer is not JSON", answer=error.content[:500])
            answer = None
    ranking = parse_ranking(answer, len(candidates))
    if not ranking:
        log.warning("no usable ranking; taking candidates in pool order")
    top = select_top(candidates, ranking)

    if not context.dry_run:
        ranks = {
            c.article_id: c.rank for c in top if c.article_id is not None and c.rank is not None
        }
        with context.sessions.begin() as session:
            ArticleRepository(session).set_ranks(ranks)

    context.stats["ranking"] = {
        "prompt_chars": len(prompt),
        "ranked": len(ranking),
        "top": len(top),
        "top_ranked": sum((c.rank or 0) <= len(ranking) for c in top),
        "sources": len({c.source_id for c in top}),
    }
    log.info("candidates ranked", **context.stats["ranking"])
    return top


def interest_context(session: Session) -> list[dict[str, Any]]:
    """Active interests as prompts take them."""
    return [
        {"topic": interest.topic, "keywords": interest.keywords, "notes": interest.notes}
        for interest in InterestRepository(session).find(active_only=True)
    ]


def _tally(names: Iterable[str | None]) -> list[dict[str, Any]]:
    """The most frequent names with their counts; ties keep the newest first."""
    counts = Counter(name for name in names if name)
    return [{"name": name, "count": count} for name, count in counts.most_common(OPENED_TALLY)]


def _whole_number(value: Any) -> int | None:
    """An ID as models write it: 7, 7.0 or "7"; never a bool."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
