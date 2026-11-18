"""Shared HTTP plumbing for provider adapters: retries, caching, errors."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

import requests
from django.conf import settings
from django.core.cache import cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """A third-party service failed in a way we can explain to the user."""

    status_code = 502
    default_detail = "An upstream service failed."

    def __init__(self, detail: Optional[str] = None, *, provider: str = ""):
        self.provider = provider
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class ProviderTimeout(ProviderError):
    status_code = 504
    default_detail = "An upstream service timed out."


class ProviderUnavailable(ProviderError):
    status_code = 503
    default_detail = "An upstream service is unavailable."


class NotFound(ProviderError):
    """The service worked; the thing the user asked for does not exist.

    Distinct from the 5xx errors because the fix is the user's (fix the spelling,
    add a state), not ours.
    """

    status_code = 422
    default_detail = "No match was found."


def _build_session() -> requests.Session:
    """A session that retries idempotent failures with exponential backoff.

    The free public endpoints we rely on occasionally return 429/5xx under load;
    retrying transparently keeps a single slow request from failing the whole
    trip plan.
    """
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": settings.OUTBOUND_USER_AGENT})
    return session


#: One pooled session per process - connection reuse matters when a single
#: trip plan fans out to several routing and weather calls.
SESSION = _build_session()


def cache_key(prefix: str, payload: Any) -> str:
    """Stable cache key from a JSON-serialisable payload."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(blob.encode()).hexdigest()[:32]
    return f"{prefix}:{digest}"


def get_json(
    url: str,
    params: dict,
    *,
    provider: str,
    timeout: float,
    cache_prefix: Optional[str] = None,
    cache_ttl: int = 0,
    headers: Optional[dict] = None,
) -> Any:
    """GET a JSON document, with optional caching and uniform error mapping."""
    key = cache_key(cache_prefix, [url, params]) if cache_prefix and cache_ttl else None
    if key:
        hit = cache.get(key)
        if hit is not None:
            logger.debug("%s cache hit", provider)
            return hit

    try:
        response = SESSION.get(url, params=params, timeout=timeout, headers=headers)
    except requests.Timeout as exc:
        raise ProviderTimeout(
            f"{provider} did not respond in time.", provider=provider
        ) from exc
    except requests.RequestException as exc:
        raise ProviderUnavailable(
            f"Could not reach {provider}.", provider=provider
        ) from exc

    if response.status_code == 429:
        raise ProviderUnavailable(
            f"{provider} is rate-limiting requests; please retry shortly.",
            provider=provider,
        )
    if response.status_code >= 500:
        raise ProviderUnavailable(
            f"{provider} returned a server error ({response.status_code}).",
            provider=provider,
        )
    if response.status_code >= 400:
        raise ProviderError(
            f"{provider} rejected the request ({response.status_code}).",
            provider=provider,
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderError(
            f"{provider} returned a malformed response.", provider=provider
        ) from exc

    if key:
        cache.set(key, data, cache_ttl)
    return data
