"""Phase 16C — Director Operations read/review API.

Every endpoint here is internal-only and has ZERO external side effects:
no AI/LLM provider call, no AI briefing generation, no WhatsApp / Meta Cloud
send, no Razorpay / PayU charge, no Delhivery shipment, no Vapi call, no
business Celery enqueue, no RuntimeKillSwitch / SandboxState mutation. The
only writes are to ``DirectorBriefingReview`` and ``TeamRoleAssignment`` rows
plus a non-PII ``AuditEvent`` describing the internal review/assignment.
"""
from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.ceo_orchestration.models import CeoOrchestrationSnapshot
from apps.audit.signals import write_event

from .models import DirectorBriefingReview, TeamRoleAssignment
from .permissions import AdminOnly, AuthenticatedReadAdminWrite

User = get_user_model()

# Match the CEO orchestration sidebar staleness threshold (daily 13:00 IST
# sweep → anything older than ~36h means a missed run).
_STALE_AFTER_MINUTES = 36 * 60

# Static documentation facts surfaced to the Director Briefing page. These are
# project-state constants, NOT provider output. They never trigger anything.
_READINESS = {
    "baseline": (
        "Phase 16B — Customer Lifecycle UI Backbone (production verified, "
        "closed)"
    ),
    "safetyShellFrozen": True,
    "liveAutomationApproved": False,
    "currentPhase": "Phase 16C — Director Daily Briefing + Team Roles UI",
}


def _mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    masked_local = (local[0] + "***") if local else "***"
    return f"{masked_local}@{domain}"


def _serialize_review(review: DirectorBriefingReview) -> dict[str, Any]:
    return {
        "id": review.pk,
        "reviewerUsername": (
            review.reviewer.username if review.reviewer_id else None
        ),
        "note": review.note,
        "decisionStatus": review.decision_status,
        "snapshotRef": review.snapshot_ref,
        "createdAt": review.created_at,
        "updatedAt": review.updated_at,
    }


def _serialize_member(
    user, assignment: TeamRoleAssignment | None
) -> dict[str, Any]:
    return {
        "userId": user.id,
        "username": user.username,
        "displayName": (
            getattr(user, "display_name", "")
            or user.get_full_name()
            or user.username
        ),
        "emailMasked": _mask_email(user.email),
        "accountRole": getattr(user, "role", "") or "",
        "operationalRole": (
            assignment.operational_role if assignment else ""
        ),
        "operationalRoleLabel": (
            assignment.get_operational_role_display()
            if assignment
            else "Unassigned"
        ),
        "isActive": bool(user.is_active),
        "notes": assignment.notes if assignment else "",
        "assignedAt": assignment.updated_at if assignment else None,
    }


def _operational_role_options() -> list[dict[str, str]]:
    return [
        {"value": value, "label": label}
        for value, label in TeamRoleAssignment.OperationalRole.choices
    ]


class DirectorBriefingOverviewView(APIView):
    """``GET /api/v1/director-ops/briefing-overview/`` — read-only composite.

    Surfaces the latest CEO/Director snapshot status (fresh / stale / missing)
    + static readiness facts + the latest internal review. NEVER generates a
    briefing or calls a provider.
    """

    permission_classes = [AdminOnly]

    def get(self, request):
        snapshot = (
            CeoOrchestrationSnapshot.objects.order_by("-snapshot_at").first()
        )

        if snapshot is None:
            briefing = {
                "status": "missing",
                "source": "unavailable",
                "snapshotId": None,
                "generatedAt": None,
                "updatedAt": None,
                "ageMinutes": None,
                "healthScore": None,
                "healthTier": None,
                "briefingText": "",
                "alerts": [],
                "top3Priorities": [],
            }
        else:
            now = timezone.now()
            age_minutes = max(
                0, int((now - snapshot.snapshot_at).total_seconds()) // 60
            )
            status_label = (
                "stale" if age_minutes >= _STALE_AFTER_MINUTES else "fresh"
            )
            briefing = {
                "status": status_label,
                "source": "system_snapshot",
                "snapshotId": snapshot.pk,
                "generatedAt": snapshot.snapshot_at,
                "updatedAt": snapshot.updated_at,
                "ageMinutes": age_minutes,
                "healthScore": snapshot.business_health_score,
                "healthTier": snapshot.health_tier,
                "briefingText": snapshot.briefing_text,
                "alerts": list(snapshot.alerts or []),
                "top3Priorities": list(snapshot.top_3_priorities or []),
            }

        latest_review = DirectorBriefingReview.objects.order_by(
            "-created_at"
        ).first()

        return Response(
            {
                "briefing": briefing,
                "readiness": dict(_READINESS),
                "latestReview": (
                    _serialize_review(latest_review)
                    if latest_review
                    else None
                ),
                "reviewCount": DirectorBriefingReview.objects.count(),
                # Explicit, machine-readable guarantee for the frontend.
                "generatedByProvider": False,
            }
        )


class DirectorBriefingReviewsView(APIView):
    """``GET`` recent reviews / ``POST`` a new internal review-note."""

    permission_classes = [AdminOnly]

    def get(self, request):
        limit = 50
        rows = list(
            DirectorBriefingReview.objects.order_by("-created_at")[:limit]
        )
        return Response(
            {
                "items": [_serialize_review(r) for r in rows],
                "total": DirectorBriefingReview.objects.count(),
            }
        )

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        note = str(data.get("note", "") or "").strip()
        decision_status = str(
            data.get("decisionStatus", "")
            or DirectorBriefingReview.DecisionStatus.REVIEWED
        ).strip()

        valid_statuses = {
            c for c, _ in DirectorBriefingReview.DecisionStatus.choices
        }
        if decision_status not in valid_statuses:
            return Response(
                {
                    "detail": "invalid_decision_status",
                    "field": "decisionStatus",
                    "allowed": sorted(valid_statuses),
                },
                status=400,
            )
        if not note and decision_status == (
            DirectorBriefingReview.DecisionStatus.NEEDS_ACTION
        ):
            return Response(
                {
                    "detail": "note_required_for_needs_action",
                    "field": "note",
                },
                status=400,
            )

        snapshot_ref_raw = data.get("snapshotRef")
        snapshot_ref: int | None
        try:
            snapshot_ref = (
                int(snapshot_ref_raw) if snapshot_ref_raw not in (None, "")
                else None
            )
        except (TypeError, ValueError):
            snapshot_ref = None

        review = DirectorBriefingReview.objects.create(
            reviewer=request.user,
            note=note,
            decision_status=decision_status,
            snapshot_ref=snapshot_ref,
        )

        # Non-PII audit row — no briefing body, no email, no phone.
        write_event(
            kind="directorops.briefing_review.created",
            text=(
                f"Director briefing review #{review.pk} recorded "
                f"({decision_status})"
            ),
            payload={
                "review_id": review.pk,
                "decision_status": decision_status,
                "snapshot_ref": snapshot_ref,
                "has_note": bool(note),
            },
            user=request.user,
        )

        return Response(_serialize_review(review), status=201)


class TeamRolesListView(APIView):
    """``GET /api/v1/director-ops/team-roles/`` — users + operational roles.

    Read = any authenticated user. No raw email / phone is exposed (email is
    masked; the User model carries no phone).
    """

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        users = list(User.objects.order_by("username"))
        assignments = {
            a.user_id: a
            for a in TeamRoleAssignment.objects.select_related("user")
        }
        members = [
            _serialize_member(u, assignments.get(u.id)) for u in users
        ]
        return Response(
            {
                "members": members,
                "total": len(members),
                "operationalRoleOptions": _operational_role_options(),
            }
        )


class TeamRoleAssignView(APIView):
    """``POST /api/v1/director-ops/team-roles/assign/`` — admin/director only.

    Upserts the operational-role label for one user. Grants NO provider
    access and activates NO automation — it is an internal coordination label.
    """

    permission_classes = [AuthenticatedReadAdminWrite]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        user_id = data.get("userId")
        operational_role = str(data.get("operationalRole", "") or "").strip()

        valid_roles = {
            c for c, _ in TeamRoleAssignment.OperationalRole.choices
        }
        if operational_role not in valid_roles:
            return Response(
                {
                    "detail": "invalid_operational_role",
                    "field": "operationalRole",
                    "allowed": sorted(valid_roles),
                },
                status=400,
            )

        target = User.objects.filter(pk=user_id).first()
        if target is None:
            return Response(
                {"detail": "user_not_found", "field": "userId"},
                status=404,
            )

        is_active = bool(data.get("isActive", True))
        notes = str(data.get("notes", "") or "").strip()[:255]

        assignment, _created = TeamRoleAssignment.objects.update_or_create(
            user=target,
            defaults={
                "operational_role": operational_role,
                "is_active": is_active,
                "notes": notes,
                "assigned_by": request.user,
            },
        )

        # Non-PII audit row — only ids + role label, never email / name.
        write_event(
            kind="directorops.team_role.assigned",
            text=(
                f"Operational role '{operational_role}' assigned to "
                f"user #{target.id}"
            ),
            payload={
                "target_user_id": target.id,
                "operational_role": operational_role,
                "is_active": is_active,
                "assigned_by_id": request.user.id,
            },
            user=request.user,
        )

        return Response(
            _serialize_member(target, assignment), status=200
        )
