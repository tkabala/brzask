"""Sites that need different handling than the default chain."""

from collections.abc import Mapping
from dataclasses import dataclass

from brzask.urls import host_matches


@dataclass(frozen=True, slots=True)
class DomainRule:
    only: frozenset[str]  # extractors allowed for the site; the snippet stays the fallback
    reason: str


FEED_ONLY = frozenset({"feed"})
VIDEO = frozenset({"youtube", "feed"})

DOMAIN_RULES: Mapping[str, DomainRule] = {
    # Fetchers get an HTTP 200 "blocked by network security" page; the feed
    # already carries the text of self posts.
    "reddit.com": DomainRule(FEED_ONLY, "Reddit blocks fetchers"),
    # Video pages have no article text, and EU visitors get a consent page; the
    # captions are the text, the feed's description the fallback.
    "youtube.com": DomainRule(VIDEO, "video page, read from its captions"),
    "youtu.be": DomainRule(VIDEO, "video page, read from its captions"),
}

# Extractors that read one kind of site only and are skipped by rule everywhere else.
SITE_EXTRACTORS: Mapping[str, tuple[str, ...]] = {"youtube": ("youtube.com", "youtu.be")}


def rule_for(host: str, rules: Mapping[str, DomainRule] = DOMAIN_RULES) -> DomainRule | None:
    return next((rule for domain, rule in rules.items() if host_matches(host, domain)), None)


def rules_allow(extractor: str, host: str, rules: Mapping[str, DomainRule] = DOMAIN_RULES) -> bool:
    """Whether the site's rule, and the extractor's own sites, let `extractor` read `host`."""
    sites = SITE_EXTRACTORS.get(extractor)
    if sites is not None and not any(host_matches(host, site) for site in sites):
        return False
    rule = rule_for(host, rules)
    return rule is None or extractor in rule.only
