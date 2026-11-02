"""URL helpers.

Links come from feeds and pages, where malformed ones (`http://[oops`) occur;
`urlsplit` raises on those, so these helpers treat them as not a URL.
"""

import re
from urllib.parse import unquote, urlsplit, urlunsplit


def host_of(url: str) -> str:
    """Lower-case host without `www.`; empty for something that is not a URL."""
    try:
        host = urlsplit(url.strip()).hostname or ""
    except ValueError:
        return ""
    return host.removeprefix("www.")


def is_http_url(url: str) -> bool:
    """True for a well-formed http(s) URL with a host."""
    try:
        parts = urlsplit(url)
        return parts.scheme in {"http", "https"} and bool(parts.hostname)
    except ValueError:
        return False


def host_matches(host: str, domain: str) -> bool:
    """True for the domain itself and its subdomains (`old.reddit.com` matches `reddit.com`)."""
    return host == domain or host.endswith(f".{domain}")


# Sites whose paths ignore case: GitHub owners and repositories, subreddits.
# Elsewhere a path's case matters (YouTube channel IDs differ only by it).
CASE_INSENSITIVE_PATHS = ("github.com", "reddit.com")


def feed_key(url: str) -> str:
    """`url` with the case that does not matter lowered, to tell whether two feeds are one.

    Scheme and host never depend on case; paths only on the sites above.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (parts.hostname or "").removeprefix("www.")
    path = parts.path
    if any(host_matches(host, site) for site in CASE_INSENSITIVE_PATHS):
        path = path.lower()
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, parts.fragment)
    )


_RELEASE_TAG = re.compile(r"^/[^/]+/[^/]+/releases/tag/([^/]+)/?$")


def item_key(link: str) -> str:
    """What two feeds share when they carry the same item under their own links.

    A GitHub release counts by its tag without a leading `v`, since a mirror or a
    fork links to its own repository (`owner/mirror/releases/tag/2.1.3` is
    `anthropics/claude-code/releases/tag/v2.1.3`); any other link by host
    (without `www.`), path without a trailing slash and query.
    """
    try:
        parts = urlsplit(link.strip())
    except ValueError:
        return link.strip()
    host = (parts.hostname or "").removeprefix("www.")
    if host == "github.com" and (tag := _RELEASE_TAG.match(parts.path)):
        return "release:" + unquote(tag.group(1)).lower().removeprefix("v")
    query = f"?{parts.query}" if parts.query else ""
    return f"{host}{parts.path.rstrip('/')}{query}"
