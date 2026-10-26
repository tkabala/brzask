import pytest
from sqlalchemy.orm import Session

from brzask.clients.feed_finder import FoundFeed
from brzask.db.models import ChangeStatus, SourceKind, SourceOrigin, SourceStatus
from brzask.repositories import ChangeRepository, SourceRepository
from brzask.services.errors import ConflictError, NotFoundError, ServiceError
from brzask.services.sources import (
    add_source,
    default_name,
    enable_source,
    find_source,
    is_release_feed,
    move_source,
    mute_source,
    name_from_feed,
    propose_source,
    unique_name,
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


def test_add_source_rejects_a_known_feed_written_in_another_case(
    session: Session, make: Factories
) -> None:
    make.source("Hermes", url="https://github.com/NousResearch/hermes-agent/releases.atom")

    with pytest.raises(ConflictError, match="already a source \\(active\\)"):
        add_source(
            session, "https://github.com/nousresearch/hermes-agent/releases.atom", actor="user"
        )


def test_add_source_reports_a_known_url_before_its_default_name(
    session: Session, make: Factories
) -> None:
    make.source("known.example", url="https://known.example/feed", status=SourceStatus.MUTED)

    with pytest.raises(ConflictError, match="already a source \\(muted\\)"):
        add_source(session, "https://known.example/feed", actor="user")


def test_add_source_reports_a_name_taken_after_the_check(
    session: Session, make: Factories, monkeypatch: pytest.MonkeyPatch
) -> None:
    make.source("Known", url="https://known.example/feed")
    # Another process adds the name between the service's check and the insert.
    monkeypatch.setattr(SourceRepository, "get_by_name", lambda _self, _name: None)

    with pytest.raises(ConflictError, match="named 'known'"):
        add_source(session, "https://new.example/feed", actor="user", name="known")


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


def test_a_blank_feed_title_falls_back_to_the_host(session: Session) -> None:
    source = add_source(session, "https://blank.example/feed", actor="user", title="  \n ")

    assert source.name == "blank.example"


def test_numeric_names_are_rejected_since_they_read_as_ids(session: Session) -> None:
    with pytest.raises(ServiceError, match="cannot be a number"):
        add_source(session, "https://digits.example/feed", actor="user", name="42")

    titled = add_source(session, "https://digits.example/feed", actor="user", title="2600")

    assert titled.name == "digits.example"


# --- Sources found by pipelines ---------------------------------------------------------


def test_name_from_feed() -> None:
    assert name_from_feed("https://blog.example/feed", " Blog ") == "Blog"
    assert name_from_feed("https://blog.example/feed", "2026") == "blog.example"
    assert name_from_feed("https://blog.example/feed", None) == "blog.example"
    assert (
        name_from_feed("https://github.com/a/b/releases.atom", "Release notes") == "github.com/a/b"
    )


def test_unique_name_adds_the_host_then_a_number(session: Session, make: Factories) -> None:
    url = "https://www.other.example/feed"
    assert unique_name(session, "Blog", url) == "Blog"

    make.source("blog")
    assert unique_name(session, "Blog", url) == "Blog (other.example)"

    make.source("Blog (other.example)")
    assert unique_name(session, "Blog", url) == "Blog (2)"

    make.source("Blog (2)")
    assert unique_name(session, "Blog", url) == "Blog (3)"


def test_propose_source_records_the_change(session: Session, make: Factories) -> None:
    make.source("Blog")
    found = FoundFeed("https://blog.other/feed", "Blog", "https://blog.other")

    source = propose_source(
        session,
        found,
        status=SourceStatus.PENDING,
        origin=SourceOrigin.DISCOVERY,
        actor="pipeline:discovery",
        origin_detail="interest:Rust",
        note="Suggested for Rust",
    )

    assert source is not None
    assert (source.name, source.status, source.kind, source.site_url) == (
        "Blog (blog.other)",
        SourceStatus.PENDING,
        SourceKind.FEED,
        "https://blog.other",
    )
    [change] = ChangeRepository(session).find(limit=5, entity_id=str(source.id))
    assert (change.actor, change.action, change.reason) == (
        "pipeline:discovery",
        "source.propose",
        "Suggested for Rust",
    )


def test_propose_source_skips_a_known_url_whatever_its_status(
    session: Session, make: Factories
) -> None:
    make.source(url="https://blog.other/feed", status=SourceStatus.REJECTED)
    found = FoundFeed("https://blog.other/feed", "Blog", "https://blog.other")

    source = propose_source(
        session, found, status=SourceStatus.PENDING, origin=SourceOrigin.VISITED, actor="x"
    )

    assert source is None


def test_a_moved_feed_takes_its_new_url_with_the_change_recorded(
    session: Session, make: Factories
) -> None:
    source = make.source(url="https://github.com/old/app/releases.atom")

    moved = move_source(
        session, source, "https://github.com/new/app/releases.atom", actor="pipeline:digest"
    )

    assert moved is True
    assert source.url == "https://github.com/new/app/releases.atom"
    [change] = ChangeRepository(session).find(
        limit=10, entity_type="source", entity_id=str(source.id)
    )
    assert (change.action, change.actor, change.before, change.after) == (
        "source.move",
        "pipeline:digest",
        {"url": "https://github.com/old/app/releases.atom"},
        {"url": "https://github.com/new/app/releases.atom"},
    )


def test_a_feed_moved_to_an_active_source_keeps_both(session: Session, make: Factories) -> None:
    old = make.source(url="https://github.com/old/app/releases.atom")
    new = make.source(url="https://github.com/new/app/releases.atom")

    assert move_source(session, old, new.url, actor="pipeline:digest") is False
    assert move_source(session, new, new.url, actor="pipeline:digest") is False
    assert old.url == "https://github.com/old/app/releases.atom"


def test_a_feed_moved_to_a_muted_duplicate_merges_it(session: Session, make: Factories) -> None:
    old = make.source(name="App", url="https://github.com/old/app/releases.atom")
    duplicate = make.source(
        name="Duplicate",
        url="https://github.com/new/app/releases.atom",
        status=SourceStatus.MUTED,
    )
    article = make.article(duplicate)
    duplicate_id = duplicate.id

    moved = move_source(session, old, duplicate.url, actor="pipeline:digest")

    assert moved is True
    assert old.url == "https://github.com/new/app/releases.atom"
    assert SourceRepository(session).get(duplicate_id) is None
    session.refresh(article)
    assert article.source_id == old.id
    [change] = ChangeRepository(session).find(limit=10, entity_type="source", entity_id=str(old.id))
    assert change.before == {
        "url": "https://github.com/old/app/releases.atom",
        "merged": {"id": duplicate_id, "name": "Duplicate", "status": "muted"},
    }
    assert change.reason == (
        "the feed redirects here permanently; merged muted source 'Duplicate' (1 articles)"
    )
