"""Serve the built React app from Django.

Keeping the SPA and the API in one process means the deployed app is a single
service with no CORS configuration and no second host to keep in sync. If the
frontend has not been built, the handler falls back to a JSON service
descriptor so the API is still usable on its own.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.http import HttpResponse, JsonResponse

API_DESCRIPTOR = {
    "service": "weather-aware truck routing API",
    "frontend": "not built - run `npm run build` in ./frontend",
    "endpoints": [
        "GET  /api/health",
        "GET  /api/rules",
        "GET  /api/geocode?q=",
        "POST /api/plan",
        "GET  /api/heatmap?plan_id=&route_id=&hours=",
    ],
}


@lru_cache(maxsize=1)
def _index_html() -> Optional[str]:
    """Read the built index.html once per process."""
    index: Path = settings.FRONTEND_DIST / "index.html"
    try:
        return index.read_text(encoding="utf-8")
    except OSError:
        return None


def spa(request, *args, **kwargs):
    """Return the SPA shell, letting the client router handle the path."""
    # Read on every request in DEBUG so a rebuild shows up without a restart.
    html = _index_html.__wrapped__() if settings.DEBUG else _index_html()
    if html is None:
        return JsonResponse(API_DESCRIPTOR)
    return HttpResponse(html, content_type="text/html; charset=utf-8")
