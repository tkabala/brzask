import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner, Result

from brzask import __version__
from brzask.cli import app, common, run_cli
from brzask.clients.feed_finder import FoundFeed
from brzask.config.settings import LLMSettings, Settings
from brzask.db.models import RunKind, RunStatus, SourceStatus
from brzask.repositories import RunRepository
from brzask.services import pipelines
from brzask.services.pause import paused_until
from brzask.services.runs import RunContext, SkipRunError
from tests.factories import Factories
from tests.services.digest.fakes import FakeEmbedder
from tests.services.test_replay import FakeModel

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


def test_an_invalid_setting_is_reported_by_its_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOG_FORMAT", "xml")
    monkeypatch.setattr("sys.argv", ["brzask", "status"])

    with pytest.raises(SystemExit) as exit_info:
        run_cli()

    assert exit_info.value.code == 1
    error = capsys.readouterr().err
    assert "Error: invalid configuration" in error
    assert "  LOG_FORMAT: Input should be 'auto', 'json' or 'console'" in error
    assert "Traceback" not in error


def test_help_lists_the_commands() -> None:
    result = runner.invoke(app, ["--help"])

    top_level = (
        "migrate", "run", "status", "sources", "interests", "pause", "resume", "replay",
        "extract-bench", "reembed",
    )  # fmt: skip
    for command in top_level:
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
    make.article(source, opened_at=datetime.now(UTC), embedding=[1.0] + [0.0] * 767)

    result = cli("status")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "Articles: 1 stored, 0 shown, 1 opened"
    assert lines[1].startswith("Sources: 1 active, 1 pending, 0 rejected")
    assert lines[2] == "Embedding model: google/gemini-embedding-001"
    assert lines[3] == "Vectors: 1 test/embedding"
    assert lines[4] == "Last digest: -"
    assert any(line.split() == ["digest", "never"] for line in lines)


# --- run -----------------------------------------------------------------------


def test_run_passes_options_and_reports_the_outcome(
    cli: Invoke, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[tuple[bool, bool]] = []

    def pipeline(context: RunContext) -> None:
        received.append((context.dry_run, context.force))
        raise SkipRunError("today's digest already exists")

    monkeypatch.setitem(pipelines.PIPELINES, RunKind.DIGEST, pipeline)

    result = cli("run", "digest", "--dry-run", "--force")

    assert result.exit_code == 0, result.output
    assert received == [(True, True)]
    assert result.stdout.startswith("digest skipped: today's digest already exists (run ")
    run = RunRepository(session).latest(RunKind.DIGEST)
    assert run is not None
    assert (run.status, run.dry_run) == (RunStatus.SKIPPED, True)


def test_run_of_a_pipeline_that_is_not_available(
    cli: Invoke, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(pipelines.PIPELINES, RunKind.DISCOVERY)

    result = cli("run", "discovery")

    assert result.exit_code == 1
    assert "discovery pipeline is not available" in result.stderr


def test_run_rejects_unknown_pipelines(cli: Invoke) -> None:
    assert cli("run", "everything").exit_code == 2


# --- replay --------------------------------------------------------------------


@pytest.fixture
def models(
    cli: Invoke, sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    """Replays read the test database and ask a fake model; collects the models asked for."""
    asked: list[str] = []

    @contextmanager
    def llm_client(settings: LLMSettings) -> Iterator[FakeModel]:
        asked.append(settings.model)
        yield FakeModel()

    monkeypatch.setattr(common, "get_read_only_sessions", lambda: sessions)
    monkeypatch.setattr(common, "llm_client", llm_client)
    return asked


def test_replay_prints_days_and_totals(
    cli: Invoke, models: list[str], make: Factories, tmp_path: Path
) -> None:
    source = make.source()
    run_at = datetime.now(UTC) - timedelta(days=1)
    make.article(
        source,
        first_seen_at=run_at - timedelta(hours=1),
        digest_date=run_at.date(),
        shown_at=run_at,
        opened_at=run_at + timedelta(hours=1),
    )
    make.article(source, first_seen_at=run_at - timedelta(hours=1))
    config = tmp_path / "candidate.toml"
    config.write_text('llm_model = "other/model"\n')
    output = tmp_path / "replay.json"

    result = cli("replay", "--days", "3", "--config", str(config), "--json", str(output))

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].split() == [
        "DATE", "POOL", "OPENED", "IN", "POOL", "SHOWN:", "OPENED", "REPLAY:", "OPENED", "SAME",
        "ERROR",
    ]  # fmt: skip
    assert lines[1].split() == [run_at.date().isoformat(), "2", "1", "1/1", "1/2", "1"]
    assert "Replay: opened 1 of 2 picks (50%); shown: opened 1 of 1 (100%)" in result.stdout
    assert models == ["other/model"]
    assert json.loads(output.read_text())["summary"]["picked"] == 2


def test_replay_without_digests(cli: Invoke, models: list[str]) -> None:
    result = cli("replay", "--days", "1")

    assert result.exit_code == 0
    assert "No digests in that period." in result.stdout


def test_replay_rejects_a_bad_config_or_prompt_dir(
    cli: Invoke, models: list[str], tmp_path: Path
) -> None:
    config = tmp_path / "candidate.toml"
    config.write_text("[ranking]\ntop_m = 3\n")
    (tmp_path / "rankng.md").write_text("typo")

    bad_config = cli("replay", "--config", str(config))
    bad_prompts = cli("replay", "--prompt-dir", str(tmp_path))

    assert bad_config.exit_code == 2
    assert "top_m" in bad_config.stderr
    assert bad_prompts.exit_code == 2
    assert "rankng.md" in bad_prompts.stderr


# --- extract-bench ---------------------------------------------------------------


def test_extract_bench_checks_the_extractors(cli: Invoke) -> None:
    unknown = cli("extract-bench", "--extractors", "trafilatura,readability")
    unconfigured = cli("extract-bench", "--extractors", "crawl4ai")

    assert unknown.exit_code == 2
    assert "unknown extractor readability" in unknown.stderr
    assert unconfigured.exit_code == 2
    assert "CRAWL4AI_BASE_URL is not set" in unconfigured.stderr


def test_extract_bench_without_stored_links(
    cli: Invoke, sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(common, "get_read_only_sessions", lambda: sessions)

    result = cli("extract-bench", "--extractors", "trafilatura")

    assert result.exit_code == 0
    assert "No stored links in that period." in result.stdout


# --- reembed -----------------------------------------------------------------------


def test_reembed_moves_vectors_and_switches(
    cli: Invoke, make: Factories, monkeypatch: pytest.MonkeyPatch
) -> None:
    make.article(extracted_text="Text", embedding=[1.0] + [0.0] * 767)
    make.article(extracted_text=None, embedding=[1.0] + [0.0] * 767)
    models: list[str] = []

    @contextmanager
    def embedder(settings: Settings, model: str) -> Iterator[FakeEmbedder]:
        models.append(model)
        fake = FakeEmbedder()
        fake.model = model
        yield fake

    monkeypatch.setattr(common, "embedder", embedder)

    computed = cli("reembed", "--model", "new/embedding", "--no-switch")
    switched = cli("reembed", "--model", "new/embedding")
    status = cli("status")

    assert computed.exit_code == 0, computed.output
    assert computed.stdout.splitlines() == [
        "1 articles embedded with new/embedding.",
        "1 embedded articles have no stored text and were skipped.",
        "Active model is still google/gemini-embedding-001.",
    ]
    assert "1 embedded, 0 to go" in computed.stderr
    assert switched.stdout.splitlines()[0] == "0 articles embedded with new/embedding."
    assert switched.stdout.splitlines()[-1] == "Active model is now new/embedding."
    assert "Embedding model: new/embedding" in status.stdout
    assert models == ["new/embedding", "new/embedding"]
