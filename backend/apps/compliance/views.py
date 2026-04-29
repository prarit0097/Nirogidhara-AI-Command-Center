from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import ADMIN_AND_UP, RoleBasedPermission
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .coverage import build_coverage_report
from .models import Claim
from .serializers import ClaimSerializer


class ClaimViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Claim.objects.all()
    serializer_class = ClaimSerializer
    pagination_class = None


class _AdminAlways(RoleBasedPermission):
    """Admin / director only — even for safe methods."""

    allowed_roles = ADMIN_AND_UP

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(request.user, "is_superuser", False):
            return True
        roles = getattr(view, "allowed_write_roles", self.allowed_roles)
        return getattr(request.user, "role", None) in roles


class ClaimVaultCoverageView(APIView):
    """Phase 5D — ``GET /api/compliance/claim-coverage/`` (admin/director).

    Returns the full coverage report. Read-only; never mutates Claim
    rows. Writes a single ``compliance.claim_coverage.checked`` audit
    so director can prove the audit ran.
    """

    permission_classes = [_AdminAlways]

    def get(self, request):
        report = build_coverage_report()
        write_event(
            kind="compliance.claim_coverage.checked",
            text=(
                f"Claim Vault coverage check · total={report.total_products} "
                f"ok={report.ok_count} weak={report.weak_count} "
                f"missing={report.missing_count}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "total": report.total_products,
                "ok": report.ok_count,
                "weak": report.weak_count,
                "missing": report.missing_count,
                "by": getattr(request.user, "username", "") or "",
            },
        )
        return Response(report.to_dict())
