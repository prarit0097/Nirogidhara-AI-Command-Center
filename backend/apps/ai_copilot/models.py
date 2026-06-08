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

    # ----- Phase 16K — Department Workboard + Ownership / SLA layer -----
    class Department(models.TextChoices):
        UNASSIGNED = "", "Unassigned"
        CALLING = "calling", "Calling"
        CONFIRMATION = "confirmation", "Confirmation"
        QA_COMPLIANCE = "qa_compliance", "QA / Compliance"
        FINANCE_ACCOUNTS = "finance_accounts", "Finance / Accounts"
        DISPATCH_WAREHOUSE = "dispatch_warehouse", "Dispatch / Warehouse"
        DELIVERY_RTO = "delivery_rto", "Delivery / RTO"
        DIRECTOR_OFFICE = "director_office", "Director Office"
        DATA_OPS = "data_ops", "Data Ops"
        AI_GOVERNANCE = "ai_governance", "AI Governance"

    class WorkStatus(models.TextChoices):
        UNASSIGNED = "unassigned", "Unassigned"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In progress"
        BLOCKED = "blocked", "Blocked"
        COMPLETED_INTERNAL = "completed_internal", "Completed (internal only)"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

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

    # ----- Phase 16K — Department Workboard + Ownership / SLA layer -----
    # `work_status` is the INTERNAL execution tracker, independent of the
    # Phase 16J queue `status` (pending/applied/rejected/cancelled). It never
    # authorises a provider or external action — completing a workboard item is
    # internal-only. `sla_status` is computed at read time from `due_at`.
    department = models.CharField(
        max_length=24, choices=Department.choices, blank=True, default="",
        db_index=True,
    )
    assignee_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ai_actions_assigned",
    )
    work_status = models.CharField(
        max_length=20, choices=WorkStatus.choices,
        default=WorkStatus.UNASSIGNED, db_index=True,
    )
    due_at = models.DateTimeField(null=True, blank=True)
    blocker_reason = models.CharField(max_length=300, blank=True, default="")
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ai_actions_completed",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)

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
            models.Index(fields=["work_status"], name="ai_act_workstatus_idx"),
            models.Index(fields=["department"], name="ai_act_dept_idx"),
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


# ---------------------------------------------------------------------------
# Phase 16K — Department Action Workboard + Ownership / SLA Execution Layer
# ---------------------------------------------------------------------------
#
# An `AiActionWorkEvent` records an INTERNAL workboard transition on an
# `AiApprovedAction` (assign / claim / start / block / unblock / complete /
# reassign / note / director-review-requested). It NEVER calls a provider,
# never sends a customer-facing message, and never changes the Phase 15 safety
# shell. It is a department-execution audit trail only (no PII).


class AiActionWorkEvent(models.Model):
    """An internal department-workboard lifecycle event (no PII)."""

    class EventType(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        CLAIMED = "claimed", "Claimed"
        STARTED = "started", "Started"
        BLOCKED = "blocked", "Blocked"
        UNBLOCKED = "unblocked", "Unblocked"
        COMPLETED_INTERNAL = "completed_internal", "Completed (internal only)"
        REASSIGNED = "reassigned", "Reassigned"
        NOTE_ADDED = "note_added", "Note added"
        DIRECTOR_REVIEW_REQUESTED = "director_review_requested", "Director review requested"

    action = models.ForeignKey(
        AiApprovedAction, on_delete=models.CASCADE, related_name="work_events",
    )
    event_type = models.CharField(
        max_length=28, choices=EventType.choices, db_index=True,
    )
    note = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="ai_act_work_created_idx"),
            models.Index(fields=["event_type"], name="ai_act_work_type_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AiActionWorkEvent #{self.pk} ({self.event_type})"


# ---------------------------------------------------------------------------
# Phase 16L — Scoped Team Member Work Permissions + My Work Queue
# ---------------------------------------------------------------------------
#
# A minimal, additive department-membership layer scoped strictly to the
# Phase 16K AI workboard. It lets a non-admin team member safely CLAIM and WORK
# internal actions in a department they belong to — WITHOUT granting any broad
# Director/Admin power. This is NOT an HR / user-management system: it only
# governs who may work an already-created internal `AiApprovedAction`. It never
# touches a provider, never changes the Phase 15 safety shell, and never
# authorises a customer-facing/live action.


class AiWorkboardDepartmentMember(models.Model):
    """Scoped membership granting a user the right to work one department's queue."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="ai_workboard_memberships",
    )
    # Reuses the same 9 internal departments as Phase 16K (the empty
    # "Unassigned" choice is rejected at the service layer).
    department = models.CharField(
        max_length=24, choices=AiApprovedAction.Department.choices, db_index=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    can_claim = models.BooleanField(default=True)
    can_work = models.BooleanField(default=True)
    can_complete = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ai_workboard_memberships_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user"], name="ai_wb_member_user_idx"),
            models.Index(fields=["department"], name="ai_wb_member_dept_idx"),
            models.Index(fields=["is_active"], name="ai_wb_member_active_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "department"],
                condition=models.Q(is_active=True),
                name="ai_wb_member_unique_active_user_dept",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AiWorkboardDepartmentMember #{self.pk} ({self.user_id}/{self.department})"


# ---------------------------------------------------------------------------
# Phase 16O — Director Briefing Snapshot History + Acknowledgement Trail
# ---------------------------------------------------------------------------
#
# An `AiDirectorBriefingSnapshot` is an INTERNAL, point-in-time saved copy of a
# Phase 16N Director AI briefing (composed deterministically from existing
# workboard data). It lets the Director review / acknowledge / follow-up /
# archive / annotate briefings over time. Saving or transitioning a snapshot is
# DB-only: it NEVER calls a live AI/LLM provider, sends WhatsApp/Meta Cloud,
# places a Vapi call, calls Razorpay/PayU/Delhivery, creates a payment link /
# AWB, mutates an `Order` / `Payment` / `Shipment` / `Customer` / `Lead` /
# `AiApprovedAction`, or changes the Phase 15 safety shell. Every snapshot
# preserves the locked safety flags (`provider_call_made=False` +
# `external_action_taken=False` + `internal_only=True` + `readonly=True` +
# `live_autonomous_locked=True`) and the sanitized briefing payload (no raw
# prompts, secrets, full phones, addresses, or customer PII).


class AiDirectorBriefingSnapshot(models.Model):
    """An internal, saved Director AI briefing for review / acknowledgement."""

    class Status(models.TextChoices):
        UNREVIEWED = "unreviewed", "Unreviewed"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        NEEDS_FOLLOW_UP = "needs_follow_up", "Needs follow-up"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(max_length=200)
    window_days = models.IntegerField(default=7)

    # Sanitized Phase 16N briefing payload + its top-level sections (stored
    # separately so the history UI can render without re-deriving).
    briefing_payload = models.JSONField(default=dict, blank=True)
    executive_summary = models.JSONField(default=list, blank=True)
    attention_items = models.JSONField(default=dict, blank=True)
    recommendations = models.JSONField(default=list, blank=True)
    blocked_live_actions = models.JSONField(default=list, blank=True)
    safety_snapshot = models.JSONField(default=dict, blank=True)

    ai_mode = models.CharField(max_length=12, default="mock")

    # Locked safety contract — a briefing snapshot never authorises a provider
    # or external action.
    readonly = models.BooleanField(default=True)
    internal_only = models.BooleanField(default=True)
    provider_call_made = models.BooleanField(default=False)
    external_action_taken = models.BooleanField(default=False)
    live_autonomous_locked = models.BooleanField(default=True)

    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.UNREVIEWED, db_index=True,
    )
    director_note = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ai_briefing_snapshots_created",
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ai_briefing_snapshots_acknowledged",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    organization = models.ForeignKey(
        "saas.Organization", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="ai_brf_snap_status_idx"),
            models.Index(fields=["-created_at"], name="ai_brf_snap_created_idx"),
            models.Index(fields=["acknowledged_at"], name="ai_brf_snap_ack_idx"),
            models.Index(fields=["created_by"], name="ai_brf_snap_creator_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AiDirectorBriefingSnapshot #{self.pk} ({self.status})"


class AiDirectorBriefingSnapshotEvent(models.Model):
    """An internal review-trail event for a briefing snapshot (no PII)."""

    class EventType(models.TextChoices):
        CREATED = "created", "Created"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        MARKED_NEEDS_FOLLOW_UP = "marked_needs_follow_up", "Marked needs follow-up"
        ARCHIVED = "archived", "Archived"
        NOTE_ADDED = "note_added", "Note added"
        VIEWED = "viewed", "Viewed"

    snapshot = models.ForeignKey(
        AiDirectorBriefingSnapshot, on_delete=models.CASCADE, related_name="events",
    )
    event_type = models.CharField(
        max_length=28, choices=EventType.choices, db_index=True,
    )
    note = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="ai_brf_snap_evt_crt_idx"),
            models.Index(fields=["event_type"], name="ai_brf_snap_evt_type_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AiDirectorBriefingSnapshotEvent #{self.pk} ({self.event_type})"
