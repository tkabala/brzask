"""Selection: the LLM picks the day's 7 from the survivors and writes them up.

Titles, summaries and "why it matters" are written in the digest language.
The answer is checked against the candidates: a link the model changed or
invented is skipped, never stored.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

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
    candidates: Sequence[Candidate],
    interests: Sequence[dict[str, Any]],
    language: Language,
    size: int = DIGEST_SIZE,
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
        digest_size=size,
        language=language,
    )


def parse_selection(
    answer: Any,
    candidates: Sequence[Candidate],
    language: Language,
    size: int = DIGEST_SIZE,
    topics: Sequence[str] = (),
) -> list[Pick]:
    """Picks from `{"articles": [...]}`, grouped by topic and numbered from 1.

    Topics keep the order in which they first appear, each read back as one of
    the interest `topics` when it is that topic with more after it (see
    `_interest_topic`); links are matched to the
    candidates (ignoring a trailing slash, and the query when the model dropped
    it and only one candidate fits), unknown and repeated ones skipped, and at
    most `size` kept. A missing title falls back to the original one.
    """
    items = answer.get("articles") if isinstance(answer, dict) else None
    if not isinstance(items, list):
        return []
    by_link = {_link_key(candidate.link): candidate for candidate in candidates}
    # Models tend to drop long tracking queries (`?utm_...`) when copying a link.
    by_path: dict[str, list[Candidate]] = {}
    for each in candidates:
        if (key := _path_key(each.link)) is not None:
            by_path.setdefault(key, []).append(each)
    chosen: list[tuple[Candidate, dict[str, Any]]] = []
    used: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or len(chosen) == size:
            continue
        link = _text(item.get("link"))
        candidate = by_link.get(_link_key(link))
        # Only a link without a query falls back: one with another query
        # (`watch?v=`, `item?id=`) names another article.
        path = _path_key(link) if candidate is None and _query(link) == "" else None
        if path is not None and len(fits := by_path.get(path, [])) == 1:
            candidate = fits[0]
        if candidate is None or candidate.link in used:
            log.info("selection names an unknown or repeated link", link=item.get("link"))
            continue
        used.add(candidate.link)
        chosen.append((candidate, item))

    groups: dict[str, list[tuple[Candidate, dict[str, Any]]]] = {}
    for candidate, item in chosen:
        topic = _interest_topic(_text(item.get("topic")), topics) or language.fallback_topic
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
    context: RunContext,
    candidates: Sequence[Candidate],
    llm: ChatModel,
    language: Language,
    size: int = DIGEST_SIZE,
) -> list[Pick]:
    """The day's picks; raises `SelectionError` when the answer names no candidate."""
    with context.sessions.begin() as session:
        interests = interest_context(session)
    prompt = selection_prompt(candidates, interests, language, size)
    with context.stage("selection"):
        answer, _ = llm.complete_json(prompt, purpose="selection", meter=context.usage)
    topics = [interest["topic"] for interest in interests]
    picks = parse_selection(answer, candidates, language, size, topics)
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


def _interest_topic(topic: str, topics: Sequence[str]) -> str:
    """The interest topic `topic` names, else `topic` itself.

    The prompt lists each interest as `topic: keywords [reader note: ...]`, and
    the model sometimes copies the whole line as the topic (one digest in 11
    days of daily runs had all five topics written that way), which names the
    groups wrongly and splits them from other days' groups. The longest
    interest topic that `topic` starts with, ignoring case and followed by
    nothing or by a character that is not a letter or digit, is taken;
    "Rustaceans" is not "Rust".
    """
    folded = topic.casefold()
    for interest in sorted(topics, key=len, reverse=True):
        name = interest.casefold()
        if folded.startswith(name) and not folded[len(name) : len(name) + 1].isalnum():
            return interest
    return topic


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _link_key(link: str) -> str:
    return link.strip().rstrip("/")


def _path_key(link: str) -> str | None:
    """The link without query and fragment; None for a link `urlsplit` rejects."""
    try:
        parts = urlsplit(link.strip())
    except ValueError:
        return None
    return _link_key(parts._replace(query="", fragment="").geturl())


def _query(link: str) -> str | None:
    try:
        return urlsplit(link.strip()).query
    except ValueError:
        return None
