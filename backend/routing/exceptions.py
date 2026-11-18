"""Uniform error envelope for the API."""

from __future__ import annotations

import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .providers.base import ProviderError

logger = logging.getLogger(__name__)


class PlanningError(Exception):
    """A trip could not be planned for a reason the user can act on."""

    status_code = 422

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def api_exception_handler(exc, context):
    """Render provider and planning failures as ``{"error": {...}}``."""
    if isinstance(exc, ProviderError):
        logger.warning("provider error (%s): %s", exc.provider, exc.detail)
        return Response(
            {"error": {"detail": exc.detail, "source": exc.provider or "upstream"}},
            status=exc.status_code,
        )

    if isinstance(exc, PlanningError):
        return Response(
            {"error": {"detail": exc.detail, "source": "planner"}},
            status=exc.status_code,
        )

    response = drf_exception_handler(exc, context)
    if response is not None and not isinstance(response.data, dict):
        response.data = {"error": {"detail": response.data}}
    elif response is not None and "error" not in response.data:
        response.data = {"error": {"detail": response.data, "source": "request"}}
    return response
