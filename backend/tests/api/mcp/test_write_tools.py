from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brzask.clients.feed_finder import FoundFeed
from brzask.db.models import Change, SourceStatus
from brzask.repositories import ChangeRepository
from tests.api.conftest import FakeFeedFinder
from tests.api.mcp.conftest import Connect, data, error_text
from tests.factories import Factories

pytestmark = pytest.mark.anyio

FEED = "https://blog.example/feed.xml"


def changes(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Change)) or 0


def last_change(session: Session) -> Change:
    return ChangeRepository(session).find(limit=1)[0]


def calls(make: Factories) -> list[tuple[str, dict[str, Any]]]:
    source = make.source("Blog")
    interest = make.interest("Postgres")
    later = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    return [
        ("add_source", {"url": "https://blog.example/"}),
        ("set_source_status", {"source": str(source.id), "status": "muted"}),
        ("rename_source", {"source": str(source.id), "name": "Other"}),
        ("set_source_note", {"source": str(source.id), "note": "x"}),
        ("add_interest", {"topic": "Rust", "keywords": ["cargo"]}),
        ("edit_interest", {"interest": str(interest.id), "notes": "x"}),
        ("pause", {"until": later}),
        ("resume", {}),
    ]


async def test_a_read_token_changes_nothing(
    connect: Connect, read_token: str, make: Factories, session: Session
) -> None:
    before = changes(session)

    async with connect(read_token) as client:
        for name, arguments in calls(make):
            result = await client.call_tool(name, arguments)
            assert "this needs a write token" in error_text(result), name

    assert changes(session) == before


async def test_add_source_proposes_it_by_default(
    connect: Connect, write_token: str, feed_finder: FakeFeedFinder, session: Session
) -> None:
    feed_finder.feeds["https://blog.example/"] = FoundFeed(FEED, "A Blog", "https://blog.example/")

    async with connect(write_token) as client:
        added = data(await client.call_tool("add_source", {"url": "https://blog.example/"}))

    assert (added["url"], added["status"], added["external"]["name"]) == (FEED, "pending", "A Blog")
    change = last_change(session)
    assert (change.action, change.actor) == ("source.propose", "agent:claude")


async def test_add_source_active_with_a_name(
    connect: Connect, write_token: str, feed_finder: FakeFeedFinder, session: Session
) -> None:
    feed_finder.feeds["https://blog.example/"] = FoundFeed(FEED, "A Blog", "https://blog.example/")

    async with connect(write_token) as client:
        added = data(
            await client.call_tool(
                "add_source", {"url": "https://blog.example/", "name": "Mine", "active": True}
            )
        )

    assert (added["status"], added["external"]["name"]) == ("active", "Mine")
    assert last_change(session).action == "source.add"


async def test_add_source_refusals(
    connect: Connect, write_token: str, make: Factories, feed_finder: FakeFeedFinder
) -> None:
    make.source("Known", url=FEED)

    async with connect(write_token) as client:
        reddit = await client.call_tool("add_source", {"url": "https://www.reddit.com/r/rust/"})
        known = await client.call_tool("add_source", {"url": FEED})
        nothing = await client.call_tool("add_source", {"url": "https://nofeed.example/"})

    assert "Reddit no longer serves feeds" in error_text(reddit)
    assert "already a source" in error_text(known)
    assert "no RSS or Atom feed found" in error_text(nothing)
    assert feed_finder.asked == ["https://nofeed.example/"]


async def test_source_status_rename_and_note(
    connect: Connect, write_token: str, make: Factories, session: Session
) -> None:
    source = make.source("Blog")
    make.source("Taken")
    ref = str(source.id)

    async with connect(write_token) as client:
        muted = data(
            await client.call_tool(
                "set_source_status", {"source": ref, "status": "muted", "reason": "never read"}
            )
        )
        taken = await client.call_tool("rename_source", {"source": ref, "name": "taken"})
        renamed = data(await client.call_tool("rename_source", {"source": ref, "name": "New"}))
        noted = data(await client.call_tool("set_source_note", {"source": ref, "note": "ok"}))
        bad = await client.call_tool("set_source_status", {"source": ref, "status": "dead"})

    assert (muted["status"], muted["note"]) == ("muted", "never read")
    assert "already exists" in error_text(taken)
    assert renamed["external"]["name"] == "New"
    assert noted["note"] == "ok"
    assert bad.is_error
    actions = [c.action for c in ChangeRepository(session).find(limit=3)]
    assert actions == ["source.note", "source.rename", "source.mute"]
    assert {c.actor for c in ChangeRepository(session).find(limit=3)} == {"agent:claude"}
    session.refresh(source)
    assert (source.status, source.name) == (SourceStatus.MUTED, "New")


async def test_interests(connect: Connect, write_token: str, session: Session) -> None:
    async with connect(write_token) as client:
        added = data(
            await client.call_tool(
                "add_interest", {"topic": "Rust", "keywords": ["cargo"], "notes": "no jobs"}
            )
        )
        edited = data(
            await client.call_tool(
                "edit_interest", {"interest": str(added["id"]), "active": False, "notes": "x"}
            )
        )

    assert (added["topic"], added["keywords"], added["active"]) == ("Rust", ["cargo"], True)
    assert (edited["active"], edited["notes"]) == (False, "x")
    assert last_change(session).actor == "agent:claude"


async def test_pause_and_resume(connect: Connect, write_token: str, session: Session) -> None:
    until = datetime.now(UTC) + timedelta(days=3)

    async with connect(write_token) as client:
        paused = data(await client.call_tool("pause", {"until": until.isoformat()}))
        past = await client.call_tool("pause", {"until": "2020-01-01T00:00:00Z"})
        resumed = data(await client.call_tool("resume", {}))
        again = data(await client.call_tool("resume", {}))

    assert datetime.fromisoformat(paused["until"]) == until
    assert "not in the future" in error_text(past)
    assert (resumed["until"], again["until"]) == (None, None)
    assert last_change(session).action == "digest.resume"
