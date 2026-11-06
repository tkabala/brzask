"""Atom rendering, read back the way a feed reader reads it."""

from datetime import UTC, datetime
from typing import Any

import feedparser

from brzask.api.atom import FeedEntry, atom_feed

NOW = datetime(2026, 11, 4, 7, 20, tzinfo=UTC)
ORIGIN = "https://news.example"


def entry(**overrides: Any) -> FeedEntry:
    values: dict[str, Any] = {
        "id": "urn:brzask:article:1",
        "title": "A title",
        "link": f"{ORIGIN}/open?id=1&sig=x",
        "summary": "What happened.",
        "why_it_matters": "Why: it changes things",
        "topic": "LLM news",
        "source": "Simon Willison",
        "published": NOW,
    }
    values.update(overrides)
    return FeedEntry(**values)


def parse(*entries: FeedEntry, language: str = "en") -> Any:
    body = atom_feed(list(entries), base=ORIGIN, language=language, updated=NOW)
    parsed = feedparser.parse(body)
    assert parsed.bozo == 0, parsed.get("bozo_exception")
    return parsed


def test_a_feed_reader_parses_it() -> None:
    parsed = parse(entry(title="A & <b>"), language="pl")

    assert parsed.feed.title == "brzask"
    assert parsed.feed.language == "pl"
    assert parsed.feed.id == "urn:brzask:feed"
    [item] = parsed.entries
    assert item.title == "A & <b>"
    assert item.link == f"{ORIGIN}/open?id=1&sig=x"
    assert item.id == "urn:brzask:article:1"
    assert item.tags[0].term == "LLM news"
    assert item.author == "Simon Willison"
    assert item.published_parsed[:5] == (2026, 11, 4, 7, 20)
    content = item.content[0].value
    assert "What happened." in content
    assert "Why: it changes things" in content


def test_self_link_has_no_token() -> None:
    body = atom_feed([], base=ORIGIN, language="en", updated=NOW)

    assert b'href="https://news.example/feed"' in body
    assert b"token" not in body
    assert feedparser.parse(body).bozo == 0


def test_text_is_escaped_in_content() -> None:
    [item] = parse(entry(summary="<script>x</script> & co")).entries

    # Shown as text, not run as markup.
    assert "<p>&lt;script&gt;x&lt;/script&gt; &amp; co</p>" in item.content[0].value


def test_characters_xml_forbids_are_dropped() -> None:
    [item] = parse(entry(title="a\x0bb\x1fc￾", summary="x\x00y")).entries

    assert item.title == "abc"
    assert "xy" in item.content[0].value


def test_missing_summary_and_reason_leave_no_empty_paragraphs() -> None:
    [item] = parse(entry(summary=None, why_it_matters=None, topic=None, source=None)).entries

    assert "<p></p>" not in item.get("content", [{"value": ""}])[0]["value"]
    assert "tags" not in item
    assert "author" not in item


def test_entries_keep_their_order() -> None:
    ids = [f"urn:brzask:article:{n}" for n in (3, 1, 2)]

    parsed = parse(*(entry(id=i) for i in ids))

    assert [e.id for e in parsed.entries] == ids


def test_the_feed_names_an_author_for_entries_without_a_source() -> None:
    # RFC 4287: a feed needs an author unless every entry has one.
    parsed = parse(entry(source=None))

    assert parsed.feed.author == "brzask"
