from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner, Result

from brzask import __version__
from brzask.cli import app, common
from brzask.clients.feed_finder import FoundFeed
from brzask.db.models import RunKind, RunStatus, SourceStatus
from brzask.repositories import RunRepository
from brzask.services import runs
from brzask.services.pause import paused_until
from brzask.services.runs import RunContext, SkipRunError
from tests.factories import Factories

runner = CliRunner()

Invoke = Callable[..., Result]


class FakeFinder:
    """Finds `feeds[url]`; any other http(s) URL is taken to be a feed without a title."""

    def __init__(self) -> None:
        self.feeds: dict[str, FoundFeed | None] = {}
        self.asked: list[str] = []

    def find(self, url: str) -> FoundFeed | None:
        self.asked.append(url)
        if url in self.feeds:
            return self.feeds[url]
        return FoundFeed(url, None, url) if url.startswith(("http://", "https://")) else None

    def close(self) -> None:
        pass


@pytest.fixture
def finder() -> FakeFinder:
    return FakeFinder()


@pytest.fixture
def cli(
    sessions: sessionmaker[Session], finder: FakeFinder, monkeypatch: pytest.MonkeyPatch
) -> Invoke:
    """Run a command against the test database, in UTC."""
    monkeypatch.setattr(common, "get_sessions", lambda: sessions)
    monkeypatch.setattr(common, "get_feed_finder", lambda: finder)
    monkeypatch.setenv("TZ", "UTC")

    def invoke(*args: str) -> Result:
        return runner.invoke(app, list(args))

    return invoke


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"brzask {__version__}"


def test_help_lists_the_commands() -> None:
    result = runner.invoke(app, ["--help"])

    for command in ("migrate", "run", "status", "sources", "interests", "pause", "resume"):
        assert command in result.stdout
    for group, commands in {
        "sources": ("list", "add", "mute", "enable"),
        "interests": ("list", "add", "edit"),
    }.items():
        output = runner.invoke(app, [group, "--help"]).stdout
        assert all(command in output for command in commands)


# --- sources -------------------------------------------------------------------


def test_sources_add_list_mute_enable(cli: Invoke) -> None:
    added = cli("sources", "add", "https://lobste.rs/rss", "--name", "Lobsters")
    assert added.exit_code == 0, added.output
    assert added.stdout.startswith("Added Lobsters (#")

    listed = cli("sources", "list")
    assert "Lobsters" in listed.stdout
    assert "https://lobste.rs/rss" in listed.stdout

    assert cli("sources", "mute", "lobsters", "--reason", "noisy").stdout == "Muted lobsters.\n"
    assert "already muted" in cli("sources", "mute", "Lobsters").stdout
    assert "No sources." in cli("sources", "list", "--status", "active").stdout
    assert "Lobsters" in cli("sources", "list", "-s", "muted").stdout

    assert cli("sources", "enable", "https://lobste.rs/rss").stdout.startswith("Enabled")


def test_sources_add_finds_the_feed_of_a_page(cli: Invoke, finder: FakeFinder) -> None:
    finder.feeds["https://blog.example.com/"] = FoundFeed(
        "https://blog.example.com/feed/", "Example Blog", "https://blog.example.com/"
    )

    added = cli("sources", "add", "https://blog.example.com/")

    assert added.exit_code == 0, added.output
    assert added.stdout.startswith("Added Example Blog (#")
    assert added.stdout.rstrip().endswith(": https://blog.example.com/feed/")


def test_sources_add_without_a_feed(cli: Invoke, finder: FakeFinder) -> None:
    finder.feeds["https://nofeed.example/"] = None

    result = cli("sources", "add", "https://nofeed.example/")

    assert result.exit_code == 1
    assert "no RSS or Atom feed found for https://nofeed.example/" in result.stderr


def test_a_known_url_is_reported_without_a_lookup(
    cli: Invoke, finder: FakeFinder, make: Factories
) -> None:
    make.source(url="https://known.example/feed", status=SourceStatus.MUTED)

    result = cli("sources", "add", "https://known.example/feed")

    assert result.exit_code == 1
    assert "already a source (muted)" in result.stderr
    assert finder.asked == []


def test_a_known_url_typed_without_a_scheme_is_reported_without_a_lookup(
    cli: Invoke, finder: FakeFinder, make: Factories
) -> None:
    make.source(url="https://known.example/feed")

    result = cli("sources", "add", " known.example/feed ")

    assert result.exit_code == 1
    assert "already a source (active)" in result.stderr
    assert finder.asked == []


def test_sources_errors_exit_with_a_message(cli: Invoke, make: Factories) -> None:
    make.source("Known", url="https://known.example/feed")

    duplicate = cli("sources", "add", "https://known.example/feed", "--name", "Other")
    missing = cli("sources", "mute", "Nope")

    assert duplicate.exit_code == 1
    assert "already a source (active)" in duplicate.stderr
    assert missing.exit_code == 1
    assert "Error: no source 'Nope'" in missing.stderr


def test_a_failed_command_writes_nothing(cli: Invoke, session: Session) -> None:
    result = cli("sources", "add", "not-a-url")

    assert result.exit_code == 1
    assert cli("sources", "list").stdout == "No sources.\n"


def test_sources_list_rejects_unknown_statuses(cli: Invoke) -> None:
    assert cli("sources", "list", "--status", "asleep").exit_code == 2


# --- interests -----------------------------------------------------------------


def test_interests_add_edit_list(cli: Invoke) -> None:
    added = cli("interests", "add", "Rust", "-k", "cargo, rustc", "-n", "skip: crate releases")
    assert added.exit_code == 0, added.output

    edited = cli("interests", "edit", "Rust", "--keywords", "cargo", "--inactive")
    assert edited.exit_code == 0, edited.output
    assert edited.stdout.startswith("Saved Rust (#")

    listed = cli("interests", "list").stdout.splitlines()
    assert listed[0].split() == ["ID", "TOPIC", "ACTIVE", "KEYWORDS", "NOTES"]
    assert listed[1].split()[1:] == ["Rust", "no", "cargo", "skip:", "crate", "releases"]
    assert cli("interests", "list", "--active").stdout == "No interests.\n"


def test_interests_edit_unknown(cli: Invoke) -> None:
    result = cli("interests", "edit", "Nope", "--notes", "x")

    assert result.exit_code == 1
    assert "no interest 'Nope'" in result.stderr


# --- pause / resume / status ---------------------------------------------------


def test_pause_and_resume(cli: Invoke, session: Session) -> None:
    paused = cli("pause", "--until", "2999-01-02")
    assert paused.exit_code == 0, paused.output
    assert paused.stdout == "Paused until 2999-01-02 00:00.\n"
    assert paused_until(session, datetime.now(UTC)) == datetime(2999, 1, 2, tzinfo=UTC)

    assert "Paused until 2999-01-02 00:00" in cli("status").stdout

    assert cli("resume").stdout == "Resumed.\n"
    assert cli("resume").stdout == "The digest was not paused.\n"


def test_pause_until_a_time_in_the_configured_zone(
    cli: Invoke, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TZ", "Europe/Warsaw")

    result = cli("pause", "--until", "2999-07-01T08:30")

    assert result.stdout == "Paused until 2999-07-01 08:30.\n"
    assert paused_until(session, datetime.now(UTC)) == datetime(2999, 7, 1, 6, 30, tzinfo=UTC)


@pytest.mark.parametrize(("value", "code"), [("tomorrow", 2), ("2000-01-01", 1)])
def test_pause_rejects_bad_or_past_dates(cli: Invoke, value: str, code: int) -> None:
    assert cli("pause", "--until", value).exit_code == code


def test_status_shows_counts_and_runs(cli: Invoke, make: Factories) -> None:
    source = make.source()
    make.source(status=SourceStatus.PENDING)
    make.article(source, opened_at=datetime.now(UTC))

    result = cli("status")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "Articles: 1 stored, 0 shown, 1 opened"
    assert lines[1].startswith("Sources: 1 active, 1 pending, 0 rejected")
    assert lines[2] == "Last digest: -"
    assert any(line.split() == ["digest", "never"] for line in lines)


# --- run -----------------------------------------------------------------------


def test_run_passes_options_and_reports_the_outcome(
    cli: Invoke, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[tuple[bool, bool]] = []

    def pipeline(context: RunContext) -> None:
        received.append((context.dry_run, context.force))
        raise SkipRunError("today's digest already exists")

    monkeypatch.setitem(runs.PIPELINES, RunKind.DIGEST, pipeline)

    result = cli("run", "digest", "--dry-run", "--force")

    assert result.exit_code == 0, result.output
    assert received == [(True, True)]
    assert result.stdout.startswith("digest skipped: today's digest already exists (run ")
    run = RunRepository(session).latest(RunKind.DIGEST)
    assert run is not None
    assert (run.status, run.dry_run) == (RunStatus.SKIPPED, True)


def test_run_of_a_pipeline_that_is_not_available(cli: Invoke) -> None:
    result = cli("run", "discovery")

    assert result.exit_code == 1
    assert "discovery pipeline is not available" in result.stderr


def test_run_rejects_unknown_pipelines(cli: Invoke) -> None:
    assert cli("run", "everything").exit_code == 2
