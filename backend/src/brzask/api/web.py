"""The built web app, served at `/` next to the API.

`index.html` gets a `<base href>` naming the path the app is served at
(`/`, or BASE_URL's path such as `/brzask/`). The build uses relative URLs,
so the bundles, the manifest and the service worker resolve against it, and
the app reads its prefix from `document.baseURI`.

Paths without a file are the app's own routes (`/archive/2026-10-01`), so
they get `index.html` and the app's router takes over. Paths under `/api`
never do: an unknown API path stays a 404 problem. Neither does a route of
the API asked with another method (`HEAD /readyz`, `POST /api/v1/status`):
mounted at `/`, this app matches every path, so the router would hand it
those requests instead of answering 405.
"""

import re
from pathlib import Path
from urllib.parse import unquote

from starlette.exceptions import HTTPException
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Match
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

INDEX = "index.html"
# Vite puts content-hashed bundles here; a new build writes new names.
ASSETS = "assets/"
IMMUTABLE = "public, max-age=31536000, immutable"
# Everything else (index.html, favicon) is revalidated on every load, so a
# new version reaches browsers on the next visit.
REVALIDATE = "no-cache"
_BASE = re.compile(r"<base\b[^>]*>", re.IGNORECASE)
_HEAD = re.compile(r"<head\b[^>]*>", re.IGNORECASE)


def with_base(index: str, base_href: str) -> str:
    """`index` with one `<base href>` element, first in its head."""
    head = _HEAD.search(index)
    if head is None:
        raise RuntimeError(f"{INDEX} has no <head> to put the <base> element in")
    index = _BASE.sub("", index)
    head = _HEAD.search(index)
    assert head is not None  # noqa: S101  (removing <base> leaves the head)
    return f'{index[: head.end()]}<base href="{base_href}">{index[head.end() :]}'


class WebApp(StaticFiles):
    """Files of the built web app, with `index.html` for the app's routes."""

    def __init__(self, directory: Path, base_href: str = "/") -> None:
        if not (directory / INDEX).is_file():
            raise RuntimeError(f"{directory} has no {INDEX}; is it the built web app?")
        super().__init__(directory=directory)
        self.index = with_base((directory / INDEX).read_text(encoding="utf-8"), base_href)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # A route the router matched by path only (another method) answers
        # itself, with its 405 and Allow header.
        for route in getattr(scope.get("app"), "routes", ()):
            match, child_scope = route.matches(scope)
            if match is Match.PARTIAL:
                await route.handle({**scope, **child_scope}, receive, send)
                return
        await super().__call__(scope, receive, send)

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        if path in ("", ".", INDEX) and scope["method"] in ("GET", "HEAD"):
            return self._index()
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or path.startswith(ASSETS):
                raise
            return self._index()
        if response.status_code < 400:
            cache = IMMUTABLE if path.startswith(ASSETS) else REVALIDATE
            response.headers["cache-control"] = cache
        return response

    def _index(self) -> Response:
        return HTMLResponse(self.index, headers={"cache-control": REVALIDATE})


class PathPrefix:
    """Serves the app under `root_path` (BASE_URL's path), and without it.

    Sets the ASGI `root_path`, which Starlette drops from a path that starts
    with it, so `/brzask/api/v1/…` and `/api/v1/…` reach the same route. Not
    uvicorn's `--root-path`: uvicorn puts it in front of every path, which
    would double a prefix the proxy passed on. `/brzask` is redirected to
    `/brzask/`, as the app's relative URLs need the trailing slash.
    """

    def __init__(self, app: ASGIApp, root_path: str) -> None:
        self.app = app
        # As in URLs (percent-encoded), for the redirect; ASGI paths are decoded.
        self.root_path = root_path
        self.decoded = unquote(root_path)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "root_path": scope.get("root_path", "") + self.decoded}
        if scope["type"] == "http" and scope["path"] == self.decoded:
            query = scope.get("query_string", b"").decode("latin-1")
            location = f"{self.root_path}/" + (f"?{query}" if query else "")
            await RedirectResponse(location, status_code=308)(scope, receive, send)
            return
        await self.app(scope, receive, send)
