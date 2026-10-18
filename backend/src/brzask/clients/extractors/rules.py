"""Sites that need different handling than the default chain."""

from collections.abc import Mapping
from dataclasses import dataclass

from brzask.urls import host_matches


@dataclass(frozen=True, slots=True)
class DomainRule:
    only: frozenset[str]  # extractors allowed for the site; the snippet stays the fallback
    reason: str


FEED_ONLY = frozenset({"feed"})

DOMAIN_RULES: Mapping[str, DomainRule] = {
    # Fetchers get an HTTP 200 "blocked by network security" page; the feed
    # already carries the text of self posts.
    "reddit.com": DomainRule(FEED_ONLY, "Reddit blocks fetchers"),
    # Video pages have no article text, and EU visitors get a consent page.
    "youtube.com": DomainRule(FEED_ONLY, "video page, no article text"),
    "youtu.be": DomainRule(FEED_ONLY, "video page, no article text"),
}


def rule_for(host: str, rules: Mapping[str, DomainRule] = DOMAIN_RULES) -> DomainRule | None:
    return next((rule for domain, rule in rules.items() if host_matches(host, domain)), None)
