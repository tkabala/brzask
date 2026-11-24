"""A conversation as Markdown, for notes apps.

Escaped and linked like a deep dive's export: no question, answer or title
can add structure or change where a link points. Only answered questions
are kept, and only the sources their answers cite, under their own numbers.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, tzinfo

from brzask.db.models import (
    Article,
    ConversationMessage,
    ConversationSource,
    MessageRole,
    MessageStatus,
)
from brzask.prompts import Language
from brzask.services.conversation.answer import Answer
from brzask.services.deep_dive.markdown import escape, link_target, slug, without_tracking

HEADINGS: dict[str, dict[str, str]] = {
    "en": {"conversation": "Conversation", "sources": "Sources"},
    "pl": {"conversation": "Rozmowa", "sources": "Źródła"},
}


def answered(messages: Sequence[ConversationMessage]) -> list[tuple[str, Answer, datetime]]:
    """Each question with its finished answer and when that answer ended, in order."""
    pairs: list[tuple[str, Answer, datetime]] = []
    asked: str | None = None
    for message in messages:
        if message.role is MessageRole.USER:
            asked = message.text
            continue
        if asked is not None and message.status is MessageStatus.DONE and message.answer:
            at = message.finished_at or message.created_at
            pairs.append((asked, Answer.from_json(message.answer), at))
        asked = None
    return pairs


def render_conversation(
    article: Article,
    messages: Sequence[ConversationMessage],
    sources: Sequence[ConversationSource],
    language: Language,
    tz: tzinfo = UTC,
) -> str:
    """The answered part of the conversation, headings in `language`, dated in `tz`."""
    words = HEADINGS.get(language.code, HEADINGS["en"])
    pairs = answered(messages)
    lines = [f"# {escape(article.digest_title or article.title)}", ""]
    if pairs:
        lines.append(f"{pairs[-1][2].astimezone(tz):%Y-%m-%d} · {_target(article.link)}")
    else:
        lines.append(_target(article.link))
    lines += ["", f"## {words['conversation']}", ""]
    cited: set[int] = set()
    for question, answer, _ in pairs:
        lines += [f"**{escape(question)}**", ""]
        for paragraph in answer.paragraphs:
            marks = "".join(f"[{n}]" for n in paragraph.sources)
            lines += [f"{escape(paragraph.text)} {marks}".rstrip(), ""]
            cited.update(paragraph.sources)
    listed = [s for s in sorted(sources, key=lambda s: s.n) if s.n in cited]
    if listed:
        lines += [f"## {words['sources']}", ""]
        # A bullet list: an ordered list would renumber sources whose numbers skip.
        lines += [f"- [{s.n}] [{escape(s.title)}]({_target(s.url)})" for s in listed]
    return "\n".join(lines).rstrip("\n") + "\n"


def filename(article: Article, messages: Sequence[ConversationMessage], tz: tzinfo = UTC) -> str:
    """`<date of the last answer>-<ascii slug of the title>-conversation.md`."""
    pairs = answered(messages)
    at = pairs[-1][2] if pairs else datetime.now(UTC)
    title = slug(article.digest_title or article.title, "article")
    return f"{at.astimezone(tz):%Y-%m-%d}-{title}-conversation.md"


def _target(url: str) -> str:
    return link_target(without_tracking(url))
