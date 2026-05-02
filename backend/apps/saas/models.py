"""Phase 6A — SaaS Foundation models.

Five tables that scaffold multi-tenancy WITHOUT touching the existing
production data shape:

- :class:`Organization` — top-level tenant.
- :class:`Branch` — child entity for multi-location operations under an
  Organization.
- :class:`OrganizationMembership` — pivot between users and organizations
  with an org-level role distinct from the existing ``User.role``.
- :class:`OrganizationFeatureFlag` — per-org boolean toggles (e.g. WhatsApp
  AI auto-reply gate, lifecycle automation, broadcast campaigns) so the
  next phase can flip flags per tenant without a global env flip.
- :class:`OrganizationSetting` — typed JSON values keyed by
  ``(organization, key)``. Rows marked ``is_sensitive=True`` are filtered
  out of every public-API selector — only management commands and admin
  scripts may read them, and they MUST be encrypted at rest before any
  real secret lands here. Phase 6A ships the schema only; no real
  credentials are written into ``OrganizationSetting`` yet.

Hard rules:

- Every column has a sane default so a future backfill / migration won't
  break.
- ``Organization.code`` is human-readable (``"nirogidhara"``) and used for
  URL slugs / cohort filtering once Phase 6C lands.
- ``OrganizationMembership`` carries an org-level role enumeration that
  intentionally does NOT mirror :class:`apps.accounts.models.User.Role`.
  The user-level role still gates global RBAC; the org-level role gates
  what the user can do *inside* a specific org once tenant filtering is
  enforced.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


_SENSITIVE_CONFIG_KEY_PARTS = (
    "secret",
    "token",
    "password",
    "api_key",
    "access_key",
    "private_key",
    "client_secret",
    "webhook_secret",
    "salt",
)


def _contains_sensitive_config_key(value) -> bool:
    """Return True when a nested config payload tries to hold secrets."""
    if isinstance(value, dict):
        for key, nested in value.items():
            key_l = str(key).lower()
            if any(part in key_l for part in _SENSITIVE_CONFIG_KEY_PARTS):
                return True
            if _contains_sensitive_config_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_config_key(item) for item in value)
    return False


def _secret_refs_are_safe_refs(value) -> bool:
    """Secret refs may point to ENV:/VAULT: only; raw values are refused."""
    if value in (None, "", {}, []):
        return True
    if isinstance(value, str):
        return value.startswith("ENV:") or value.startswith("VAULT:")
    if isinstance(value, dict):
        return all(_secret_refs_are_safe_refs(item) for item in value.values())
    if isinstance(value, list):
        return all(_secret_refs_are_safe_refs(item) for item in value)
    return False


class Organization(models.Model):
    """Top-level SaaS tenant."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        ARCHIVED = "archived", "Archived"

    code = models.SlugField(
        max_length=64,
        unique=True,
        help_text="Stable, lowercase slug — e.g. 'nirogidhara'.",
    )
    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    country = models.CharField(max_length=2, default="IN")
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        indexes = (models.Index(fields=("status",)),)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} [{self.code}]"


class Branch(models.Model):
    """Child location/branch under an Organization."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="branches",
    )
    code = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    address_line1 = models.CharField(max_length=255, blank=True, default="")
    address_line2 = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=120, blank=True, default="")
    state = models.CharField(max_length=120, blank=True, default="")
    pincode = models.CharField(max_length=12, blank=True, default="")
    country = models.CharField(max_length=2, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("organization", "name")
        constraints = (
            models.UniqueConstraint(
                fields=("organization", "code"),
                name="saas_branch_unique_org_code",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} ({self.organization.code}/{self.code})"


class OrganizationMembership(models.Model):
    """Per-user membership in an organization."""

    class OrgRole(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MANAGER = "manager", "Manager"
        AGENT = "agent", "Agent"
        VIEWER = "viewer", "Viewer"

    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saas_memberships",
    )
    role = models.CharField(
        max_length=16,
        choices=OrgRole.choices,
        default=OrgRole.VIEWER,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("organization", "user_id")
        constraints = (
            models.UniqueConstraint(
                fields=("organization", "user"),
                name="saas_membership_unique_org_user",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.user_id}@{self.organization.code} ({self.role})"


class OrganizationFeatureFlag(models.Model):
    """Per-org boolean feature toggle."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="feature_flags",
    )
    key = models.CharField(max_length=120)
    enabled = models.BooleanField(default=False)
    config = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("organization", "key")
        constraints = (
            models.UniqueConstraint(
                fields=("organization", "key"),
                name="saas_feature_flag_unique_org_key",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.organization.code}/{self.key}={self.enabled}"


class OrganizationSetting(models.Model):
    """Per-org typed JSON setting.

    Rows with ``is_sensitive=True`` MUST never appear in the public API.
    The current selectors filter them out. Phase 6A ships the schema
    only — no real provider credentials live here yet.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="settings",
    )
    key = models.CharField(max_length=160)
    value = models.JSONField(default=dict, blank=True)
    is_sensitive = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("organization", "key")
        constraints = (
            models.UniqueConstraint(
                fields=("organization", "key"),
                name="saas_setting_unique_org_key",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover
        suffix = " [sensitive]" if self.is_sensitive else ""
        return f"{self.organization.code}/{self.key}{suffix}"


class OrganizationIntegrationSetting(models.Model):
    """Per-org provider readiness settings.

    Phase 6E intentionally does not route runtime providers through this
    table. It stores non-sensitive config plus secret references only
    (for example ``ENV:OPENAI_API_KEY`` or ``VAULT:tenant/openai``).
    """

    class ProviderType(models.TextChoices):
        WHATSAPP_META = "whatsapp_meta", "WhatsApp Meta"
        RAZORPAY = "razorpay", "Razorpay"
        PAYU = "payu", "PayU"
        DELHIVERY = "delhivery", "Delhivery"
        VAPI = "vapi", "Vapi"
        OPENAI = "openai", "OpenAI"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIGURED = "configured", "Configured"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        INVALID = "invalid", "Invalid"

    class ValidationStatus(models.TextChoices):
        NOT_CHECKED = "not_checked", "Not checked"
        VALID = "valid", "Valid"
        INVALID = "invalid", "Invalid"
        WARNING = "warning", "Warning"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="integration_settings",
    )
    provider_type = models.CharField(
        max_length=32,
        choices=ProviderType.choices,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    display_name = models.CharField(max_length=120, blank=True, default="")
    config = models.JSONField(default=dict, blank=True)
    secret_refs = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)
    last_validated_at = models.DateTimeField(null=True, blank=True)
    validation_status = models.CharField(
        max_length=16,
        choices=ValidationStatus.choices,
        default=ValidationStatus.NOT_CHECKED,
    )
    validation_message = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("organization", "provider_type", "display_name")
        constraints = (
            models.UniqueConstraint(
                fields=("organization", "provider_type", "display_name"),
                name="saas_integration_unique_org_provider_name",
            ),
        )
        indexes = (
            models.Index(fields=("organization", "provider_type")),
            models.Index(fields=("status", "validation_status")),
        )

    def clean(self):
        super().clean()
        if _contains_sensitive_config_key(self.config or {}):
            raise ValidationError(
                {
                    "config": (
                        "Sensitive values are not allowed in config. "
                        "Store only ENV:/VAULT: references in secret_refs."
                    )
                }
            )
        if not _secret_refs_are_safe_refs(self.secret_refs or {}):
            raise ValidationError(
                {
                    "secret_refs": (
                        "Secret references must start with ENV: or VAULT:."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:  # pragma: no cover
        name = self.display_name or self.provider_type
        return f"{self.organization.code}/{name} ({self.status})"


class RuntimeLiveGatePolicySnapshot(models.Model):
    """Immutable-ish snapshot of a live-gate policy decision.

    Phase 6H keeps runtime execution blocked by default. Snapshots let
    operators audit which policy was evaluated without depending on the
    current in-code registry staying identical forever.
    """

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_live_gate_policy_snapshots",
    )
    branch = models.ForeignKey(
        Branch,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_live_gate_policy_snapshots",
    )
    operation_type = models.CharField(max_length=96, db_index=True)
    provider_type = models.CharField(max_length=48, db_index=True)
    risk_level = models.CharField(max_length=16, default="high")
    live_allowed_by_default = models.BooleanField(default=False)
    approval_required = models.BooleanField(default=True)
    caio_review_required = models.BooleanField(default=False)
    consent_required = models.BooleanField(default=False)
    claim_vault_required = models.BooleanField(default=False)
    webhook_required = models.BooleanField(default=False)
    idempotency_required = models.BooleanField(default=True)
    kill_switch_can_block = models.BooleanField(default=True)
    policy_version = models.CharField(max_length=32, default="phase6h.v1")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("organization", "operation_type")),
            models.Index(fields=("provider_type", "risk_level")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.operation_type} [{self.policy_version}]"


class RuntimeLiveExecutionRequest(models.Model):
    """Auditable live-execution request.

    A row here is never a provider call. It records whether an operator
    asked for a future live side effect and why the Phase 6H gate refused
    or accepted the request for audit-only readiness.
    """

    class ApprovalStatus(models.TextChoices):
        NOT_REQUIRED = "not_required", "Not required"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"
        BLOCKED = "blocked", "Blocked"

    class GateDecision(models.TextChoices):
        DRY_RUN_ALLOWED = "dry_run_allowed", "Dry-run allowed"
        BLOCKED_BY_DEFAULT = "blocked_by_default", "Blocked by default"
        BLOCKED_BY_KILL_SWITCH = (
            "blocked_by_kill_switch",
            "Blocked by kill switch",
        )
        BLOCKED_MISSING_APPROVAL = (
            "blocked_missing_approval",
            "Blocked missing approval",
        )
        BLOCKED_MISSING_PROVIDER_CONFIG = (
            "blocked_missing_provider_config",
            "Blocked missing provider config",
        )
        BLOCKED_MISSING_CONSENT = (
            "blocked_missing_consent",
            "Blocked missing consent",
        )
        BLOCKED_MISSING_CAIO_REVIEW = (
            "blocked_missing_caio_review",
            "Blocked missing CAIO review",
        )
        BLOCKED_MISSING_CLAIM_VAULT = (
            "blocked_missing_claim_vault",
            "Blocked missing Claim Vault",
        )
        BLOCKED_MISSING_WEBHOOK = (
            "blocked_missing_webhook",
            "Blocked missing webhook",
        )
        LIVE_READY_BUT_NOT_EXECUTED = (
            "live_ready_but_not_executed",
            "Live ready but not executed",
        )

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_live_execution_requests",
    )
    branch = models.ForeignKey(
        Branch,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_live_execution_requests",
    )
    operation_type = models.CharField(max_length=96, db_index=True)
    provider_type = models.CharField(max_length=48, db_index=True)
    runtime_source = models.CharField(max_length=32, default="env_config")
    per_org_runtime_enabled = models.BooleanField(default=False)
    dry_run = models.BooleanField(default=True)
    live_execution_requested = models.BooleanField(default=False)
    live_execution_allowed = models.BooleanField(default=False)
    external_call_will_be_made = models.BooleanField(default=False)
    approval_required = models.BooleanField(default=True)
    approval_status = models.CharField(
        max_length=24,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
        db_index=True,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_live_requests_created",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_live_requests_approved",
    )
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_live_requests_rejected",
    )
    requested_at = models.DateTimeField(null=True, blank=True, db_index=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    risk_level = models.CharField(max_length=16, default="high")
    payload_hash = models.CharField(max_length=64, blank=True, default="")
    safe_payload_summary = models.JSONField(default=dict, blank=True)
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    gate_decision = models.CharField(
        max_length=48,
        choices=GateDecision.choices,
        default=GateDecision.BLOCKED_BY_DEFAULT,
        db_index=True,
    )
    idempotency_key = models.CharField(
        max_length=160,
        blank=True,
        default="",
        db_index=True,
    )
    audit_event_id = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("organization", "operation_type")),
            models.Index(fields=("approval_status", "gate_decision")),
            models.Index(fields=("-created_at", "operation_type")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.operation_type} ({self.approval_status})"


class RuntimeLiveGateSimulation(models.Model):
    """Phase 6I single internal live-gate simulation.

    This model records an operator-approved simulation around the Phase
    6H live gate. A row here is never a provider call and never implies a
    payment, WhatsApp send, shipment, call, or customer-facing AI output.
    """

    class Status(models.TextChoices):
        PREPARED = "prepared", "Prepared"
        APPROVAL_REQUESTED = "approval_requested", "Approval requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        BLOCKED = "blocked", "Blocked"
        SIMULATED = "simulated", "Simulated"
        ROLLED_BACK = "rolled_back", "Rolled back"
        FAILED = "failed", "Failed"

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_live_gate_simulations",
    )
    branch = models.ForeignKey(
        Branch,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_live_gate_simulations",
    )
    live_execution_request = models.ForeignKey(
        RuntimeLiveExecutionRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="simulations",
    )
    operation_type = models.CharField(
        max_length=96,
        default="razorpay.create_order",
        db_index=True,
    )
    provider_type = models.CharField(
        max_length=48,
        default="razorpay",
        db_index=True,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PREPARED,
        db_index=True,
    )
    approval_status = models.CharField(
        max_length=24,
        choices=RuntimeLiveExecutionRequest.ApprovalStatus.choices,
        default=RuntimeLiveExecutionRequest.ApprovalStatus.NOT_REQUIRED,
        db_index=True,
    )
    runtime_source = models.CharField(max_length=32, default="env_config")
    per_org_runtime_enabled = models.BooleanField(default=False)
    dry_run = models.BooleanField(default=True)
    live_execution_requested = models.BooleanField(default=False)
    live_execution_allowed = models.BooleanField(default=False)
    external_call_will_be_made = models.BooleanField(default=False)
    external_call_was_made = models.BooleanField(default=False)
    provider_call_attempted = models.BooleanField(default=False)
    kill_switch_active = models.BooleanField(default=True)
    risk_level = models.CharField(max_length=16, default="medium")
    payload_hash = models.CharField(max_length=64, blank=True, default="")
    safe_payload_summary = models.JSONField(default=dict, blank=True)
    blockers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    gate_decision = models.CharField(
        max_length=48,
        choices=RuntimeLiveExecutionRequest.GateDecision.choices,
        default=RuntimeLiveExecutionRequest.GateDecision.BLOCKED_BY_DEFAULT,
        db_index=True,
    )
    idempotency_key = models.CharField(
        max_length=160,
        blank=True,
        default="",
        db_index=True,
    )
    simulation_result = models.JSONField(default=dict, blank=True)
    audit_event_id = models.PositiveIntegerField(null=True, blank=True)
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_gate_simulations_prepared",
    )
    approval_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_gate_simulations_requested",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_gate_simulations_approved",
    )
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_gate_simulations_rejected",
    )
    run_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_gate_simulations_run",
    )
    rolled_back_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_gate_simulations_rolled_back",
    )
    prepared_at = models.DateTimeField(null=True, blank=True, db_index=True)
    approval_requested_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    run_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("organization", "operation_type")),
            models.Index(fields=("status", "approval_status")),
            models.Index(fields=("-created_at", "status")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.operation_type} simulation ({self.status})"


class RuntimeKillSwitch(models.Model):
    """Live side-effect kill switch.

    ``enabled=True`` means the switch blocks matching live external
    side effects. Phase 6H seeds the global switch enabled.
    """

    class Scope(models.TextChoices):
        GLOBAL = "global", "Global"
        ORGANIZATION = "organization", "Organization"
        PROVIDER = "provider", "Provider"
        OPERATION = "operation", "Operation"

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_kill_switches",
    )
    scope = models.CharField(
        max_length=24,
        choices=Scope.choices,
        default=Scope.GLOBAL,
        db_index=True,
    )
    provider_type = models.CharField(max_length=48, blank=True, default="")
    operation_type = models.CharField(max_length=96, blank=True, default="")
    enabled = models.BooleanField(default=True, db_index=True)
    reason = models.TextField(blank=True, default="")
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runtime_kill_switch_changes",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("scope", "provider_type", "operation_type")
        indexes = (
            models.Index(fields=("scope", "enabled")),
            models.Index(fields=("organization", "scope")),
            models.Index(fields=("provider_type", "operation_type")),
        )

    def __str__(self) -> str:  # pragma: no cover
        target = self.operation_type or self.provider_type or "all"
        return f"{self.scope}:{target} enabled={self.enabled}"
