"""Marking what third parties wrote.

Feed entries and web pages are written by anyone, and the summaries and
reasons brzask stores were written by a model reading them. In tool results
such text sits under an `external` key, which the server's instructions tell
agents to treat as data only.
"""

# Enough of an article to judge it, short enough that a few fit in a reply.
TEXT_CHARS = 8000


def cap(text: str | None, limit: int = TEXT_CHARS) -> tuple[str | None, bool]:
    """`text` cut to `limit` characters, and whether it was cut."""
    if text is None or len(text) <= limit:
        return text, False
    return text[:limit], True
