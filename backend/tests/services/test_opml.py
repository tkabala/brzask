import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from structlog.testing import capture_logs

from brzask.clients.feed_finder import FoundFeed
from brzask.db.models import Change, Source, SourceOrigin, SourceStatus
from brzask.services.errors import ServiceError
from brzask.services.opml import NO_FEED, Outline, _find, import_outlines, parse_opml, render_opml
from tests.factories import Factories

OPML = b"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>My feeds</title></head>
  <body>
    <outline text="Tech" title="Tech">
      <outline type="rss" text="A Blog" xmlUrl="https://a.example/feed" htmlUrl="https://a.example/"/>
      <outline text="Deeper">
        <outline type="rss" text="B" xmlurl="https://b.example/rss.xml"/>
      </outline>
    </outline>
    <outline type="rss" title="A again" xmlUrl="https://a.example/feed"/>
    <outline text="Just a site" htmlUrl="https://c.example/"/>
    <outline text="Empty folder"/>
  </body>
</opml>
"""


def test_parses_feeds_from_nested_folders_once_each() -> None:
    assert parse_opml(OPML) == [
        Outline("https://a.example/feed", "https://a.example/", "A Blog", "Tech"),
        Outline("https://b.example/rss.xml", None, "B", "Deeper"),
        Outline(None, "https://c.example/", "Just a site", None),
    ]


def test_reads_decoded_text_whatever_encoding_it_declares() -> None:
    text = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        '<opml><body><outline text="Zażółć" xmlUrl="https://z.example/"/></body></opml>'
    )

    assert [outline.title for outline in parse_opml(text)] == ["Zażółć"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"<rss><channel/></rss>", "root element is <rss>"),
        (b"<opml><head/></opml>", "no <body>"),
        (b"not xml at all", "not an OPML file"),
        (
            b'<?xml version="1.0"?><!DOCTYPE opml [<!ENTITY a "aaaa">]>'
            b'<opml><body><outline xmlUrl="&a;"/></body></opml>',
            "not an OPML file",
        ),
    ],
)
def test_refuses_what_is_not_opml(data: bytes, message: str) -> None:
    with pytest.raises(ServiceError, match=message):
        parse_opml(data)


def test_renders_a_file_it_can_read_back() -> None:
    sources = [
        Source(name="A & B", url="https://a.example/feed?x=1&y=2", site_url="https://a.example/"),
        Source(name="Bell\x07 feed", url="https://b.example/rss", site_url=None),
    ]

    data = render_opml(sources, datetime(2026, 11, 5, 12, 0, tzinfo=UTC))

    assert b"<dateCreated>Thu, 05 Nov 2026 12:00:00 +0000</dateCreated>" in data
    assert parse_opml(data) == [
        Outline("https://a.example/feed?x=1&y=2", "https://a.example/", "A & B", None),
        Outline("https://b.example/rss", None, "Bell feed", None),
    ]


@dataclass
class Finder:
    feeds: dict[str, FoundFeed] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)
    hold: set[str] = field(default_factory=set)  # these wait for `release`
    release: threading.Event = field(default_factory=threading.Event)

    def find(self, url: str) -> FoundFeed | None:
        self.asked.append(url)
        if url in self.hold:
            self.release.wait(5)
        if url == "https://boom.example/":
            raise RuntimeError("unexpected")
        return self.feeds.get(url)


def feed(url: str, title: str | None = "Feed title") -> FoundFeed:
    return FoundFeed(url=url, title=title, site_url=url.rsplit("/", 1)[0] + "/")


def test_imports_new_feeds_as_pending_with_the_files_names(
    sessions: sessionmaker[Session], session: Session
) -> None:
    finder = Finder({"https://a.example/feed": feed("https://a.example/feed")})
    outline = Outline("https://a.example/feed", None, "My name for A", "Tech")

    report = import_outlines(sessions, finder, [outline], actor="cli")

    source = session.scalars(select(Source)).one()
    assert (source.name, source.status, source.origin, source.origin_detail) == (
        "My name for A",
        SourceStatus.PENDING,
        SourceOrigin.OPML,
        "Tech",
    )
    assert source.note == "In an imported OPML file."
    assert [(a.name, a.status) for a in report.added] == [("My name for A", SourceStatus.PENDING)]
    change = session.scalars(select(Change)).one()
    assert (change.actor, change.action) == ("cli", "source.propose")


def test_follows_them_right_away_when_asked(
    sessions: sessionmaker[Session], session: Session
) -> None:
    finder = Finder({"https://a.example/feed": feed("https://a.example/feed")})

    import_outlines(
        sessions,
        finder,
        [Outline("https://a.example/feed", None, None, None)],
        actor="cli",
        active=True,
    )

    source = session.scalars(select(Source)).one()
    assert (source.name, source.status, source.note) == ("Feed title", SourceStatus.ACTIVE, None)


def test_leaves_known_feeds_alone_without_asking_the_site(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    make.source("Declined", url="https://a.example/feed", status=SourceStatus.REJECTED)
    finder = Finder()

    report = import_outlines(
        sessions, finder, [Outline("a.example/feed", None, "A", None)], actor="cli"
    )

    assert [(k.name, k.status) for k in report.known] == [("Declined", SourceStatus.REJECTED)]
    assert finder.asked == []


def test_a_feed_found_under_a_known_url_counts_as_known(
    sessions: sessionmaker[Session], make: Factories
) -> None:
    make.source("Followed", url="https://a.example/feed")
    finder = Finder({"https://a.example/": feed("https://a.example/feed")})

    report = import_outlines(
        sessions, finder, [Outline(None, "https://a.example/", "A", None)], actor="cli"
    )

    assert (report.added, [k.name for k in report.known]) == ([], ["Followed"])


def test_looks_up_the_site_when_the_feed_url_fails(sessions: sessionmaker[Session]) -> None:
    finder = Finder({"https://a.example/": feed("https://a.example/new-feed")})

    report = import_outlines(
        sessions,
        finder,
        [Outline("https://a.example/old-feed", "https://a.example/", "A", None)],
        actor="cli",
    )

    assert [a.url for a in report.added] == ["https://a.example/new-feed"]
    assert finder.asked == ["https://a.example/old-feed", "https://a.example/"]


def test_reports_feeds_that_cannot_be_found(sessions: sessionmaker[Session]) -> None:
    outlines = [
        Outline("https://gone.example/feed", None, None, None),
        Outline(None, "https://boom.example/", None, None),
        Outline("ftp://files.example/feed", None, None, None),
    ]

    report = import_outlines(sessions, Finder(), outlines, actor="cli")

    assert [(f.url, f.reason) for f in report.failed] == [
        ("ftp://files.example/feed", "not an http(s) URL"),
        ("https://gone.example/feed", NO_FEED),
        ("https://boom.example/", NO_FEED),
    ]


def test_stops_looking_at_the_deadline(sessions: sessionmaker[Session]) -> None:
    finder = Finder(
        {
            "https://fast.example/feed": feed("https://fast.example/feed"),
            "https://slow.example/feed": feed("https://slow.example/feed"),
        },
        hold={"https://slow.example/feed"},
    )
    outlines = [
        Outline("https://slow.example/feed", None, None, None),
        Outline("https://fast.example/feed", None, None, None),
    ]
    now = [0.0]

    def clock() -> float:
        return now[0]

    try:
        report = import_outlines(
            sessions, finder, outlines, actor="api", deadline=0.2, workers=2, clock=clock
        )
    finally:
        finder.release.set()

    assert [a.url for a in report.added] == ["https://fast.example/feed"]
    assert report.unchecked == ["https://slow.example/feed"]


def test_two_outlines_of_one_feed_add_it_once(sessions: sessionmaker[Session]) -> None:
    finder = Finder(
        {
            "https://a.example/feed": feed("https://a.example/feed"),
            "https://a.example/": feed("https://a.example/feed"),
        }
    )
    outlines = [
        Outline("https://a.example/feed", None, "A", None),
        Outline(None, "https://a.example/", "A site", None),
    ]

    report = import_outlines(sessions, finder, outlines, actor="cli")

    assert [a.name for a in report.added] == ["A"]
    assert [(k.url, k.name) for k in report.known] == [("https://a.example/", "A")]


def test_the_files_name_wins_over_a_release_feeds_project_name(
    sessions: sessionmaker[Session], session: Session
) -> None:
    release = "https://github.com/owner/tool/releases.atom"
    finder = Finder(
        {release: feed(release), "https://n.example/feed": feed("https://n.example/feed")}
    )
    outlines = [
        Outline(release, None, "Tool releases", None),
        Outline("https://n.example/feed", None, "42", None),  # would read as an ID
    ]

    import_outlines(sessions, finder, outlines, actor="cli")

    assert session.scalars(select(Source.name).order_by(Source.id)).all() == [
        "Tool releases",
        "Feed title",
    ]


def test_a_lookup_cut_off_at_the_deadline_gives_up_quietly() -> None:
    stopped = threading.Event()
    stopped.set()
    finder = Finder()

    found = _find(finder, Outline("https://boom.example/", None, None, None), stopped)

    assert (found, finder.asked) == (None, [])


def test_an_error_after_the_deadline_is_not_logged() -> None:
    stopped = threading.Event()

    class Closing(Finder):
        def find(self, url: str) -> FoundFeed | None:
            self.asked.append(url)
            stopped.set()  # the deadline passes while the site is asked
            raise RuntimeError("Cannot send a request, as the client has been closed.")

    finder = Closing()
    outline = Outline("https://a.example/feed", "https://a.example/", None, None)

    with capture_logs() as logs:
        assert _find(finder, outline, stopped) is None

    assert logs == []
    assert finder.asked == ["https://a.example/feed"]  # not the site after it
