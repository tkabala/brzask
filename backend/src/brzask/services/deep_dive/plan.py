"""The plan stage: what to search for, in the web and in the archive."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from brzask import prompts
from brzask.clients.llm import LLMError
from brzask.clients.usage import UsageMeter
from brzask.db.models import Article, ArticleBrief, ArticleContent
from brzask.log import get_logger
from brzask.prompts import Language
from brzask.services.briefs import BRIEF_INPUT_CHARS, clip
from brzask.services.digest.ranking import ChatModel

log = get_logger(__name__)

# Starting values, confirmed or corrected by the real checks before release.
MAX_BACKGROUND = 3
MAX_PRACTICE = 3
MAX_ARCHIVE = 2
QUERY_CHARS = 200


@dataclass(frozen=True, slots=True)
class Queries:
    background: list[str] = field(default_factory=list)
    practice: list[str] = field(default_factory=list)
    archive: list[str] = field(default_factory=list)


def parse_queries(answer: Any, title: str) -> Queries:
    """The model's queries, cleaned; the title alone when nothing usable is left.

    Queries are stripped, cut to `QUERY_CHARS`, blank ones and repeats (case
    ignored) dropped, and each list cut to its maximum.
    """
    if not isinstance(answer, dict):
        answer = {}
    queries = Queries(
        _queries(answer.get("background"), MAX_BACKGROUND),
        _queries(answer.get("practice"), MAX_PRACTICE),
        _queries(answer.get("archive"), MAX_ARCHIVE),
    )
    if not queries.background and not queries.practice:
        title = title.strip()[:QUERY_CHARS]
        return Queries([title], [], [title])
    return queries


def plan_queries(
    llm: ChatModel,
    article: Article,
    brief: ArticleBrief | None,
    content: ArticleContent,
    interests: Sequence[dict[str, Any]],
    focus: str,
    language: Language,
    meter: UsageMeter | None,
) -> Queries:
    """Search queries for a deep dive on `article`; the title when the model fails."""
    text, _ = clip(content.text, BRIEF_INPUT_CHARS)
    prompt = prompts.render(
        "deep_dive_plan",
        interests=interests,
        title=article.title,
        gist=brief.gist if brief is not None else None,
        points=brief.points if brief is not None else [],
        text=text,
        focus=focus,
        language=language,
    )
    try:
        answer, _ = llm.complete_json(prompt, purpose="deep_dive_plan", meter=meter)
    except LLMError as error:
        log.warning("deep dive plan failed; searching for the title", error=str(error))
        answer = None
    return parse_queries(answer, article.title)


def _queries(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    queries: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        query = item.strip()[:QUERY_CHARS].strip()
        if query and query.casefold() not in seen:
            seen.add(query.casefold())
            queries.append(query)
    return queries[:limit]
