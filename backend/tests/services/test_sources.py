import pytest
from sqlalchemy.orm import Session

from brzask.db.models import ChangeStatus, SourceKind, SourceOrigin, SourceStatus
from brzask.repositories import ChangeRepository
from brzask.services.errors import ConflictError, NotFoundError, ServiceError
from brzask.services.sources import (
    add_source,
    default_name,
    enable_source,
    find_source,
    is_release_feed,
    mute_source,
)
from tests.factories import Factories


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/astral-sh/uv/releases.atom", True),
        ("https://github.com/astral-sh/uv/releases.atom/", True),
        ("https://github.com/astral-sh/uv/tags.atom", False),
        ("https://example.com/feed.xml?from=releases.atom", False),
        ("https://example.com/blog/releases.atom-notes", False),
    ],
)
def test_is_release_feed(url: str, expected: bool) -> None:
    assert is_release_feed(url) is expected


def test_default_name_is_the_host() -> None:
    assert default_name("https://www.example.com/feed.xml") == "example.com"
    assert default_name("https://blog.example.com/rss") == "blog.example.com"


def test_release_feeds_are_named_after_the_project() -> None:
    assert (
        default_name("https://github.com/astral-sh/uv/releases.atom") == "github.com/astral-sh/uv"
    )


def test_two_release_feeds_from_one_host_can_be_added(session: Session) -> None:
    add_source(session, "https://github.com/astral-sh/uv/releases.atom", actor="user")
    second = add_source(session, "https://github.com/astral-sh/ruff/releases.atom", actor="user")

    assert second.name == "github.com/astral-sh/ruff"


def test_add_source_records_the_change(session: Session) -> None:
    source = add_source(session, "https://github.com/a/b/releases.atom", actor="user")

    assert (source.name, source.status, source.origin, source.kind) == (
        "github.com/a/b",
        SourceStatus.ACTIVE,
        SourceOrigin.MANUAL,
        SourceKind.RELEASE,
    )
    [change] = ChangeRepository(session).find(limit=5)
    assert (change.action, change.entity_id, change.status) == (
        "source.add",
        str(source.id),
        ChangeStatus.APPLIED,
    )


def test_add_source_rejects_known_urls_and_names(session: Session, make: Factories) -> None:
    make.source("Known", url="https://known.example/feed", status=SourceStatus.REJECTED)

    with pytest.raises(ConflictError, match="already a source \\(rejected\\)"):
        add_source(session, "https://known.example/feed", actor="user", name="Other")
    with pytest.raises(ConflictError, match="named 'known'"):
        add_source(session, "https://new.example/feed", actor="user", name="known")


def test_add_source_reports_a_known_url_before_its_default_name(
    session: Session, make: Factories
) -> None:
    make.source("known.example", url="https://known.example/feed", status=SourceStatus.MUTED)

    with pytest.raises(ConflictError, match="already a source \\(muted\\)"):
        add_source(session, "https://known.example/feed", actor="user")


@pytest.mark.parametrize("url", ["ftp://example.com/feed", "example.com/feed", "https://"])
def test_add_source_needs_an_http_url(session: Session, url: str) -> None:
    with pytest.raises(ServiceError, match="not an http"):
        add_source(session, url, actor="user")


def test_find_source_by_id_url_or_name(session: Session, make: Factories) -> None:
    source = make.source("Lobsters", url="https://lobste.rs/rss")

    assert find_source(session, str(source.id)) is source
    assert find_source(session, "https://lobste.rs/rss") is source
    assert find_source(session, "lobsters") is source
    with pytest.raises(NotFoundError):
        find_source(session, "Slashdot")
    with pytest.raises(NotFoundError):
        find_source(session, "9" * 30)  # larger than any ID


def test_mute_then_enable(session: Session, make: Factories) -> None:
    source = make.source("Noisy")

    assert mute_source(session, "Noisy", actor="user", reason="too chatty")
    assert not mute_source(session, "Noisy", actor="user")
    assert source.status is SourceStatus.MUTED
    assert source.note == "too chatty"

    assert enable_source(session, "Noisy", actor="user")
    assert not enable_source(session, "Noisy", actor="user")
    enabled = find_source(session, "Noisy")
    assert (enabled.status, enabled.note) == (SourceStatus.ACTIVE, None)

    changes = ChangeRepository(session).find(limit=10)
    assert [(c.action, c.before, c.after) for c in changes] == [
        ("source.enable", {"status": "muted"}, {"status": "active"}),
        ("source.mute", {"status": "active"}, {"status": "muted"}),
    ]
    assert changes[1].reason == "too chatty"


def test_enable_a_pending_source(session: Session, make: Factories) -> None:
    source = make.source(status=SourceStatus.PENDING)

    assert enable_source(session, str(source.id), actor="user")
    assert source.status is SourceStatus.ACTIVE


def test_feed_title_names_the_source_unless_given_a_name(session: Session) -> None:
    titled = add_source(
        session,
        "https://blog.example.com/feed/",
        actor="user",
        title="  Example Blog ",
        site_url="https://blog.example.com/",
    )
    named = add_source(
        session, "https://other.example/rss", actor="user", name="Mine", title="Their title"
    )

    assert (titled.name, titled.site_url) == ("Example Blog", "https://blog.example.com/")
    assert named.name == "Mine"


def test_release_feeds_ignore_the_generic_feed_title(session: Session) -> None:
    source = add_source(
        session,
        "https://github.com/astral-sh/uv/releases.atom",
        actor="user",
        title="Release notes from uv",
    )

    assert source.name == "github.com/astral-sh/uv"


def test_a_blank_name_falls_back_to_the_feed_title(session: Session) -> None:
    source = add_source(
        session, "https://blank.example/feed", actor="user", name="   ", title="Blank Blog"
    )

    assert source.name == "Blank Blog"
