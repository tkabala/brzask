"""What the model sees for an answer, built fresh for every question.

In order: the reader's interests, the article, its brief, its finished deep
dives, the conversation's sources, the last exchanges and the question.
Everything third parties or a model wrote is inside `<untrusted>` marks; the
reader's questions stay outside them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from brzask import prompts
from brzask.db.models import (
    Article,
    ArticleBrief,
    ArticleContent,
    ConversationMessage,
    ConversationSource,
    ConversationSourceOrigin,
    DeepDive,
    DeepDiveStatus,
    MessageRole,
    MessageStatus,
)
from brzask.prompts import Language
from brzask.repositories.conversations import NewSource
from brzask.services.briefs import BRIEF_INPUT_CHARS, clip
from brzask.services.conversation.answer import Answer

# Starting values, confirmed or corrected by the real checks.
HISTORY_EXCHANGES = 20  # earlier questions and answers the model sees
SEARCHED_CHARS = 60_000  # characters of searched texts shared by all sources

_DIVE_ORIGINS = {
    "web": ConversationSourceOrigin.REPORT,
    "archive": ConversationSourceOrigin.ARCHIVE,
}


@dataclass(frozen=True, slots=True)
class SourceView:
    n: int
    title: str
    url: str
    text: str | None


@dataclass(frozen=True, slots=True)
class Exchange:
    question: str
    answer: str


def dive_sources(dives: Sequence[DeepDive]) -> list[NewSource]:
    """Sources of the finished dives, the article (their number 1) left out, without text."""
    found: list[NewSource] = []
    for dive in dives:
        if dive.status is not DeepDiveStatus.DONE:
            continue
        for item in dive.sources:
            origin = _DIVE_ORIGINS.get(str(item.get("origin")))
            if item.get("n") == 1 or origin is None:
                continue
            found.append(
                NewSource(str(item["url"]), str(item["title"]), origin, item.get("article_id"))
            )
    return found


def fit_sources(
    sources: Sequence[ConversationSource], limit: int = SEARCHED_CHARS
) -> list[SourceView]:
    """Every source by number; texts go to the newest sources while whole texts fit
    in `limit`, the rest are given by title and link. The article's text (1) is
    given on its own, never here."""
    with_text: set[int] = set()
    left = limit
    for source in sorted(sources, key=lambda s: s.n, reverse=True):
        if source.n == 1 or source.text is None or len(source.text) > left:
            continue
        with_text.add(source.n)
        left -= len(source.text)
    return [
        SourceView(s.n, s.title, s.url, s.text if s.n in with_text else None)
        for s in sorted(sources, key=lambda s: s.n)
    ]


def history(
    messages: Sequence[ConversationMessage], limit: int = HISTORY_EXCHANGES
) -> list[Exchange]:
    """The last `limit` questions with a finished answer, oldest first."""
    exchanges: list[Exchange] = []
    asked: str | None = None
    for message in messages:
        if message.role is MessageRole.USER:
            asked = message.text
            continue
        if asked is not None and message.status is MessageStatus.DONE and message.answer:
            exchanges.append(Exchange(asked, Answer.from_json(message.answer).text))
        asked = None
    return exchanges[-limit:] if limit else []


def dive_views(dives: Sequence[DeepDive], numbers: Mapping[str, int]) -> list[dict[str, Any]]:
    """Each finished dive's focus and report, its source numbers translated to the
    conversation's by link; a number without one is dropped."""
    views: list[dict[str, Any]] = []
    for dive in dives:
        if dive.status is not DeepDiveStatus.DONE or not dive.report:
            continue
        own = {int(s["n"]): numbers.get(str(s["url"])) for s in dive.sources}

        def mapped(values: Sequence[Any], own: dict[int, int | None] = own) -> list[int]:
            return [n for value in values if (n := own.get(value)) is not None]

        report = dive.report
        views.append(
            {
                "focus": dive.focus,
                "background": [
                    {"text": p["text"], "sources": mapped(p["sources"])}
                    for p in report.get("background", [])
                ],
                "practice": [
                    {
                        "text": s["text"],
                        "command": s.get("command"),
                        "sources": mapped(s["sources"]),
                    }
                    for s in report.get("practice", [])
                ],
                "further": [
                    {"source": n, "why": r["why"]}
                    for r in report.get("further", [])
                    if (n := own.get(r["source"])) is not None
                ],
            }
        )
    return views


def prompt(
    article: Article,
    content: ArticleContent,
    brief: ArticleBrief | None,
    dives: Sequence[DeepDive],
    sources: Sequence[ConversationSource],
    messages: Sequence[ConversationMessage],
    question: str,
    interests: Sequence[dict[str, Any]],
    language: Language,
) -> str:
    """The prompt for an answer to `question`."""
    text, clipped = clip(content.text, BRIEF_INPUT_CHARS)
    return prompts.render(
        "conversation",
        interests=interests,
        title=article.title,
        source=article.source.name if article.source is not None else None,
        kind=content.kind.value,
        text=text,
        partial=clipped,
        brief=None
        if brief is None
        else {"gist": brief.gist, "points": brief.points, "caveats": brief.caveats},
        dives=dive_views(dives, {s.url: s.n for s in sources}),
        sources=fit_sources(sources),
        history=history(messages),
        question=question,
        language=language,
    )
