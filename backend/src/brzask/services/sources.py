"""Adding, muting and enabling sources."""

from collections.abc import Sequence
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from brzask.clients.feed_finder import FeedFinder, FoundFeed
from brzask.db.models import ChangeStatus, Source, SourceKind, SourceOrigin, SourceStatus
from brzask.repositories import ChangeRepository, SourceRepository
from brzask.services.errors import ConflictError, NotFoundError, ServiceError
from brzask.services.refs import as_id


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


def ensure_unknown(session: Session, url: str) -> None:
    """Raise when `url` is already a source, whatever its status."""
    known = SourceRepository(session).get_by_url(url)
    if known is not None:
        raise ConflictError(f"{url} is already a source ({known.status.value})")


def find_feed(finder: FeedFinder, url: str) -> FoundFeed:
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
    name = ((name or "").strip() or (None if release else title) or default_name(url)).strip()
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
    if source is None:  # added by another process since the check above
        raise ConflictError(f"{url} is already a source")
    ChangeRepository(session).record(
        actor=actor,
        action="source.add",
        entity_type="source",
        entity_id=str(source.id),
        status=ChangeStatus.APPLIED,
        after={"name": source.name, "url": source.url, "kind": source.kind.value},
    )
    return source


def mute_source(session: Session, ref: str, *, actor: str, reason: str | None = None) -> bool:
    """Stop fetching a source. False when it was already muted."""
    return _set_status(session, ref, SourceStatus.MUTED, actor=actor, reason=reason)


def enable_source(session: Session, ref: str, *, actor: str) -> bool:
    """Fetch a source again, whatever its status. False when it was already active."""
    return _set_status(session, ref, SourceStatus.ACTIVE, actor=actor, reason=None)


def _set_status(
    session: Session, ref: str, status: SourceStatus, *, actor: str, reason: str | None
) -> bool:
    source = find_source(session, ref)
    before = source.status
    if before is status:
        return False
    SourceRepository(session).set_status(source, status, reason)
    ChangeRepository(session).record(
        actor=actor,
        action="source.mute" if status is SourceStatus.MUTED else "source.enable",
        entity_type="source",
        entity_id=str(source.id),
        status=ChangeStatus.APPLIED,
        before={"status": before.value},
        after={"status": status.value},
        reason=reason,
    )
    return True
