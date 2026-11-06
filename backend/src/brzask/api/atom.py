"""The digest as an Atom feed (RFC 4287), for feed readers.

Rendering only: the route decides which articles go in and how their links
are signed.
"""

import html
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from brzask.text import xml_chars

ATOM = "http://www.w3.org/2005/Atom"
FEED_ID = "urn:brzask:feed"
TITLE = "brzask"

ET.register_namespace("", ATOM)


@dataclass(frozen=True, slots=True)
class FeedEntry:
    id: str  # urn:brzask:article:<id>
    title: str
    link: str  # absolute; through /open, so following it records the open
    summary: str | None
    why_it_matters: str | None
    topic: str | None
    source: str | None
    published: datetime  # aware


def atom_feed(
    entries: Sequence[FeedEntry], *, base: str, language: str, updated: datetime
) -> bytes:
    """The feed document; `base` is the server's public address with its path prefix,
    without a trailing slash (`https://home.example/brzask`)."""
    feed = ET.Element(_tag("feed"), {"xml:lang": language})
    _text(feed, "id", FEED_ID)
    _text(feed, "title", TITLE)
    _text(feed, "updated", _date(updated))
    # The self link leaves the token out: the document must not repeat it.
    _link(feed, f"{base}/feed", rel="self", type="application/atom+xml")
    _link(feed, f"{base}/", rel="alternate", type="text/html")
    _text(feed, "generator", TITLE)
    # RFC 4287 wants a feed author unless every entry has one; an article
    # whose source was removed has none.
    author = ET.SubElement(feed, _tag("author"))
    _text(author, "name", TITLE)
    for item in entries:
        feed.append(_entry(item))
    document: bytes = ET.tostring(feed, encoding="utf-8", xml_declaration=True)
    return document


def _entry(item: FeedEntry) -> ET.Element:
    entry = ET.Element(_tag("entry"))
    _text(entry, "id", item.id)
    _text(entry, "title", item.title)
    _link(entry, item.link, rel="alternate", type="text/html")
    _text(entry, "published", _date(item.published))
    _text(entry, "updated", _date(item.published))
    if item.source:
        author = ET.SubElement(entry, _tag("author"))
        _text(author, "name", item.source)
    if item.topic:
        ET.SubElement(entry, _tag("category"), {"term": xml_chars(item.topic)})
    paragraphs = [
        f"<p>{html.escape(xml_chars(text), quote=False)}</p>"
        for text in (item.summary, item.why_it_matters)
        if text
    ]
    if paragraphs:
        _text(entry, "content", "".join(paragraphs), type="html")
    return entry


def _tag(name: str) -> str:
    return f"{{{ATOM}}}{name}"


def _text(parent: ET.Element, name: str, value: str, **attributes: str) -> None:
    ET.SubElement(parent, _tag(name), attributes).text = xml_chars(value)


def _link(parent: ET.Element, href: str, **attributes: str) -> None:
    ET.SubElement(parent, _tag("link"), {"href": xml_chars(href), **attributes})


def _date(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
