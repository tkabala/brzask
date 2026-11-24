from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from brzask import prompts
from brzask.db.models import (
    Article,
    ConversationMessage,
    ConversationSource,
    ConversationSourceOrigin,
    MessageRole,
    MessageStatus,
)
from brzask.services.conversation.markdown import filename, render_conversation

AT = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
ARTICLE = Article(id=1, title="Postgres 18 (async I/O)", link="https://pg.example/18?utm_source=x")


def question(text: str, at: datetime = AT) -> ConversationMessage:
    return ConversationMessage(
        role=MessageRole.USER, status=MessageStatus.DONE, text=text, created_at=at, finished_at=at
    )


def answer(
    paragraphs: list[tuple[str, list[int]]],
    at: datetime = AT,
    status: MessageStatus = MessageStatus.DONE,
) -> ConversationMessage:
    return ConversationMessage(
        role=MessageRole.ASSISTANT,
        status=status,
        answer={
            "answer": [{"text": text, "sources": numbers} for text, numbers in paragraphs],
            "enough": True,
            "suggestions": ["Not exported?"],
        },
        created_at=at,
        finished_at=at,
    )


def source(n: int, title: str, url: str) -> ConversationSource:
    return ConversationSource(
        n=n, title=title, url=url, origin=ConversationSourceOrigin.WEB, text="Not exported."
    )


SOURCES = [
    source(1, "Postgres 18", "https://pg.example/18"),
    source(2, "Never cited", "https://unused.example/"),
    source(3, "io docs", "https://docs.example/io"),
    source(4, "Wiki", "https://wiki.example/AIO_(Postgres)"),
]

MESSAGES = [
    question("What is *new*?"),
    answer([("Reads go async.", [1]), ("It needs io_uring.", [3, 1])]),
    question("Is it faster?"),
    answer([], status=MessageStatus.FAILED),
    question("And on ZFS?", AT + timedelta(hours=2)),
    answer([("Not measured yet.", [4])], AT + timedelta(hours=2, minutes=1)),
    question("Still writing?", AT + timedelta(hours=3)),
    ConversationMessage(role=MessageRole.ASSISTANT, status=MessageStatus.ANSWERING),
]

ENGLISH = """\
# Postgres 18 (async I/O)

2026-11-24 · https://pg.example/18

## Conversation

**What is \\*new\\*?**

Reads go async. [1]

It needs io\\_uring. [3][1]

**And on ZFS?**

Not measured yet. [4]

## Sources

- [1] [Postgres 18](https://pg.example/18)
- [3] [io docs](https://docs.example/io)
- [4] [Wiki](https://wiki.example/AIO_%28Postgres%29)
"""


def test_render_in_english() -> None:
    assert render_conversation(ARTICLE, MESSAGES, SOURCES, prompts.language("en")) == ENGLISH


def test_render_in_polish_with_the_local_date() -> None:
    late = [
        question("Co nowego?", AT),
        answer([("Odczyty.", [1])], datetime(2026, 11, 24, 23, 30, tzinfo=UTC)),
    ]
    text = render_conversation(
        ARTICLE, late, SOURCES, prompts.language("pl"), ZoneInfo("Europe/Warsaw")
    )
    assert text.splitlines()[2] == "2026-11-25 · https://pg.example/18"
    assert "## Rozmowa" in text and "## Źródła" in text
    assert "Never cited" not in text and "Not exported" not in text


def test_a_hostile_title_cannot_change_a_link_target() -> None:
    hostile = [source(1, "x](https://evil.example/) [y", "https://pg.example/18")]
    text = render_conversation(
        ARTICLE, [question("Q?"), answer([("A.", [1])])], hostile, prompts.language("en")
    )
    assert "](https://evil.example/)" not in text
    assert "(https://pg.example/18)" in text


def test_filename() -> None:
    messages = [question("Q?"), answer([("A.", [1])])]
    assert filename(ARTICLE, messages) == "2026-11-24-postgres-18-async-i-o-conversation.md"
