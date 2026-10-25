from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint

from brzask.clients.extractors import (
    SNIPPET,
    Extracted,
    ExtractionBlockedError,
    ExtractionError,
    ExtractionInput,
    ExtractorChain,
    Outcome,
    build_chain,
)
from brzask.clients.extractors.chain import ATTEMPTS_METRIC, attempts_counter
from brzask.config.settings import ExtractorSettings

USABLE = "A real article paragraph. " * 20
URL = "https://blog.example.com/post"


@dataclass
class Fake:
    """An extractor that returns a fixed text, None, or raises."""

    name: str
    result: str | Exception | None = USABLE
    fetches_page: bool = True
    calls: list[str] = field(default_factory=list)

    def extract(self, item: ExtractionInput) -> Extracted | None:
        self.calls.append(item.url)
        if isinstance(self.result, Exception):
            raise self.result
        return Extracted(self.result) if self.result is not None else None


@dataclass
class Robots:
    allow: bool = True
    checks: int = 0

    def allowed(self, url: str) -> bool:
        self.checks += 1
        return self.allow


@pytest.fixture
def metrics() -> Iterator[tuple[MeterProvider, InMemoryMetricReader]]:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    yield provider, reader
    provider.shutdown()


def chain(
    *extractors: Fake, robots: Robots | None = None, provider: MeterProvider | None = None
) -> ExtractorChain:
    counter = attempts_counter(provider.get_meter("test")) if provider else None
    return ExtractorChain(list(extractors), robots, counter=counter)


def test_the_first_usable_extractor_wins() -> None:
    first, second, third = Fake("a", None), Fake("b"), Fake("c")

    result = chain(first, second, third).extract(ExtractionInput(URL))

    assert (result.text, result.extracted_by) == (USABLE.strip(), "b")
    assert [a.outcome for a in result.attempts] == [Outcome.EMPTY, Outcome.USABLE]
    assert third.calls == []


def test_unusable_and_failing_extractors_fall_through() -> None:
    extractors = (
        Fake("short", "Too short."),
        Fake("blocked", "You've been blocked by network security. " * 10),
        Fake("broken", ExtractionError("HTTPStatusError: 503")),
        Fake("good"),
    )

    result = chain(*extractors).extract(ExtractionInput(URL))

    assert result.extracted_by == "good"
    assert [(a.extractor, a.outcome) for a in result.attempts] == [
        ("short", Outcome.TOO_SHORT),
        ("blocked", Outcome.BLOCKED),
        ("broken", Outcome.FAILED),
        ("good", Outcome.USABLE),
    ]
    assert result.attempts[0].chars == len("Too short.")
    assert result.attempts[2].error == "HTTPStatusError: 503"


def test_a_site_that_refuses_the_extractor_counts_as_blocked() -> None:
    refused = Fake("browser", ExtractionBlockedError("Blocked by anti-bot protection: HTTP 403"))

    result = chain(refused, Fake("good")).extract(ExtractionInput(URL))

    assert result.extracted_by == "good"
    assert result.attempts[0].outcome is Outcome.BLOCKED
    assert result.attempts[0].error == "Blocked by anti-bot protection: HTTP 403"


def test_the_snippet_is_the_final_fallback() -> None:
    result = chain(Fake("a", None)).extract(
        ExtractionInput(URL, snippet="<p>Feed <b>summary</b></p>")
    )

    assert (result.text, result.extracted_by, result.extracted) == ("Feed summary", SNIPPET, None)


def test_nothing_at_all() -> None:
    result = chain(Fake("a", None)).extract(ExtractionInput(URL))

    assert (result.text, result.extracted_by) == (None, None)


def test_the_text_starts_at_the_headline_given_by_the_feed() -> None:
    page = f"## Newsletter\n\nSign up.\n\n# The Headline\n\n{USABLE}"

    result = chain(Fake("reader", page)).extract(ExtractionInput(URL, title="The headline"))

    assert result.text == f"# The Headline\n\n{USABLE}".strip()
    assert result.extracted is not None and result.extracted.text.startswith("# The Headline")


def test_the_usable_check_reads_the_text_from_the_headline() -> None:
    page = f"{USABLE}\n\n# The Headline\n\nA teaser."

    result = chain(Fake("reader", page)).extract(ExtractionInput(URL, title="The Headline"))

    assert [a.outcome for a in result.attempts] == [Outcome.TOO_SHORT]


def test_site_rules_limit_the_extractors() -> None:
    feed = Fake("feed", USABLE, fetches_page=False)
    page = Fake("trafilatura")

    result = chain(page, feed).extract(ExtractionInput("https://www.reddit.com/r/x/comments/1"))

    assert result.extracted_by == "feed"
    assert page.calls == []
    assert result.attempts[0].outcome is Outcome.SKIPPED_RULE


def test_reddit_without_feed_content_falls_back_to_the_snippet() -> None:
    page = Fake("jina")

    result = chain(Fake("feed", None, fetches_page=False), page).extract(
        ExtractionInput("https://old.reddit.com/r/x/comments/1", snippet="Self post text")
    )

    assert (result.text, result.extracted_by) == ("Self post text", SNIPPET)
    assert page.calls == []


def test_robots_blocks_only_extractors_that_fetch_the_page() -> None:
    robots = Robots(allow=False)
    page, reader = Fake("trafilatura"), Fake("jina")
    feed = Fake("feed", USABLE, fetches_page=False)

    result = chain(page, reader, feed, robots=robots).extract(ExtractionInput(URL))

    assert result.extracted_by == "feed"
    assert page.calls == reader.calls == []
    assert [a.outcome for a in result.attempts[:2]] == [Outcome.SKIPPED_ROBOTS] * 2
    assert robots.checks == 1  # asked once per article


def test_robots_is_not_asked_when_the_feed_wins_first() -> None:
    robots = Robots()

    chain(Fake("feed", USABLE, fetches_page=False), Fake("jina"), robots=robots).extract(
        ExtractionInput(URL)
    )

    assert robots.checks == 0


def test_attempts_are_counted_per_extractor_domain_and_outcome(
    metrics: tuple[MeterProvider, InMemoryMetricReader],
) -> None:
    provider, reader = metrics
    extractors = chain(Fake("a", None), Fake("b"), provider=provider)

    extractors.extract(ExtractionInput("https://www.example.com/1"))
    extractors.extract(ExtractionInput("https://www.example.com/2"))

    data = reader.get_metrics_data()
    assert data is not None
    [metric] = [
        m
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name == ATTEMPTS_METRIC
    ]
    points = [p for p in metric.data.data_points if isinstance(p, NumberDataPoint)]
    counts = {
        tuple(dict(p.attributes or {})[key] for key in ("extractor", "domain", "outcome")): p.value
        for p in points
    }
    assert counts == {("a", "example.com", "empty"): 2, ("b", "example.com", "usable"): 2}


def test_build_chain_follows_the_configured_order() -> None:
    settings = ExtractorSettings.model_validate(
        {"EXTRACTORS": "jina,feed,crawl4ai", "CRAWL4AI_BASE_URL": "http://crawl4ai:11235"}
    )

    built = build_chain(settings)

    assert [e.name for e in built.extractors] == ["jina", "feed", "crawl4ai"]
    assert built.robots is not None
