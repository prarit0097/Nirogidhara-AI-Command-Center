"""Phase 5A — WhatsApp service layer.

The single path between callers (HTTP views / Celery tasks / future
service callers) and the provider. Owns the full safety stack:

1. Provider dispatch — ``get_provider()`` returns the singleton instance.
2. Active connection — ``get_active_connection()``.
3. Consent + opt-out — :mod:`apps.whatsapp.consent` helpers.
4. Approved + active template — :mod:`apps.whatsapp.template_registry`.
5. Approved Claim Vault — :func:`apps.compliance.lookup_claim` when
   ``template.claim_vault_required=True``.
6. CAIO hard stop — refused at the service entry (defence in depth on
   top of approval-engine + execute layer guards).
7. Approval Matrix — ``apps.ai_governance.approval_engine.enforce_or_queue``
   for every action key.
8. Idempotency — :class:`WhatsAppMessage.idempotency_key` unique
   constraint prevents Celery double-sends.

Every state-change in this module writes a ``whatsapp.*`` AuditEvent.
Failed sends NEVER mutate ``Order`` / ``Payment`` / ``Shipment``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps._id import next_id
from apps.ai_governance import approval_engine
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer

from .consent import (
    OPT_OUT_KEYWORDS,
    consent_state_for,
    detect_opt_out_keyword,
    has_whatsapp_consent,
    record_opt_out,
)
from .integrations.whatsapp.base import (
    ProviderError,
    ProviderHealth,
    ProviderSendResult,
    ProviderWebhookEvent,
    WhatsAppProvider,
)
from .integrations.whatsapp.mock import MockProvider
from .models import (
    WhatsAppConnection,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppMessageStatusEvent,
    WhatsAppSendLog,
    WhatsAppTemplate,
    WhatsAppWebhookEvent,
)
from .template_registry import (
    TemplateRegistryError,
    get_template_for_action,
    render_template_components,
    validate_template_variables,
)


# Provider instance is built per-request so settings changes (test patches)
# are honoured. Trivial cost — providers hold no state beyond config refs.

CAIO_AGENT_TOKEN = "caio"


class WhatsAppServiceError(Exception):
    """Raised when the service refuses to queue / send a message."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int = 400,
        block_reason: str = "",
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.block_reason = block_reason


@dataclass(frozen=True)
class QueuedMessage:
    """Result of :func:`queue_template_message`."""

    message: WhatsAppMessage
    conversation: WhatsAppConversation
    auto_approved: bool
    approval_request_id: str | None


def get_provider() -> WhatsAppProvider:
    """Return the configured provider instance.

    Lazy-imports the heavier providers so the test suite (mock-only) does
    not depend on the ``requests`` package being installed.
    """
    name = (getattr(settings, "WHATSAPP_PROVIDER", "mock") or "mock").lower()
    if name == "mock":
        return MockProvider()
    if name == "meta_cloud":
        from .integrations.whatsapp.meta_cloud_client import MetaCloudProvider

        return MetaCloudProvider()
    if name == "baileys_dev":
        from .integrations.whatsapp.baileys_dev import BaileysDevProvider

        return BaileysDevProvider()
    raise WhatsAppServiceError(
        f"Unknown WHATSAPP_PROVIDER='{name}' — must be one of mock|meta_cloud|baileys_dev.",
        http_status=500,
        block_reason="provider_misconfigured",
    )


def get_active_connection() -> WhatsAppConnection:
    """Return the most recently-updated connected row, or a mock fallback.

    Phase 5A uses a single-tenant default. When no row exists (fresh DB,
    test fixtures), we lazily create a mock-mode row so the service can
    still operate in tests without needing the WABA setup screen.
    """
    qs = (
        WhatsAppConnection.objects.filter(
            status=WhatsAppConnection.Status.CONNECTED
        )
        .order_by("-updated_at")
    )
    connection = qs.first()
    if connection is not None:
        return connection
    # Fallback: latest row of any status, or auto-seed a mock connection.
    connection = WhatsAppConnection.objects.order_by("-updated_at").first()
    if connection is not None:
        return connection
    provider_name = (
        getattr(settings, "WHATSAPP_PROVIDER", "mock") or "mock"
    ).lower()
    return WhatsAppConnection.objects.create(
        id=next_id("WAC", WhatsAppConnection, base=10001),
        provider=provider_name
        if provider_name in WhatsAppConnection.Provider.values
        else WhatsAppConnection.Provider.MOCK,
        display_name="Nirogidhara WhatsApp",
        phone_number="",
        status=(
            WhatsAppConnection.Status.CONNECTED
            if provider_name == "mock"
            else WhatsAppConnection.Status.DISCONNECTED
        ),
        metadata={"auto_seeded": True},
    )


def get_or_open_conversation(
    customer: Customer,
    *,
    connection: WhatsAppConnection | None = None,
) -> WhatsAppConversation:
    """Return the open conversation for the customer or create one."""
    connection = connection or get_active_connection()
    convo = (
        WhatsAppConversation.objects.filter(
            customer=customer,
            connection=connection,
        )
        .exclude(status=WhatsAppConversation.Status.RESOLVED)
        .order_by("-updated_at")
        .first()
    )
    if convo is not None:
        return convo
    return WhatsAppConversation.objects.create(
        id=next_id("WCV", WhatsAppConversation, base=10001),
        customer=customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
        ai_status=WhatsAppConversation.AiStatus.DISABLED,
    )


def provider_status() -> dict[str, Any]:
    """Return a redacted status payload for the ``/api/whatsapp/provider/status/`` endpoint."""
    provider = get_provider()
    health = _safe_health(provider)
    connection: WhatsAppConnection | None
    try:
        connection = get_active_connection()
    except Exception:  # noqa: BLE001 - defensive
        connection = None
    return {
        "provider": getattr(provider, "name", "unknown"),
        "configured": bool(_provider_is_configured()),
        "healthy": health.healthy,
        "detail": health.detail,
        "connection": (
            {
                "id": connection.id,
                "displayName": connection.display_name,
                "phoneNumber": connection.phone_number,
                "phoneNumberId": _mask_id(connection.phone_number_id),
                "businessAccountId": _mask_id(connection.business_account_id),
                "status": connection.status,
                "lastConnectedAt": (
                    connection.last_connected_at.isoformat()
                    if connection.last_connected_at
                    else None
                ),
                "lastHealthCheckAt": (
                    connection.last_health_check_at.isoformat()
                    if connection.last_health_check_at
                    else None
                ),
            }
            if connection is not None
            else None
        ),
        "accessTokenSet": bool(getattr(settings, "META_WA_ACCESS_TOKEN", "")),
        "verifyTokenSet": bool(getattr(settings, "META_WA_VERIFY_TOKEN", "")),
        "appSecretSet": bool(
            getattr(settings, "META_WA_APP_SECRET", "")
            or getattr(settings, "WHATSAPP_WEBHOOK_SECRET", "")
        ),
        "apiVersion": getattr(settings, "META_WA_API_VERSION", "v20.0"),
        "devProviderEnabled": bool(
            getattr(settings, "WHATSAPP_DEV_PROVIDER_ENABLED", False)
        ),
        "metadata": dict(health.metadata or {}),
    }


def _safe_health(provider: WhatsAppProvider) -> ProviderHealth:
    try:
        return provider.health_check()
    except Exception as exc:  # noqa: BLE001 - defensive
        return ProviderHealth(
            provider=getattr(provider, "name", "unknown"),
            healthy=False,
            detail=f"health_check raised: {exc}",
            metadata={},
        )


def _provider_is_configured() -> bool:
    name = (getattr(settings, "WHATSAPP_PROVIDER", "mock") or "mock").lower()
    if name == "mock":
        return True
    if name == "meta_cloud":
        return bool(
            getattr(settings, "META_WA_ACCESS_TOKEN", "")
            and getattr(settings, "META_WA_PHONE_NUMBER_ID", "")
        )
    if name == "baileys_dev":
        return bool(getattr(settings, "WHATSAPP_DEV_PROVIDER_ENABLED", False))
    return False


def _mask_id(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}…{value[-2:]}"


# ---------------------------------------------------------------------------
# Send pipeline
# ---------------------------------------------------------------------------


def queue_template_message(
    *,
    customer: Customer,
    action_key: str,
    variables: Mapping[str, Any] | None = None,
    template: WhatsAppTemplate | None = None,
    triggered_by: str = "",
    actor_role: str = "",
    actor_agent: str = "",
    approval_request_id: str = "",
    idempotency_key: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
    by_user=None,
) -> QueuedMessage:
    """Queue a template send for the customer.

    Pipeline:

    1. Refuse CAIO actor.
    2. Refuse :data:`OPT_OUT_KEYWORDS` action keys (not in matrix).
    3. Resolve the template (via ``action_key`` or explicit row) and
       validate variables / approval / Claim Vault.
    4. Run :func:`approval_engine.enforce_or_queue`. ``allowed=False``
       → ``WhatsAppServiceError``; allowed → continue.
    5. Insert the :class:`WhatsAppMessage` row in ``status=queued`` and
       open / re-use the conversation.
    """
    actor_agent_lower = (actor_agent or "").lower()
    if actor_agent_lower == CAIO_AGENT_TOKEN:
        _block(
            customer,
            action_key=action_key,
            reason=(
                "CAIO can never originate a customer-facing WhatsApp send "
                "(Master Blueprint §26 #5)."
            ),
            block_reason="caio_no_send",
            extra={"actor_agent": actor_agent_lower},
        )
        raise WhatsAppServiceError(
            "CAIO cannot send WhatsApp messages.",
            http_status=403,
            block_reason="caio_no_send",
        )

    if not customer.phone:
        _block(
            customer,
            action_key=action_key,
            reason="Customer has no phone number on record.",
            block_reason="missing_phone",
        )
        raise WhatsAppServiceError(
            "Customer has no phone number on record.",
            http_status=400,
            block_reason="missing_phone",
        )

    # Consent gate.
    if not has_whatsapp_consent(customer):
        _block(
            customer,
            action_key=action_key,
            reason="Customer has not opted in to WhatsApp.",
            block_reason="consent_missing",
            extra={"consentState": consent_state_for(customer)},
        )
        raise WhatsAppServiceError(
            "Customer has not opted in to WhatsApp.",
            http_status=403,
            block_reason="consent_missing",
        )

    # Template gate.
    connection = get_active_connection()
    if template is None:
        try:
            template = get_template_for_action(
                action_key=action_key, connection=connection
            )
        except TemplateRegistryError as exc:
            _block(
                customer,
                action_key=action_key,
                reason=str(exc),
                block_reason="template_missing",
            )
            raise WhatsAppServiceError(
                str(exc),
                http_status=400,
                block_reason="template_missing",
            ) from exc

    if not template.is_active:
        _block(
            customer,
            action_key=action_key,
            reason="Template is locally deactivated.",
            block_reason="template_inactive",
            extra={"templateId": template.id},
        )
        raise WhatsAppServiceError(
            "Template is locally deactivated.",
            http_status=400,
            block_reason="template_inactive",
        )
    if template.status != WhatsAppTemplate.Status.APPROVED:
        _block(
            customer,
            action_key=action_key,
            reason=f"Template status={template.status}; only APPROVED can send.",
            block_reason="template_not_approved",
            extra={"templateId": template.id, "status": template.status},
        )
        raise WhatsAppServiceError(
            f"Template status={template.status}; only APPROVED can send.",
            http_status=400,
            block_reason="template_not_approved",
        )

    variables = dict(variables or {})
    try:
        validate_template_variables(template, variables)
    except TemplateRegistryError as exc:
        _block(
            customer,
            action_key=action_key,
            reason=str(exc),
            block_reason="template_variables_invalid",
            extra={"templateId": template.id},
        )
        raise WhatsAppServiceError(
            str(exc), http_status=400, block_reason="template_variables_invalid"
        ) from exc

    # Claim Vault gate.
    if template.claim_vault_required:
        if not _has_approved_claim_for(customer, variables):
            _block(
                customer,
                action_key=action_key,
                reason=(
                    "Template requires Claim Vault grounding and no approved "
                    "Claim was found for the relevant product."
                ),
                block_reason="claim_vault_missing",
                extra={"templateId": template.id},
            )
            raise WhatsAppServiceError(
                "Template requires Claim Vault grounding.",
                http_status=403,
                block_reason="claim_vault_missing",
            )

    # Approval matrix gate.
    target = {
        "app": "crm",
        "model": "Customer",
        "id": customer.id,
        "consent": {"whatsapp": True},
    }
    matrix_payload = {
        "customer_consent": True,
        "customer_id": customer.id,
        "templateId": template.id,
        "actionKey": action_key,
    }
    decision = approval_engine.enforce_or_queue(
        action=action_key,
        payload=matrix_payload,
        actor_role=actor_role,
        actor_agent=actor_agent_lower,
        target=target,
        by_user=by_user,
    )
    if not decision.allowed:
        _block(
            customer,
            action_key=action_key,
            reason=decision.reason,
            block_reason="approval_pending",
            extra={
                "approvalRequestId": decision.approval_request_id,
                "mode": decision.mode,
                "status": decision.status,
            },
        )
        raise WhatsAppServiceError(
            f"Approval not granted: {decision.reason}",
            http_status=403,
            block_reason="approval_pending",
        )

    # Persist the queued row inside a single atomic block. Blocks above
    # this point already wrote ``whatsapp.send.blocked`` audits via
    # ``_block`` BEFORE raising, so a rollback inside this transaction
    # cannot drop them.
    with transaction.atomic():
        convo = get_or_open_conversation(customer, connection=connection)
        idempotency = idempotency_key or _build_idempotency_key(
            customer=customer,
            template=template,
            variables=variables,
            action_key=action_key,
        )
        metadata = {
            "actor_agent": actor_agent_lower,
            "actor_role": (actor_role or "").lower(),
            "trigger": triggered_by,
            "approval_request_id": decision.approval_request_id,
            **dict(extra_metadata or {}),
        }
        message = WhatsAppMessage.objects.create(
            id=next_id("WAM", WhatsAppMessage, base=100001),
            conversation=convo,
            customer=customer,
            direction=WhatsAppMessage.Direction.OUTBOUND,
            status=WhatsAppMessage.Status.QUEUED,
            type=WhatsAppMessage.Type.TEMPLATE,
            body=_render_preview(template, variables),
            template=template,
            template_variables=dict(variables),
            approval_request_id=approval_request_id or decision.approval_request_id,
            idempotency_key=idempotency,
            metadata=metadata,
            queued_at=timezone.now(),
        )

        write_event(
            kind="whatsapp.message.queued",
            text=(
                f"WhatsApp message {message.id} queued · {action_key} · "
                f"customer={customer.id}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "message_id": message.id,
                "conversation_id": convo.id,
                "customer_id": customer.id,
                "action_key": action_key,
                "template_id": template.id,
                "approval_request_id": decision.approval_request_id,
                "actor_role": (actor_role or "").lower(),
                "actor_agent": actor_agent_lower,
                "idempotency_key": idempotency,
            },
        )

    return QueuedMessage(
        message=message,
        conversation=convo,
        auto_approved=decision.status == "auto_approved",
        approval_request_id=decision.approval_request_id,
    )


def send_queued_message(message_id: str) -> WhatsAppMessage:
    """Drive a queued message through the provider once.

    Idempotent: a message that already has ``provider_message_id`` (or is
    already past the queued state) returns early without a second call.
    Failures are recorded and re-raised as :class:`ProviderError` so the
    Celery task layer can decide whether to retry.
    """
    message = WhatsAppMessage.objects.select_related(
        "conversation", "customer", "template"
    ).get(pk=message_id)

    # Defence in depth — re-check CAIO marker on dispatch.
    if (message.metadata or {}).get("actor_agent", "").lower() == CAIO_AGENT_TOKEN:
        _mark_failed_locally(
            message,
            error_message="CAIO cannot send customer messages.",
            error_code="caio_no_send",
        )
        raise WhatsAppServiceError(
            "CAIO cannot send WhatsApp messages.",
            http_status=403,
            block_reason="caio_no_send",
        )

    if message.status not in {
        WhatsAppMessage.Status.QUEUED,
        WhatsAppMessage.Status.FAILED,
    }:
        return message
    if message.provider_message_id:
        return message

    # Re-check consent at dispatch time.
    if not has_whatsapp_consent(message.customer):
        _mark_failed_locally(
            message,
            error_message="Consent revoked before send.",
            error_code="consent_missing",
        )
        return message

    provider = get_provider()
    template = message.template
    if template is None:
        _mark_failed_locally(
            message,
            error_message="Outbound message missing template.",
            error_code="template_missing",
        )
        return message

    components = render_template_components(template, message.template_variables)
    started = timezone.now()
    attempt = (message.attempt_count or 0) + 1
    try:
        result: ProviderSendResult = provider.send_template_message(
            to_phone=message.customer.phone,
            template_name=template.name,
            language=template.language,
            components=components,
            idempotency_key=message.idempotency_key,
        )
    except ProviderError as exc:
        _record_send_log(
            message=message,
            attempt=attempt,
            provider_name=getattr(provider, "name", "unknown"),
            request_payload={
                "to": message.customer.phone,
                "template": template.name,
                "language": template.language,
            },
            response_status=0,
            response_payload={"error": str(exc), "code": exc.error_code},
            started_at=started,
            error_code=exc.error_code,
        )
        _mark_failed_locally(
            message,
            error_message=str(exc),
            error_code=exc.error_code or "provider_error",
            attempt=attempt,
        )
        raise

    completed = timezone.now()
    _record_send_log(
        message=message,
        attempt=attempt,
        provider_name=result.provider,
        request_payload=dict(result.request_payload),
        response_status=result.response_status,
        response_payload=dict(result.response_payload),
        started_at=started,
        completed_at=completed,
        latency_ms=result.latency_ms,
    )

    message.status = WhatsAppMessage.Status.SENT
    message.provider_message_id = result.provider_message_id
    message.attempt_count = attempt
    message.sent_at = completed
    message.save(
        update_fields=[
            "status",
            "provider_message_id",
            "attempt_count",
            "sent_at",
            "updated_at",
        ]
    )

    write_event(
        kind="whatsapp.message.sent",
        text=(
            f"WhatsApp message {message.id} sent · "
            f"provider_message_id={result.provider_message_id}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "message_id": message.id,
            "provider_message_id": result.provider_message_id,
            "conversation_id": message.conversation_id,
            "customer_id": message.customer_id,
            "provider": result.provider,
            "latency_ms": result.latency_ms,
        },
    )
    write_event(
        kind="whatsapp.template.sent",
        text=(
            f"Template {template.name}/{template.language} sent to "
            f"{message.customer_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "template_id": template.id,
            "name": template.name,
            "language": template.language,
            "message_id": message.id,
            "customer_id": message.customer_id,
        },
    )
    return message


def _mark_failed_locally(
    message: WhatsAppMessage,
    *,
    error_message: str,
    error_code: str,
    attempt: int | None = None,
) -> None:
    message.status = WhatsAppMessage.Status.FAILED
    message.error_message = (error_message or "")[:1000]
    message.error_code = (error_code or "")[:24]
    if attempt is not None:
        message.attempt_count = attempt
    message.save(
        update_fields=[
            "status",
            "error_message",
            "error_code",
            "attempt_count",
            "updated_at",
        ]
    )
    write_event(
        kind="whatsapp.message.failed",
        text=f"WhatsApp message {message.id} failed: {error_message}",
        tone=AuditEvent.Tone.DANGER,
        payload={
            "message_id": message.id,
            "customer_id": message.customer_id,
            "error_code": error_code,
            "error_message": error_message,
            "attempt_count": message.attempt_count,
        },
    )


def _record_send_log(
    *,
    message: WhatsAppMessage,
    attempt: int,
    provider_name: str,
    request_payload: Mapping[str, Any],
    response_status: int,
    response_payload: Mapping[str, Any],
    started_at,
    completed_at=None,
    latency_ms: int = 0,
    error_code: str = "",
) -> WhatsAppSendLog:
    return WhatsAppSendLog.objects.create(
        message=message,
        attempt=attempt,
        provider=provider_name,
        request_payload=_redact(request_payload),
        response_status=response_status,
        response_payload=_redact(response_payload),
        latency_ms=latency_ms,
        error_code=(error_code or "")[:32],
        started_at=started_at,
        completed_at=completed_at or timezone.now(),
    )


def _redact(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strip Authorization-bearing keys before persisting.

    Defensive: providers should never put tokens into the payload, but the
    helper makes it impossible to accidentally log one.
    """
    redacted: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        lowered = str(key).lower()
        if "token" in lowered or "secret" in lowered or "authorization" in lowered:
            redacted[key] = "***redacted***"
        else:
            redacted[key] = value
    return redacted


def _has_approved_claim_for(
    customer: Customer, variables: Mapping[str, Any]
) -> bool:
    """Look up :class:`apps.compliance.Claim` for the relevant product.

    Phase 5A keeps the lookup permissive: any Claim row whose ``approved``
    JSON list is non-empty for the customer's :attr:`product_interest`
    is enough to satisfy the gate. Phase 5C tightens the per-sentence
    post-LLM filter inside the prompt builder.
    """
    try:
        from apps.compliance.models import Claim
    except Exception:  # pragma: no cover - defensive
        return False

    product_keys: list[str] = []
    direct = variables.get("product") if isinstance(variables, Mapping) else None
    if direct:
        product_keys.append(str(direct))
    if getattr(customer, "product_interest", ""):
        product_keys.append(str(customer.product_interest))
    if not product_keys:
        return False

    for key in product_keys:
        claim = Claim.objects.filter(product__iexact=key).first()
        if claim is not None and claim.approved:
            return True
    return False


def _build_idempotency_key(
    *,
    customer: Customer,
    template: WhatsAppTemplate | None,
    variables: Mapping[str, Any],
    action_key: str,
) -> str:
    """Stable key per (customer, template, variables hash, day) tuple.

    ``template`` is optional — Phase 5C freeform AI replies pass
    ``None`` because they're TEXT messages, not templates.
    """
    import hashlib
    import json

    blob = json.dumps(
        {
            "customer_id": customer.id,
            "template_id": getattr(template, "id", "freeform"),
            "variables": variables,
            "action_key": action_key,
            "day": timezone.now().date().isoformat(),
            # Add nanoseconds for freeform sends so back-to-back AI
            # replies in the same minute still mint distinct keys.
            "ts_us": (
                timezone.now().timestamp() if template is None else 0
            ),
        },
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    digest = hashlib.sha256(blob).hexdigest()[:24]
    return f"wsp:{digest}"


def _render_preview(template: WhatsAppTemplate, variables: Mapping[str, Any]) -> str:
    """Cheap preview text for inbox display (max 500 chars)."""
    if not template.body_components:
        return f"[{template.name}] " + ", ".join(
            f"{k}={v}" for k, v in variables.items()
        )[:480]
    body_block = next(
        (c for c in template.body_components if (c or {}).get("type", "").upper() == "BODY"),
        None,
    )
    text = ""
    if isinstance(body_block, dict):
        text = str(body_block.get("text") or "")
    if not text:
        text = template.name
    # Replace ``{{1}}`` / ``{{2}}`` with positional values when possible.
    ordered_values = list(variables.values())
    for index, value in enumerate(ordered_values, start=1):
        text = text.replace("{{" + str(index) + "}}", str(value))
    return text[:500]


def _block(
    customer: Customer,
    *,
    action_key: str,
    reason: str,
    block_reason: str,
    extra: Mapping[str, Any] | None = None,
) -> None:
    write_event(
        kind="whatsapp.send.blocked",
        text=f"WhatsApp send blocked · {action_key} · {block_reason}",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "customer_id": customer.id,
            "action_key": action_key,
            "block_reason": block_reason,
            "detail": reason,
            **dict(extra or {}),
        },
    )


# ---------------------------------------------------------------------------
# Webhook event handling
# ---------------------------------------------------------------------------


@transaction.atomic
def handle_inbound_message_event(
    event: ProviderWebhookEvent,
    *,
    connection: WhatsAppConnection,
) -> WhatsAppMessage | None:
    """Persist an inbound message + run opt-out detection.

    Returns the new :class:`WhatsAppMessage` row, or ``None`` when the
    customer cannot be matched and we deliberately skip persistence
    (Phase 5A keeps customer-creation conservative — Phase 5B widens it).
    """
    customer = _match_customer_by_phone(event.from_phone)
    if customer is None:
        write_event(
            kind="whatsapp.inbound.received",
            text=(
                f"Inbound WhatsApp from {event.from_phone} (no Customer match)"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "from_phone": event.from_phone,
                "provider_message_id": event.provider_message_id,
                "matched": False,
                "body_excerpt": (event.body or "")[:80],
            },
        )
        return None

    convo = get_or_open_conversation(customer, connection=connection)
    inbound_at = timezone.datetime.fromtimestamp(
        event.timestamp, tz=timezone.get_current_timezone()
    ) if event.timestamp else timezone.now()

    message, created = WhatsAppMessage.objects.get_or_create(
        provider_message_id=event.provider_message_id,
        defaults={
            "id": next_id("WAM", WhatsAppMessage, base=100001),
            "conversation": convo,
            "customer": customer,
            "direction": WhatsAppMessage.Direction.INBOUND,
            "status": WhatsAppMessage.Status.DELIVERED,
            "type": WhatsAppMessage.Type.TEXT,
            "body": (event.body or "")[:4096],
            "metadata": {"raw": dict(event.raw)},
            "queued_at": inbound_at,
            "sent_at": inbound_at,
            "delivered_at": inbound_at,
        },
    )
    if not created:
        return message

    convo.last_message_at = inbound_at
    convo.last_inbound_at = inbound_at
    convo.last_message_text = (event.body or "")[:500]
    convo.unread_count = (convo.unread_count or 0) + 1
    convo.save(
        update_fields=[
            "last_message_at",
            "last_inbound_at",
            "last_message_text",
            "unread_count",
            "updated_at",
        ]
    )

    # Update consent timestamp and opt-out detection.
    consent_obj, _ = customer.whatsapp_consent.__class__.objects.get_or_create(  # noqa: SLF001
        customer=customer,
        defaults={"consent_state": "unknown"},
    )
    consent_obj.last_inbound_at = inbound_at
    consent_obj.save(update_fields=["last_inbound_at", "updated_at"])

    keyword = detect_opt_out_keyword(event.body or "")
    if keyword:
        record_opt_out(
            customer,
            keyword=keyword,
            inbound_message_id=message.id,
        )

    write_event(
        kind="whatsapp.inbound.received",
        text=(
            f"Inbound WhatsApp message {message.id} from {customer.id} · "
            f"'{(event.body or '')[:60]}'"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "message_id": message.id,
            "conversation_id": convo.id,
            "customer_id": customer.id,
            "provider_message_id": event.provider_message_id,
            "body_excerpt": (event.body or "")[:80],
            "opt_out_keyword": keyword or "",
        },
    )

    # Phase 5C — fire the WhatsApp AI Chat Agent task on commit so the
    # webhook returns 200 immediately and the LLM dispatch happens out
    # of band. The orchestrator handles its own consent / safety gates;
    # the dispatch here is opt-out-only — sending the inbound through
    # the AI never blocks the inbound persistence above.
    if not keyword:
        _enqueue_ai_run(convo.id, message.id)

    return message


def _enqueue_ai_run(conversation_id: str, inbound_message_id: str) -> None:
    """Schedule ``run_whatsapp_ai_agent_for_conversation``.

    In Celery **eager mode** (default for tests + local dev) the task
    runs synchronously inside the current process; we dispatch
    immediately so the orchestrator sees the just-persisted inbound and
    the test transaction sees the AI audit rows.

    In **real broker mode** (production) we wrap the dispatch in
    ``transaction.on_commit`` so the broker only learns about the
    inbound after the DB commit completes. In both modes a missing
    broker / dispatch error must never break the webhook write path.
    """
    from django.conf import settings

    eager_mode = bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False))

    def _send():
        try:
            from .tasks import run_whatsapp_ai_agent_for_conversation

            run_whatsapp_ai_agent_for_conversation.delay(
                conversation_id, inbound_message_id, triggered_by="inbound"
            )
        except Exception:  # noqa: BLE001 - defensive; never break webhook
            pass

    if eager_mode:
        # Eager mode: dispatch right away — the inbound row is already
        # persisted at this point in ``handle_inbound_message_event``.
        _send()
        return
    try:
        transaction.on_commit(_send)
    except Exception:  # noqa: BLE001 - also defensive
        pass


@transaction.atomic
def handle_status_event(
    event: ProviderWebhookEvent,
) -> WhatsAppMessageStatusEvent | None:
    """Persist a status webhook event + bump the matching message."""
    target = WhatsAppMessage.objects.filter(
        provider_message_id=event.provider_message_id,
        direction=WhatsAppMessage.Direction.OUTBOUND,
    ).first()
    if target is None:
        return None

    # Idempotent on provider_event_id (DB unique constraint).
    status_event, created = WhatsAppMessageStatusEvent.objects.get_or_create(
        provider_event_id=event.event_id,
        defaults={
            "message": target,
            "status": _normalise_status(event.status),
            "event_at": (
                timezone.datetime.fromtimestamp(
                    event.timestamp, tz=timezone.get_current_timezone()
                )
                if event.timestamp
                else timezone.now()
            ),
            "raw_payload": dict(event.raw),
        },
    )
    if not created:
        return status_event

    new_status = _normalise_status(event.status)
    target_changed = False
    if new_status == WhatsAppMessage.Status.DELIVERED and not target.delivered_at:
        target.delivered_at = status_event.event_at
        target.status = WhatsAppMessage.Status.DELIVERED
        target_changed = True
    elif new_status == WhatsAppMessage.Status.READ:
        target.read_at = status_event.event_at
        target.status = WhatsAppMessage.Status.READ
        target_changed = True
    elif new_status == WhatsAppMessage.Status.FAILED:
        target.status = WhatsAppMessage.Status.FAILED
        target.error_message = (
            (event.raw or {}).get("errors", [{}])[0].get("message", "")
            if event.raw
            else "failed"
        )[:500]
        target_changed = True
    if target_changed:
        target.save(
            update_fields=[
                "status",
                "delivered_at",
                "read_at",
                "error_message",
                "updated_at",
            ]
        )

    audit_kind = {
        WhatsAppMessage.Status.DELIVERED: "whatsapp.message.delivered",
        WhatsAppMessage.Status.READ: "whatsapp.message.read",
        WhatsAppMessage.Status.FAILED: "whatsapp.message.failed",
    }.get(new_status)
    if audit_kind is not None:
        write_event(
            kind=audit_kind,
            text=f"WhatsApp message {target.id} → {new_status}",
            tone=(
                AuditEvent.Tone.SUCCESS
                if new_status in (
                    WhatsAppMessage.Status.DELIVERED,
                    WhatsAppMessage.Status.READ,
                )
                else AuditEvent.Tone.DANGER
            ),
            payload={
                "message_id": target.id,
                "provider_message_id": event.provider_message_id,
                "status": new_status,
            },
        )
    return status_event


def _normalise_status(value: str) -> str:
    canonical = (value or "").lower().strip()
    if canonical in (WhatsAppMessage.Status.values):
        return canonical
    if canonical == "sent":
        return WhatsAppMessage.Status.SENT
    if canonical == "delivered":
        return WhatsAppMessage.Status.DELIVERED
    if canonical == "read":
        return WhatsAppMessage.Status.READ
    if canonical in ("failed", "undelivered", "rejected"):
        return WhatsAppMessage.Status.FAILED
    return WhatsAppMessage.Status.SENT


def _match_customer_by_phone(phone: str) -> Customer | None:
    """Match an inbound number to a Customer by relaxed E.164 comparison.

    Phase 5A does NOT auto-create customers from inbound numbers. Phase 5B
    builds the inbox + relaxed customer creation flow.
    """
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    # Try exact, +-prefixed, and trailing 10-digit match.
    candidates = {phone, f"+{digits}", digits, digits[-10:]}
    for needle in candidates:
        match = Customer.objects.filter(phone__iexact=needle).first()
        if match is not None:
            return match
    return Customer.objects.filter(phone__icontains=digits[-10:]).first()


def record_webhook_envelope(
    *,
    raw_payload: Mapping[str, Any],
    signature_header: str,
    signature_verified: bool,
    event_id_hint: str = "",
    event_type: str = "",
) -> tuple[WhatsAppWebhookEvent, bool]:
    """Insert the webhook envelope row idempotently."""
    provider_event_id = (
        event_id_hint
        or _envelope_event_id(raw_payload)
        or f"webhook:{timezone.now().isoformat()}"
    )
    event, created = WhatsAppWebhookEvent.objects.get_or_create(
        provider_event_id=provider_event_id,
        defaults={
            "provider": "meta_cloud",
            "event_type": event_type or "messages",
            "signature_header": (signature_header or "")[:160],
            "signature_verified": signature_verified,
            "raw_payload": dict(raw_payload or {}),
            "processing_status": (
                WhatsAppWebhookEvent.ProcessingStatus.RECEIVED
                if signature_verified
                else WhatsAppWebhookEvent.ProcessingStatus.REJECTED
            ),
        },
    )
    return event, created


def _envelope_event_id(payload: Mapping[str, Any]) -> str:
    entries = payload.get("entry") or []
    if entries and isinstance(entries[0], dict):
        return f"entry:{entries[0].get('id') or ''}:{entries[0].get('time') or ''}"
    return ""


def send_freeform_text_message(
    *,
    customer: Customer,
    conversation: WhatsAppConversation,
    body: str,
    actor_role: str = "ai_chat",
    actor_agent: str = "ai_chat",
    ai_generated: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> WhatsAppMessage:
    """Phase 5C — send a freeform text reply through the configured provider.

    Used by the WhatsApp AI Chat Agent for non-template replies (after
    the locked greeting template has been delivered, the LLM continues
    in the customer's language with freeform messages).

    Hard rules (Phase 5C / Master Blueprint §26):
    - CAIO can never originate a customer-facing send (refused here).
    - No consent / opted-out → block + audit + raise.
    - Failed provider calls never mutate Order / Payment / Shipment.
    - Caller is responsible for Claim Vault + blocked-phrase validation;
      see :mod:`apps.whatsapp.ai_orchestration` for the reference path.
    """
    actor_agent_lower = (actor_agent or "").lower()
    if actor_agent_lower == CAIO_AGENT_TOKEN:
        _block(
            customer,
            action_key="whatsapp.freeform_reply",
            reason=(
                "CAIO can never originate a customer-facing WhatsApp "
                "send (Master Blueprint §26 #5)."
            ),
            block_reason="caio_no_send",
            extra={"actor_agent": actor_agent_lower},
        )
        raise WhatsAppServiceError(
            "CAIO cannot send WhatsApp messages.",
            http_status=403,
            block_reason="caio_no_send",
        )

    if not customer.phone:
        raise WhatsAppServiceError(
            "Customer has no phone number on record.",
            http_status=400,
            block_reason="missing_phone",
        )

    if not has_whatsapp_consent(customer):
        _block(
            customer,
            action_key="whatsapp.freeform_reply",
            reason="Customer has not opted in to WhatsApp.",
            block_reason="consent_missing",
        )
        raise WhatsAppServiceError(
            "Customer has not opted in to WhatsApp.",
            http_status=403,
            block_reason="consent_missing",
        )

    body_clean = (body or "").strip()
    if not body_clean:
        raise WhatsAppServiceError(
            "Empty body — refusing to send.",
            http_status=400,
            block_reason="empty_body",
        )

    provider = get_provider()
    started = timezone.now()
    idempotency = _build_idempotency_key(
        customer=customer,
        template=None,
        variables={"body": body_clean[:120]},
        action_key="whatsapp.freeform_reply",
    )

    with transaction.atomic():
        message = WhatsAppMessage.objects.create(
            id=next_id("WAM", WhatsAppMessage, base=100001),
            conversation=conversation,
            customer=customer,
            direction=WhatsAppMessage.Direction.OUTBOUND,
            status=WhatsAppMessage.Status.QUEUED,
            type=WhatsAppMessage.Type.TEXT,
            body=body_clean[:4096],
            template=None,
            template_variables={},
            ai_generated=bool(ai_generated),
            metadata={
                "actor_agent": actor_agent_lower,
                "actor_role": (actor_role or "").lower(),
                "trigger": "ai_chat",
                **dict(metadata or {}),
            },
            idempotency_key=idempotency,
            queued_at=started,
        )

    try:
        result = provider.send_text_message(
            to_phone=customer.phone,
            body=body_clean,
            idempotency_key=message.idempotency_key,
        )
    except ProviderError as exc:
        _record_send_log(
            message=message,
            attempt=1,
            provider_name=getattr(provider, "name", "unknown"),
            request_payload={"to": customer.phone, "type": "text"},
            response_status=0,
            response_payload={"error": str(exc), "code": exc.error_code},
            started_at=started,
            error_code=exc.error_code,
        )
        _mark_failed_locally(
            message,
            error_message=str(exc),
            error_code=exc.error_code or "provider_error",
            attempt=1,
        )
        raise WhatsAppServiceError(
            f"Provider send failed: {exc}",
            http_status=502,
            block_reason="provider_error",
        ) from exc

    completed = timezone.now()
    _record_send_log(
        message=message,
        attempt=1,
        provider_name=result.provider,
        request_payload=dict(result.request_payload),
        response_status=result.response_status,
        response_payload=dict(result.response_payload),
        started_at=started,
        completed_at=completed,
        latency_ms=result.latency_ms,
    )
    message.status = WhatsAppMessage.Status.SENT
    message.provider_message_id = result.provider_message_id
    message.attempt_count = 1
    message.sent_at = completed
    message.save(
        update_fields=[
            "status",
            "provider_message_id",
            "attempt_count",
            "sent_at",
            "updated_at",
        ]
    )
    write_event(
        kind="whatsapp.message.sent",
        text=(
            f"WhatsApp message {message.id} sent (freeform) · "
            f"provider_message_id={result.provider_message_id}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "message_id": message.id,
            "provider_message_id": result.provider_message_id,
            "conversation_id": conversation.id,
            "customer_id": customer.id,
            "provider": result.provider,
            "latency_ms": result.latency_ms,
            "ai_generated": True,
        },
    )
    return message


__all__ = (
    "QueuedMessage",
    "WhatsAppServiceError",
    "get_active_connection",
    "get_or_open_conversation",
    "get_provider",
    "handle_inbound_message_event",
    "handle_status_event",
    "provider_status",
    "queue_template_message",
    "record_webhook_envelope",
    "send_freeform_text_message",
    "send_queued_message",
)
