"""Phase 5A — WhatsApp HTTP layer.

Read endpoints stay open to authenticated users (operations+); writes
require ``ADMIN_AND_UP`` for sync / provider-config / consent override
and ``OPERATIONS_AND_UP`` for send + retry. Anonymous traffic is allowed
only on the webhook entrypoint (handled in :mod:`apps.whatsapp.webhooks`).
"""
from __future__ import annotations

from typing import Any

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import (
    ADMIN_AND_UP,
    OPERATIONS_AND_UP,
    RoleBasedPermission,
)
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer

from . import services
from .consent import (
    grant_whatsapp_consent,
    revoke_whatsapp_consent,
)
from .models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppTemplate,
)
from .serializers import (
    ConsentPatchPayloadSerializer,
    SendTemplatePayloadSerializer,
    TemplateSyncPayloadSerializer,
    WhatsAppConnectionSerializer,
    WhatsAppConsentSerializer,
    WhatsAppConversationSerializer,
    WhatsAppMessageSerializer,
    WhatsAppTemplateSerializer,
)
from .tasks import send_whatsapp_message
from .template_registry import sync_templates_from_provider


class _AdminWritePermission(RoleBasedPermission):
    allowed_roles = ADMIN_AND_UP


class _AdminAlways(RoleBasedPermission):
    """Admin/director only — applies to safe AND unsafe methods.

    Used by the provider-status endpoint where even reads expose
    redacted-but-sensitive operational metadata.
    """

    allowed_roles = ADMIN_AND_UP

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(request.user, "is_superuser", False):
            return True
        roles = getattr(view, "allowed_write_roles", self.allowed_roles)
        return getattr(request.user, "role", None) in roles


class _OperationsWritePermission(RoleBasedPermission):
    allowed_roles = OPERATIONS_AND_UP


class _ReadAuthRequired(IsAuthenticated):
    """Reads on this app require an authenticated user."""


# ----- Connections / templates / conversations / messages -----


class WhatsAppConnectionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """``GET /api/whatsapp/connections/`` — list connections (read-only)."""

    queryset = WhatsAppConnection.objects.all().order_by("-updated_at")
    serializer_class = WhatsAppConnectionSerializer
    pagination_class = None
    permission_classes = [_ReadAuthRequired]


class WhatsAppTemplateViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """``GET /api/whatsapp/templates/`` — list mirrored Meta templates."""

    queryset = WhatsAppTemplate.objects.all().select_related("connection")
    serializer_class = WhatsAppTemplateSerializer
    pagination_class = None
    permission_classes = [_ReadAuthRequired]

    def get_queryset(self):
        qs = super().get_queryset()
        action_key = self.request.query_params.get("actionKey")
        if action_key:
            qs = qs.filter(action_key=action_key)
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs.order_by("name", "language")


class WhatsAppConversationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = (
        WhatsAppConversation.objects.all()
        .select_related("customer", "connection")
        .order_by("-updated_at")
    )
    serializer_class = WhatsAppConversationSerializer
    pagination_class = None
    permission_classes = [_ReadAuthRequired]

    def get_queryset(self):
        qs = super().get_queryset()
        customer_id = self.request.query_params.get("customerId")
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


class WhatsAppMessageViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = (
        WhatsAppMessage.objects.all()
        .select_related("conversation", "customer", "template")
        .order_by("-created_at")
    )
    serializer_class = WhatsAppMessageSerializer
    pagination_class = None
    permission_classes = [_ReadAuthRequired]

    def get_queryset(self):
        qs = super().get_queryset()
        conversation_id = self.request.query_params.get("conversationId")
        if conversation_id:
            qs = qs.filter(conversation_id=conversation_id)
        customer_id = self.request.query_params.get("customerId")
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        try:
            limit = max(1, min(int(self.request.query_params.get("limit") or 200), 1000))
        except (TypeError, ValueError):
            limit = 200
        return qs[:limit]


# ----- Conversation messages convenience endpoint -----


class WhatsAppConversationMessagesView(APIView):
    """``GET /api/whatsapp/conversations/{id}/messages/``"""

    permission_classes = [_ReadAuthRequired]

    def get(self, _request, pk: str):
        conversation = WhatsAppConversation.objects.filter(pk=pk).first()
        if conversation is None:
            raise NotFound(f"Conversation {pk} not found.")
        messages = (
            WhatsAppMessage.objects.filter(conversation=conversation)
            .select_related("template")
            .order_by("-created_at")[:200]
        )
        return Response(WhatsAppMessageSerializer(messages, many=True).data)


# ----- Provider status -----


class WhatsAppProviderStatusView(APIView):
    """``GET /api/whatsapp/provider/status/`` — admin/director only.

    Always returns redacted values for sensitive fields. Anonymous and
    operations users are blocked even on the safe (GET) method.
    """

    permission_classes = [_AdminAlways]

    def get(self, _request):
        return Response(services.provider_status())


# ----- Send template -----


class WhatsAppSendTemplateView(APIView):
    """``POST /api/whatsapp/send-template/`` — operations+ allowed."""

    permission_classes = [_OperationsWritePermission]

    def post(self, request):
        payload = SendTemplatePayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        customer = Customer.objects.filter(pk=data["customerId"]).first()
        if customer is None:
            raise NotFound(f"Customer {data['customerId']} not found.")

        template = None
        template_id = (data.get("templateId") or "").strip()
        if template_id:
            template = WhatsAppTemplate.objects.filter(pk=template_id).first()
            if template is None:
                raise NotFound(f"Template {template_id} not found.")

        try:
            queued = services.queue_template_message(
                customer=customer,
                action_key=data["actionKey"],
                template=template,
                variables=data.get("variables") or {},
                triggered_by=data.get("triggeredBy") or "manual_api",
                actor_role=getattr(request.user, "role", "") or "",
                idempotency_key=data.get("idempotencyKey") or "",
                by_user=request.user,
            )
        except services.WhatsAppServiceError as exc:
            return Response(
                {
                    "detail": str(exc),
                    "blockReason": exc.block_reason,
                },
                status=exc.http_status,
            )

        # Schedule the actual send. Eager-mode dev runs it synchronously.
        send_whatsapp_message.delay(queued.message.id)

        message = WhatsAppMessage.objects.get(pk=queued.message.id)
        return Response(
            {
                "message": WhatsAppMessageSerializer(message).data,
                "conversationId": queued.conversation.id,
                "approvalRequestId": queued.approval_request_id,
                "autoApproved": queued.auto_approved,
            },
            status=status.HTTP_201_CREATED,
        )


# ----- Retry -----


class WhatsAppMessageRetryView(APIView):
    """``POST /api/whatsapp/messages/{id}/retry/`` — operations+ retry failed sends."""

    permission_classes = [_OperationsWritePermission]

    def post(self, request, pk: str):
        message = WhatsAppMessage.objects.filter(pk=pk).first()
        if message is None:
            raise NotFound(f"Message {pk} not found.")
        if message.direction != WhatsAppMessage.Direction.OUTBOUND:
            return Response(
                {"detail": "Cannot retry an inbound message."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if message.status not in {
            WhatsAppMessage.Status.FAILED,
            WhatsAppMessage.Status.QUEUED,
        }:
            return Response(
                {
                    "detail": (
                        f"Cannot retry a message in status '{message.status}'. "
                        f"Only 'failed' / 'queued' are retryable."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Reset to queued before re-driving the task.
        message.status = WhatsAppMessage.Status.QUEUED
        message.error_message = ""
        message.error_code = ""
        message.save(
            update_fields=[
                "status",
                "error_message",
                "error_code",
                "updated_at",
            ]
        )
        write_event(
            kind="whatsapp.message.queued",
            text=f"WhatsApp message {message.id} requeued by {getattr(request.user, 'username', '')}",
            tone=AuditEvent.Tone.INFO,
            payload={
                "message_id": message.id,
                "customer_id": message.customer_id,
                "by": getattr(request.user, "username", ""),
                "trigger": "retry",
            },
        )

        send_whatsapp_message.delay(message.id)
        return Response(
            WhatsAppMessageSerializer(WhatsAppMessage.objects.get(pk=message.id)).data,
            status=status.HTTP_200_OK,
        )


# ----- Consent -----


class WhatsAppConsentView(APIView):
    """``GET / PATCH /api/whatsapp/consent/{customer_id}/``"""

    def get_permissions(self):
        if self.request.method == "PATCH":
            return [_OperationsWritePermission()]
        return [_ReadAuthRequired()]

    def get(self, _request, customer_id: str):
        customer = Customer.objects.filter(pk=customer_id).first()
        if customer is None:
            raise NotFound(f"Customer {customer_id} not found.")
        consent, _ = WhatsAppConsent.objects.get_or_create(
            customer=customer,
            defaults={"consent_state": WhatsAppConsent.State.UNKNOWN},
        )
        return Response(
            {
                "customerId": customer.id,
                "consentWhatsapp": bool(customer.consent_whatsapp),
                "history": WhatsAppConsentSerializer(consent).data,
            }
        )

    def patch(self, request, customer_id: str):
        customer = Customer.objects.filter(pk=customer_id).first()
        if customer is None:
            raise NotFound(f"Customer {customer_id} not found.")
        payload = ConsentPatchPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        new_state = payload.validated_data["consentState"]
        source = payload.validated_data.get("source") or "operator"
        note = payload.validated_data.get("note") or ""
        actor = getattr(request.user, "username", "") or ""

        if new_state == WhatsAppConsent.State.GRANTED:
            consent = grant_whatsapp_consent(
                customer, source=source, actor=actor, note=note
            )
        elif new_state in {
            WhatsAppConsent.State.REVOKED,
            WhatsAppConsent.State.OPTED_OUT,
        }:
            consent = revoke_whatsapp_consent(
                customer, source=source, actor=actor, note=note
            )
        else:
            return Response(
                {"detail": "Only granted/revoked/opted_out are settable via PATCH."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "customerId": customer.id,
                "consentWhatsapp": bool(customer.consent_whatsapp),
                "history": WhatsAppConsentSerializer(consent).data,
            }
        )


# ----- Template sync -----


class WhatsAppTemplateSyncView(APIView):
    """``POST /api/whatsapp/templates/sync/`` — admin/director only."""

    permission_classes = [_AdminWritePermission]

    def post(self, request):
        payload = TemplateSyncPayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        connection = services.get_active_connection()
        result = sync_templates_from_provider(
            connection=connection,
            payload={"data": payload.validated_data.get("data") or []},
            actor=getattr(request.user, "username", "") or "",
        )
        return Response(result, status=status.HTTP_200_OK)


__all__ = (
    "WhatsAppConnectionViewSet",
    "WhatsAppConsentView",
    "WhatsAppConversationMessagesView",
    "WhatsAppConversationViewSet",
    "WhatsAppMessageRetryView",
    "WhatsAppMessageViewSet",
    "WhatsAppProviderStatusView",
    "WhatsAppSendTemplateView",
    "WhatsAppTemplateSyncView",
    "WhatsAppTemplateViewSet",
)
