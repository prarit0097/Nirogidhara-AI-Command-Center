"""Phase 10A — Diagnostics read-only API.

GET-only endpoints exposing read-only operational drilldowns.
POST/PATCH/DELETE explicitly return 405 — these views never mutate.
"""
from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    list_pending_payments_drilldown,
)


class _AdminDiagnosticsPermission(BasePermission):
    """Admin / director / superuser only."""

    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = getattr(user, "role", "") or ""
        return role.lower() in {"admin", "director", "owner"}


def _parse_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_int_param(raw: Any, default: int, *, lo: int = 1, hi: int = MAX_LIMIT) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


class PendingPaymentsDrilldownView(APIView):
    """``GET /api/v1/diagnostics/pending-payments/``.

    Query params:
      ``include_partial`` (default true)
      ``limit`` (default 100, max 500)
      ``state`` (optional case-insensitive Order.state filter)

    Admin / director / superuser only. POST/PATCH/DELETE → 405.
    """

    permission_classes = [_AdminDiagnosticsPermission]
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        include_partial = _parse_bool(
            request.query_params.get("include_partial"), default=True
        )
        limit = _parse_int_param(
            request.query_params.get("limit"),
            DEFAULT_LIMIT,
            lo=1,
            hi=MAX_LIMIT,
        )
        state_filter = (request.query_params.get("state") or "").strip() or None
        rows = list_pending_payments_drilldown(
            include_partial=include_partial,
            limit=limit,
            state_filter=state_filter,
        )
        return Response(
            {
                "count": len(rows),
                "filters": {
                    "include_partial": include_partial,
                    "limit": limit,
                    "state": state_filter,
                },
                "results": rows,
            }
        )
