"""Trying extractors in order until one returns usable text."""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from opentelemetry import metrics

from brzask.clients.extractors.base import (
    Extracted,
    ExtractionError,
    ExtractionInput,
    Extractor,
    unusable_reason,
)
from brzask.clients.extractors.rules import DOMAIN_RULES, DomainRule, rule_for
from brzask.log import get_logger
from brzask.text import strip_html
from brzask.urls import host_of

log = get_logger(__name__)

# Recorded as `extracted_by` when no extractor produced usable text.
SNIPPET = "snippet"

ATTEMPTS_METRIC = "brzask.extraction.attempts"


def attempts_counter(meter: metrics.Meter | None = None) -> metrics.Counter:
    return (meter or metrics.get_meter("brzask.extraction")).create_counter(
        ATTEMPTS_METRIC, description="Extraction attempts by extractor, site and outcome."
    )


class RobotsCheck(Protocol):
    def allowed(self, url: str) -> bool: ...


class Outcome(StrEnum):
    USABLE = "usable"
    TOO_SHORT = "too_short"
    BLOCKED = "blocked"  # an anti-bot or error page served with HTTP 200
    EMPTY = "empty"  # the extractor found no text
    FAILED = "failed"  # network error, HTTP error, unsupported content
    SKIPPED_RULE = "skipped_rule"  # the site's rule does not allow this extractor
    SKIPPED_ROBOTS = "skipped_robots"  # robots.txt disallows fetching the page


@dataclass(frozen=True, slots=True)
class Attempt:
    extractor: str
    outcome: Outcome
    chars: int = 0
    duration_ms: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    text: str | None  # None only when there is neither extracted text nor a snippet
    extracted_by: str | None  # the extractor's name, SNIPPET, or None
    extracted: Extracted | None = None  # the winning extractor's output, with metadata
    attempts: list[Attempt] = field(default_factory=list)


class ExtractorChain:
    """Extractors in the configured order; the feed snippet is the final fallback.

    Safe to share between threads when the extractors' HTTP client is.
    """

    def __init__(
        self,
        extractors: Sequence[Extractor],
        robots: RobotsCheck | None,
        rules: Mapping[str, DomainRule] = DOMAIN_RULES,
        counter: metrics.Counter | None = None,
    ) -> None:
        self.extractors = list(extractors)
        self.robots = robots
        self.rules = rules
        self.counter = counter or attempts_counter()

    def extract(self, item: ExtractionInput) -> ExtractionResult:
        host = host_of(item.url)
        rule = rule_for(host, self.rules)
        attempts: list[Attempt] = []
        robots_allowed: bool | None = None
        for extractor in self.extractors:
            if rule is not None and extractor.name not in rule.only:
                attempts.append(self._record(extractor.name, host, Outcome.SKIPPED_RULE))
                continue
            if extractor.fetches_page and self.robots is not None:
                if robots_allowed is None:
                    robots_allowed = self.robots.allowed(item.url)
                if not robots_allowed:
                    attempts.append(self._record(extractor.name, host, Outcome.SKIPPED_ROBOTS))
                    continue
            attempt, extracted = self._try(extractor, item, host)
            attempts.append(attempt)
            if extracted is not None:
                return ExtractionResult(extracted.text.strip(), extractor.name, extracted, attempts)

        snippet = strip_html(item.snippet) or None
        log.info("no usable extraction, using the snippet", url=item.url, attempts=len(attempts))
        return ExtractionResult(snippet, SNIPPET if snippet else None, None, attempts)

    def _try(
        self, extractor: Extractor, item: ExtractionInput, host: str
    ) -> tuple[Attempt, Extracted | None]:
        started = time.perf_counter()
        try:
            extracted = extractor.extract(item)
        except ExtractionError as error:
            elapsed = _ms(started)
            log.info("extraction failed", extractor=extractor.name, url=item.url, error=str(error))
            return self._record(extractor.name, host, Outcome.FAILED, 0, elapsed, str(error)), None
        elapsed = _ms(started)
        if extracted is None:
            return self._record(extractor.name, host, Outcome.EMPTY, 0, elapsed), None
        chars = len(extracted.text.strip())
        reason = unusable_reason(extracted.text)
        if reason is not None:
            outcome = Outcome(reason)
            return self._record(extractor.name, host, outcome, chars, elapsed), None
        return self._record(extractor.name, host, Outcome.USABLE, chars, elapsed), extracted

    def _record(
        self,
        extractor: str,
        host: str,
        outcome: Outcome,
        chars: int = 0,
        duration_ms: int = 0,
        error: str | None = None,
    ) -> Attempt:
        self.counter.add(1, {"extractor": extractor, "domain": host, "outcome": outcome.value})
        return Attempt(extractor, outcome, chars, duration_ms, error)


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
