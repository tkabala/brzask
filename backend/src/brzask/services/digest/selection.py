"""Selection: the LLM picks the day's 7 from the survivors and writes them up.

Titles, summaries and "why it matters" are written in the digest language.
The answer is checked against the candidates: a link the model changed or
invented is skipped, never stored.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from brzask import prompts
from brzask.log import get_logger
from brzask.prompts import Language
from brzask.services.digest.pool import Candidate
from brzask.services.digest.ranking import ChatModel, interest_context
from brzask.services.runs import RunContext

log = get_logger(__name__)

# The digest is a fixed number of articles, not everything above a score.
DIGEST_SIZE = 7
# Characters of article text per candidate in the selection prompt.
PROMPT_TEXT_CHARS = 3000


class SelectionError(Exception):
    """The model's answer named none of the candidates; nothing is shown."""


@dataclass(frozen=True, slots=True)
class Pick:
    candidate: Candidate
    position: int  # 1-based, in topic groups
    title: str
    summary: str
    why_it_matters: str
    topic: str


def selection_prompt(
    candidates: Sequence[Candidate], interests: Sequence[dict[str, Any]], language: Language
) -> str:
    return prompts.render(
        "selection",
        interests=interests,
        candidates=[
            {
                "title": candidate.title,
                "link": candidate.link,
                "source": candidate.source_name,
                "published": (
                    candidate.published_at.date().isoformat() if candidate.published_at else None
                ),
                "rank": candidate.rank,
                "release": candidate.release,
                "text": (candidate.text or candidate.snippet or "")[:PROMPT_TEXT_CHARS],
            }
            for candidate in candidates
        ],
        digest_size=DIGEST_SIZE,
        language=language,
    )


def parse_selection(answer: Any, candidates: Sequence[Candidate], language: Language) -> list[Pick]:
    """Picks from `{"articles": [...]}`, grouped by topic and numbered from 1.

    Topics keep the order in which they first appear; links are matched to the
    candidates (ignoring a trailing slash), unknown and repeated ones skipped,
    and at most DIGEST_SIZE kept. A missing title falls back to the original one.
    """
    items = answer.get("articles") if isinstance(answer, dict) else None
    if not isinstance(items, list):
        return []
    by_link = {_link_key(candidate.link): candidate for candidate in candidates}
    chosen: list[tuple[Candidate, dict[str, Any]]] = []
    used: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or len(chosen) == DIGEST_SIZE:
            continue
        candidate = by_link.get(_link_key(_text(item.get("link"))))
        if candidate is None or candidate.link in used:
            log.info("selection names an unknown or repeated link", link=item.get("link"))
            continue
        used.add(candidate.link)
        chosen.append((candidate, item))

    groups: dict[str, list[tuple[Candidate, dict[str, Any]]]] = {}
    for candidate, item in chosen:
        topic = _text(item.get("topic")) or language.fallback_topic
        groups.setdefault(topic, []).append((candidate, item))
    ordered = [(topic, pair) for topic, pairs in groups.items() for pair in pairs]
    return [
        Pick(
            candidate=candidate,
            position=position,
            title=_text(item.get("title")) or candidate.title,
            summary=_text(item.get("summary")),
            why_it_matters=_text(item.get("whyItMatters")),
            topic=topic,
        )
        for position, (topic, (candidate, item)) in enumerate(ordered, start=1)
    ]


def select_digest(
    context: RunContext, candidates: Sequence[Candidate], llm: ChatModel, language: Language
) -> list[Pick]:
    """The day's picks; raises `SelectionError` when the answer names no candidate."""
    with context.sessions.begin() as session:
        interests = interest_context(session)
    prompt = selection_prompt(candidates, interests, language)
    with context.stage("selection"):
        answer, _ = llm.complete_json(prompt, purpose="selection", meter=context.usage)
    picks = parse_selection(answer, candidates, language)
    if not picks:
        raise SelectionError("the selection answer named none of the candidates")
    context.stats["selection"] = {
        "prompt_chars": len(prompt),
        "candidates": len(candidates),
        "picked": len(picks),
        "topics": list(dict.fromkeys(pick.topic for pick in picks)),
    }
    log.info("digest selected", **context.stats["selection"])
    return picks


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _link_key(link: str) -> str:
    return link.strip().rstrip("/")
