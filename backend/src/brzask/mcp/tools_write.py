"""Tools that change sources, interests and the pause; each needs a write token.

Every change goes through the same services as the CLI and the web app, so
it is logged in the change log as `agent:<token name>` and can be rolled
back with `brzask config rollback`.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import AwareDatetime, Field
from sqlalchemy.orm import Session

from brzask.clients.feed_finder import with_scheme
from brzask.db.models import Source, SourceOrigin, SourceStatus
from brzask.mcp import models
from brzask.mcp.errors import service_errors
from brzask.mcp.server import McpDeps, require_write
from brzask.services import interests, sources
from brzask.services import pause as pausing
from brzask.services.errors import ConflictError

SourceRef = Annotated[str, Field(description="Source ID, feed URL or name.")]


def register(server: MCPServer[Any], deps: McpDeps) -> None:
    sessions = deps.sessions

    @server.tool()
    def add_source(
        url: Annotated[
            str,
            Field(min_length=1, max_length=2000, description="Any page of the site, or its feed."),
        ],
        name: Annotated[str | None, Field(max_length=200)] = None,
        active: Annotated[
            bool,
            Field(description="Read it from the next digest on; otherwise it waits for the owner."),
        ] = False,
    ) -> models.SourceItem:
        """Find the site's RSS or Atom feed and add it, pending the owner's decision by default."""
        actor = require_write().actor
        with service_errors():
            with sessions.begin() as session:
                # Before any request to the site, as the finder will read the URL.
                sources.ensure_unknown(session, with_scheme(url))
            # No transaction is held while the site answers.
            with deps.clients.feed_finder() as finder:
                found = sources.find_feed(finder, url)
            with sessions.begin() as session:
                if active:
                    source: Source | None = sources.add_source(
                        session,
                        found.url,
                        actor=actor,
                        name=name,
                        title=found.title,
                        site_url=found.site_url,
                    )
                else:
                    source = sources.propose_source(
                        session,
                        found,
                        status=SourceStatus.PENDING,
                        origin=SourceOrigin.MANUAL,
                        actor=actor,
                        name=name,
                    )
                if source is None:
                    raise ConflictError(f"{found.url} is already a source")
                return _out(session, source)

    @server.tool()
    def set_source_status(
        source: SourceRef,
        status: Literal["active", "muted", "rejected"],
        reason: Annotated[
            str | None, Field(max_length=500, description="Kept as its note.")
        ] = None,
    ) -> models.SourceItem:
        """Read a source again (active), stop reading it (muted) or turn a pending one down."""
        actor = require_write().actor
        with sessions.begin() as session, service_errors():
            found = sources.find_source(session, source)
            sources.change_status(session, found, SourceStatus(status), actor=actor, reason=reason)
            return _out(session, found)

    @server.tool()
    def rename_source(
        source: SourceRef, name: Annotated[str, Field(min_length=1, max_length=200)]
    ) -> models.SourceItem:
        """Give a source another name, unique ignoring case."""
        actor = require_write().actor
        with sessions.begin() as session, service_errors():
            found = sources.find_source(session, source)
            sources.rename_source(session, found, name, actor=actor)
            return _out(session, found)

    @server.tool()
    def set_source_note(
        source: SourceRef,
        note: Annotated[str | None, Field(max_length=2000, description="Empty or null clears it.")],
    ) -> models.SourceItem:
        """Replace a source's note, e.g. why it is kept although rarely opened."""
        actor = require_write().actor
        with sessions.begin() as session, service_errors():
            found = sources.find_source(session, source)
            sources.set_note(session, found, note, actor=actor)
            return _out(session, found)

    @server.tool()
    def add_interest(
        topic: Annotated[str, Field(min_length=1, max_length=200)],
        keywords: Annotated[list[str], Field(max_length=50)] = [],  # noqa: B006 - pydantic copies it
        notes: Annotated[
            str, Field(max_length=4000, description="What the owner wants, in words.")
        ] = "",
    ) -> models.InterestItem:
        """Add an interest the ranking and source discovery should follow."""
        actor = require_write().actor
        with sessions.begin() as session, service_errors():
            added = interests.add_interest(
                session, topic, actor=actor, keywords=keywords, notes=notes
            )
            return models.InterestItem.of(added)

    @server.tool()
    def edit_interest(
        interest: Annotated[str, Field(description="Interest ID or topic.")],
        topic: Annotated[str | None, Field(max_length=200)] = None,
        keywords: Annotated[list[str] | None, Field(max_length=50)] = None,
        notes: Annotated[str | None, Field(max_length=4000)] = None,
        active: bool | None = None,
    ) -> models.InterestItem:
        """Change the given fields of an interest; inactive ones are ignored by the pipelines."""
        actor = require_write().actor
        with sessions.begin() as session, service_errors():
            edited = interests.edit_interest(
                session,
                interest,
                actor=actor,
                topic=topic,
                keywords=keywords,
                notes=notes,
                active=active,
            )
            return models.InterestItem.of(edited)

    @server.tool()
    def pause(
        until: Annotated[AwareDatetime, Field(description="When digests start again.")],
    ) -> models.PauseState:
        """Build no digest until `until`, e.g. for a holiday; replaces a pause already set."""
        actor = require_write().actor
        with sessions.begin() as session, service_errors():
            pausing.pause(session, until, datetime.now(UTC), actor=actor)
            return models.PauseState(until=until)

    @server.tool()
    def resume() -> models.PauseState:
        """End a pause now; nothing happens when the digest is not paused."""
        actor = require_write().actor
        with sessions.begin() as session, service_errors():
            pausing.resume(session, datetime.now(UTC), actor=actor)
            return models.PauseState(until=None)


def _out(session: Session, source: Source) -> models.SourceItem:
    stats = sources.recent_stats(session, datetime.now(UTC), [source.id])
    return models.SourceItem.of(source, stats.get(source.id))
