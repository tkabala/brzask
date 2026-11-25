"""Security headers on every response.

The web app talks only to the server it came from, so its Content Security
Policy allows nothing else. Scripts come from the app's own files plus the
inline scripts of `index.html` (the theme script that must run before first
paint), allowed by hash; the hashes are taken from the built file at startup,
so editing that script cannot leave it blocked. Styles allow inline elements:
the dialog and menu components add `<style>` elements at run time.

The API's Swagger page is the one exception: FastAPI builds it from files on
cdn.jsdelivr.net, an inline script and an icon on fastapi.tiangolo.com.

HSTS is left to the reverse proxy that terminates TLS: brzask itself may be
served over plain HTTP on a home network.
"""

import base64
import hashlib
import re
from collections.abc import Sequence

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_INLINE_SCRIPT = re.compile(
    r"<script\b(?P<attributes>[^>]*)>(?P<body>.*?)</script\s*>", re.IGNORECASE | re.DOTALL
)
_SRC = re.compile(r"\bsrc\s*=", re.IGNORECASE)

COMMON = {
    "x-content-type-options": "nosniff",
    # Sites opened from a digest never learn the address brzask is served at.
    "referrer-policy": "no-referrer",
    # For browsers that predate frame-ancestors.
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}

SWAGGER_CDN = "https://cdn.jsdelivr.net"
SWAGGER_ICON = "https://fastapi.tiangolo.com"
DOCS_POLICY = "; ".join(
    (
        "default-src 'self'",
        # FastAPI writes the page's setup as an inline script whose text
        # depends on the request's path prefix, so it cannot be hashed ahead.
        f"script-src 'self' 'unsafe-inline' {SWAGGER_CDN}",
        f"style-src 'self' 'unsafe-inline' {SWAGGER_CDN}",
        f"img-src 'self' data: {SWAGGER_ICON}",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    )
)


def inline_script_hashes(page: str) -> list[str]:
    """CSP sources (`'sha256-…'`) for each inline `<script>` of an HTML page."""
    hashes = []
    for script in _INLINE_SCRIPT.finditer(page):
        if _SRC.search(script["attributes"]):
            continue
        digest = hashlib.sha256(script["body"].encode()).digest()
        hashes.append(f"'sha256-{base64.b64encode(digest).decode()}'")
    return hashes


def app_policy(script_hashes: Sequence[str]) -> str:
    """The web app's Content Security Policy."""
    return "; ".join(
        (
            "default-src 'self'",
            " ".join(("script-src 'self'", *script_hashes)),
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "manifest-src 'self'",
            "worker-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        )
    )


class SecurityHeaders:
    """Adds the common headers and a Content Security Policy to each response."""

    def __init__(self, app: ASGIApp, *, policy: str, docs_path: str) -> None:
        self.app = app
        self.policy = policy
        self.docs_path = docs_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        policy = DOCS_POLICY if _route_path(scope) == self.docs_path else self.policy

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in COMMON.items():
                    headers.setdefault(name, value)
                headers.setdefault("content-security-policy", policy)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _route_path(scope: Scope) -> str:
    """The request's path without the prefix the app is served under."""
    path: str = scope["path"]
    root: str = scope.get("root_path", "")
    if root and path.startswith(root):
        return path[len(root) :]
    return path
