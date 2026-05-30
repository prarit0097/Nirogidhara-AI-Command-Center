"""Phase 16F — Controlled Internal Pilot Readiness + End-to-End Dry Run models.

Two additive, internal-only tables that record a Director's pilot dry-run
evaluation across the full business lifecycle (lead/imported contact → call
outcome → order → confirmation → payment readiness → shipment readiness →
delivery/RTO readiness) and the Director's review/sign-off decision.

**Nothing in this app calls a provider.** A dry-run NEVER creates a live
Razorpay/PayU payment link, captures/refunds, books a Delhivery AWB, sends
WhatsApp/Meta Cloud, places a Vapi call, calls any AI/LLM provider, enqueues a
business Celery job, or mutates `RuntimeKillSwitch` / `SandboxState`. It only
reads existing data + configuration and writes its own `PilotDryRun` /
`PilotDecision` rows (plus a non-PII `AuditEvent`). Linked Lead / Customer /
Order / imported-campaign rows are referenced, never mutated.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class PilotDryRun(models.Model):
    """One internal end-to-end pilot-readiness dry-run evaluation."""

    class ScenarioType(models.TextChoices):
        FRESH_LEAD = "fresh_lead", "Fresh lead"
        IMPORTED_CAMPAIGN = "imported_campaign", "Imported campaign"
        EXISTING_ORDER = "existing_order", "Existing order"
        PAYMENT_LOGISTICS = "payment_logistics", "Payment / logistics"
        FULL_LIFECYCLE = "full_lifecycle", "Full lifecycle"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PASSED = "passed", "Passed"
        WARNING = "warning", "Warning"
        BLOCKED = "blocked", "Blocked"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=160)
    scenario_type = models.CharField(
        max_length=24,
        choices=ScenarioType.choices,
        default=ScenarioType.FULL_LIFECYCLE,
        db_index=True,
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    # Optional references to existing records — referenced, NEVER mutated.
    selected_lead = models.ForeignKey(
        "crm.Lead", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    selected_customer = models.ForeignKey(
        "crm.Customer", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    selected_order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    selected_import_campaign = models.ForeignKey(
        "data_imports.ImportedCallingCampaign", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    selected_queue_item = models.ForeignKey(
        "data_imports.ImportedCallQueueItem", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pilot_dry_runs",
    )
    organization = models.ForeignKey(
        "saas.Organization", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    result_summary = models.TextField(blank=True, default="")
    gate_results = models.JSONField(default=list, blank=True)
    blocked_reasons = models.JSONField(default=list, blank=True)
    safety_snapshot = models.JSONField(default=dict, blank=True)

    # Locked-safety contract: a dry-run NEVER attempts a provider action and
    # ALWAYS reports provider actions as blocked.
    provider_actions_attempted = models.BooleanField(default=False)
    provider_actions_blocked = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="pilot_dr_created_idx"),
            models.Index(fields=["status"], name="pilot_dr_status_idx"),
            models.Index(fields=["scenario_type"], name="pilot_dr_scenario_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"PilotDryRun #{self.pk} ({self.status})"


class PilotDecision(models.Model):
    """An internal Director review / sign-off decision on a pilot dry-run."""

    class Decision(models.TextChoices):
        REVIEWED = "reviewed", "Reviewed"
        APPROVED_FOR_NEXT_PHASE = "approved_for_next_phase", "Approved for next phase"
        DEFERRED = "deferred", "Deferred"
        BLOCKED = "blocked", "Blocked"

    dry_run = models.ForeignKey(
        PilotDryRun, on_delete=models.CASCADE, related_name="decisions",
    )
    decision = models.CharField(
        max_length=32,
        choices=Decision.choices,
        default=Decision.REVIEWED,
        db_index=True,
    )
    note = models.TextField(blank=True, default="")
    # Internal-only sign-off checklist (booleans), e.g. pilot_team_selected,
    # allowed_list_approved, payment_mode_approved, etc. Stored as JSON so the
    # checklist can evolve without a migration. NEVER authorises a live action.
    signoff_checklist = models.JSONField(default=dict, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pilot_decisions",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="pilot_dec_created_idx"),
            models.Index(fields=["decision"], name="pilot_dec_decision_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"PilotDecision #{self.pk} ({self.decision})"
