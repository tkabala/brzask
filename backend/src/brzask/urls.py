"""URL helpers."""

from urllib.parse import urlsplit


def host_of(url: str) -> str:
    """Lower-case host without `www.`; empty for something that is not a URL."""
    host = urlsplit(url.strip()).hostname or ""
    return host.removeprefix("www.")


def host_matches(host: str, domain: str) -> bool:
    """True for the domain itself and its subdomains (`old.reddit.com` matches `reddit.com`)."""
    return host == domain or host.endswith(f".{domain}")
