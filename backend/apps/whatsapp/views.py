"""WhatsApp HTTP layer.

Phase 5A shipped the live-sender endpoints (provider status, send-template,
templates / conversations / messages list, retry, consent, template sync).

Phase 5B adds the inbox surface: aggregate inbox endpoint with conversation
counts, internal notes (CRUD), per-conversation mark-read + safe field
update + manual template send, and a WhatsApp-only customer timeline. AI
auto-reply stays disabled — every send still flows through Phase 5A's
``queue_template_message`` (consent + approved-template + Claim Vault +
approval matrix + CAIO hard stop + idempotency).

Read endpoints stay open to authenticated users (operations+); writes
require ``ADMIN_AND_UP`` for sync / provider-config / consent override
and ``OPERATIONS_AND_UP`` for send + retry + notes + mark-read +
conversation update. Anonymous traffic is allowed only on the webhook
entrypoint (handled in :mod:`apps.whatsapp.webhooks`).
"""
from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
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
    WhatsAppHandoffToCall,
    WhatsAppInternalNote,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
    WhatsAppMessageStatusEvent,
    WhatsAppTemplate,
)
from .serializers import (
    ConsentPatchPayloadSerializer,
    CreateInternalNotePayloadSerializer,
    SendConversationTemplatePayloadSerializer,
    SendTemplatePayloadSerializer,
    TemplateSyncPayloadSerializer,
    UpdateConversationPayloadSerializer,
    WhatsAppConnectionSerializer,
    WhatsAppConsentSerializer,
    WhatsAppConversationSerializer,
    WhatsAppInternalNoteSerializer,
    WhatsAppMessageSerializer,
    WhatsAppMessageStatusEventSerializer,
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


class _ConversationPermission(RoleBasedPermission):
    """Reads need auth; PATCH needs operations+."""

    allowed_roles = OPERATIONS_AND_UP

    def has_permission(self, request, view) -> bool:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return bool(request.user and request.user.is_authenticated)
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(request.user, "is_superuser", False):
            return True
        return getattr(request.user, "role", None) in self.allowed_roles


class WhatsAppConversationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = (
        WhatsAppConversation.objects.all()
        .select_related("customer", "connection", "assigned_to")
        .order_by("-updated_at")
    )
    serializer_class = WhatsAppConversationSerializer
    pagination_class = None
    permission_classes = [_ConversationPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        # Slicing collapses the queryset into a list — only do it on `list`,
        # never on `retrieve` / `partial_update` (DRF needs to apply a pk
        # filter on the queryset there).
        if self.action != "list":
            return qs
        customer_id = self.request.query_params.get("customerId")
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        assigned_to = self.request.query_params.get("assignedTo")
        if assigned_to:
            try:
                qs = qs.filter(assigned_to_id=int(assigned_to))
            except ValueError:
                pass
        unread = (self.request.query_params.get("unread") or "").lower()
        if unread in {"1", "true", "yes"}:
            qs = qs.filter(unread_count__gt=0)
        query = (self.request.query_params.get("q") or "").strip()
        if query:
            qs = qs.filter(
                Q(customer__name__icontains=query)
                | Q(customer__phone__icontains=query)
                | Q(last_message_text__icontains=query)
                | Q(subject__icontains=query)
            )
        try:
            limit = max(1, min(int(self.request.query_params.get("limit") or 200), 1000))
        except (TypeError, ValueError):
            limit = 200
        return qs[:limit]

    def partial_update(self, request, pk: str = None):
        """``PATCH /api/whatsapp/conversations/{id}/`` — operations+ safe-field update."""
        return _patch_conversation(request, pk or "")


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


# ============================================================================
# Phase 5B — Inbox / Customer 360 timeline / internal notes / mark-read /
# conversation update / per-conversation send-template.
# ============================================================================


def _get_conversation_or_404(pk: str) -> WhatsAppConversation:
    convo = (
        WhatsAppConversation.objects.select_related("customer", "connection")
        .filter(pk=pk)
        .first()
    )
    if convo is None:
        raise NotFound(f"Conversation {pk} not found.")
    return convo


class WhatsAppInboxView(APIView):
    """``GET /api/whatsapp/inbox/`` — aggregate inbox snapshot.

    Returns the conversations the operator should see by default plus
    counts the left-pane filter chips display, plus an explicit AI
    suggestions placeholder so the frontend never invents AI behavior.
    """

    permission_classes = [_ReadAuthRequired]

    def get(self, request):
        qs = (
            WhatsAppConversation.objects.select_related(
                "customer", "connection", "assigned_to"
            )
            .order_by("-updated_at")
        )
        all_count = qs.count()
        counts = {
            "all": all_count,
            "unread": qs.filter(unread_count__gt=0).count(),
            "open": qs.filter(status=WhatsAppConversation.Status.OPEN).count(),
            "pending": qs.filter(
                status=WhatsAppConversation.Status.PENDING
            ).count(),
            "resolved": qs.filter(
                status=WhatsAppConversation.Status.RESOLVED
            ).count(),
            "escalatedToHuman": qs.filter(
                status=WhatsAppConversation.Status.ESCALATED
            ).count(),
        }
        try:
            limit = max(1, min(int(request.query_params.get("limit") or 50), 200))
        except (TypeError, ValueError):
            limit = 50
        conversations = qs[:limit]
        return Response(
            {
                "conversations": WhatsAppConversationSerializer(
                    conversations, many=True
                ).data,
                "counts": counts,
                "aiSuggestions": _ai_suggestions_status(),
            }
        )


def _patch_conversation(request, pk: str):
    """Apply the safe-field PATCH used by the conversation ViewSet."""
    convo = _get_conversation_or_404(pk)
    payload = UpdateConversationPayloadSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    data = payload.validated_data
    if not data:
        return Response(
            {"detail": "No safe fields supplied to update."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    updated_fields: list[str] = []
    previous_assigned_to_id = convo.assigned_to_id
    previous_status = convo.status

    if "status" in data:
        convo.status = data["status"]
        updated_fields.append("status")
        if convo.status == WhatsAppConversation.Status.RESOLVED:
            convo.resolved_at = timezone.now()
            convo.resolved_by = request.user
            updated_fields.extend(["resolved_at", "resolved_by"])
    if "assignedToId" in data:
        convo.assigned_to_id = data["assignedToId"]
        updated_fields.append("assigned_to")
    if "tags" in data:
        convo.tags = list(data["tags"])
        updated_fields.append("tags")
    if "subject" in data:
        convo.subject = data["subject"][:240]
        updated_fields.append("subject")

    if updated_fields:
        updated_fields.append("updated_at")
        convo.save(update_fields=updated_fields)

    if (
        "assignedToId" in data
        and convo.assigned_to_id != previous_assigned_to_id
    ):
        write_event(
            kind="whatsapp.conversation.assigned",
            text=(
                f"WhatsApp conversation {convo.id} assigned to "
                f"user {convo.assigned_to_id}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "conversation_id": convo.id,
                "assigned_to_id": convo.assigned_to_id,
                "by": getattr(request.user, "username", "") or "",
            },
        )

    write_event(
        kind="whatsapp.conversation.updated",
        text=f"WhatsApp conversation {convo.id} updated",
        tone=AuditEvent.Tone.INFO,
        payload={
            "conversation_id": convo.id,
            "previous_status": previous_status,
            "new_status": convo.status,
            "fields": [f for f in updated_fields if f != "updated_at"],
            "by": getattr(request.user, "username", "") or "",
        },
    )
    return Response(WhatsAppConversationSerializer(convo).data)


class WhatsAppConversationMarkReadView(APIView):
    """``POST /api/whatsapp/conversations/{id}/mark-read/`` — operations+."""

    permission_classes = [_OperationsWritePermission]

    def post(self, request, pk: str):
        convo = _get_conversation_or_404(pk)
        if convo.unread_count == 0:
            return Response(
                WhatsAppConversationSerializer(convo).data, status=status.HTTP_200_OK
            )
        convo.unread_count = 0
        convo.save(update_fields=["unread_count", "updated_at"])
        write_event(
            kind="whatsapp.conversation.read",
            text=f"WhatsApp conversation {convo.id} marked read",
            tone=AuditEvent.Tone.INFO,
            payload={
                "conversation_id": convo.id,
                "by": getattr(request.user, "username", "") or "",
            },
        )
        return Response(
            WhatsAppConversationSerializer(convo).data, status=status.HTTP_200_OK
        )


class WhatsAppConversationNotesView(APIView):
    """``GET / POST /api/whatsapp/conversations/{id}/notes/``."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [_OperationsWritePermission()]
        return [_ReadAuthRequired()]

    def get(self, _request, pk: str):
        convo = _get_conversation_or_404(pk)
        notes = (
            WhatsAppInternalNote.objects.filter(conversation=convo)
            .select_related("author")
            .order_by("-created_at")
        )
        return Response(WhatsAppInternalNoteSerializer(notes, many=True).data)

    def post(self, request, pk: str):
        convo = _get_conversation_or_404(pk)
        payload = CreateInternalNotePayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        body = payload.validated_data["body"].strip()
        if not body:
            raise ValidationError({"body": "Note body cannot be empty."})

        note = WhatsAppInternalNote.objects.create(
            conversation=convo,
            author=request.user if request.user.is_authenticated else None,
            body=body[:4000],
            metadata=dict(payload.validated_data.get("metadata") or {}),
        )
        write_event(
            kind="whatsapp.internal_note.created",
            text=(
                f"Internal note added on conversation {convo.id} by "
                f"{getattr(request.user, 'username', '') or 'unknown'}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "conversation_id": convo.id,
                "note_id": note.id,
                "author": getattr(request.user, "username", "") or "",
                "preview": note.body[:80],
            },
        )
        return Response(
            WhatsAppInternalNoteSerializer(note).data,
            status=status.HTTP_201_CREATED,
        )


class WhatsAppConversationSendTemplateView(APIView):
    """``POST /api/whatsapp/conversations/{id}/send-template/`` — operations+.

    Routes through Phase 5A's ``queue_template_message`` so the consent /
    template / Claim Vault / approval-matrix / CAIO / idempotency gates
    all stay in force. The customer is resolved from the conversation
    so operators cannot accidentally pick the wrong one.
    """

    permission_classes = [_OperationsWritePermission]

    def post(self, request, pk: str):
        convo = _get_conversation_or_404(pk)
        payload = SendConversationTemplatePayloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        template = None
        template_id = (data.get("templateId") or "").strip()
        if template_id:
            template = WhatsAppTemplate.objects.filter(pk=template_id).first()
            if template is None:
                raise NotFound(f"Template {template_id} not found.")

        write_event(
            kind="whatsapp.template.manual_send_requested",
            text=(
                f"Operator-triggered template send requested on "
                f"conversation {convo.id} · {data['actionKey']}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "conversation_id": convo.id,
                "customer_id": convo.customer_id,
                "action_key": data["actionKey"],
                "template_id": template_id,
                "by": getattr(request.user, "username", "") or "",
            },
        )

        try:
            queued = services.queue_template_message(
                customer=convo.customer,
                action_key=data["actionKey"],
                template=template,
                variables=data.get("variables") or {},
                triggered_by=data.get("triggeredBy") or "manual_inbox",
                actor_role=getattr(request.user, "role", "") or "",
                idempotency_key=data.get("idempotencyKey") or "",
                by_user=request.user,
                extra_metadata={"conversation_id": convo.id},
            )
        except services.WhatsAppServiceError as exc:
            return Response(
                {"detail": str(exc), "blockReason": exc.block_reason},
                status=exc.http_status,
            )

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


class WhatsAppCustomerTimelineView(APIView):
    """``GET /api/whatsapp/customers/{customer_id}/timeline/``.

    WhatsApp-only: messages + status events + internal notes interleaved
    by event timestamp. Phase 5B intentionally does NOT merge calls /
    payments / orders — that's a Phase 5C/5D Customer 360 concern.
    """

    permission_classes = [_ReadAuthRequired]

    def get(self, request, customer_id: str):
        customer = Customer.objects.filter(pk=customer_id).first()
        if customer is None:
            raise NotFound(f"Customer {customer_id} not found.")

        conversations = list(
            WhatsAppConversation.objects.filter(customer=customer)
            .select_related("connection", "assigned_to")
            .order_by("-updated_at")
        )
        convo_ids = [c.id for c in conversations]
        try:
            limit = max(1, min(int(request.query_params.get("limit") or 200), 1000))
        except (TypeError, ValueError):
            limit = 200

        messages = list(
            WhatsAppMessage.objects.filter(conversation_id__in=convo_ids)
            .select_related("template")
            .order_by("-created_at")[:limit]
        )
        notes = list(
            WhatsAppInternalNote.objects.filter(conversation_id__in=convo_ids)
            .select_related("author")
            .order_by("-created_at")[:limit]
        )
        status_events = list(
            WhatsAppMessageStatusEvent.objects.filter(
                message__conversation_id__in=convo_ids
            )
            .select_related("message")
            .order_by("-event_at")[:limit]
        )

        items: list[dict[str, Any]] = []
        for m in messages:
            items.append(
                {
                    "kind": "message",
                    "id": m.id,
                    "occurredAt": (m.created_at or timezone.now()).isoformat(),
                    "data": WhatsAppMessageSerializer(m).data,
                }
            )
        for n in notes:
            items.append(
                {
                    "kind": "internal_note",
                    "id": str(n.id),
                    "occurredAt": (n.created_at or timezone.now()).isoformat(),
                    "data": WhatsAppInternalNoteSerializer(n).data,
                }
            )
        for s in status_events:
            items.append(
                {
                    "kind": "status_event",
                    "id": str(s.id),
                    "occurredAt": s.event_at.isoformat(),
                    "data": WhatsAppMessageStatusEventSerializer(s).data,
                }
            )

        items.sort(key=lambda row: row["occurredAt"], reverse=True)

        return Response(
            {
                "customerId": customer.id,
                "consentWhatsapp": bool(customer.consent_whatsapp),
                "conversations": WhatsAppConversationSerializer(
                    conversations, many=True
                ).data,
                "items": items[:limit],
                "aiSuggestions": _ai_suggestions_status(),
            }
        )


def _ai_suggestions_status() -> dict[str, Any]:
    """Phase 5C — global AI status block returned by inbox + timeline."""
    from django.conf import settings

    auto_enabled = bool(
        getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
    )
    provider = (getattr(settings, "AI_PROVIDER", "disabled") or "disabled").lower()

    if provider == "disabled":
        return {
            "enabled": False,
            "status": "provider_disabled",
            "message": (
                "AI provider is disabled (settings.AI_PROVIDER). Enable "
                "OpenAI / Anthropic and set WHATSAPP_AI_AUTO_REPLY_ENABLED "
                "to turn on the WhatsApp Chat Sales Agent."
            ),
            "provider": provider,
            "autoReplyEnabled": auto_enabled,
            "confidenceThreshold": float(
                getattr(
                    settings,
                    "WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD",
                    0.75,
                )
            ),
        }
    if not auto_enabled:
        return {
            "enabled": False,
            "status": "auto_reply_off",
            "message": (
                "AI suggestions are computed but auto-reply is OFF. The "
                "agent stores a suggestion on each inbound; ops can review "
                "and approve manually. Set "
                "WHATSAPP_AI_AUTO_REPLY_ENABLED=true to activate."
            ),
            "provider": provider,
            "autoReplyEnabled": auto_enabled,
            "confidenceThreshold": float(
                getattr(
                    settings,
                    "WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD",
                    0.75,
                )
            ),
        }
    return {
        "enabled": True,
        "status": "auto",
        "message": (
            "AI Chat Sales Agent runs in auto mode. Backend gates "
            "(consent + Claim Vault + approval matrix + safety + rate "
            "limits) still apply on every send."
        ),
        "provider": provider,
        "autoReplyEnabled": auto_enabled,
        "confidenceThreshold": float(
            getattr(
                settings,
                "WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD",
                0.75,
            )
        ),
    }


# ============================================================================
# Phase 5C — WhatsApp AI Chat Sales Agent endpoints.
# ============================================================================


class WhatsAppAiStatusView(APIView):
    """``GET /api/whatsapp/ai/status/`` — global AI agent status."""

    permission_classes = [_ReadAuthRequired]

    def get(self, _request):
        from django.conf import settings

        return Response(
            {
                **_ai_suggestions_status(),
                "rateLimits": {
                    "maxTurnsPerConversationPerHour": int(
                        getattr(
                            settings,
                            "WHATSAPP_AI_MAX_TURNS_PER_CONVERSATION_PER_HOUR",
                            10,
                        )
                    ),
                    "maxMessagesPerCustomerPerDay": int(
                        getattr(
                            settings,
                            "WHATSAPP_AI_MAX_MESSAGES_PER_CUSTOMER_PER_DAY",
                            30,
                        )
                    ),
                },
            }
        )


class WhatsAppConversationAiModeView(APIView):
    """``PATCH /api/whatsapp/conversations/{id}/ai-mode/`` — toggle per-convo AI."""

    permission_classes = [_OperationsWritePermission]

    def patch(self, request, pk: str):
        convo = _get_conversation_or_404(pk)
        ai_state = dict((convo.metadata or {}).get("ai") or {})
        body = request.data or {}

        changed = False
        if "aiEnabled" in body:
            ai_state["aiEnabled"] = bool(body.get("aiEnabled"))
            changed = True
        if "aiMode" in body:
            mode = str(body.get("aiMode") or "").lower().strip()
            if mode not in {"auto", "suggest", "disabled"}:
                return Response(
                    {"detail": "aiMode must be one of auto/suggest/disabled."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            ai_state["aiMode"] = mode
            changed = True
        if not changed:
            return Response(
                {"detail": "No supported fields supplied."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        metadata = dict(convo.metadata or {})
        metadata["ai"] = ai_state
        convo.metadata = metadata
        convo.save(update_fields=["metadata", "updated_at"])

        write_event(
            kind="whatsapp.conversation.updated",
            text=f"AI mode updated · conversation={convo.id}",
            tone=AuditEvent.Tone.INFO,
            payload={
                "conversation_id": convo.id,
                "ai_enabled": ai_state.get("aiEnabled"),
                "ai_mode": ai_state.get("aiMode"),
                "by": getattr(request.user, "username", "") or "",
            },
        )
        return Response(_ai_state_payload(convo, ai_state))


class WhatsAppConversationRunAiView(APIView):
    """``POST /api/whatsapp/conversations/{id}/run-ai/`` — manual trigger."""

    permission_classes = [_OperationsWritePermission]

    def post(self, request, pk: str):
        from .ai_orchestration import run_whatsapp_ai_agent

        convo = _get_conversation_or_404(pk)
        outcome = run_whatsapp_ai_agent(
            conversation_id=convo.id,
            triggered_by=f"manual:{getattr(request.user, 'username', '')}",
            actor_role=getattr(request.user, "role", "operations") or "operations",
            force=True,
        )
        return Response(
            {
                "conversationId": outcome.conversation_id,
                "inboundMessageId": outcome.inbound_message_id,
                "action": outcome.action,
                "sent": outcome.sent,
                "sentMessageId": outcome.sent_message_id,
                "handoffRequired": outcome.handoff_required,
                "handoffReason": outcome.handoff_reason,
                "blockedReason": outcome.blocked_reason,
                "stage": outcome.stage,
                "confidence": outcome.confidence,
                "language": outcome.detection_language,
                "category": outcome.detected_category,
                "orderId": outcome.order_id,
                "paymentId": outcome.payment_id,
            }
        )


class WhatsAppConversationAiRunsView(APIView):
    """``GET /api/whatsapp/conversations/{id}/ai-runs/`` — recent AI activity."""

    permission_classes = [_ReadAuthRequired]

    def get(self, _request, pk: str):
        convo = _get_conversation_or_404(pk)
        ai_state = dict((convo.metadata or {}).get("ai") or {})
        # Pull the most recent AI-related audit rows for this conversation.
        kinds = [
            "whatsapp.ai.run_started",
            "whatsapp.ai.run_completed",
            "whatsapp.ai.run_failed",
            "whatsapp.ai.reply_auto_sent",
            "whatsapp.ai.reply_blocked",
            "whatsapp.ai.suggestion_stored",
            "whatsapp.ai.greeting_sent",
            "whatsapp.ai.greeting_blocked",
            "whatsapp.ai.language_detected",
            "whatsapp.ai.category_detected",
            "whatsapp.ai.address_updated",
            "whatsapp.ai.order_draft_created",
            "whatsapp.ai.order_booked",
            "whatsapp.ai.payment_link_created",
            "whatsapp.ai.handoff_required",
            "whatsapp.ai.discount_objection_handled",
            "whatsapp.ai.discount_offered",
            "whatsapp.ai.discount_blocked",
        ]
        rows = (
            AuditEvent.objects.filter(
                kind__in=kinds, payload__conversation_id=convo.id
            )
            .order_by("-occurred_at")[:50]
        )
        return Response(
            {
                "ai": _ai_state_payload(convo, ai_state)["ai"],
                "events": [
                    {
                        "id": r.pk,
                        "kind": r.kind,
                        "text": r.text,
                        "tone": r.tone,
                        "occurredAt": r.occurred_at.isoformat(),
                        "payload": dict(r.payload or {}),
                    }
                    for r in rows
                ],
            }
        )


class WhatsAppConversationHandoffView(APIView):
    """``POST /api/whatsapp/conversations/{id}/handoff/`` — operator forces handoff."""

    permission_classes = [_OperationsWritePermission]

    def post(self, request, pk: str):
        convo = _get_conversation_or_404(pk)
        reason = str((request.data or {}).get("reason") or "").strip() or "operator_handoff"
        ai_state = dict((convo.metadata or {}).get("ai") or {})
        ai_state["handoffRequired"] = True
        ai_state["handoffReason"] = reason
        ai_state["aiEnabled"] = False
        metadata = dict(convo.metadata or {})
        metadata["ai"] = ai_state
        convo.metadata = metadata
        convo.status = WhatsAppConversation.Status.ESCALATED
        convo.save(update_fields=["metadata", "status", "updated_at"])

        write_event(
            kind="whatsapp.ai.handoff_required",
            text=f"Operator handoff · conversation={convo.id} · {reason}",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "conversation_id": convo.id,
                "reason": reason,
                "by": getattr(request.user, "username", "") or "",
                "manual": True,
            },
        )
        return Response(_ai_state_payload(convo, ai_state))


class WhatsAppConversationResumeAiView(APIView):
    """``POST /api/whatsapp/conversations/{id}/resume-ai/`` — re-enable AI."""

    permission_classes = [_OperationsWritePermission]

    def post(self, request, pk: str):
        convo = _get_conversation_or_404(pk)
        ai_state = dict((convo.metadata or {}).get("ai") or {})
        ai_state["handoffRequired"] = False
        ai_state["handoffReason"] = ""
        ai_state["aiEnabled"] = True
        metadata = dict(convo.metadata or {})
        metadata["ai"] = ai_state
        convo.metadata = metadata
        # Only flip status back if the conversation was escalated.
        if convo.status == WhatsAppConversation.Status.ESCALATED:
            convo.status = WhatsAppConversation.Status.OPEN
            convo.save(
                update_fields=["metadata", "status", "updated_at"]
            )
        else:
            convo.save(update_fields=["metadata", "updated_at"])

        write_event(
            kind="whatsapp.conversation.updated",
            text=f"AI resumed · conversation={convo.id}",
            tone=AuditEvent.Tone.INFO,
            payload={
                "conversation_id": convo.id,
                "ai_resumed": True,
                "by": getattr(request.user, "username", "") or "",
            },
        )
        return Response(_ai_state_payload(convo, ai_state))


def _ai_state_payload(
    convo: WhatsAppConversation, ai_state: dict[str, Any] | None = None
) -> dict[str, Any]:
    state = dict(ai_state or (convo.metadata or {}).get("ai") or {})
    return {
        "conversationId": convo.id,
        "ai": {
            "aiEnabled": bool(state.get("aiEnabled", True)),
            "aiMode": state.get("aiMode") or "auto",
            "stage": state.get("stage") or "greeting",
            "detectedLanguage": state.get("detectedLanguage") or "",
            "detectedCategory": state.get("detectedCategory") or "",
            "lastAiAction": state.get("lastAiAction") or "",
            "lastAiConfidence": state.get("lastAiConfidence") or 0.0,
            "discountAskCount": state.get("discountAskCount") or 0,
            "totalDiscountPct": state.get("totalDiscountPct") or 0,
            "offeredDiscountPct": state.get("offeredDiscountPct") or 0,
            "handoffRequired": bool(state.get("handoffRequired") or False),
            "handoffReason": state.get("handoffReason") or "",
            "orderId": state.get("orderId") or "",
            "paymentId": state.get("paymentId") or "",
            "paymentLink": state.get("paymentLink") or "",
            "lastSuggestion": state.get("lastSuggestion") or None,
        },
    }


# ============================================================================
# Phase 5D — Chat-to-call handoff endpoints + lifecycle endpoints.
# ============================================================================


class WhatsAppConversationHandoffToCallView(APIView):
    """``POST /api/whatsapp/conversations/{id}/handoff-to-call/`` — operator manual call trigger.

    Operations / admin / director allowed. Viewer + anonymous blocked.
    CAIO actor agent token never reaches this view (it has no auth path).
    """

    permission_classes = [_OperationsWritePermission]

    def post(self, request, pk: str):
        from .call_handoff import trigger_vapi_call_from_whatsapp

        convo = _get_conversation_or_404(pk)
        body = request.data or {}
        reason = str(body.get("reason") or "customer_requested_call").strip()
        note = str(body.get("note") or "")[:500]

        try:
            result = trigger_vapi_call_from_whatsapp(
                conversation=convo,
                reason=reason,
                triggered_by=request.user,
                inbound_message=None,
                trigger_source=WhatsAppHandoffToCall.TriggerSource.OPERATOR,
                metadata={"note": note} if note else None,
            )
        except Exception as exc:  # noqa: BLE001 - never 5xx the API
            return Response(
                {"detail": f"Handoff failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {
                "handoffId": result.handoff_id,
                "status": result.status,
                "callId": result.call_id,
                "providerCallId": result.provider_call_id,
                "reason": result.reason,
                "skipped": result.skipped,
                "errorMessage": result.error_message,
                "message": (
                    "Call triggered" if not result.skipped else f"Skipped: {result.error_message}"
                ),
            },
            status=status.HTTP_201_CREATED if not result.skipped else status.HTTP_200_OK,
        )


class WhatsAppConversationHandoffsListView(APIView):
    """``GET /api/whatsapp/conversations/{id}/handoffs/`` — list call handoffs."""

    permission_classes = [_ReadAuthRequired]

    def get(self, _request, pk: str):
        convo = _get_conversation_or_404(pk)
        rows = (
            WhatsAppHandoffToCall.objects.filter(conversation=convo)
            .select_related("call", "requested_by", "inbound_message")
            .order_by("-created_at")[:50]
        )
        return Response(
            [
                _serialize_handoff(row)
                for row in rows
            ]
        )


class WhatsAppLifecycleEventsListView(APIView):
    """``GET /api/whatsapp/lifecycle-events/`` — read recent lifecycle events.

    Optional filters: ``objectType``, ``objectId``, ``status``, ``limit``.
    """

    permission_classes = [_ReadAuthRequired]

    def get(self, request):
        qs = WhatsAppLifecycleEvent.objects.all().select_related(
            "customer", "message"
        )
        object_type = request.query_params.get("objectType")
        if object_type:
            qs = qs.filter(object_type=object_type)
        object_id = request.query_params.get("objectId")
        if object_id:
            qs = qs.filter(object_id=object_id)
        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        try:
            limit = max(1, min(int(request.query_params.get("limit") or 100), 500))
        except (TypeError, ValueError):
            limit = 100
        rows = qs.order_by("-created_at")[:limit]
        return Response([_serialize_lifecycle_event(row) for row in rows])


# ----- Phase 5E — Day-20 reorder admin endpoints -----


class WhatsAppReorderDay20StatusView(APIView):
    """``GET /api/whatsapp/reorder/day20/status/`` — admin/director view."""

    permission_classes = [_AdminAlways]

    def get(self, _request):
        from django.conf import settings

        from .reorder import (
            DAY20_LOWER_BOUND_DAYS,
            DAY20_UPPER_BOUND_DAYS,
        )

        rows = (
            WhatsAppLifecycleEvent.objects.filter(
                action_key="whatsapp.reorder_day20_reminder"
            )
            .order_by("-created_at")[:50]
        )
        return Response(
            {
                "enabled": bool(
                    getattr(settings, "WHATSAPP_REORDER_DAY20_ENABLED", False)
                ),
                "lowerBoundDays": DAY20_LOWER_BOUND_DAYS,
                "upperBoundDays": DAY20_UPPER_BOUND_DAYS,
                "lifecycleEnabled": bool(
                    getattr(settings, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED", False)
                ),
                "events": [_serialize_lifecycle_event(row) for row in rows],
            }
        )


class WhatsAppReorderDay20RunView(APIView):
    """``POST /api/whatsapp/reorder/day20/run/`` — admin/director sweep trigger."""

    permission_classes = [_AdminAlways]

    def post(self, request):
        from .reorder import run_day20_reorder_sweep

        dry_run = bool((request.data or {}).get("dryRun"))
        result = run_day20_reorder_sweep(dry_run=dry_run)
        return Response(result.to_dict())


def _serialize_handoff(row: WhatsAppHandoffToCall) -> dict[str, Any]:
    return {
        "id": row.pk,
        "conversationId": row.conversation_id,
        "customerId": row.customer_id,
        "inboundMessageId": row.inbound_message_id or "",
        "reason": row.reason,
        "triggerSource": row.trigger_source,
        "status": row.status,
        "callId": row.call_id or "",
        "providerCallId": row.provider_call_id or "",
        "requestedBy": getattr(row.requested_by, "username", "") or "",
        "metadata": dict(row.metadata or {}),
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
        "triggeredAt": row.triggered_at.isoformat() if row.triggered_at else None,
        "errorMessage": row.error_message or "",
    }


def _serialize_lifecycle_event(row: WhatsAppLifecycleEvent) -> dict[str, Any]:
    return {
        "id": row.pk,
        "actionKey": row.action_key,
        "objectType": row.object_type,
        "objectId": row.object_id,
        "eventKind": row.event_kind,
        "customerId": row.customer_id or "",
        "messageId": row.message_id or "",
        "status": row.status,
        "blockReason": row.block_reason or "",
        "errorMessage": row.error_message or "",
        "idempotencyKey": row.idempotency_key,
        "metadata": dict(row.metadata or {}),
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }


__all__ = (
    "WhatsAppAiStatusView",
    "WhatsAppConnectionViewSet",
    "WhatsAppConsentView",
    "WhatsAppConversationAiModeView",
    "WhatsAppConversationAiRunsView",
    "WhatsAppConversationHandoffToCallView",
    "WhatsAppConversationHandoffView",
    "WhatsAppConversationHandoffsListView",
    "WhatsAppConversationMarkReadView",
    "WhatsAppConversationMessagesView",
    "WhatsAppConversationNotesView",
    "WhatsAppConversationResumeAiView",
    "WhatsAppConversationRunAiView",
    "WhatsAppConversationSendTemplateView",
    "WhatsAppConversationViewSet",
    "WhatsAppCustomerTimelineView",
    "WhatsAppInboxView",
    "WhatsAppLifecycleEventsListView",
    "WhatsAppReorderDay20RunView",
    "WhatsAppReorderDay20StatusView",
    "WhatsAppMessageRetryView",
    "WhatsAppMessageViewSet",
    "WhatsAppProviderStatusView",
    "WhatsAppSendTemplateView",
    "WhatsAppTemplateSyncView",
    "WhatsAppTemplateViewSet",
)
