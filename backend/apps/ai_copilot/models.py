"""Phase 16I — AI Copilot Enablement + Human Approval Workflow models.

Two additive, internal-only tables that record an AI **copilot suggestion**
(analysis / draft / recommendation generated deterministically by default) and
the human review decisions taken on it.

**Nothing in this app executes a business action or a live provider call.** A
suggestion NEVER sends WhatsApp/Meta Cloud, places a Vapi call, calls
Razorpay/PayU/Delhivery live, creates a payment link / AWB, mutates an
`Order` / `Payment` / `Shipment` / `Customer` / `Lead`, or changes the Phase 15
safety shell (`RuntimeKillSwitch` / `SandboxState`). Every suggestion carries
the locked contract `provider_call_made=False` + `external_action_allowed=False`
+ `external_action_taken=False`. AI generation is deterministic ("mock") by
default; a live LLM provider is NEVER called in this phase. Stored outputs are
sanitized — no full phone numbers, no full addresses, no raw provider payloads.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class AiCopilotSuggestion(models.Model):
    """One internal AI copilot suggestion awaiting human review."""

    class SuggestionType(models.TextChoices):
        LEAD_SUMMARY = "lead_summary", "Lead / customer summary"
        CALL_PRIORITY = "call_priority", "Call priority recommendation"
        CALL_SCRIPT = "call_script", "Suggested call script"
        OBJECTION_HANDLING = "objection_handling", "Objection handling"
        COMPLIANCE_RISK = "compliance_risk", "QA / compliance risk review"
        PILOT_RECOMMENDATION = "pilot_recommendation", "Pilot recommendation"
        TASK_RECOMMENDATION = "task_recommendation", "Task recommendation"
        DIRECTOR_BRIEFING = "director_briefing", "Director briefing recommendation"
        WHATSAPP_DRAFT = "whatsapp_draft", "WhatsApp follow-up draft"
        PAYMENT_FOLLOWUP_DRAFT = "payment_followup_draft", "Payment follow-up draft"
        RTO_RESCUE_DRAFT = "rto_rescue_draft", "RTO rescue draft"

    class SourceType(models.TextChoices):
        LEAD = "lead", "Lead"
        CUSTOMER = "customer", "Customer"
        ORDER = "order", "Order"
        IMPORTED_QUEUE_ITEM = "imported_queue_item", "Imported call-queue item"
        PILOT_PLAN = "pilot_plan", "Pilot plan"
        PILOT_TASK = "pilot_task", "Pilot task"
        MANUAL = "manual", "Manual / none"

    class AiMode(models.TextChoices):
        MOCK = "mock", "Mock (deterministic)"
        SANDBOX = "sandbox", "Sandbox (deterministic)"
        LIVE_GATED = "live_gated", "Live-gated (not invoked)"
        UNAVAILABLE = "unavailable", "Unavailable"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_REVIEW = "pending_review", "Pending review"
        APPROVED = "approved", "Approved (internal)"
        REJECTED = "rejected", "Rejected"
        APPLIED_INTERNAL = "applied_internal", "Applied (internal only)"

    suggestion_type = models.CharField(
        max_length=32, choices=SuggestionType.choices, db_index=True,
    )
    source_type = models.CharField(
        max_length=24, choices=SourceType.choices,
        default=SourceType.MANUAL, db_index=True,
    )
    # Source PK is a string because some sources (Lead/Order) use CharField PKs.
    source_id = models.CharField(max_length=64, blank=True, default="")

    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True, default="")
    recommendation = models.TextField(blank=True, default="")
    # Sanitized structured detail (risk flags, scores, draft body, etc).
    risk_flags = models.JSONField(default=list, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    confidence_score = models.FloatField(default=0.0)

    ai_mode = models.CharField(
        max_length=12, choices=AiMode.choices, default=AiMode.MOCK, db_index=True,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING_REVIEW, db_index=True,
    )
    reviewer_note = models.TextField(blank=True, default="")

    # Locked-safety contract — a copilot suggestion never touches a provider or
    # takes an external action in this phase.
    provider_call_made = models.BooleanField(default=False)
    external_action_allowed = models.BooleanField(default=False)
    external_action_taken = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ai_copilot_suggestions_created",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ai_copilot_suggestions_reviewed",
    )
    organization = models.ForeignKey(
        "saas.Organization", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="ai_cop_sug_created_idx"),
            models.Index(fields=["status"], name="ai_cop_sug_status_idx"),
            models.Index(fields=["suggestion_type"], name="ai_cop_sug_type_idx"),
            models.Index(fields=["source_type"], name="ai_cop_sug_source_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AiCopilotSuggestion #{self.pk} ({self.suggestion_type}/{self.status})"


class AiCopilotReviewEvent(models.Model):
    """An internal human review action on a copilot suggestion (no PII)."""

    class Action(models.TextChoices):
        GENERATED = "generated", "Generated"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        COMMENTED = "commented", "Commented"
        APPLIED_INTERNAL = "applied_internal", "Applied (internal only)"

    suggestion = models.ForeignKey(
        AiCopilotSuggestion, on_delete=models.CASCADE, related_name="events",
    )
    action = models.CharField(
        max_length=20, choices=Action.choices, db_index=True,
    )
    note = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="ai_cop_evt_created_idx"),
            models.Index(fields=["action"], name="ai_cop_evt_action_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AiCopilotReviewEvent #{self.pk} ({self.action})"
