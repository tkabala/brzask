from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from brzask.clients.feeds import FeedEntry, FeedResult, FetchStatus
from brzask.db.models import Article, SourceKind, SourceStatus
from brzask.services.digest.pool import (
    MAX_AGE,
    SNIPPET_CHARS,
    Candidate,
    FeedSource,
    carried_candidates,
    filter_candidates,
    fresh_candidates,
    gather_candidates,
    take_in_turns,
)
from tests.factories import Factories
from tests.services.digest.fakes import NOW, FakeFeeds, context, entry

HOUR = timedelta(hours=1)


def candidate(
    link: str, source_id: int = 1, published_at: datetime | None = NOW, **fields: object
) -> Candidate:
    return Candidate(
        link=f"https://news.example/{link}",
        title=link,
        source_id=source_id,
        source_name=f"Source {source_id}",
        release=False,
        snippet=None,
        published_at=published_at,
        **fields,  # type: ignore[arg-type]
    )


def links(candidates: Sequence[Candidate]) -> list[str]:
    return [c.link.removeprefix("https://news.example/") for c in candidates]


# --- Sources and entries -----------------------------------------------------------


def test_release_sources_are_marked_by_kind_or_release_feed_url(make: Factories) -> None:
    by_kind = make.source(kind=SourceKind.RELEASE)
    by_url = make.source(url="https://github.com/astral-sh/uv/releases.atom")
    plain = make.source()

    assert FeedSource.of(by_kind).release
    assert FeedSource.of(by_url).release
    assert not FeedSource.of(plain).release


def test_fresh_snippet_is_the_summary_or_else_the_content_cut_to_length() -> None:
    source = FeedSource(id=1, name="Blog", url="https://blog.example/feed", release=True)
    entries = [
        FeedEntry("https://blog.example/a", "A", "Short summary", "Full text", NOW),
        FeedEntry("https://blog.example/b", "B", None, "x" * 2000, None),
        FeedEntry("https://blog.example/c", "C", None, None, None),
    ]

    a, b, c = fresh_candidates(source, entries)

    assert (a.snippet, a.content, a.release, a.source_name) == (
        "Short summary",
        "Full text",
        True,
        "Blog",
    )
    assert b.snippet == "x" * SNIPPET_CHARS
    assert b.content == "x" * 2000
    assert c.snippet is None


def test_carry_over_from_sources_no_longer_fetched_is_dropped(make: Factories) -> None:
    active = make.source(name="Active")
    muted = make.source(status=SourceStatus.MUTED)
    kept = make.article(active, snippet="Kept")
    from_muted = make.article(muted)
    orphan = make.article(None)

    candidates, dropped = carried_candidates(
        [kept, from_muted, orphan], {active.id: FeedSource.of(active)}
    )

    assert [(c.link, c.article_id, c.source_name, c.snippet) for c in candidates] == [
        (kept.link, kept.id, "Active", "Kept")
    ]
    assert candidates[0].content is None
    assert dropped == 2


# --- Filters -----------------------------------------------------------------------


def test_drops_shown_and_stale_entries_and_keeps_undated_ones() -> None:
    fresh = [
        candidate("new"),
        candidate("shown"),
        candidate("stale", published_at=NOW - MAX_AGE - HOUR),
        candidate("edge", published_at=NOW - MAX_AGE),
        candidate("undated", published_at=None),
    ]
    carried = [candidate("old-stale", published_at=NOW - timedelta(days=30))]

    kept, counts = filter_candidates(fresh, carried, {"https://news.example/shown"}, NOW)

    assert links(kept) == ["new", "edge", "undated"]
    assert (counts.fresh, counts.carried_over) == (5, 1)
    assert (counts.stale, counts.already_shown, counts.unique) == (2, 1, 3)


def test_a_fresh_entry_wins_over_its_carried_over_copy() -> None:
    fresh = [candidate("same", content="Full text"), candidate("same", source_id=2)]
    carried = [candidate("same", article_id=7), candidate("only-carried", article_id=8)]

    kept, counts = filter_candidates(fresh, carried, set(), NOW)

    assert links(kept) == ["same", "only-carried"]
    assert (kept[0].content, kept[0].source_id, kept[0].article_id) == ("Full text", 1, None)
    assert counts.unique == 2


# --- Taking sources in turns ------------------------------------------------------


def test_sources_take_turns_newest_first() -> None:
    chatty = [candidate(f"chatty-{n}", source_id=1, published_at=NOW - n * HOUR) for n in range(5)]
    quiet = [
        candidate("quiet-undated", source_id=2, published_at=None),
        candidate("quiet-old", source_id=2, published_at=NOW - 9 * HOUR),
        candidate("quiet-new", source_id=2, published_at=NOW - HOUR),
    ]

    pool = take_in_turns([*reversed(chatty), *quiet], cap=100)

    assert links(pool) == [
        "chatty-0",
        "quiet-new",
        "chatty-1",
        "quiet-old",
        "chatty-2",
        "quiet-undated",
        "chatty-3",
        "chatty-4",
    ]


def test_the_cap_cuts_the_last_round_not_a_source() -> None:
    entries = [
        candidate(f"s{source}-{n}", source_id=source, published_at=NOW - n * HOUR)
        for source in (1, 2, 3)
        for n in range(4)
    ]

    pool = take_in_turns(entries, cap=7)

    assert links(pool) == ["s1-0", "s2-0", "s3-0", "s1-1", "s2-1", "s3-1", "s1-2"]
    assert take_in_turns([], cap=7) == []


# --- The stage against the database -------------------------------------------------


def article_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Article)) or 0


def test_gather_stores_the_pool_and_each_sources_fetch_outcome(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    ok = make.source(name="Ok", url="https://ok.example/feed", etag='"old"')
    unchanged = make.source(url="https://unchanged.example/feed", etag='"same"')
    gone = make.source(url="https://gone.example/feed")
    make.source(url="https://muted.example/feed", status=SourceStatus.MUTED)
    carried = make.article(unchanged, first_seen_at=NOW - timedelta(days=2))
    make.article(unchanged, first_seen_at=NOW - timedelta(days=8))  # past the carry-over
    shown = make.article(  # long ago: a link is shown once, however old
        ok, first_seen_at=NOW - timedelta(days=90), digest_date=(NOW - timedelta(days=90)).date()
    )
    feeds = FakeFeeds(
        {
            ok.url: FeedResult(
                ok.url,
                FetchStatus.OK,
                [entry("https://ok.example/new"), entry(shown.link)],
                etag='"new"',
                last_modified="Sun, 18 Oct 2026 06:00:00 GMT",
            ),
            unchanged.url: FeedResult(unchanged.url, FetchStatus.NOT_MODIFIED, etag='"same"'),
            gone.url: FeedResult(gone.url, FetchStatus.FAILED, error="HTTPStatusError: 404"),
        }
    )
    run = context(sessions)

    pool = gather_candidates(run, feeds)

    assert {request.url for request in feeds.requests} == {ok.url, unchanged.url, gone.url}
    assert next(r for r in feeds.requests if r.url == ok.url).etag == '"old"'
    assert sorted(c.link for c in pool) == sorted(["https://ok.example/new", carried.link])
    stored = session.scalars(select(Article).where(Article.link == "https://ok.example/new")).one()
    assert next(c for c in pool if c.link == stored.link).article_id == stored.id
    assert (stored.source_id, stored.snippet, stored.published_at) == (ok.id, "Summary", NOW)
    assert next(c for c in pool if c.link == carried.link).article_id == carried.id

    session.expire_all()
    assert (ok.fetched_at, ok.etag, ok.last_modified) == (
        NOW,
        '"new"',
        "Sun, 18 Oct 2026 06:00:00 GMT",
    )
    assert (unchanged.fetched_at, unchanged.etag, unchanged.fetch_failures) == (NOW, '"same"', 0)
    assert (gone.fetched_at, gone.failing_since, gone.permanent_failing_since) == (None, NOW, NOW)
    assert gone.fetch_error == "HTTPStatusError: 404"

    assert run.stats["pool"] == {
        "sources": 3,
        "not_modified": 1,
        "failed": 1,
        "fresh": 2,
        "carried_over": 1,
        "stale": 0,
        "already_shown": 1,
        "source_inactive": 0,
        "unique": 2,
        "candidates": 2,
        "releases": 0,
    }
    assert "fetch" in run.timings


def test_a_temporary_failure_is_recorded_as_one(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    busy = make.source(url="https://busy.example/feed")
    feeds = FakeFeeds(
        {busy.url: FeedResult(busy.url, FetchStatus.FAILED, error="429", temporary=True)}
    )

    gather_candidates(context(sessions), feeds)
    session.expire_all()

    assert (busy.failing_since, busy.permanent_failing_since, busy.fetch_failures) == (NOW, None, 1)


def test_a_source_whose_feed_moved_for_good_follows_it(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    source = make.source(url="https://github.com/old/app/releases.atom")
    new_url = "https://github.com/new/app/releases.atom"
    feeds = FakeFeeds(
        {
            source.url: FeedResult(
                new_url, FetchStatus.OK, [entry("https://x.example/1")], moved_to=new_url
            )
        }
    )

    gather_candidates(context(sessions), feeds)
    session.expire_all()

    assert (source.url, source.fetched_at) == (new_url, NOW)


def test_a_dry_run_writes_nothing(
    sessions: sessionmaker[Session], session: Session, make: Factories
) -> None:
    source = make.source(url="https://ok.example/feed")
    before = article_count(session)
    feeds = FakeFeeds(
        {
            source.url: FeedResult(
                source.url, FetchStatus.OK, [entry("https://ok.example/new")], etag='"new"'
            )
        }
    )

    pool = gather_candidates(context(sessions, dry_run=True), feeds)

    assert [(c.link, c.article_id) for c in pool] == [("https://ok.example/new", None)]
    session.expire_all()
    assert article_count(session) == before
    assert (source.fetched_at, source.etag) == (None, None)
