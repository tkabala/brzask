"""The built web app, served at `/` next to the API.

Paths without a file are the app's own routes (`/archive/2026-10-01`), so
they get `index.html` and the app's router takes over. Paths under `/api`
never do: an unknown API path stays a 404 problem.
"""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

INDEX = "index.html"
# Vite puts content-hashed bundles here; a new build writes new names.
ASSETS = "assets/"
IMMUTABLE = "public, max-age=31536000, immutable"
# Everything else (index.html, favicon) is revalidated on every load, so a
# new version reaches browsers on the next visit.
REVALIDATE = "no-cache"


class WebApp(StaticFiles):
    """Files of the built web app, with `index.html` for the app's routes."""

    def __init__(self, directory: Path) -> None:
        if not (directory / INDEX).is_file():
            raise RuntimeError(f"{directory} has no {INDEX}; is it the built web app?")
        super().__init__(directory=directory)

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or path.startswith(ASSETS):
                raise
            response = await super().get_response(INDEX, scope)
        if response.status_code < 400:
            cache = IMMUTABLE if path.startswith(ASSETS) else REVALIDATE
            response.headers["cache-control"] = cache
        return response
