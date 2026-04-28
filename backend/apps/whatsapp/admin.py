"""Phase 5A — Django admin for the WhatsApp app."""
from __future__ import annotations

from django.contrib import admin

from .models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppMessageAttachment,
    WhatsAppMessageStatusEvent,
    WhatsAppSendLog,
    WhatsAppTemplate,
    WhatsAppWebhookEvent,
)


@admin.register(WhatsAppConnection)
class WhatsAppConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "display_name",
        "phone_number",
        "status",
        "updated_at",
    )
    list_filter = ("provider", "status")
    search_fields = ("id", "display_name", "phone_number", "phone_number_id")


@admin.register(WhatsAppTemplate)
class WhatsAppTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "language",
        "category",
        "status",
        "is_active",
        "claim_vault_required",
        "action_key",
        "last_synced_at",
    )
    list_filter = ("status", "is_active", "claim_vault_required", "category")
    search_fields = ("id", "name", "action_key")


@admin.register(WhatsAppConsent)
class WhatsAppConsentAdmin(admin.ModelAdmin):
    list_display = (
        "customer",
        "consent_state",
        "granted_at",
        "revoked_at",
        "last_inbound_at",
        "source",
    )
    list_filter = ("consent_state", "source")
    search_fields = ("customer__id", "customer__name")


@admin.register(WhatsAppConversation)
class WhatsAppConversationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "status",
        "ai_status",
        "unread_count",
        "last_inbound_at",
        "updated_at",
    )
    list_filter = ("status", "ai_status")
    search_fields = ("id", "customer__id", "customer__name")


@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "conversation",
        "direction",
        "status",
        "type",
        "template",
        "attempt_count",
        "created_at",
    )
    list_filter = ("direction", "status", "type")
    search_fields = (
        "id",
        "provider_message_id",
        "idempotency_key",
        "customer__id",
        "customer__name",
    )


@admin.register(WhatsAppMessageAttachment)
class WhatsAppMessageAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "mime_type", "size_bytes", "created_at")


@admin.register(WhatsAppMessageStatusEvent)
class WhatsAppMessageStatusEventAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "status", "event_at", "received_at")
    list_filter = ("status",)
    search_fields = ("provider_event_id",)


@admin.register(WhatsAppWebhookEvent)
class WhatsAppWebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "event_type",
        "processing_status",
        "signature_verified",
        "received_at",
    )
    list_filter = ("processing_status", "signature_verified", "provider")
    search_fields = ("provider_event_id",)


@admin.register(WhatsAppSendLog)
class WhatsAppSendLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "message",
        "attempt",
        "provider",
        "response_status",
        "latency_ms",
        "completed_at",
    )
    list_filter = ("provider",)
    search_fields = ("message__id",)
