"""Phase 16D — Uploaded Customer Data Campaigns + Calling Lifecycle models.

Four additive, internal-only tables that let the Director upload existing
offline/old customer data, validate + deduplicate it, build a manual calling
campaign + queue from the valid rows, record call outcomes, and create an
internal Order from an interested contact via the existing safe order service.

**Nothing in this app calls a provider.** No Vapi call, no WhatsApp/Meta Cloud
send, no Razorpay/PayU charge, no Delhivery shipment, no AI/LLM call, no
business Celery enqueue, no `RuntimeKillSwitch` / `SandboxState` mutation. The
only writes are to these four tables plus (on explicit user action) a reused
`crm.Lead` / `orders.Order` row and a non-PII `AuditEvent`.

Phone numbers are stored (needed to actually call the contact) but are NEVER
returned in full by the API serializers (last-4 masked) and NEVER written to
logs or audit payloads.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class ImportedDataset(models.Model):
    """One uploaded customer-data batch (CSV)."""

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        VALIDATING = "validating", "Validating"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        ARCHIVED = "archived", "Archived"

    name = models.CharField(max_length=160)
    source_label = models.CharField(max_length=120, blank=True, default="")
    problem_category = models.CharField(max_length=120, blank=True, default="")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="imported_datasets",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.READY,
        db_index=True,
    )
    total_rows = models.IntegerField(default=0)
    valid_rows = models.IntegerField(default=0)
    duplicate_rows = models.IntegerField(default=0)
    invalid_rows = models.IntegerField(default=0)
    imported_rows = models.IntegerField(default=0)
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
            models.Index(fields=["-created_at"], name="imp_ds_created_idx"),
            models.Index(fields=["status"], name="imp_ds_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Dataset #{self.pk} ({self.name})"


class ImportedDataRow(models.Model):
    """One parsed + validated row from an uploaded dataset."""

    class ValidationStatus(models.TextChoices):
        VALID = "valid", "Valid"
        DUPLICATE_IN_FILE = "duplicate_in_file", "Duplicate in file"
        DUPLICATE_EXISTING = "duplicate_existing", "Duplicate of existing"
        INVALID_PHONE = "invalid_phone", "Invalid phone"
        MISSING_REQUIRED = "missing_required", "Missing required"
        SKIPPED = "skipped", "Skipped"
        IMPORTED = "imported", "Imported"

    dataset = models.ForeignKey(
        ImportedDataset,
        on_delete=models.CASCADE,
        related_name="rows",
    )
    row_number = models.IntegerField(default=0)
    raw_name = models.CharField(max_length=160, blank=True, default="")
    # Stored to enable the call workflow; NEVER exposed in full by the API.
    raw_phone = models.CharField(max_length=32, blank=True, default="")
    normalized_phone = models.CharField(
        max_length=20, blank=True, default="", db_index=True
    )
    problem_category = models.CharField(max_length=120, blank=True, default="")
    city = models.CharField(max_length=80, blank=True, default="")
    state = models.CharField(max_length=60, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    product = models.CharField(max_length=120, blank=True, default="")
    source_label = models.CharField(max_length=120, blank=True, default="")
    old_status = models.CharField(max_length=80, blank=True, default="")
    last_order_date = models.CharField(max_length=40, blank=True, default="")
    validation_status = models.CharField(
        max_length=24,
        choices=ValidationStatus.choices,
        default=ValidationStatus.VALID,
        db_index=True,
    )
    validation_message = models.CharField(max_length=200, blank=True, default="")
    linked_lead = models.ForeignKey(
        "crm.Lead",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    linked_customer = models.ForeignKey(
        "crm.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["dataset_id", "row_number"]
        indexes = [
            models.Index(fields=["dataset", "validation_status"], name="imp_row_ds_status_idx"),
            models.Index(fields=["normalized_phone"], name="imp_row_phone_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Row #{self.pk} ({self.validation_status})"


class ImportedCallingCampaign(models.Model):
    """A manual (NON-provider) calling campaign built from valid dataset rows."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        ARCHIVED = "archived", "Archived"

    name = models.CharField(max_length=160)
    dataset = models.ForeignKey(
        ImportedDataset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="campaigns",
    )
    problem_category = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    assigned_team = models.CharField(max_length=64, blank=True, default="")
    total_contacts = models.IntegerField(default=0)
    pending_count = models.IntegerField(default=0)
    completed_count = models.IntegerField(default=0)
    interested_count = models.IntegerField(default=0)
    not_interested_count = models.IntegerField(default=0)
    callback_count = models.IntegerField(default=0)
    wrong_number_count = models.IntegerField(default=0)
    order_created_count = models.IntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="imported_campaigns",
    )
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
            models.Index(fields=["-created_at"], name="imp_camp_created_idx"),
            models.Index(fields=["status"], name="imp_camp_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Campaign #{self.pk} ({self.name})"


class ImportedCallQueueItem(models.Model):
    """One call-queue contact inside an imported calling campaign."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ASSIGNED = "assigned", "Assigned"
        CALLED = "called", "Called"
        CALLBACK = "callback", "Callback"
        INTERESTED = "interested", "Interested"
        NOT_INTERESTED = "not_interested", "Not interested"
        WRONG_NUMBER = "wrong_number", "Wrong number"
        ORDER_CREATED = "order_created", "Order created"
        CLOSED = "closed", "Closed"

    campaign = models.ForeignKey(
        ImportedCallingCampaign,
        on_delete=models.CASCADE,
        related_name="queue_items",
    )
    data_row = models.ForeignKey(
        ImportedDataRow,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="queue_items",
    )
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="imported_queue_items",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    last_outcome = models.CharField(max_length=32, blank=True, default="")
    call_attempts = models.IntegerField(default=0)
    next_follow_up_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    # "" | "medical_emergency" | "senior_review" — surfaced as a UI warning;
    # never triggers an automated escalation / provider call.
    escalation_flag = models.CharField(max_length=24, blank=True, default="")
    linked_order = models.ForeignKey(
        "orders.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["campaign_id", "id"]
        indexes = [
            models.Index(fields=["campaign", "status"], name="imp_q_camp_status_idx"),
            models.Index(fields=["status"], name="imp_q_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"QueueItem #{self.pk} ({self.status})"
