"""Phase 11D — Learning Loop Gate read-only API.

GET-only endpoints for Director dashboard. POST/PATCH/DELETE return
405. Admin / director / owner / superuser only. None of these views
ever mutate a proposal or trigger any side effect — Director uses
the CLI commands for state transitions.
"""
from __future__ import annotations

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LearningProposal
from .service import get_proposals_summary


class _AdminLearningPermission(BasePermission):
    """Admin / director / owner / superuser only."""

    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = getattr(user, "role", "") or ""
        return role.lower() in {"admin", "director", "owner"}


def _serialize(row: LearningProposal) -> dict:
    return {
        "id": row.pk,
        "sourceAgent": row.source_agent,
        "proposalType": row.proposal_type,
        "title": row.title,
        "status": row.status,
        "impactScope": row.impact_scope,
        "evidence": dict(row.evidence or {}),
        "proposedChangeText": row.proposed_change_text,
        "directorDecision": row.director_decision,
        "directorNote": row.director_note,
        "reviewedBy": row.reviewed_by,
        "reviewedAt": (
            row.reviewed_at.isoformat() if row.reviewed_at else None
        ),
        "implementationNote": row.implementation_note,
        "implementedAt": (
            row.implemented_at.isoformat() if row.implemented_at else None
        ),
        "implementedBy": row.implemented_by,
        "caioSnapshotId": row.caio_snapshot_id,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


class LearningProposalsListView(APIView):
    """``GET /api/v1/learning/proposals/?status=&type=&limit=N``."""

    permission_classes = [_AdminLearningPermission]
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        qs = LearningProposal.objects.all()
        status = (request.query_params.get("status") or "").strip()
        proposal_type = (request.query_params.get("type") or "").strip()
        if status:
            qs = qs.filter(status=status)
        if proposal_type:
            qs = qs.filter(proposal_type=proposal_type)
        try:
            limit = int(request.query_params.get("limit") or 50)
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(200, limit))
        rows = list(qs.order_by("-created_at")[:limit])
        return Response(
            {
                "count": len(rows),
                "results": [_serialize(r) for r in rows],
            }
        )


class LearningProposalsPendingView(APIView):
    """``GET /api/v1/learning/proposals/pending/`` — shortcut for status=pending."""

    permission_classes = [_AdminLearningPermission]
    http_method_names = ["get", "head", "options"]

    def get(self, _request):
        rows = list(
            LearningProposal.objects.filter(
                status=LearningProposal.Status.PENDING.value
            ).order_by("-created_at")[:200]
        )
        return Response(
            {
                "count": len(rows),
                "results": [_serialize(r) for r in rows],
            }
        )


class LearningProposalsSummaryView(APIView):
    """``GET /api/v1/learning/proposals/summary/``."""

    permission_classes = [_AdminLearningPermission]
    http_method_names = ["get", "head", "options"]

    def get(self, _request):
        summary = get_proposals_summary()
        # camelCase the response for direct frontend consumption.
        return Response(
            {
                "pending": summary["pending"],
                "approved": summary["approved"],
                "rejected": summary["rejected"],
                "implemented": summary["implemented"],
                "cancelled": summary["cancelled"],
                "highImpactPending": summary["high_impact_pending"],
                "total": summary["total"],
            }
        )


class LearningProposalDetailView(APIView):
    """``GET /api/v1/learning/proposals/<int:pk>/``."""

    permission_classes = [_AdminLearningPermission]
    http_method_names = ["get", "head", "options"]

    def get(self, _request, pk: int):
        row = LearningProposal.objects.filter(pk=pk).first()
        if row is None:
            raise NotFound(f"LearningProposal {pk} not found.")
        return Response(_serialize(row))
