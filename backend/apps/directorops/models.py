"""Phase 16C — Director Operations models.

Two additive, internal-only review/coordination tables:

* ``DirectorBriefingReview`` — a Director's review/note/decision recorded
  against the latest CEO/Director briefing snapshot. Creating one is a pure
  DB write; it NEVER generates an AI briefing, calls a provider, sends
  WhatsApp, takes a payment, books a shipment, calls a customer, or enqueues
  a business Celery job.

* ``TeamRoleAssignment`` — an internal *operational team* label layered on
  top of the core ``User.role`` RBAC. It is for human coordination only and
  is NOT consulted by any send / payment / courier / call / provider code
  path. Assigning a role grants NO provider access and activates NO
  automation.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class DirectorBriefingReview(models.Model):
    """Internal-only Director review/note on the latest briefing snapshot."""

    class DecisionStatus(models.TextChoices):
        REVIEWED = "reviewed", "Reviewed"
        NEEDS_ACTION = "needs_action", "Needs action"
        DEFERRED = "deferred", "Deferred"

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="director_briefing_reviews",
    )
    note = models.TextField(blank=True, default="")
    decision_status = models.CharField(
        max_length=20,
        choices=DecisionStatus.choices,
        default=DecisionStatus.REVIEWED,
        db_index=True,
    )
    # Opaque pointer to the CeoOrchestrationSnapshot.id this review was made
    # against. Kept as a plain IntegerField (NOT a ForeignKey) so deleting a
    # snapshot never breaks the review trail and ``apps.directorops`` stays
    # decoupled from the agents app.
    snapshot_ref = models.IntegerField(null=True, blank=True)
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="dbr_created_idx"),
            models.Index(fields=["decision_status"], name="dbr_decision_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"BriefingReview #{self.pk} ({self.decision_status})"


class TeamRoleAssignment(models.Model):
    """Internal operational-team label for a user (additive over User.role)."""

    class OperationalRole(models.TextChoices):
        DIRECTOR_ADMIN = "director_admin", "Director / Admin"
        CALLING_AGENT = "calling_agent", "Calling Agent"
        CONFIRMATION_TEAM = "confirmation_team", "Confirmation Team"
        WAREHOUSE_DISPATCH = "warehouse_dispatch", "Warehouse / Dispatch"
        DELIVERY_RTO = "delivery_rto", "Delivery / RTO Team"
        QA_COMPLIANCE = "qa_compliance", "QA / Compliance"
        FINANCE_ACCOUNTS = "finance_accounts", "Finance / Accounts"
        READ_ONLY_VIEWER = "read_only_viewer", "Read-only Viewer"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_role_assignment",
    )
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    operational_role = models.CharField(
        max_length=40,
        choices=OperationalRole.choices,
        default=OperationalRole.READ_ONLY_VIEWER,
        db_index=True,
    )
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True, default="")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="team_role_assignments_made",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["operational_role", "user_id"]
        indexes = [
            models.Index(fields=["operational_role"], name="tra_role_idx"),
            models.Index(fields=["is_active"], name="tra_active_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.user_id} -> {self.operational_role}"
