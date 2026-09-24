"""Cache headers for the built frontend that FastAPI serves itself.

- HTML (index.html, and any other page in dist/) is revalidated on every load,
  so a browser, or an app installed from the home screen, never starts the old
  build after an upgrade: the old HTML would point at hashed chunks that no
  longer exist. The web app manifest too, so a new name or icon arrives with
  the next launch.
- /assets/* file names are content hashes, so they can be cached for a year.
  The header goes on 200 and 304 responses only, never on a 404.
"""

from __future__ import annotations

import os
from pathlib import Path

from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

NO_CACHE = "no-cache"
IMMUTABLE = "public, max-age=31536000, immutable"


def frontend_file(path: Path) -> FileResponse:
    """A file from dist/, with the Cache-Control its kind needs."""
    revalidate = path.suffix == ".html" or path.name == "manifest.webmanifest"
    headers = {"Cache-Control": NO_CACHE} if revalidate else None
    return FileResponse(path, headers=headers)


class ImmutableStaticFiles(StaticFiles):
    """StaticFiles for content-hashed assets: cached for a year once found."""

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        # Only called for a file that exists; the answer is 200 or 304 (NotModified).
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = IMMUTABLE
        return response
