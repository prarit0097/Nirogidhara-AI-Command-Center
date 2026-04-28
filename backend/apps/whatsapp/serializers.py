"""Phase 5A — DRF serializers for the WhatsApp app.

Backend snake_case → frontend camelCase via ``source=`` mapping per the
project convention.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppMessageStatusEvent,
    WhatsAppSendLog,
    WhatsAppTemplate,
)


class WhatsAppConnectionSerializer(serializers.ModelSerializer):
    displayName = serializers.CharField(source="display_name")
    phoneNumber = serializers.CharField(source="phone_number")
    phoneNumberId = serializers.CharField(source="phone_number_id")
    businessAccountId = serializers.CharField(source="business_account_id")
    lastConnectedAt = serializers.DateTimeField(
        source="last_connected_at", allow_null=True
    )
    lastHealthCheckAt = serializers.DateTimeField(
        source="last_health_check_at", allow_null=True
    )
    lastError = serializers.CharField(source="last_error")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = WhatsAppConnection
        fields = (
            "id",
            "provider",
            "displayName",
            "phoneNumber",
            "phoneNumberId",
            "businessAccountId",
            "status",
            "lastConnectedAt",
            "lastHealthCheckAt",
            "lastError",
            "metadata",
            "createdAt",
            "updatedAt",
        )


class WhatsAppTemplateSerializer(serializers.ModelSerializer):
    connectionId = serializers.CharField(source="connection_id")
    bodyComponents = serializers.JSONField(source="body_components")
    variablesSchema = serializers.JSONField(source="variables_schema")
    actionKey = serializers.CharField(source="action_key")
    claimVaultRequired = serializers.BooleanField(source="claim_vault_required")
    isActive = serializers.BooleanField(source="is_active")
    lastSyncedAt = serializers.DateTimeField(
        source="last_synced_at", allow_null=True
    )
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = WhatsAppTemplate
        fields = (
            "id",
            "connectionId",
            "name",
            "language",
            "category",
            "status",
            "bodyComponents",
            "variablesSchema",
            "actionKey",
            "claimVaultRequired",
            "isActive",
            "lastSyncedAt",
            "metadata",
            "createdAt",
            "updatedAt",
        )


class WhatsAppConsentSerializer(serializers.ModelSerializer):
    customerId = serializers.CharField(source="customer_id")
    consentState = serializers.CharField(source="consent_state")
    grantedAt = serializers.DateTimeField(source="granted_at", allow_null=True)
    revokedAt = serializers.DateTimeField(source="revoked_at", allow_null=True)
    optOutKeyword = serializers.CharField(source="opt_out_keyword")
    expiresAt = serializers.DateTimeField(source="expires_at", allow_null=True)
    lastInboundAt = serializers.DateTimeField(
        source="last_inbound_at", allow_null=True
    )
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = WhatsAppConsent
        fields = (
            "customerId",
            "consentState",
            "grantedAt",
            "revokedAt",
            "optOutKeyword",
            "expiresAt",
            "lastInboundAt",
            "source",
            "metadata",
            "createdAt",
            "updatedAt",
        )


class WhatsAppMessageSerializer(serializers.ModelSerializer):
    conversationId = serializers.CharField(source="conversation_id")
    customerId = serializers.CharField(source="customer_id")
    providerMessageId = serializers.CharField(source="provider_message_id")
    templateId = serializers.CharField(source="template_id", allow_null=True)
    templateVariables = serializers.JSONField(source="template_variables")
    mediaUrl = serializers.CharField(source="media_url")
    aiGenerated = serializers.BooleanField(source="ai_generated")
    approvalRequestId = serializers.CharField(
        source="approval_request_id", allow_null=True
    )
    errorMessage = serializers.CharField(source="error_message")
    errorCode = serializers.CharField(source="error_code")
    attemptCount = serializers.IntegerField(source="attempt_count")
    idempotencyKey = serializers.CharField(source="idempotency_key")
    queuedAt = serializers.DateTimeField(source="queued_at", allow_null=True)
    sentAt = serializers.DateTimeField(source="sent_at", allow_null=True)
    deliveredAt = serializers.DateTimeField(source="delivered_at", allow_null=True)
    readAt = serializers.DateTimeField(source="read_at", allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = WhatsAppMessage
        fields = (
            "id",
            "conversationId",
            "customerId",
            "providerMessageId",
            "direction",
            "status",
            "type",
            "body",
            "templateId",
            "templateVariables",
            "mediaUrl",
            "aiGenerated",
            "approvalRequestId",
            "errorMessage",
            "errorCode",
            "attemptCount",
            "idempotencyKey",
            "metadata",
            "queuedAt",
            "sentAt",
            "deliveredAt",
            "readAt",
            "createdAt",
            "updatedAt",
        )


class WhatsAppConversationSerializer(serializers.ModelSerializer):
    customerId = serializers.CharField(source="customer_id")
    connectionId = serializers.CharField(source="connection_id")
    assignedToId = serializers.IntegerField(
        source="assigned_to_id", allow_null=True
    )
    aiStatus = serializers.CharField(source="ai_status")
    unreadCount = serializers.IntegerField(source="unread_count")
    lastMessageText = serializers.CharField(source="last_message_text")
    lastMessageAt = serializers.DateTimeField(
        source="last_message_at", allow_null=True
    )
    lastInboundAt = serializers.DateTimeField(
        source="last_inbound_at", allow_null=True
    )
    resolvedAt = serializers.DateTimeField(source="resolved_at", allow_null=True)
    resolvedById = serializers.IntegerField(
        source="resolved_by_id", allow_null=True
    )
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = WhatsAppConversation
        fields = (
            "id",
            "customerId",
            "connectionId",
            "assignedToId",
            "status",
            "aiStatus",
            "unreadCount",
            "lastMessageText",
            "lastMessageAt",
            "lastInboundAt",
            "subject",
            "tags",
            "resolvedAt",
            "resolvedById",
            "metadata",
            "createdAt",
            "updatedAt",
        )


class WhatsAppMessageStatusEventSerializer(serializers.ModelSerializer):
    messageId = serializers.CharField(source="message_id")
    eventAt = serializers.DateTimeField(source="event_at")
    providerEventId = serializers.CharField(source="provider_event_id")
    rawPayload = serializers.JSONField(source="raw_payload")
    receivedAt = serializers.DateTimeField(source="received_at")

    class Meta:
        model = WhatsAppMessageStatusEvent
        fields = (
            "id",
            "messageId",
            "status",
            "eventAt",
            "providerEventId",
            "rawPayload",
            "receivedAt",
        )


class WhatsAppSendLogSerializer(serializers.ModelSerializer):
    messageId = serializers.CharField(source="message_id")
    requestPayload = serializers.JSONField(source="request_payload")
    responseStatus = serializers.IntegerField(source="response_status")
    responsePayload = serializers.JSONField(source="response_payload")
    latencyMs = serializers.IntegerField(source="latency_ms")
    errorCode = serializers.CharField(source="error_code")
    startedAt = serializers.DateTimeField(source="started_at", allow_null=True)
    completedAt = serializers.DateTimeField(source="completed_at", allow_null=True)

    class Meta:
        model = WhatsAppSendLog
        fields = (
            "id",
            "messageId",
            "attempt",
            "provider",
            "requestPayload",
            "responseStatus",
            "responsePayload",
            "latencyMs",
            "errorCode",
            "startedAt",
            "completedAt",
        )


# ----- Write payloads -----


class SendTemplatePayloadSerializer(serializers.Serializer):
    customerId = serializers.CharField(max_length=32)
    actionKey = serializers.CharField(max_length=120)
    templateId = serializers.CharField(max_length=40, required=False, allow_blank=True)
    variables = serializers.DictField(child=serializers.JSONField(), required=False)
    triggeredBy = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    idempotencyKey = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )


class ConsentPatchPayloadSerializer(serializers.Serializer):
    consentState = serializers.ChoiceField(
        choices=WhatsAppConsent.State.choices,
        required=True,
    )
    source = serializers.CharField(max_length=40, required=False, allow_blank=True)
    note = serializers.CharField(
        max_length=240, required=False, allow_blank=True
    )


class TemplateSyncPayloadSerializer(serializers.Serializer):
    data = serializers.ListField(child=serializers.DictField(), required=False)


__all__ = (
    "ConsentPatchPayloadSerializer",
    "SendTemplatePayloadSerializer",
    "TemplateSyncPayloadSerializer",
    "WhatsAppConnectionSerializer",
    "WhatsAppConsentSerializer",
    "WhatsAppConversationSerializer",
    "WhatsAppMessageSerializer",
    "WhatsAppMessageStatusEventSerializer",
    "WhatsAppSendLogSerializer",
    "WhatsAppTemplateSerializer",
)
