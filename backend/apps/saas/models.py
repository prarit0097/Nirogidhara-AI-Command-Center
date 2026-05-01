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
from django.db import models


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
