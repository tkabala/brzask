"""Briefs: what each picked article says, written ahead for reading on a phone.

After the digest run has stored the day's picks, the `briefs` stage writes one
brief per digest article from its stored text: a gist, points with their
specifics, caveats and, for videos, chapters with timestamps. The model's
answer is checked against that shape and cleaned to it (empty items dropped,
lists cut to their maximum, chapters outside the video dropped); an answer
that cannot be cleaned is asked for once more, then the article is counted as
failed and tried again by the next run while it is recent. Nothing in the
stage ever fails the digest run.
"""

import re
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from brzask import prompts
from brzask.clients.extractors.base import MIN_CHARS
from brzask.clients.llm import InvalidJSONError
from brzask.clients.usage import UsageMeter
from brzask.db.models import Article, ArticleContent, BriefBasis, ContentKind
from brzask.log import get_logger
from brzask.prompts import Language
from brzask.repositories import BriefRepository
from brzask.repositories.briefs import Brief, Chapter
from brzask.services.digest.ranking import ChatModel, interest_context
from brzask.services.runs import RunContext

__all__ = [
    "BRIEF_INPUT_CHARS",
    "Brief",
    "BriefError",
    "Chapter",
    "basis",
    "clip",
    "last_marker",
    "parse_brief",
    "write_brief",
    "write_missing",
]

log = get_logger(__name__)

# Characters of stored text the model reads. Covers the longest picked text
# seen, 115k characters (the transcript of a 2-hour video); a longer text is
# cut at a paragraph and the brief marked partial.
BRIEF_INPUT_CHARS = 120_000

# The prompt asks for 4-7 points; three good ones still make a brief.
MIN_POINTS = 3
MAX_POINTS = 7
MAX_CAVEATS = 3
MAX_CHAPTERS = 8

# A paragraph marker of a transcript: `[mm:ss]` or `[h:mm:ss]` at its start.
_MARKER = re.compile(r"^\[(\d+):(\d{2})(?::(\d{2}))?\]", re.MULTILINE)


class BriefError(Exception):
    """The model's answer cannot be cleaned into a brief."""


def clip(text: str, limit: int = BRIEF_INPUT_CHARS) -> tuple[str, bool]:
    """`text` cut to at most `limit` characters, and whether it was cut.

    The cut is at the last blank line before the limit, so it never splits a
    paragraph; a text without one there is cut at the limit itself.
    """
    if len(text) <= limit:
        return text, False
    end = text.rfind("\n\n", 0, limit)
    if end <= 0:
        return text[:limit], True
    return text[:end].rstrip(), True


def last_marker(text: str) -> int | None:
    """Seconds of the latest paragraph marker in a transcript; None without markers."""
    seconds = [_seconds(match) for match in _MARKER.finditer(text)]
    return max(seconds) if seconds else None


def basis(kind: ContentKind, clipped: bool) -> BriefBasis:
    """What a brief was written from; a cut text is partial whatever its kind."""
    if clipped:
        return BriefBasis.PARTIAL
    return {
        ContentKind.PAGE: BriefBasis.FULL_TEXT,
        ContentKind.TRANSCRIPT: BriefBasis.TRANSCRIPT,
        ContentKind.DESCRIPTION: BriefBasis.DESCRIPTION,
    }[kind]


def parse_brief(answer: Any, kind: ContentKind, last_second: int | None) -> Brief:
    """The brief in `answer`, cleaned to the contract; raises `BriefError`.

    `gist` must be non-empty text and at least `MIN_POINTS` points must be
    left once empty ones are dropped; points over `MAX_POINTS` and caveats
    over `MAX_CAVEATS` are cut. Chapters are kept for a transcript only: each
    needs a title and a whole-second start within the video (0 to
    `last_second`, the latest marker the model saw), and they are sorted by
    start, one per start, at most `MAX_CHAPTERS`. A missing or null list is an
    empty one; a list field of another type is an error (chapters: of a
    transcript).
    """
    if not isinstance(answer, dict):
        raise BriefError(f"the answer is not an object: {type(answer).__name__}")
    gist = _text(answer.get("gist"))
    if not gist:
        raise BriefError("the answer has no gist")
    points = _texts(answer, "points")
    if len(points) < MIN_POINTS:
        raise BriefError(f"the answer has {len(points)} points, fewer than {MIN_POINTS}")
    caveats = _texts(answer, "caveats")
    # Whatever a model writes as chapters of a page is ignored, not an error.
    chapters = (
        _chapters(_list(answer, "chapters"), last_second) if kind is ContentKind.TRANSCRIPT else []
    )
    return Brief(
        gist=gist, points=points[:MAX_POINTS], caveats=caveats[:MAX_CAVEATS], chapters=chapters
    )


def write_brief(
    llm: ChatModel,
    content: ArticleContent,
    article: Article,
    interests: Sequence[dict[str, Any]],
    language: Language,
    meter: UsageMeter | None,
) -> tuple[Brief, BriefBasis, str]:
    """The brief of one article, what it was written from, and the model that wrote it.

    One call, asked once more when the answer is not JSON or cannot be
    cleaned into a brief; raises `BriefError` or `InvalidJSONError` when the
    second answer fails too, and lets other errors of the call through.
    """
    text, clipped = clip(content.text, BRIEF_INPUT_CHARS)
    prompt = prompts.render(
        "brief",
        interests=interests,
        title=article.title,
        source=article.source.name if article.source is not None else None,
        kind=content.kind.value,
        text=text,
        partial=clipped,
        language=language,
    )
    last_second = last_marker(text) if content.kind is ContentKind.TRANSCRIPT else None
    for attempt in (1, 2):
        try:
            answer, completion = llm.complete_json(prompt, purpose="brief", meter=meter)
            brief = parse_brief(answer, content.kind, last_second)
        except (BriefError, InvalidJSONError) as error:
            if attempt == 2:
                raise
            log.info("brief answer unusable; asking again", article_id=article.id, error=str(error))
            continue
        return brief, basis(content.kind, clipped), completion.usage.model
    raise AssertionError("unreachable")  # pragma: no cover


def write_missing(context: RunContext, llm: ChatModel, language: Language, day: date) -> None:
    """Write the briefs that digest articles of `day` and the day before still lack.

    The day before is included so an article whose brief failed is tried once
    more by the next day's run, and not later. Each brief is stored in its own
    transaction, so one failure loses only that brief; a text under
    `MIN_CHARS` gets none. Counts go to `context.stats["briefs"]`.
    """
    stats = {"written": 0, "failed": 0, "skipped": 0}
    context.stats["briefs"] = stats
    with context.stage("briefs"):
        with context.sessions.begin() as session:
            missing = BriefRepository(session).missing(since=day - timedelta(days=1))
            interests = interest_context(session)
        for article, content in missing:
            if len(content.text.strip()) < MIN_CHARS:
                stats["skipped"] += 1
                continue
            try:
                brief, written_on, model = write_brief(
                    llm, content, article, interests, language, context.usage
                )
                with context.sessions.begin() as session:
                    BriefRepository(session).save(article.id, brief, written_on, model)
            except Exception as error:
                # One article's failure, whatever it is, must not cost the others theirs.
                log.warning(
                    "brief not written",
                    article_id=article.id,
                    error=f"{type(error).__name__}: {error}",
                )
                stats["failed"] += 1
                continue
            stats["written"] += 1
    log.info("briefs written", **stats)


def _seconds(match: re.Match[str]) -> int:
    first, second, third = match.groups()
    if third is None:  # mm:ss
        return int(first) * 60 + int(second)
    return int(first) * 3600 + int(second) * 60 + int(third)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _list(answer: dict[str, Any], key: str) -> list[Any]:
    value = answer.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise BriefError(f"{key!r} is not a list: {type(value).__name__}")
    return value


def _texts(answer: dict[str, Any], key: str) -> list[str]:
    """The non-empty strings of a list field, stripped; other items are dropped."""
    return [text for item in _list(answer, key) if (text := _text(item))]


def _chapters(items: list[Any], last_second: int | None) -> list[Chapter]:
    if last_second is None:  # a transcript without markers has no time range to check
        return []
    chapters: list[Chapter] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start, title = _whole_second(item.get("start")), _text(item.get("title"))
        if start is not None and title and 0 <= start <= last_second:
            chapters.append(Chapter(start, title))
    unique: dict[int, Chapter] = {}
    for chapter in sorted(chapters, key=lambda chapter: chapter.start):
        unique.setdefault(chapter.start, chapter)
    return list(unique.values())[:MAX_CHAPTERS]


def _whole_second(value: Any) -> int | None:
    """A start as models write it: 754 or 754.0; never a bool, a fraction or a string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
