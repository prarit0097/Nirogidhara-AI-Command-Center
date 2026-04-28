"""Phase 5A — WhatsApp Live Sender Foundation models.

Eight tables under ``apps.whatsapp``:

- :class:`WhatsAppConnection`         — one row per WABA phone-number-id.
- :class:`WhatsAppTemplate`           — Meta-approved templates mirrored locally.
- :class:`WhatsAppConsent`            — per-customer consent state + history.
- :class:`WhatsAppConversation`       — inbox thread per Customer.
- :class:`WhatsAppMessage`            — every inbound + outbound message.
- :class:`WhatsAppMessageAttachment`  — binary attachments (Phase 5A is
  metadata-only; the binary stays in Meta's CDN).
- :class:`WhatsAppMessageStatusEvent` — append-only status history per
  outbound message.
- :class:`WhatsAppWebhookEvent`       — idempotent log of every inbound
  webhook delivery.
- :class:`WhatsAppSendLog`            — one row per provider send attempt
  (request + response + latency, no secrets).

The whole graph is single-tenant for Phase 5A. ``Customer.consent_whatsapp``
remains the live gate; the :class:`WhatsAppConsent` row carries the lifecycle
history so audits can reconstruct who flipped what when.

LOCKED Phase 5A rules:
- Templates are mirrored from Meta — frontend cannot create new templates.
- Every send writes both a :class:`WhatsAppMessage` and an audit row.
- Failed sends NEVER mutate ``Order`` / ``Payment`` / ``Shipment``.
- CAIO can never appear as ``WhatsAppMessage.metadata.actor_agent`` —
  service entry guards this in :mod:`apps.whatsapp.services`.
"""
from __future__ import annotations

from django.db import models


class WhatsAppConnection(models.Model):
    """One row per active WhatsApp phone-number / WABA pair.

    Phase 5A treats this as a single-tenant config row. Production keeps
    only one ``status=connected`` row at a time — the unique constraint on
    ``phone_number_id`` (when not blank) prevents duplicate Meta phone
    numbers from being registered twice.
    """

    class Provider(models.TextChoices):
        MOCK = "mock", "mock"
        META_CLOUD = "meta_cloud", "meta_cloud"
        BAILEYS_DEV = "baileys_dev", "baileys_dev"

    class Status(models.TextChoices):
        CONNECTED = "connected", "connected"
        DISCONNECTED = "disconnected", "disconnected"
        ERROR = "error", "error"

    id = models.CharField(primary_key=True, max_length=40)
    provider = models.CharField(
        max_length=16, choices=Provider.choices, default=Provider.MOCK
    )
    display_name = models.CharField(max_length=120, default="")
    phone_number = models.CharField(max_length=24, db_index=True, default="")
    phone_number_id = models.CharField(max_length=64, blank=True, default="")
    business_account_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DISCONNECTED
    )
    last_connected_at = models.DateTimeField(null=True, blank=True)
    last_health_check_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = (
            models.Index(fields=("provider", "status")),
            models.Index(fields=("phone_number",)),
        )
        constraints = (
            models.UniqueConstraint(
                fields=("phone_number_id",),
                condition=~models.Q(phone_number_id=""),
                name="uniq_whatsapp_connection_phone_number_id",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.id} · {self.provider} · {self.status}"


class WhatsAppTemplate(models.Model):
    """Meta-approved template mirrored locally.

    Phase 5A treats this row as **read-only data** that is upserted by the
    template-sync service from the WABA Graph API
    (``GET /v20.0/{waba_id}/message_templates``). Admin / Director can flip
    ``is_active`` (UI-only kill switch) and ``claim_vault_required`` (forces
    a Claim Vault gate at send time even when Meta categorises the template
    as MARKETING / UTILITY).
    """

    class Category(models.TextChoices):
        AUTHENTICATION = "AUTHENTICATION", "AUTHENTICATION"
        MARKETING = "MARKETING", "MARKETING"
        UTILITY = "UTILITY", "UTILITY"

    class Status(models.TextChoices):
        PENDING = "PENDING", "PENDING"
        APPROVED = "APPROVED", "APPROVED"
        REJECTED = "REJECTED", "REJECTED"
        DISABLED = "DISABLED", "DISABLED"

    id = models.CharField(primary_key=True, max_length=40)
    connection = models.ForeignKey(
        WhatsAppConnection,
        on_delete=models.CASCADE,
        related_name="templates",
    )
    name = models.CharField(max_length=120)
    language = models.CharField(max_length=12, default="hi")
    category = models.CharField(
        max_length=24, choices=Category.choices, default=Category.UTILITY
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    body_components = models.JSONField(default=list, blank=True)
    variables_schema = models.JSONField(default=dict, blank=True)
    action_key = models.CharField(max_length=120, blank=True, default="")
    claim_vault_required = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = (
            models.UniqueConstraint(
                fields=("connection", "name", "language"),
                name="uniq_whatsapp_template_per_connection",
            ),
        )
        indexes = (
            models.Index(fields=("status", "is_active")),
            models.Index(fields=("action_key",)),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name}/{self.language} · {self.status}"


class WhatsAppConsent(models.Model):
    """Per-customer consent lifecycle row.

    The boolean ``crm.Customer.consent_whatsapp`` is the live gate (kept
    for backwards-compatibility with the existing approval-engine ``target``
    payload shape). This row tracks the lifecycle so an audit can answer
    "when did this customer opt in?" and "did they opt out via STOP?".
    """

    class State(models.TextChoices):
        UNKNOWN = "unknown", "unknown"
        GRANTED = "granted", "granted"
        REVOKED = "revoked", "revoked"
        OPTED_OUT = "opted_out", "opted_out"

    customer = models.OneToOneField(
        "crm.Customer",
        on_delete=models.CASCADE,
        related_name="whatsapp_consent",
    )
    consent_state = models.CharField(
        max_length=16, choices=State.choices, default=State.UNKNOWN
    )
    granted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    opt_out_keyword = models.CharField(max_length=24, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=40, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = (
            models.Index(fields=("consent_state",)),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.customer_id} · {self.consent_state}"


class WhatsAppConversation(models.Model):
    """Inbox thread per Customer.

    Phase 5A only writes to this from inbound webhook handling and from
    the manual operator-triggered template-send flow (where the
    conversation is implicitly opened by the outbound message). Phase 5B
    builds the inbox UI on top.
    """

    class Status(models.TextChoices):
        OPEN = "open", "open"
        PENDING = "pending", "pending"
        RESOLVED = "resolved", "resolved"
        ESCALATED = "escalated_to_human", "escalated_to_human"

    class AiStatus(models.TextChoices):
        DISABLED = "disabled", "disabled"
        SUGGEST = "suggest", "suggest"
        PENDING_APPROVAL = "pending_approval", "pending_approval"
        AUTO_AFTER_APPROVAL = "auto_after_approval", "auto_after_approval"

    id = models.CharField(primary_key=True, max_length=40)
    customer = models.ForeignKey(
        "crm.Customer",
        on_delete=models.PROTECT,
        related_name="whatsapp_conversations",
    )
    connection = models.ForeignKey(
        WhatsAppConnection,
        on_delete=models.PROTECT,
        related_name="conversations",
    )
    assigned_to = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="whatsapp_conversations",
    )
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.OPEN
    )
    ai_status = models.CharField(
        max_length=24, choices=AiStatus.choices, default=AiStatus.DISABLED
    )
    unread_count = models.IntegerField(default=0)
    last_message_text = models.CharField(max_length=500, blank=True, default="")
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    subject = models.CharField(max_length=240, blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Phase 5A-1 anticipated metadata.address_collection slot — Phase 5C
    # populates this; Phase 5A keeps it free-form so future code doesn't
    # need a migration.
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = (
            models.Index(fields=("customer", "status", "-updated_at")),
            models.Index(fields=("assigned_to", "status", "-updated_at")),
            models.Index(fields=("status", "-last_message_at")),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.customer_id} · {self.status}"


class WhatsAppMessage(models.Model):
    """One row per inbound + outbound WhatsApp message.

    Outbound flow:
        services.queue_template_message → status=queued
            → tasks.send_whatsapp_message_task → provider.send_template_message
            → status=sent (provider_message_id assigned)
            → webhook → status=delivered / read / failed (also writes
              :class:`WhatsAppMessageStatusEvent`)

    Inbound flow:
        webhook → handle_inbound_event → row created with direction=inbound
                  + status=delivered (Meta delivered it to us).

    LOCKED rule: the audit ledger is the source of truth for live activity;
    every status transition writes both a ``WhatsAppMessage`` field update
    and a ``whatsapp.message.*`` audit row.
    """

    class Direction(models.TextChoices):
        INBOUND = "inbound", "inbound"
        OUTBOUND = "outbound", "outbound"

    class Status(models.TextChoices):
        QUEUED = "queued", "queued"
        SENT = "sent", "sent"
        DELIVERED = "delivered", "delivered"
        READ = "read", "read"
        FAILED = "failed", "failed"

    class Type(models.TextChoices):
        TEXT = "text", "text"
        TEMPLATE = "template", "template"
        IMAGE = "image", "image"
        DOCUMENT = "document", "document"
        AUDIO = "audio", "audio"
        LOCATION = "location", "location"
        INTERACTIVE = "interactive", "interactive"
        SYSTEM = "system", "system"

    id = models.CharField(primary_key=True, max_length=40)
    conversation = models.ForeignKey(
        WhatsAppConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    customer = models.ForeignKey(
        "crm.Customer",
        on_delete=models.PROTECT,
        related_name="whatsapp_messages",
    )
    provider_message_id = models.CharField(
        max_length=128, blank=True, default=""
    )
    direction = models.CharField(max_length=12, choices=Direction.choices)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.QUEUED
    )
    type = models.CharField(
        max_length=16, choices=Type.choices, default=Type.TEMPLATE
    )
    body = models.TextField(blank=True, default="")
    template = models.ForeignKey(
        WhatsAppTemplate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="messages",
    )
    template_variables = models.JSONField(default=dict, blank=True)
    media_url = models.URLField(blank=True, default="")
    ai_generated = models.BooleanField(default=False)
    approval_request = models.ForeignKey(
        "ai_governance.ApprovalRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="whatsapp_messages",
    )
    error_message = models.TextField(blank=True, default="")
    error_code = models.CharField(max_length=24, blank=True, default="")
    attempt_count = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(
        max_length=120, blank=True, default=""
    )
    queued_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("conversation", "-created_at")),
            models.Index(fields=("status", "-created_at")),
            models.Index(fields=("direction", "-created_at")),
        )
        constraints = (
            models.UniqueConstraint(
                fields=("provider_message_id",),
                condition=~models.Q(provider_message_id=""),
                name="uniq_whatsapp_message_provider_id",
            ),
            models.UniqueConstraint(
                fields=("idempotency_key",),
                condition=~models.Q(idempotency_key=""),
                name="uniq_whatsapp_message_idempotency_key",
            ),
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.id} · {self.direction} · {self.status}"


class WhatsAppMessageAttachment(models.Model):
    """Binary attachment metadata. Phase 5A stores metadata only.

    The binary itself stays in Meta's CDN — we keep the ``media_id`` so a
    later phase can fetch it on demand.
    """

    message = models.ForeignKey(
        WhatsAppMessage,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file_url = models.URLField(blank=True, default="")
    mime_type = models.CharField(max_length=80, blank=True, default="")
    size_bytes = models.IntegerField(default=0)
    media_id = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class WhatsAppMessageStatusEvent(models.Model):
    """Append-only status history per outbound message.

    Idempotent on ``provider_event_id`` so duplicate webhook deliveries
    don't double-count.
    """

    message = models.ForeignKey(
        WhatsAppMessage,
        on_delete=models.CASCADE,
        related_name="status_events",
    )
    status = models.CharField(
        max_length=12, choices=WhatsAppMessage.Status.choices
    )
    event_at = models.DateTimeField()
    provider_event_id = models.CharField(max_length=128, unique=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-received_at",)
        indexes = (
            models.Index(fields=("message", "-event_at")),
        )


class WhatsAppWebhookEvent(models.Model):
    """One row per inbound webhook delivery — idempotency log.

    Insert is gated on the unique ``provider_event_id`` constraint so
    Meta retries collapse into a single row.
    """

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "received", "received"
        ACCEPTED = "accepted", "accepted"
        DUPLICATE = "duplicate", "duplicate"
        REJECTED = "rejected", "rejected"
        ERROR = "error", "error"

    provider = models.CharField(max_length=16, default="meta_cloud")
    event_type = models.CharField(max_length=64, default="")
    provider_event_id = models.CharField(max_length=160, unique=True)
    signature_header = models.CharField(max_length=160, blank=True, default="")
    signature_verified = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_status = models.CharField(
        max_length=16,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
    )
    raw_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-received_at",)
        indexes = (
            models.Index(fields=("processing_status", "-received_at")),
        )


class WhatsAppSendLog(models.Model):
    """One row per provider send attempt.

    Captures the request/response pair (with the access token redacted
    upstream) plus latency for diagnostics. Never carries secrets — the
    service helper strips ``Authorization`` headers / token fields before
    persisting.
    """

    message = models.ForeignKey(
        WhatsAppMessage,
        on_delete=models.CASCADE,
        related_name="send_logs",
    )
    attempt = models.IntegerField(default=1)
    provider = models.CharField(max_length=16)
    request_payload = models.JSONField(default=dict, blank=True)
    response_status = models.IntegerField(default=0)
    response_payload = models.JSONField(default=dict, blank=True)
    latency_ms = models.IntegerField(default=0)
    error_code = models.CharField(max_length=32, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-completed_at",)
        indexes = (
            models.Index(fields=("message", "attempt")),
        )
