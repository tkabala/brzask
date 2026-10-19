from datetime import time
from decimal import Decimal
from ipaddress import ip_network
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import HttpUrl, ValidationError
from pydantic_settings import SettingsError

from brzask.config import Settings
from brzask.config.env_example import render
from brzask.config.settings import (
    GROUPS,
    AuthSettings,
    BudgetSettings,
    DatabaseSettings,
    EmbeddingSettings,
    ExtractorSettings,
    LLMSettings,
    LoggingSettings,
    Schedule,
    SchedulerSettings,
    WebSearchSettings,
    env_name,
)

ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"
SESSION_SECRET = "s" * 32


# --- Sources: defaults, environment, files -------------------------------------


def test_defaults_apply_when_nothing_is_set() -> None:
    llm = LLMSettings()

    assert llm.base_url == HttpUrl("https://openrouter.ai/api/v1")
    assert llm.model == "deepseek/deepseek-v4-flash"
    assert llm.api_key is None


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "llama3.2")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")

    llm = LLMSettings()

    assert llm.model == "llama3.2"
    assert str(llm.base_url) == "http://localhost:11434/v1"


def test_empty_secret_counts_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")

    assert LLMSettings().api_key is None


def test_secret_is_read_from_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret = tmp_path / "db_password"
    secret.write_text("from-file\n")
    monkeypatch.setenv("DB_PASSWORD_FILE", str(secret))

    assert DatabaseSettings().password.get_secret_value() == "from-file"


def test_secret_and_secret_file_together_are_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "key"
    secret.write_text("from-file")
    monkeypatch.setenv("LLM_API_KEY", "from-env")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(secret))

    with pytest.raises(SettingsError, match="either LLM_API_KEY or LLM_API_KEY_FILE"):
        LLMSettings()


def test_secret_file_wins_over_an_empty_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "key"
    secret.write_text("from-file")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(secret))

    api_key = LLMSettings().api_key

    assert api_key is not None
    assert api_key.get_secret_value() == "from-file"


def test_missing_secret_file_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DB_PASSWORD_FILE", str(tmp_path / "missing"))

    with pytest.raises(SettingsError, match="cannot read DB_PASSWORD_FILE"):
        DatabaseSettings()


def test_file_variables_only_apply_to_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = tmp_path / "model"
    model.write_text("other-model")
    monkeypatch.setenv("LLM_MODEL_FILE", str(model))

    assert LLMSettings().model == "deepseek/deepseek-v4-flash"


def test_secrets_are_not_shown_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PASSWORD", "hunter2")

    assert "hunter2" not in repr(DatabaseSettings())


# --- Groups ---------------------------------------------------------------------


def test_groups_are_validated_only_when_used() -> None:
    settings = Settings()

    # No DB_PASSWORD and no auth settings are set; the LLM group still loads.
    assert settings.llm.model
    with pytest.raises(ValidationError, match="password"):
        _ = settings.database


def test_database_url_escapes_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PASSWORD", "p@ss:w/rd")
    monkeypatch.setenv("DB_HOST", "db")

    url = DatabaseSettings().url

    assert url == "postgresql+psycopg://brzask:p%40ss%3Aw%2Frd@db:5432/brzask"


def test_database_url_brackets_ipv6_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PASSWORD", "x")
    monkeypatch.setenv("DB_HOST", "::1")

    assert DatabaseSettings().url == "postgresql+psycopg://brzask:x@[::1]:5432/brzask"


def test_database_port_must_be_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PASSWORD", "x")
    monkeypatch.setenv("DB_PORT", "70000")

    with pytest.raises(ValidationError, match="port"):
        DatabaseSettings()


def test_embedding_base_url_may_be_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_BASE_URL", "")

    assert EmbeddingSettings().base_url is None


def test_extractors_are_read_as_a_comma_separated_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACTORS", "trafilatura, feed")

    assert ExtractorSettings().extractors == ["trafilatura", "feed"]


def test_empty_extractors_leave_only_the_snippet_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXTRACTORS", "")

    assert ExtractorSettings().extractors == []


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"EXTRACTORS": "feed,unknown"}, "Input should be"),
        ({"EXTRACTORS": "feed,feed"}, "more than once"),
        ({"EXTRACTORS": "crawl4ai"}, "CRAWL4AI_BASE_URL"),
        ({"EXTRACTORS": "firecrawl"}, "FIRECRAWL_API_KEY"),
    ],
)
def test_invalid_extractor_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], message: str
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError, match=message):
        ExtractorSettings()


def test_self_hosted_firecrawl_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACTORS", "firecrawl")
    monkeypatch.setenv("FIRECRAWL_BASE_URL", "http://firecrawl:3002")

    assert ExtractorSettings().extractors == ["firecrawl"]


def test_web_search_is_off_by_default() -> None:
    assert WebSearchSettings().provider is None


@pytest.mark.parametrize(
    ("provider", "message"),
    [("searxng", "SEARXNG_URL"), ("brave", "BRAVE_API_KEY"), ("google", "Input should be")],
)
def test_web_search_provider_requirements(
    monkeypatch: pytest.MonkeyPatch, provider: str, message: str
) -> None:
    monkeypatch.setenv("WEB_SEARCH", provider)

    with pytest.raises(ValidationError, match=message):
        WebSearchSettings()


def test_llm_online_search_needs_only_the_llm_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_SEARCH", "llm-online")

    assert WebSearchSettings().provider == "llm-online"


def test_password_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_PASSWORD_HASH", ARGON2_HASH)
    monkeypatch.setenv("AUTH_SESSION_SECRET", SESSION_SECRET)

    assert AuthSettings().mode == "password"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"AUTH_SESSION_SECRET": SESSION_SECRET}, "requires AUTH_PASSWORD_HASH"),
        (
            {"AUTH_PASSWORD_HASH": "plain-text", "AUTH_SESSION_SECRET": SESSION_SECRET},
            "must be an argon2 hash",
        ),
        ({"AUTH_PASSWORD_HASH": ARGON2_HASH, "AUTH_SESSION_SECRET": "short"}, "32\\+ characters"),
        (
            {"AUTH_MODE": "header", "AUTH_SESSION_SECRET": SESSION_SECRET},
            "requires TRUSTED_PROXIES",
        ),
    ],
)
def test_invalid_auth_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], message: str
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError, match=message):
        AuthSettings()


def test_header_auth_reads_trusted_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "header")
    monkeypatch.setenv("AUTH_SESSION_SECRET", SESSION_SECRET)
    monkeypatch.setenv("TRUSTED_PROXIES", "172.18.0.0/16, 10.0.0.5, ::1")

    auth = AuthSettings()

    assert auth.trusted_proxies == [
        ip_network("172.18.0.0/16"),
        ip_network("10.0.0.5/32"),
        ip_network("::1/128"),
    ]


def test_no_auth_needs_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "none")

    assert AuthSettings().mode == "none"


def test_schedule_defaults() -> None:
    scheduler = SchedulerSettings()

    assert scheduler.digest_at == Schedule(time(7, 0))
    assert scheduler.review_at == Schedule(time(7, 30), weekday=0)
    assert scheduler.timezone == ZoneInfo("UTC")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("06:15", Schedule(time(6, 15))),
        ("Sun 21:00", Schedule(time(21, 0), weekday=6)),
        ("off", None),
        ("", None),
    ],
)
def test_schedule_parsing(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: Schedule | None
) -> None:
    monkeypatch.setenv("DIGEST_AT", value)

    assert SchedulerSettings().digest_at == expected


@pytest.mark.parametrize("value", ["7", "25:00", "funday 07:00", "mon"])
def test_invalid_schedule_is_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("DIGEST_AT", value)

    with pytest.raises(ValidationError):
        SchedulerSettings()


def test_schedule_round_trips_through_text() -> None:
    for text in ["07:00", "mon 07:30"]:
        assert str(Schedule.parse(text)) == text


def test_time_zone_comes_from_tz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Europe/Warsaw")

    assert SchedulerSettings().timezone == ZoneInfo("Europe/Warsaw")


def test_unknown_time_zone_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Mars/Olympus")

    with pytest.raises(ValidationError, match="unknown time zone"):
        SchedulerSettings()


def test_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BUDGET_DAILY_USD", "0.50")
    monkeypatch.setenv("LLM_BUDGET_MONTHLY_USD", "")

    budget = BudgetSettings()

    assert budget.daily_usd == Decimal("0.50")
    assert budget.monthly_usd is None


def test_budget_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BUDGET_DAILY_USD", "0")

    with pytest.raises(ValidationError):
        BudgetSettings()


# --- .env.example ---------------------------------------------------------------


def test_env_example_is_up_to_date() -> None:
    path = Path(__file__).parents[2] / ".env.example"

    assert path.read_text() == render(), "stale .env.example: run `just env-example`"


def test_env_example_lists_every_setting() -> None:
    rendered = render()

    for group in GROUPS:
        for name in group.model_fields:
            assert f"{env_name(group, name)}=" in rendered


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")

    assert LoggingSettings().level == "DEBUG"
