"""Phase 6M-0 — MCP Gateway models.

Six tables that define a SAFE registry for the future MCP-style
remote AI clients. Phase 6M-0 ships only the schema + read-only
defaults; no external client is active, no write tool is enabled,
no provider tool is enabled.

Hard rules (enforced by tests):

- Every model has safe defaults so a future migration won't break.
- No model stores raw secrets / raw tokens / raw provider responses.
- Customer PII is never persisted on these tables; ``McpToolInvocationLog``
  carries hashed input + safe summaries only.
- ``read_only=True`` is the default everywhere; ``allow_write_tools`` /
  ``allow_provider_tools`` default ``False``.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class McpClientApp(models.Model):
    """Future remote MCP client (Claude / ChatGPT / Codex / internal).

    Phase 6M-0 ships the schema only; no row is auto-activated.
    """

    class Provider(models.TextChoices):
        CLAUDE = "claude", "Claude"
        CHATGPT = "chatgpt", "ChatGPT"
        CODEX = "codex", "Codex"
        INTERNAL = "internal", "Internal"
        OTHER = "other", "Other"

    class AuthMode(models.TextChoices):
        BEARER_TOKEN = "bearer_token", "Bearer token"
        OAUTH_FUTURE = "oauth_future", "OAuth (future)"
        INTERNAL_ONLY = "internal_only", "Internal only"

    client_id = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    provider = models.CharField(
        max_length=24,
        choices=Provider.choices,
        default=Provider.OTHER,
        db_index=True,
    )
    description = models.TextField(blank=True, default="")
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mcp_client_apps",
    )
    branch = models.ForeignKey(
        "saas.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mcp_client_apps",
    )
    is_active = models.BooleanField(default=False, db_index=True)
    read_only = models.BooleanField(default=True)
    auth_mode = models.CharField(
        max_length=24,
        choices=AuthMode.choices,
        default=AuthMode.INTERNAL_ONLY,
    )
    allowed_origins = models.JSONField(default=list, blank=True)
    allowed_scopes = models.JSONField(default=list, blank=True)
    denied_scopes = models.JSONField(default=list, blank=True)
    rate_limit_per_minute = models.PositiveIntegerField(default=30)
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        indexes = (
            models.Index(fields=("is_active", "provider")),
            models.Index(fields=("organization", "is_active")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.client_id} ({self.provider})"


class McpAccessPolicy(models.Model):
    """Per-client / per-org policy that further restricts what the
    Phase 6M-0 registry will accept."""

    name = models.CharField(max_length=200)
    client_app = models.ForeignKey(
        McpClientApp,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="access_policies",
    )
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mcp_access_policies",
    )
    branch = models.ForeignKey(
        "saas.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mcp_access_policies",
    )
    enabled = models.BooleanField(default=True, db_index=True)
    read_only = models.BooleanField(default=True)
    allowed_tools = models.JSONField(default=list, blank=True)
    denied_tools = models.JSONField(default=list, blank=True)
    allowed_resources = models.JSONField(default=list, blank=True)
    denied_resources = models.JSONField(default=list, blank=True)
    allowed_prompts = models.JSONField(default=list, blank=True)
    denied_prompts = models.JSONField(default=list, blank=True)
    max_output_chars = models.PositiveIntegerField(default=12000)
    allow_write_tools = models.BooleanField(default=False)
    allow_provider_tools = models.BooleanField(default=False)
    require_human_approval_for_writes = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        indexes = (
            models.Index(fields=("enabled", "read_only")),
            models.Index(fields=("organization", "enabled")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} (read_only={self.read_only})"


class McpToolDefinition(models.Model):
    """One Phase 6M-0 MCP tool. Every tool defaults to ``read_only=True``,
    ``provider_call_allowed=False``, ``business_mutation_allowed=False``.
    Forbidden tools never get a row here."""

    class Category(models.TextChoices):
        SYSTEM = "system", "System"
        SAAS = "saas", "SaaS"
        AUDIT = "audit", "Audit"
        DASHBOARD = "dashboard", "Dashboard"
        WHATSAPP = "whatsapp", "WhatsApp"
        RAZORPAY = "razorpay", "Razorpay"
        PAYMENTS = "payments", "Payments"
        CRM = "crm", "CRM"
        ORDERS = "orders", "Orders"
        SHIPMENTS = "shipments", "Shipments"
        AGENTS = "agents", "Agents"

    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class PiiExposureLevel(models.TextChoices):
        NONE = "none", "None"
        MASKED = "masked", "Masked"
        SENSITIVE_BLOCKED = "sensitive_blocked", "Sensitive (blocked)"

    name = models.CharField(max_length=128, unique=True, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.CharField(
        max_length=24,
        choices=Category.choices,
        default=Category.SYSTEM,
        db_index=True,
    )
    handler_key = models.CharField(max_length=128, db_index=True)
    enabled = models.BooleanField(default=True, db_index=True)
    read_only = models.BooleanField(default=True)
    risk_level = models.CharField(
        max_length=16,
        choices=RiskLevel.choices,
        default=RiskLevel.LOW,
        db_index=True,
    )
    requires_auth = models.BooleanField(default=True)
    requires_org_context = models.BooleanField(default=True)
    requires_human_approval = models.BooleanField(default=False)
    provider_call_allowed = models.BooleanField(default=False)
    business_mutation_allowed = models.BooleanField(default=False)
    pii_exposure_level = models.CharField(
        max_length=24,
        choices=PiiExposureLevel.choices,
        default=PiiExposureLevel.NONE,
    )
    input_schema = models.JSONField(default=dict, blank=True)
    output_schema = models.JSONField(default=dict, blank=True)
    required_scopes = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("category", "name")
        indexes = (
            models.Index(fields=("enabled", "read_only")),
            models.Index(fields=("provider_call_allowed", "business_mutation_allowed")),
            models.Index(fields=("category", "risk_level")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} ({self.category}, {self.risk_level})"


class McpResourceDefinition(models.Model):
    """Read-only Phase 6M-0 MCP resource."""

    uri = models.CharField(max_length=200, unique=True, db_index=True)
    name = models.CharField(max_length=128)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    mime_type = models.CharField(max_length=64, default="application/json")
    enabled = models.BooleanField(default=True, db_index=True)
    read_only = models.BooleanField(default=True)
    requires_auth = models.BooleanField(default=True)
    required_scopes = models.JSONField(default=list, blank=True)
    pii_exposure_level = models.CharField(
        max_length=24,
        choices=McpToolDefinition.PiiExposureLevel.choices,
        default=McpToolDefinition.PiiExposureLevel.NONE,
    )
    handler_key = models.CharField(max_length=128, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("uri",)
        indexes = (
            models.Index(fields=("enabled", "read_only")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return self.uri


class McpPromptDefinition(models.Model):
    """Phase 6M-0 MCP prompt template. Templates only — never embed
    raw secrets or live values."""

    name = models.CharField(max_length=128, unique=True, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    template = models.TextField(blank=True, default="")
    variables_schema = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True, db_index=True)
    requires_auth = models.BooleanField(default=True)
    required_scopes = models.JSONField(default=list, blank=True)
    risk_level = models.CharField(
        max_length=16,
        choices=McpToolDefinition.RiskLevel.choices,
        default=McpToolDefinition.RiskLevel.LOW,
        db_index=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        indexes = (
            models.Index(fields=("enabled", "risk_level")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class McpToolInvocationLog(models.Model):
    """Audit row for one MCP tool invocation.

    Phase 6M-0 hard rules: NEVER stores raw input / raw secrets /
    full PII. ``input_hash`` lets the operator correlate replays;
    ``safe_input_summary`` and ``safe_output_summary`` carry only
    masked / aggregated info.
    """

    class Status(models.TextChoices):
        ALLOWED = "allowed", "Allowed"
        DENIED = "denied", "Denied"
        BLOCKED = "blocked", "Blocked"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    invocation_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
    )
    client_app = models.ForeignKey(
        McpClientApp,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invocations",
    )
    organization = models.ForeignKey(
        "saas.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mcp_invocations",
    )
    branch = models.ForeignKey(
        "saas.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mcp_invocations",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mcp_invocations",
    )
    tool_name = models.CharField(max_length=128, db_index=True)
    tool_category = models.CharField(max_length=24, blank=True, default="")
    handler_key = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ALLOWED,
        db_index=True,
    )
    denied_reason = models.CharField(max_length=200, blank=True, default="")
    risk_level = models.CharField(max_length=16, blank=True, default="low")
    read_only = models.BooleanField(default=True)
    provider_call_allowed = models.BooleanField(default=False)
    business_mutation_allowed = models.BooleanField(default=False)
    input_hash = models.CharField(max_length=64, blank=True, default="")
    safe_input_summary = models.JSONField(default=dict, blank=True)
    safe_output_summary = models.JSONField(default=dict, blank=True)
    output_truncated = models.BooleanField(default=False)
    raw_secret_exposed = models.BooleanField(default=False)
    full_pii_exposed = models.BooleanField(default=False)
    provider_call_attempted = models.BooleanField(default=False, db_index=True)
    business_mutation_attempted = models.BooleanField(default=False, db_index=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    error_summary = models.CharField(max_length=200, blank=True, default="")
    request_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("tool_name", "status")),
            models.Index(fields=("-created_at", "status")),
            models.Index(fields=("provider_call_attempted", "business_mutation_attempted")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.invocation_id} {self.tool_name} ({self.status})"
