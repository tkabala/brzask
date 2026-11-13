"""Sources in and out as OPML, the subscription list every feed reader exports.

An import checks every feed before it becomes a source: the feed URL first,
then the site's page when the feed no longer answers (feeds move, and the
page's autodetection finds where to). Imported feeds wait for a decision as
`pending` sources, unless the reader asks to follow them right away.
"""

import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import format_datetime
from xml.etree.ElementTree import Element

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.feed_finder import FoundFeed, with_scheme
from brzask.clients.http import AddressNotAllowedError
from brzask.concurrency import ContextThreadPoolExecutor
from brzask.db.models import Source, SourceOrigin, SourceStatus
from brzask.log import get_logger
from brzask.repositories import SourceRepository
from brzask.services.errors import ServiceError
from brzask.services.sources import SiteFeedFinder, propose_source
from brzask.text import xml_chars
from brzask.urls import is_http_url

log = get_logger(__name__)

TITLE = "brzask sources"
# A feed that is down for now (429, 5xx) cannot be told from one that is gone;
# the reason says both, and importing the file again retries it.
NO_FEED = "no working RSS or Atom feed found (the site may be down for now)"
# As many lookups at once as the daily feed fetch makes.
WORKERS = 8


@dataclass(frozen=True, slots=True)
class Outline:
    """One feed of an OPML file."""

    xml_url: str | None  # the feed
    html_url: str | None  # its site; the only URL of an outline that names a site
    title: str | None
    folder: str | None  # the outline it is nested in, as feed readers group feeds

    @property
    def url(self) -> str:
        """The URL the outline is known by: its feed, or its site."""
        return self.xml_url or self.html_url or ""


@dataclass(frozen=True, slots=True)
class Imported:
    id: int
    name: str
    url: str
    status: SourceStatus


@dataclass(frozen=True, slots=True)
class Known:
    url: str  # as in the file
    name: str  # of the source that has it
    status: SourceStatus


@dataclass(frozen=True, slots=True)
class Failed:
    url: str
    reason: str


@dataclass(slots=True)
class ImportReport:
    added: list[Imported] = field(default_factory=list)
    known: list[Known] = field(default_factory=list)
    failed: list[Failed] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)  # not looked up before the deadline


def parse_opml(data: bytes | str) -> list[Outline]:
    """The feeds of an OPML file, in file order, one per URL.

    Folders (outlines that only hold others) are walked, not returned. An
    outline without a feed URL but with a page is a site whose feed is looked
    up on import. Attribute names are matched ignoring case, as some readers
    write `xmlurl`. DTDs are refused: an OPML file needs none, and entities are
    how XML files blow up a parser. Text that was already decoded is read as
    it is, whatever encoding its declaration names.
    """
    try:
        root = fromstring(data, forbid_dtd=True)
    except DefusedXmlException as error:
        raise ServiceError(f"not an OPML file: {error}") from error
    except ET.ParseError as error:
        raise ServiceError(f"not an OPML file: {error}") from error
    if _local(root.tag) != "opml":
        raise ServiceError(f"not an OPML file: the root element is <{_local(root.tag)}>")
    body = next((child for child in root if _local(child.tag) == "body"), None)
    if body is None:
        raise ServiceError("not an OPML file: it has no <body>")
    outlines: dict[str, Outline] = {}
    for outline in _walk(body, None):
        outlines.setdefault(outline.url, outline)
    return list(outlines.values())


def _walk(parent: Element, folder: str | None) -> Iterable[Outline]:
    for element in parent:
        if _local(element.tag) != "outline":
            continue
        attributes = {key.lower(): value.strip() for key, value in element.attrib.items()}
        title = attributes.get("title") or attributes.get("text") or None
        xml_url = attributes.get("xmlurl") or None
        children = [child for child in element if _local(child.tag) == "outline"]
        html_url = attributes.get("htmlurl") or None
        if xml_url or (html_url and not children):
            yield Outline(xml_url, html_url, title, folder)
        if children:
            yield from _walk(element, title or folder)


def _local(tag: str) -> str:
    """A tag without its namespace."""
    return tag.rpartition("}")[2]


def render_opml(sources: Sequence[Source], created: datetime) -> bytes:
    """An OPML 2.0 file of `sources`, one outline each, in the given order."""
    root = ET.Element("opml", version="2.0")
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "title").text = TITLE
    ET.SubElement(head, "dateCreated").text = format_datetime(created)
    body = ET.SubElement(root, "body")
    for source in sources:
        attributes = {
            "type": "rss",
            "text": xml_chars(source.name),
            "title": xml_chars(source.name),
            "xmlUrl": xml_chars(source.url),
        }
        if source.site_url:
            attributes["htmlUrl"] = xml_chars(source.site_url)
        ET.SubElement(body, "outline", attributes)
    ET.indent(root)
    document: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return document + b"\n"


def import_outlines(
    sessions: sessionmaker[Session],
    finder: SiteFeedFinder,
    outlines: Sequence[Outline],
    *,
    actor: str,
    active: bool = False,
    deadline: float | None = None,
    workers: int = WORKERS,
    clock: Callable[[], float] = time.monotonic,
) -> ImportReport:
    """Add the feeds of `outlines` that are not sources yet, after checking each one.

    Feeds known in any status are left as they are, so a rejected feed is not
    proposed again and importing the same file twice adds nothing. Lookups run
    `workers` at a time; those not finished by `deadline` (a `clock` reading)
    are reported as unchecked and the file can simply be imported again.
    """
    report = ImportReport()
    with sessions.begin() as session:
        lookup: list[Outline] = []
        for outline in outlines:
            known = _known(session, outline.xml_url)
            if known is not None:
                report.known.append(Known(outline.url, known.name, known.status))
            elif not any(is_http_url(with_scheme(url)) for url in _urls(outline)):
                report.failed.append(Failed(outline.url, "not an http(s) URL"))
            else:
                lookup.append(outline)

    found, unchecked = _look_up(finder, lookup, workers, deadline, clock)
    status = SourceStatus.ACTIVE if active else SourceStatus.PENDING
    for outline in lookup:
        if outline.url in unchecked:
            report.unchecked.append(outline.url)
            continue
        feed = found.get(outline.url)
        if feed is None:
            report.failed.append(Failed(outline.url, NO_FEED))
            continue
        with sessions.begin() as session:
            source = propose_source(
                session,
                feed,
                status=status,
                origin=SourceOrigin.OPML,
                actor=actor,
                origin_detail=outline.folder,
                note=None if active else "In an imported OPML file.",
                name=outline.title,
            )
            if source is not None:
                report.added.append(Imported(source.id, source.name, source.url, source.status))
            elif (known := _known(session, feed.url)) is not None:
                report.known.append(Known(outline.url, known.name, known.status))
    log.info(
        "opml imported",
        outlines=len(outlines),
        added=len(report.added),
        known=len(report.known),
        failed=len(report.failed),
        unchecked=len(report.unchecked),
    )
    return report


def _known(session: Session, url: str | None) -> Source | None:
    return SourceRepository(session).get_by_url(with_scheme(url)) if url else None


def _urls(outline: Outline) -> list[str]:
    return list(dict.fromkeys(url for url in (outline.xml_url, outline.html_url) if url))


def _look_up(
    finder: SiteFeedFinder,
    outlines: Sequence[Outline],
    workers: int,
    deadline: float | None,
    clock: Callable[[], float],
) -> tuple[dict[str, FoundFeed], set[str]]:
    """The feed found for each outline's URL, and the URLs not looked up in time."""
    found: dict[str, FoundFeed] = {}
    stopped = threading.Event()
    pool = ContextThreadPoolExecutor(max_workers=workers)
    futures: dict[Future[FoundFeed | None], Outline] = {
        pool.submit(_find, finder, outline, stopped): outline for outline in outlines
    }
    done: set[str] = set()
    try:
        timeout = None if deadline is None else max(0.0, deadline - clock())
        for future in as_completed(futures, timeout=timeout):
            outline = futures[future]
            done.add(outline.url)
            if (feed := future.result()) is not None:
                found[outline.url] = feed
    except FuturesTimeout:
        log.info("opml lookups stopped at the deadline", done=len(done), total=len(futures))
    finally:
        # Lookups still running only read; their results are dropped, and the
        # finder may be closed under them.
        stopped.set()
        pool.shutdown(wait=deadline is None, cancel_futures=True)
    return found, {outline.url for outline in outlines} - done


def _find(finder: SiteFeedFinder, outline: Outline, stopped: threading.Event) -> FoundFeed | None:
    """The feed at the outline's feed URL, else the one its site points to."""
    for url in _urls(outline):
        if stopped.is_set():
            return None
        try:
            if (feed := finder.find(url)) is not None:
                return feed
        except AddressNotAllowedError as error:
            log.info("feed not fetched", url=url, reason=str(error))
        except Exception:  # one odd URL must not stop the whole import
            if stopped.is_set():  # its client was closed after the deadline
                return None
            log.exception("feed lookup failed", url=url)
    return None
