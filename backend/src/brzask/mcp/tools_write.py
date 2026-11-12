"""Tools that change sources, interests and the pause; each needs a write or propose token.

Every change goes through the same services as the CLI and the web app, so
it is logged in the change log as `agent:<token name>` and can be rolled
back with `brzask config rollback`. With a propose token the same write is
only proposed: it is validated and logged as `proposed`, and the owner
applies or rejects it.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import AwareDatetime, Field
from sqlalchemy.orm import Session

from brzask.clients.feed_finder import with_scheme
from brzask.db.models import Interest, Source, SourceOrigin, SourceStatus
from brzask.mcp import models
from brzask.mcp.errors import service_errors
from brzask.mcp.server import McpDeps, require_change
from brzask.services import interests, proposals, sources
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
    ) -> models.SourceItem | models.ProposalItem:
        """Find the site's RSS or Atom feed and add it, pending the owner's decision by default.

        Active with a propose token, the addition is proposed instead.
        """
        identity = require_change()
        actor = identity.actor
        with service_errors():
            with sessions.begin() as session:
                # Before any request to the site, as the finder will read the URL.
                sources.ensure_unknown(session, with_scheme(url))
            # No transaction is held while the site answers.
            with deps.clients.feed_finder() as finder:
                found = sources.find_feed(finder, url)
            with sessions.begin() as session:

                def write() -> Source:
                    return sources.add_source(
                        session,
                        found.url,
                        actor=actor,
                        name=name,
                        title=found.title,
                        site_url=found.site_url,
                    )

                if active and identity.proposes:
                    return _proposal(session, write)
                if active:
                    source: Source | None = write()
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
    ) -> models.SourceItem | models.ProposalItem:
        """Read a source again (active), stop reading it (muted) or turn a pending one down."""
        identity = require_change()
        actor = identity.actor
        with sessions.begin() as session, service_errors():
            found = sources.find_source(session, source)

            def write() -> object:
                return sources.change_status(
                    session, found, SourceStatus(status), actor=actor, reason=reason
                )

            if identity.proposes:
                return _proposal(session, write)
            write()
            return _out(session, found)

    @server.tool()
    def rename_source(
        source: SourceRef, name: Annotated[str, Field(min_length=1, max_length=200)]
    ) -> models.SourceItem | models.ProposalItem:
        """Give a source another name, unique ignoring case."""
        identity = require_change()
        actor = identity.actor
        with sessions.begin() as session, service_errors():
            found = sources.find_source(session, source)

            def write() -> object:
                return sources.rename_source(session, found, name, actor=actor)

            if identity.proposes:
                return _proposal(session, write)
            write()
            return _out(session, found)

    @server.tool()
    def set_source_note(
        source: SourceRef,
        note: Annotated[str | None, Field(max_length=2000, description="Empty or null clears it.")],
    ) -> models.SourceItem | models.ProposalItem:
        """Replace a source's note, e.g. why it is kept although rarely opened."""
        identity = require_change()
        actor = identity.actor
        with sessions.begin() as session, service_errors():
            found = sources.find_source(session, source)

            def write() -> object:
                return sources.set_note(session, found, note, actor=actor)

            if identity.proposes:
                return _proposal(session, write)
            write()
            return _out(session, found)

    @server.tool()
    def add_interest(
        topic: Annotated[str, Field(min_length=1, max_length=200)],
        keywords: Annotated[list[str], Field(max_length=50)] = [],  # noqa: B006 - pydantic copies it
        notes: Annotated[
            str, Field(max_length=4000, description="What the owner wants, in words.")
        ] = "",
    ) -> models.InterestItem | models.ProposalItem:
        """Add an interest the ranking and source discovery should follow."""
        identity = require_change()
        actor = identity.actor
        with sessions.begin() as session, service_errors():

            def write() -> Interest:
                return interests.add_interest(
                    session, topic, actor=actor, keywords=keywords, notes=notes
                )

            if identity.proposes:
                return _proposal(session, write)
            return models.InterestItem.of(write())

    @server.tool()
    def edit_interest(
        interest: Annotated[str, Field(description="Interest ID or topic.")],
        topic: Annotated[str | None, Field(max_length=200)] = None,
        keywords: Annotated[list[str] | None, Field(max_length=50)] = None,
        notes: Annotated[str | None, Field(max_length=4000)] = None,
        active: bool | None = None,
    ) -> models.InterestItem | models.ProposalItem:
        """Change the given fields of an interest; inactive ones are ignored by the pipelines."""
        identity = require_change()
        actor = identity.actor
        with sessions.begin() as session, service_errors():

            def write() -> Interest:
                return interests.edit_interest(
                    session,
                    interest,
                    actor=actor,
                    topic=topic,
                    keywords=keywords,
                    notes=notes,
                    active=active,
                )

            if identity.proposes:
                return _proposal(session, write)
            return models.InterestItem.of(write())

    @server.tool()
    def pause(
        until: Annotated[AwareDatetime, Field(description="When digests start again.")],
    ) -> models.PauseState | models.ProposalItem:
        """Build no digest until `until`, e.g. for a holiday; replaces a pause already set."""
        identity = require_change()
        actor = identity.actor
        with sessions.begin() as session, service_errors():

            def write() -> None:
                pausing.pause(session, until, datetime.now(UTC), actor=actor)

            if identity.proposes:
                return _proposal(session, write)
            write()
            return models.PauseState(until=until)

    @server.tool()
    def resume() -> models.PauseState | models.ProposalItem:
        """End a pause now; nothing happens when the digest is not paused."""
        identity = require_change()
        actor = identity.actor
        with sessions.begin() as session, service_errors():

            def write() -> object:
                return pausing.resume(session, datetime.now(UTC), actor=actor)

            if identity.proposes:
                return _proposal(session, write)
            write()
            return models.PauseState(until=None)


def _proposal(session: Session, write: Callable[[], object]) -> models.ProposalItem:
    """Propose what `write` would change; the owner approves or rejects it."""
    change = proposals.propose(session, write)
    if change is None:
        raise ToolError("nothing to change: it is already so")
    return models.ProposalItem(change_id=change.id, action=change.action)


def _out(session: Session, source: Source) -> models.SourceItem:
    stats = sources.recent_stats(session, datetime.now(UTC), [source.id])
    return models.SourceItem.of(source, stats.get(source.id))
