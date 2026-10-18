"""URL helpers.

Links come from feeds and pages, where malformed ones (`http://[oops`) occur;
`urlsplit` raises on those, so these helpers treat them as not a URL.
"""

from urllib.parse import urlsplit


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
