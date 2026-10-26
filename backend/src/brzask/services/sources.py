"""Adding, muting, enabling and moving sources."""

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from brzask.clients.feed_finder import FoundFeed
from brzask.db.models import ChangeStatus, Source, SourceKind, SourceOrigin, SourceStatus
from brzask.log import get_logger
from brzask.repositories import ChangeRepository, SourceRepository
from brzask.repositories.sources import SourceStats
from brzask.services.errors import ConflictError, NotFoundError, ServiceError
from brzask.services.refs import as_id

log = get_logger(__name__)


class SiteFeedFinder(Protocol):
    """Finds the feed of a site from any of its pages (`FeedFinder`)."""

    def find(self, url: str) -> FoundFeed | None: ...


# The window of the per-source counts shown next to each source.
RECENT = timedelta(days=30)


def is_release_feed(url: str) -> bool:
    """GitHub release feeds (`.../<owner>/<repo>/releases.atom`) carry release notes."""
    return urlsplit(url).path.rstrip("/").endswith("/releases.atom")


def default_name(url: str) -> str:
    """A readable name from the feed URL: its host without `www.`.

    Release feeds keep the project path (`github.com/<owner>/<repo>`), since
    many of them share one host.
    """
    parts = urlsplit(url)
    host = (parts.hostname or url).removeprefix("www.")
    if is_release_feed(url):
        project = parts.path.rstrip("/").removesuffix("/releases.atom")
        return f"{host}{project}"
    return host


def name_from_feed(url: str, title: str | None) -> str:
    """The feed's title, or the name `default_name` gives.

    Release feeds are named after their project, which tells them apart
    better; a numeric title would read as an ID, so the host names it instead.
    """
    feed_title = "" if is_release_feed(url) else (title or "").strip()
    return (feed_title if as_id(feed_title) is None else "") or default_name(url)


def unique_name(session: Session, name: str, url: str) -> str:
    """`name`, or `name (host)`, or `name (2)`, ...: the first not taken, ignoring case."""
    sources = SourceRepository(session)
    host = urlsplit(url).hostname or ""
    tried = [name, f"{name} ({host.removeprefix('www.')})"] if host else [name]
    for candidate in tried:
        if sources.get_by_name(candidate) is None:
            return candidate
    number = 2
    while sources.get_by_name(f"{name} ({number})") is not None:
        number += 1
    return f"{name} ({number})"


_PROPOSAL_ACTIONS = {
    SourceStatus.ACTIVE: "source.add",
    SourceStatus.PENDING: "source.propose",
    SourceStatus.REJECTED: "source.reject",
}


def propose_source(
    session: Session,
    found: FoundFeed,
    *,
    status: SourceStatus,
    origin: SourceOrigin,
    actor: str,
    origin_detail: str | None = None,
    note: str | None = None,
) -> Source | None:
    """Add a source found by a pipeline, under a free name; None when its URL is known.

    A known URL counts whatever its status, so a rejected feed is never
    proposed again.
    """
    sources = SourceRepository(session)
    if sources.get_by_url(found.url) is not None:
        return None
    name = unique_name(session, name_from_feed(found.url, found.title), found.url)
    source = sources.add(
        name=name,
        url=found.url,
        status=status,
        origin=origin,
        kind=SourceKind.RELEASE if is_release_feed(found.url) else SourceKind.FEED,
        site_url=found.site_url,
        origin_detail=origin_detail,
        note=note,
    )
    if source is None:  # added by another process since the check above
        return None
    ChangeRepository(session).record(
        actor=actor,
        action=_PROPOSAL_ACTIONS.get(status, f"source.{status.value}"),
        entity_type="source",
        entity_id=str(source.id),
        status=ChangeStatus.APPLIED,
        after={"name": source.name, "url": source.url, "status": status.value},
        reason=note,
    )
    return source


def find_source(session: Session, ref: str) -> Source:
    """A source by ID, feed URL or name (ignoring case)."""
    sources = SourceRepository(session)
    source_id = as_id(ref)
    source = (
        sources.get(source_id)
        if source_id is not None
        else sources.get_by_url(ref) or sources.get_by_name(ref)
    )
    if source is None:
        raise NotFoundError(f"no source {ref!r}")
    return source


def list_sources(session: Session, *statuses: SourceStatus) -> Sequence[Source]:
    return SourceRepository(session).find(*statuses)


def page_sources(
    session: Session,
    limit: int,
    statuses: Collection[SourceStatus] = (),
    after: tuple[str, int] | None = None,
) -> Sequence[Source]:
    """Sources by name, `limit` at a time; `after` is the (name, id) of the last one seen."""
    return SourceRepository(session).page(limit, statuses, after)


def get_source(session: Session, source_id: int) -> Source:
    source = SourceRepository(session).get(source_id)
    if source is None:
        raise NotFoundError(f"no source {source_id}")
    return source


def recent_stats(
    session: Session, now: datetime, source_ids: Collection[int]
) -> dict[int, SourceStats]:
    """What the sources `source_ids` produced over the last `RECENT` days."""
    return SourceRepository(session).stats(now - RECENT, source_ids)


def ensure_unknown(session: Session, url: str) -> None:
    """Raise when `url` is already a source, whatever its status."""
    known = SourceRepository(session).get_by_url(url)
    if known is not None:
        raise ConflictError(f"{url} is already a source ({known.status.value})")


def find_feed(finder: SiteFeedFinder, url: str) -> FoundFeed:
    """The feed of the site `url` belongs to; `url` may be the feed itself or any page."""
    found = finder.find(url)
    if found is None:
        raise NotFoundError(f"no RSS or Atom feed found for {url}")
    return found


def add_source(
    session: Session,
    url: str,
    *,
    actor: str,
    name: str | None = None,
    title: str | None = None,
    site_url: str | None = None,
) -> Source:
    """Add a feed by its URL; it is fetched from the next digest on.

    Without `name`, the feed's `title` is used, or the host; release feeds are
    named after their project instead, which tells them apart better.
    """
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ServiceError(f"not an http(s) URL: {url!r}")
    sources = SourceRepository(session)
    ensure_unknown(session, url)
    release = is_release_feed(url)
    name = (name or "").strip()
    if as_id(name) is not None:
        raise ServiceError(f"a source name cannot be a number ({name}); it would read as an ID")
    name = name or name_from_feed(url, title)
    if sources.get_by_name(name) is not None:
        raise ConflictError(f"a source named {name!r} already exists; choose another name")
    source = sources.add(
        name=name,
        url=url,
        status=SourceStatus.ACTIVE,
        origin=SourceOrigin.MANUAL,
        kind=SourceKind.RELEASE if release else SourceKind.FEED,
        site_url=site_url,
    )
    if source is None:  # added by another process since the checks above
        if sources.get_by_url(url) is not None:
            raise ConflictError(f"{url} is already a source")
        raise ConflictError(f"a source named {name!r} already exists; choose another name")
    ChangeRepository(session).record(
        actor=actor,
        action="source.add",
        entity_type="source",
        entity_id=str(source.id),
        status=ChangeStatus.APPLIED,
        after={"name": source.name, "url": source.url, "kind": source.kind.value},
    )
    return source


def rename_source(session: Session, source: Source, name: str, *, actor: str) -> bool:
    """Give a source another name, unique ignoring case. False when it already had it."""
    name = name.strip()
    if not name:
        raise ServiceError("a source name must not be empty")
    if as_id(name) is not None:
        raise ServiceError(f"a source name cannot be a number ({name}); it would read as an ID")
    if name == source.name:
        return False
    other = SourceRepository(session).get_by_name(name)
    if other is not None and other.id != source.id:
        raise ConflictError(f"a source named {name!r} already exists; choose another name")
    before = source.name
    source.name = name
    session.flush()
    ChangeRepository(session).record(
        actor=actor,
        action="source.rename",
        entity_type="source",
        entity_id=str(source.id),
        status=ChangeStatus.APPLIED,
        before={"name": before},
        after={"name": name},
    )
    return True


def move_source(session: Session, source: Source, url: str, *, actor: str) -> bool:
    """Point a source at the URL its feed moved to for good. False when nothing changed.

    Keeping the old URL would let discovery add the new one as a second source
    of the same feed. A source that is not active and holds the new URL (often
    the duplicate discovery added, then muted) is merged into this one: its
    articles move here and its row goes. Two active sources both stay, and a
    person decides which to keep.
    """
    if url == source.url:
        return False
    sources = SourceRepository(session)
    other = sources.get_by_url(url)
    if other is not None and (other.id == source.id or other.status is SourceStatus.ACTIVE):
        log.warning("source moved to a followed feed", source=source.id, other=other.id, url=url)
        return False
    before: dict[str, Any] = {"url": source.url}
    reason = "the feed redirects here permanently"
    if other is not None:
        merged = {"id": other.id, "name": other.name, "status": other.status.value}
        articles = sources.absorb(source, other)
        before["merged"] = merged
        reason += f"; merged {merged['status']} source {merged['name']!r} ({articles} articles)"
    source.url = url
    session.flush()
    ChangeRepository(session).record(
        actor=actor,
        action="source.move",
        entity_type="source",
        entity_id=str(source.id),
        status=ChangeStatus.APPLIED,
        before=before,
        after={"url": url},
        reason=reason,
    )
    return True


def mute_source(session: Session, ref: str, *, actor: str, reason: str | None = None) -> bool:
    """Stop fetching a source. False when it was already muted."""
    return change_status(
        session, find_source(session, ref), SourceStatus.MUTED, actor=actor, reason=reason
    )


def enable_source(session: Session, ref: str, *, actor: str) -> bool:
    """Fetch a source again, whatever its status. False when it was already active.

    Its fetch failures are forgotten, so a revived dead source gets the full
    grace period again before the review can mark it dead.
    """
    return change_status(session, find_source(session, ref), SourceStatus.ACTIVE, actor=actor)


_STATUS_ACTIONS = {
    SourceStatus.MUTED: "source.mute",
    SourceStatus.ACTIVE: "source.enable",
    SourceStatus.DEAD: "source.dead",
}


def change_status(
    session: Session,
    source: Source,
    status: SourceStatus,
    *,
    actor: str,
    reason: str | None = None,
) -> bool:
    """Set a source's status and record the change. False when it already had that status."""
    before = source.status
    if before is status:
        return False
    sources = SourceRepository(session)
    sources.set_status(source, status, reason)
    if status is SourceStatus.ACTIVE:
        sources.reset_fetch_health(source)
    ChangeRepository(session).record(
        actor=actor,
        action=_STATUS_ACTIONS.get(status, f"source.{status.value}"),
        entity_type="source",
        entity_id=str(source.id),
        status=ChangeStatus.APPLIED,
        before={"status": before.value},
        after={"status": status.value},
        reason=reason,
    )
    return True
