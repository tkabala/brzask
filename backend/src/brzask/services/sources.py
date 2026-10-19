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
    name = (name or "").strip()
    if as_id(name) is not None:
        raise ServiceError(f"a source name cannot be a number ({name}); it would read as an ID")
    feed_title = "" if release else (title or "").strip()
    # A numeric feed title would read as an ID too; the host names the source instead.
    name = name or (feed_title if as_id(feed_title) is None else "") or default_name(url)
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
