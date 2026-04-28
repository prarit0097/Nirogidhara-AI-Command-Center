from __future__ import annotations

from django.db import models


class CeoBriefing(models.Model):
    """Singleton-ish: latest briefing wins. Blueprint Section 6.2.

    Phase 3+ will replace the seeded briefing with a generated one (LLM call
    over yesterday's KPIs); the storage shape stays identical.
    """

    date = models.CharField(max_length=40)
    headline = models.CharField(max_length=240)
    summary = models.TextField()
    alerts = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)


class CeoRecommendation(models.Model):
    briefing = models.ForeignKey(CeoBriefing, on_delete=models.CASCADE, related_name="recommendations")
    id_str = models.CharField(max_length=32)
    title = models.CharField(max_length=240)
    reason = models.TextField()
    impact = models.CharField(max_length=120)
    requires = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order",)


class CaioAudit(models.Model):
    """Blueprint Section 6.3 — audit findings the CAIO Agent surfaces.

    CAIO never executes business actions; this table is read-only from the
    governance UI's perspective in this phase.
    """

    class Severity(models.TextChoices):
        CRITICAL = "Critical", "Critical"
        HIGH = "High", "High"
        MEDIUM = "Medium", "Medium"
        LOW = "Low", "Low"

    agent = models.CharField(max_length=120)
    issue = models.CharField(max_length=240)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    suggestion = models.TextField()
    status = models.CharField(max_length=80, default="Open")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order",)


class AgentRun(models.Model):
    """Phase 3A — every dispatch to an LLM-backed agent is logged here.

    The model captures the prompt version, raw input slice, raw output, the
    provider/model that ran it, and timing/cost so operators can audit every
    decision the AI surfaces. Phase 3A always runs in read-only / dry-run
    mode: an AgentRun never directly mutates business state. Phase 5 builds
    the approval-matrix middleware that turns vetted suggestions into
    actions.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        SUCCESS = "success", "success"
        FAILED = "failed", "failed"
        SKIPPED = "skipped", "skipped"

    class Agent(models.TextChoices):
        CEO = "ceo", "ceo"
        CAIO = "caio", "caio"
        ADS = "ads", "ads"
        RTO = "rto", "rto"
        SALES_GROWTH = "sales_growth", "sales_growth"
        MARKETING = "marketing", "marketing"
        CFO = "cfo", "cfo"
        COMPLIANCE = "compliance", "compliance"

    id = models.CharField(primary_key=True, max_length=32)
    agent = models.CharField(max_length=24, choices=Agent.choices)
    prompt_version = models.CharField(max_length=24, default="v1.0")
    input_payload = models.JSONField(default=dict, blank=True)
    output_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=16, default="disabled")
    model = models.CharField(max_length=64, blank=True, default="")
    latency_ms = models.IntegerField(default=0)
    cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    # Phase 3C — token usage + provider fallback bookkeeping.
    prompt_tokens = models.IntegerField(null=True, blank=True)
    completion_tokens = models.IntegerField(null=True, blank=True)
    total_tokens = models.IntegerField(null=True, blank=True)
    provider_attempts = models.JSONField(default=list, blank=True)
    fallback_used = models.BooleanField(default=False)
    pricing_snapshot = models.JSONField(default=dict, blank=True)
    # Phase 3D — sandbox + prompt version + budget bookkeeping.
    sandbox_mode = models.BooleanField(default=False)
    prompt_version_ref = models.ForeignKey(
        "ai_governance.PromptVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_runs",
    )
    budget_status = models.CharField(max_length=12, blank=True, default="")
    budget_snapshot = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    dry_run = models.BooleanField(default=True)
    triggered_by = models.CharField(max_length=80, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("agent",)),
            models.Index(fields=("status",)),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.agent} · {self.status}"


class PromptVersion(models.Model):
    """Phase 3D — versioned prompt content per agent.

    A PromptVersion overrides the hard-coded ``system_policy`` /
    ``role_prompt`` blocks in ``apps.ai_governance.prompting`` for a
    specific agent. Only ONE row per agent is allowed to be ``is_active``
    at a time — activation flips the previous active version off.
    Rollback re-activates a prior version and writes an audit row.

    Compliance: a PromptVersion CANNOT skip the Approved Claim Vault
    block. The prompt builder always appends the relevant Claim entries
    on top of whatever ``system_policy`` / ``role_prompt`` the version
    supplies. This cannot be disabled from a PromptVersion row.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "draft"
        SANDBOX = "sandbox", "sandbox"
        ACTIVE = "active", "active"
        ROLLED_BACK = "rolled_back", "rolled_back"
        ARCHIVED = "archived", "archived"

    id = models.CharField(primary_key=True, max_length=32)
    agent = models.CharField(max_length=24, choices=AgentRun.Agent.choices)
    version = models.CharField(max_length=24)
    title = models.CharField(max_length=120, blank=True, default="")
    system_policy = models.TextField(blank=True, default="")
    role_prompt = models.TextField(blank=True, default="")
    instruction_payload = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.CharField(max_length=80, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    rollback_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.UniqueConstraint(
                fields=("agent", "version"),
                name="uniq_promptversion_agent_version",
            ),
            models.UniqueConstraint(
                fields=("agent",),
                condition=models.Q(is_active=True),
                name="uniq_promptversion_active_per_agent",
            ),
        )
        indexes = (
            models.Index(fields=("agent",)),
            models.Index(fields=("status",)),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.agent}:{self.version} ({self.status})"


class AgentBudget(models.Model):
    """Phase 3D — per-agent daily + monthly USD budgets.

    The runtime computes the agent's spend for the current period by
    summing ``AgentRun.cost_usd`` for that agent / period. When
    ``is_enforced=True`` and the spend has crossed the budget, the
    runtime refuses to dispatch the call and writes a ``failed`` AgentRun.
    Above ``alert_threshold_pct`` percent of the budget, we emit a
    ``ai.budget.warning`` audit row but still allow the call.
    """

    agent = models.CharField(
        max_length=24, choices=AgentRun.Agent.choices, unique=True
    )
    daily_budget_usd = models.DecimalField(
        max_digits=10, decimal_places=4, default=0
    )
    monthly_budget_usd = models.DecimalField(
        max_digits=10, decimal_places=4, default=0
    )
    is_enforced = models.BooleanField(default=True)
    alert_threshold_pct = models.IntegerField(default=80)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("agent",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.agent} · daily ${self.daily_budget_usd} / monthly ${self.monthly_budget_usd}"


class SandboxState(models.Model):
    """Singleton row holding the live sandbox toggle.

    ``is_enabled`` defaults to ``settings.AI_SANDBOX_MODE``. The PATCH
    endpoint ``/api/ai/sandbox/status/`` flips this row and writes an
    ``ai.sandbox.enabled`` / ``ai.sandbox.disabled`` audit event.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    is_enabled = models.BooleanField(default=False)
    note = models.CharField(max_length=240, blank=True, default="")
    updated_by = models.CharField(max_length=80, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"SandboxState(enabled={self.is_enabled})"


# ---------------------------------------------------------------------------
# Phase 4C — Approval Matrix Middleware enforcement.
# ---------------------------------------------------------------------------


class ApprovalRequest(models.Model):
    """Phase 4C — one row per business action that needs human/CEO-AI sign-off.

    Created by :mod:`apps.ai_governance.approval_engine` whenever an action
    classified ``approval_required``, ``director_override``, or
    ``human_escalation`` in :data:`apps.ai_governance.approval_matrix.APPROVAL_MATRIX`
    is requested. The middleware never silently executes; this row is the
    single durable record of intent + outcome.

    ``policy_snapshot`` freezes the matrix row that gated the request so
    later policy edits don't rewrite history.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        APPROVED = "approved", "approved"
        REJECTED = "rejected", "rejected"
        AUTO_APPROVED = "auto_approved", "auto_approved"
        BLOCKED = "blocked", "blocked"
        ESCALATED = "escalated", "escalated"
        EXPIRED = "expired", "expired"

    class Mode(models.TextChoices):
        AUTO = "auto", "auto"
        AUTO_WITH_CONSENT = "auto_with_consent", "auto_with_consent"
        APPROVAL_REQUIRED = "approval_required", "approval_required"
        DIRECTOR_OVERRIDE = "director_override", "director_override"
        HUMAN_ESCALATION = "human_escalation", "human_escalation"

    id = models.CharField(primary_key=True, max_length=40)
    action = models.CharField(max_length=120)
    mode = models.CharField(max_length=24, choices=Mode.choices)
    approver = models.CharField(max_length=24, default="auto")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests",
    )
    requested_by_agent = models.CharField(max_length=64, blank=True, default="")
    target_app = models.CharField(max_length=64, blank=True, default="")
    target_model = models.CharField(max_length=64, blank=True, default="")
    target_object_id = models.CharField(max_length=64, blank=True, default="")
    proposed_payload = models.JSONField(default=dict, blank=True)
    policy_snapshot = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default="")
    decision_note = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("action",)),
            models.Index(fields=("status",)),
            models.Index(fields=("mode",)),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.id} · {self.action} · {self.status}"


class ApprovalDecisionLog(models.Model):
    """Audit-style log for every status transition on an :class:`ApprovalRequest`.

    Decisions write a row here even when they also write a Master Event
    Ledger row, because the `metadata` and `note` fields belong in the
    governance domain rather than the global activity feed.
    """

    approval_request = models.ForeignKey(
        ApprovalRequest,
        on_delete=models.CASCADE,
        related_name="decision_logs",
    )
    old_status = models.CharField(max_length=16, blank=True, default="")
    new_status = models.CharField(max_length=16)
    decided_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (models.Index(fields=("approval_request", "created_at")),)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"{self.approval_request_id} · {self.old_status} → {self.new_status}"
        )
