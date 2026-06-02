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


# ---------------------------------------------------------------------------
# Phase 16J — AI-Approved Internal Action Queue + Work Execution Bridge
# ---------------------------------------------------------------------------
#
# An `AiApprovedAction` converts an **approved** `AiCopilotSuggestion` into a
# safe, INTERNAL-only work item (a follow-up / QA / pilot / note / review task).
# Applying an action NEVER calls a provider, never sends a customer-facing
# message, never mutates a real `Order` / `Payment` / `Shipment` / `Customer`
# beyond an optional internal note/task, and never changes the Phase 15 safety
# shell. Every row keeps `provider_action_attempted=False` +
# `provider_action_taken=False` + `external_action_allowed=False` +
# `external_action_taken=False`.


class AiApprovedAction(models.Model):
    """An internal-only work item derived from an approved AI suggestion."""

    class ActionType(models.TextChoices):
        CALLING_FOLLOWUP_TASK = "create_calling_followup_task", "Create calling follow-up task"
        QA_REVIEW_TASK = "create_qa_review_task", "Create QA / compliance review task"
        PILOT_TASK = "create_pilot_task", "Create pilot task"
        CUSTOMER_NOTE = "create_customer_note", "Create customer note"
        ORDER_NOTE = "create_order_note", "Create order note"
        CALLBACK_ITEM = "create_callback_item", "Create callback reminder item"
        RTO_REVIEW_TASK = "create_rto_review_task", "Create RTO review task"
        PAYMENT_FOLLOWUP_TASK = "create_payment_followup_task", "Create payment follow-up task"
        DISPATCH_REVIEW_TASK = "create_dispatch_review_task", "Create dispatch readiness review task"
        DIRECTOR_REVIEW_ITEM = "create_director_review_item", "Create Director review item"

    class SourceType(models.TextChoices):
        LEAD = "lead", "Lead"
        CUSTOMER = "customer", "Customer"
        ORDER = "order", "Order"
        IMPORTED_QUEUE_ITEM = "imported_queue_item", "Imported call-queue item"
        PILOT_PLAN = "pilot_plan", "Pilot plan"
        PILOT_TASK = "pilot_task", "Pilot task"
        MANUAL = "manual", "Manual / none"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        PENDING_INTERNAL_ACTION = "pending_internal_action", "Pending internal action"
        APPLIED_INTERNAL = "applied_internal", "Applied (internal only)"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    source_suggestion = models.ForeignKey(
        AiCopilotSuggestion, on_delete=models.CASCADE, related_name="approved_actions",
    )
    action_type = models.CharField(
        max_length=40, choices=ActionType.choices, db_index=True,
    )
    source_type = models.CharField(
        max_length=24, choices=SourceType.choices,
        default=SourceType.MANUAL, db_index=True,
    )
    source_id = models.CharField(max_length=64, blank=True, default="")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    assigned_team = models.CharField(max_length=64, blank=True, default="")
    priority = models.CharField(
        max_length=8, choices=Priority.choices, default=Priority.NORMAL,
    )
    status = models.CharField(
        max_length=24, choices=Status.choices,
        default=Status.PENDING_INTERNAL_ACTION, db_index=True,
    )

    # Locked-safety contract — an internal action never touches a provider or
    # takes an external action.
    provider_action_attempted = models.BooleanField(default=False)
    provider_action_taken = models.BooleanField(default=False)
    external_action_allowed = models.BooleanField(default=False)
    external_action_taken = models.BooleanField(default=False)

    safety_snapshot = models.JSONField(default=dict, blank=True)
    result_payload = models.JSONField(default=dict, blank=True)
    failure_reason = models.CharField(max_length=200, blank=True, default="")

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ai_actions_approved",
    )
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ai_actions_applied",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ai_actions_created",
    )
    organization = models.ForeignKey(
        "saas.Organization", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="ai_act_created_idx"),
            models.Index(fields=["status"], name="ai_act_status_idx"),
            models.Index(fields=["action_type"], name="ai_act_type_idx"),
            models.Index(fields=["source_type"], name="ai_act_source_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AiApprovedAction #{self.pk} ({self.action_type}/{self.status})"


class AiApprovedActionEvent(models.Model):
    """An internal lifecycle event for an AI-approved action (no PII)."""

    class EventType(models.TextChoices):
        CREATED = "created", "Created"
        APPLIED_INTERNAL = "applied_internal", "Applied (internal only)"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"
        NOTE_ADDED = "note_added", "Note added"

    action = models.ForeignKey(
        AiApprovedAction, on_delete=models.CASCADE, related_name="events",
    )
    event_type = models.CharField(
        max_length=20, choices=EventType.choices, db_index=True,
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
            models.Index(fields=["-created_at"], name="ai_act_evt_created_idx"),
            models.Index(fields=["event_type"], name="ai_act_evt_type_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AiApprovedActionEvent #{self.pk} ({self.event_type})"
