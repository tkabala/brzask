"""Application settings read from environment variables.

Settings are split into groups. Each group reads its own variables (``DB_HOST``,
``LLM_MODEL``, ...) and is validated the first time it is used, so a command only
needs the variables of the groups it touches. Every secret can also be read from
a file named by ``<NAME>_FILE``, which is how Docker and Kubernetes mount secrets.
"""

import os
import re
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from functools import cached_property, lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from typing import Annotated, Any, Literal, Self, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BeforeValidator,
    Field,
    HttpUrl,
    PlainSerializer,
    SecretStr,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
)
from sqlalchemy.engine import URL

# --- Helpers -----------------------------------------------------------------


def env_name(group: type[BaseSettings], field_name: str) -> str:
    """Environment variable that sets ``field_name`` of ``group``."""
    field = group.model_fields[field_name]
    if isinstance(field.validation_alias, str):
        return field.validation_alias
    return (group.model_config.get("env_prefix", "") + field_name).upper()


def is_secret(field: FieldInfo) -> bool:
    return field.annotation is SecretStr or SecretStr in get_args(field.annotation)


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _empty_to_none(value: object) -> object:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


OptionalSecret = Annotated[SecretStr | None, BeforeValidator(_empty_to_none)]
"""A secret that may be left out; an empty value counts as not set."""

CommaList = NoDecode, BeforeValidator(_split_csv)
"""Read a list from a comma-separated variable (``a,b,c``) instead of JSON."""


# --- Schedule ----------------------------------------------------------------

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_SCHEDULE_RE = re.compile(r"^(?:(?P<day>[a-z]{3})\s+)?(?P<hour>\d{1,2}):(?P<minute>\d{2})$")


@dataclass(frozen=True)
class Schedule:
    """When a pipeline runs: daily at ``at``, or weekly when ``weekday`` is set."""

    at: time
    weekday: int | None = None  # 0 = Monday

    @classmethod
    def parse(cls, value: str) -> Self:
        match = _SCHEDULE_RE.match(value.strip().lower())
        if match is None:
            raise ValueError(f"expected 'HH:MM' or '<mon..sun> HH:MM', got {value!r}")
        day = match["day"]
        if day is not None and day not in _WEEKDAYS:
            raise ValueError(f"unknown weekday {day!r}, expected one of {', '.join(_WEEKDAYS)}")
        at = time(int(match["hour"]), int(match["minute"]))
        return cls(at=at, weekday=None if day is None else _WEEKDAYS.index(day))

    def __str__(self) -> str:
        clock = self.at.strftime("%H:%M")
        return clock if self.weekday is None else f"{_WEEKDAYS[self.weekday]} {clock}"


def _parse_schedule(value: object) -> object:
    if isinstance(value, str):
        if value.strip().lower() in {"", "off"}:
            return None
        return Schedule.parse(value)
    return value


ScheduleSetting = Annotated[Schedule | None, BeforeValidator(_parse_schedule), PlainSerializer(str)]


def _parse_zone(value: object) -> object:
    if isinstance(value, str):
        try:
            return ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown time zone {value!r}") from error
    return value


Zone = Annotated[ZoneInfo, BeforeValidator(_parse_zone), PlainSerializer(str)]


# --- Base group ----------------------------------------------------------------


class SecretFilesSource(PydanticBaseSettingsSource):
    """Reads secret fields from the files named by ``<NAME>_FILE`` variables."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        # Values are produced in bulk by __call__.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, field in self.settings_cls.model_fields.items():
            if not is_secret(field):
                continue
            variable = env_name(self.settings_cls, name)
            path = os.environ.get(f"{variable}_FILE")
            if path is None:
                continue
            # An empty variable counts as not set, like `LLM_API_KEY=` in .env.example.
            if os.environ.get(variable):
                raise SettingsError(f"set either {variable} or {variable}_FILE, not both")
            try:
                # Secret files usually end with a newline that is not part of the secret.
                values[name] = Path(path).read_text(encoding="utf-8").strip()
            except OSError as error:
                raise SettingsError(f"cannot read {variable}_FILE={path}: {error}") from error
        return values


class SettingsGroup(BaseSettings):
    """A group of settings read from the environment."""

    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Secret files come before the environment so a file wins over an empty variable;
        # a non-empty variable together with its file is rejected by SecretFilesSource.
        return init_settings, SecretFilesSource(settings_cls), env_settings


# --- Groups --------------------------------------------------------------------


class DatabaseSettings(SettingsGroup):
    """Database: Postgres 17 with the pgvector extension."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    host: str = Field("localhost", description="Postgres host.")
    port: int = Field(5432, ge=1, le=65535, description="Postgres port.")
    name: str = Field("brzask", description="Database name.")
    user: str = Field("brzask", description="Database user.")
    password: SecretStr = Field(description="Database password.", examples=["brzask"])

    @property
    def url(self) -> str:
        """SQLAlchemy URL for the psycopg driver."""
        # URL.create escapes the parts and brackets IPv6 hosts.
        url = URL.create(
            "postgresql+psycopg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )
        return url.render_as_string(hide_password=False)


class LLMSettings(SettingsGroup):
    """LLM: any OpenAI-compatible chat completions API."""

    model_config = SettingsConfigDict(env_prefix="LLM_")

    base_url: HttpUrl = Field(
        HttpUrl("https://openrouter.ai/api/v1"),
        description="Base URL of the OpenAI-compatible API (OpenRouter, Ollama, ...).",
    )
    model: str = Field(
        "deepseek/deepseek-v4-flash", description="Model used for ranking and selection."
    )
    api_key: OptionalSecret = Field(None, description="API key; leave empty for local servers.")
    timeout_seconds: float = Field(
        300,
        gt=0,
        description="How long one request may take; ranking prompts are long.",
    )


class EmbeddingSettings(SettingsGroup):
    """Embeddings: any OpenAI-compatible /embeddings API."""

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_")

    base_url: Annotated[HttpUrl | None, BeforeValidator(_empty_to_none)] = Field(
        None, description="Base URL of the embeddings API; defaults to LLM_BASE_URL."
    )
    model: str = Field(
        "google/gemini-embedding-001",
        description="Embedding model; `brzask reembed` moves stored vectors to another one.",
    )
    api_key: OptionalSecret = Field(None, description="API key; defaults to LLM_API_KEY.")


class JudgeSettings(SettingsGroup):
    """Judgements: short typed questions (yes/no, one of a set, a level) about articles."""

    model_config = SettingsConfigDict(env_prefix="JUDGE_")

    backend: Literal["system-one", "llm"] = Field(
        "system-one",
        description="system-one (a System One model such as Jev or d1) or llm "
        "(the chat model answers in JSON; works with local servers).",
    )
    model: Annotated[str | None, BeforeValidator(_empty_to_none)] = Field(
        None,
        description="Model with its author prefix; defaults to typesafe/jev-1.13 "
        "for system-one and to LLM_MODEL for llm.",
    )
    base_url: Annotated[HttpUrl | None, BeforeValidator(_empty_to_none)] = Field(
        None, description="Base URL of the API; defaults to LLM_BASE_URL."
    )
    api_key: OptionalSecret = Field(None, description="API key; defaults to LLM_API_KEY.")


Extractor = Literal["feed", "trafilatura", "jina", "firecrawl", "crawl4ai"]

FIRECRAWL_CLOUD_URL = HttpUrl("https://api.firecrawl.dev")


class ExtractorSettings(SettingsGroup):
    """Article text extraction."""

    extractors: Annotated[list[Extractor], *CommaList] = Field(
        ["feed", "trafilatura", "jina"],
        validation_alias="EXTRACTORS",
        description="Extractors tried in order; the feed snippet is the final fallback.",
    )
    jina_api_key: OptionalSecret = Field(
        None, description="Jina Reader API key; optional, raises rate limits."
    )
    firecrawl_base_url: HttpUrl = Field(
        FIRECRAWL_CLOUD_URL, description="Firecrawl API URL; change it for a self-hosted instance."
    )
    firecrawl_api_key: OptionalSecret = Field(
        None, description="Firecrawl API key; required for the hosted service."
    )
    crawl4ai_base_url: Annotated[HttpUrl | None, BeforeValidator(_empty_to_none)] = Field(
        None, description="Crawl4AI server URL; required when crawl4ai is enabled."
    )

    @model_validator(mode="after")
    def _check_extractors(self) -> Self:
        if len(set(self.extractors)) != len(self.extractors):
            raise ValueError("EXTRACTORS lists an extractor more than once")
        if "crawl4ai" in self.extractors and self.crawl4ai_base_url is None:
            raise ValueError("EXTRACTORS includes crawl4ai but CRAWL4AI_BASE_URL is not set")
        if (
            "firecrawl" in self.extractors
            and self.firecrawl_base_url == FIRECRAWL_CLOUD_URL
            and self.firecrawl_api_key is None
        ):
            raise ValueError("EXTRACTORS includes firecrawl but FIRECRAWL_API_KEY is not set")
        return self


class WebSearchSettings(SettingsGroup):
    """Web search used by source discovery."""

    provider: Annotated[
        Literal["searxng", "llm-online", "brave"] | None, BeforeValidator(_empty_to_none)
    ] = Field(
        None,
        validation_alias="WEB_SEARCH",
        description="searxng, llm-online (recommended with OpenRouter) or brave; "
        "empty turns source discovery off.",
    )
    searxng_url: Annotated[HttpUrl | None, BeforeValidator(_empty_to_none)] = Field(
        None, description="SearXNG instance URL (JSON format must be enabled)."
    )
    brave_api_key: OptionalSecret = Field(None, description="Brave Search API key.")
    web_search_model: str = Field(
        "perplexity/sonar", description="Online model used by llm-online, through the LLM API."
    )

    @model_validator(mode="after")
    def _check_provider(self) -> Self:
        if self.provider == "searxng" and self.searxng_url is None:
            raise ValueError("WEB_SEARCH=searxng requires SEARXNG_URL")
        if self.provider == "brave" and self.brave_api_key is None:
            raise ValueError("WEB_SEARCH=brave requires BRAVE_API_KEY")
        return self


ProxyNetwork = IPv4Network | IPv6Network


def _parse_networks(value: object) -> object:
    items = _split_csv(value)
    if isinstance(items, list):
        return [ip_network(item, strict=False) if isinstance(item, str) else item for item in items]
    return items


class AuthSettings(SettingsGroup):
    """Authentication for the web UI and API."""

    model_config = SettingsConfigDict(env_prefix="AUTH_")

    mode: Literal["password", "header", "none"] = Field(
        "password",
        description="password, header (trust a reverse proxy) or none (no login, local use only).",
    )
    password_hash: OptionalSecret = Field(
        None, description="Argon2 hash of the login password (mode=password)."
    )
    session_secret: OptionalSecret = Field(
        None,
        description="Random string of at least 32 characters that signs CSRF tokens "
        "and article links.",
    )
    cookie_secure: bool = Field(
        True,
        description="Send the session cookie over HTTPS only; set false to log in "
        "over plain HTTP from another machine (localhost works either way).",
    )
    header: str = Field("Remote-User", description="Header with the user name (mode=header).")
    trusted_proxies: Annotated[list[ProxyNetwork], NoDecode, BeforeValidator(_parse_networks)] = (
        Field(
            [],
            validation_alias="TRUSTED_PROXIES",
            description="Comma-separated proxy addresses or networks allowed to set the header.",
        )
    )

    @model_validator(mode="after")
    def _check_mode(self) -> Self:
        if self.mode == "password":
            if self.password_hash is None:
                raise ValueError("AUTH_MODE=password requires AUTH_PASSWORD_HASH")
            if not self.password_hash.get_secret_value().startswith("$argon2"):
                raise ValueError("AUTH_PASSWORD_HASH must be an argon2 hash ($argon2id$...)")
        if self.mode != "none" and (
            self.session_secret is None or len(self.session_secret.get_secret_value()) < 32
        ):
            raise ValueError(
                f"AUTH_MODE={self.mode} requires AUTH_SESSION_SECRET of 32+ characters"
            )
        if self.mode == "header" and not self.trusted_proxies:
            raise ValueError("AUTH_MODE=header requires TRUSTED_PROXIES")
        return self


class SchedulerSettings(SettingsGroup):
    """Pipeline schedule for the worker. 'HH:MM' runs daily, '<mon..sun> HH:MM' weekly,
    'off' never."""

    digest_at: ScheduleSetting = Field(
        Schedule(time(7, 0)), description="When the daily digest is built."
    )
    review_at: ScheduleSetting = Field(
        Schedule(time(7, 30), weekday=0), description="When sources are reviewed."
    )
    visited_at: ScheduleSetting = Field(
        Schedule(time(7, 45), weekday=0),
        description="When opened links are checked for new sources.",
    )
    discovery_at: ScheduleSetting = Field(
        Schedule(time(8, 0), weekday=0), description="When new sources are searched for."
    )
    timezone: Zone = Field(
        ZoneInfo("UTC"),
        validation_alias="TZ",
        description="Time zone of the schedule and digest dates.",
    )


class DigestSettings(SettingsGroup):
    """Digest output."""

    model_config = SettingsConfigDict(env_prefix="DIGEST_")

    language: Literal["en", "pl"] = Field(
        "en", description="Language of digest titles and summaries."
    )
    ranking: Literal["llm", "judge"] = Field(
        "llm",
        description="llm (the LLM orders the pool) or judge (each article scored "
        "on several dimensions by JUDGE_BACKEND, weighted in code).",
    )
    deduplication: Literal["judge", "threshold"] = Field(
        "judge",
        description="judge (JUDGE_BACKEND decides same-day pairs in the grey zone; "
        "the threshold if it fails) or threshold (an adaptive similarity threshold).",
    )


PositiveAmount = Annotated[Annotated[Decimal, Field(gt=0)] | None, BeforeValidator(_empty_to_none)]


class BudgetSettings(SettingsGroup):
    """LLM spending limits; above a limit, expensive steps are skipped."""

    model_config = SettingsConfigDict(env_prefix="LLM_BUDGET_")

    daily_usd: PositiveAmount = Field(None, description="Daily limit in USD; empty for none.")
    monthly_usd: PositiveAmount = Field(None, description="Monthly limit in USD; empty for none.")


class LoggingSettings(SettingsGroup):
    """Logging."""

    model_config = SettingsConfigDict(env_prefix="LOG_")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        "INFO", description="Minimum level: DEBUG, INFO, WARNING or ERROR."
    )
    format: Literal["auto", "json", "console"] = Field(
        "auto",
        description="json (one object per line), console (readable) or auto (console on a TTY).",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalise_level(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("level"), str):
            data = {**data, "level": data["level"].upper()}
        return data


class TelemetrySettings(SettingsGroup):
    """Traces, metrics and error reports; all off unless configured."""

    otlp_endpoint: Annotated[HttpUrl | None, BeforeValidator(_empty_to_none)] = Field(
        None,
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
        description="OTLP/HTTP collector URL; traces and metrics are sent only when set.",
    )
    service_name: str = Field(
        "brzask", validation_alias="OTEL_SERVICE_NAME", description="Service name in traces."
    )
    sentry_dsn: OptionalSecret = Field(
        None, description="Sentry DSN; errors are reported only when set."
    )
    sentry_environment: str = Field(
        "production", description="Environment name attached to Sentry reports."
    )


GROUPS: tuple[type[SettingsGroup], ...] = (
    DatabaseSettings,
    LLMSettings,
    EmbeddingSettings,
    JudgeSettings,
    ExtractorSettings,
    WebSearchSettings,
    AuthSettings,
    SchedulerSettings,
    DigestSettings,
    BudgetSettings,
    LoggingSettings,
    TelemetrySettings,
)


# --- Entry point ---------------------------------------------------------------


class Settings:
    """All settings groups, each read and validated on first access."""

    @cached_property
    def database(self) -> DatabaseSettings:
        return DatabaseSettings()

    @cached_property
    def llm(self) -> LLMSettings:
        return LLMSettings()

    @cached_property
    def embedding(self) -> EmbeddingSettings:
        return EmbeddingSettings()

    @cached_property
    def judge(self) -> JudgeSettings:
        return JudgeSettings()

    @cached_property
    def extractors(self) -> ExtractorSettings:
        return ExtractorSettings()

    @cached_property
    def web_search(self) -> WebSearchSettings:
        return WebSearchSettings()

    @cached_property
    def auth(self) -> AuthSettings:
        return AuthSettings()

    @cached_property
    def scheduler(self) -> SchedulerSettings:
        return SchedulerSettings()

    @cached_property
    def digest(self) -> DigestSettings:
        return DigestSettings()

    @cached_property
    def budget(self) -> BudgetSettings:
        return BudgetSettings()

    @cached_property
    def logging(self) -> LoggingSettings:
        return LoggingSettings()

    @cached_property
    def telemetry(self) -> TelemetrySettings:
        return TelemetrySettings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings."""
    return Settings()
