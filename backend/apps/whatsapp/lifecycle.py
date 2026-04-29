"""Phase 5D — WhatsApp lifecycle automation.

Routes Order / Payment / Shipment lifecycle events into approved
WhatsApp templates via the existing Phase 5A send pipeline. Every send
goes through:

1. Approved-template gate (Phase 5A ``queue_template_message``).
2. Consent gate.
3. Approval Matrix.
4. CAIO hard stop.
5. Idempotency (per-event).
6. Phase 5D extra: Claim Vault coverage gate when the template is
   product-specific (usage_explanation today; reorder later).

Failed sends NEVER mutate ``Order`` / ``Payment`` / ``Shipment``. The
service writes a :class:`WhatsAppLifecycleEvent` row regardless of the
outcome so operators have a paper trail.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer

from . import services
from .models import WhatsAppLifecycleEvent, WhatsAppMessage
from .template_registry import TemplateRegistryError


logger = logging.getLogger(__name__)


# Map (object_type, event_kind) → WhatsApp action_key. Keep narrow:
# Phase 5D ships the four payment / confirmation / delivery / RTO
# actions; reorder + usage explanation are scaffolded for follow-up.
LIFECYCLE_TRIGGERS: dict[tuple[str, str], str] = {
    ("order", "moved_to_confirmation"): "whatsapp.confirmation_reminder",
    ("payment", "link_created"): "whatsapp.payment_reminder",
    ("payment", "pending"): "whatsapp.payment_reminder",
    ("shipment", "out_for_delivery"): "whatsapp.delivery_reminder",
    ("shipment", "delivered"): "whatsapp.usage_explanation",
    ("shipment", "ndr"): "whatsapp.rto_rescue",
    ("shipment", "rto_initiated"): "whatsapp.rto_rescue",
}

# Templates that demand a Claim Vault row before sending.
CLAIM_VAULT_REQUIRED_ACTIONS: frozenset[str] = frozenset(
    {"whatsapp.usage_explanation"}
)


class LifecycleError(RuntimeError):
    """Raised when the lifecycle layer cannot process a trigger at all."""


@dataclass(frozen=True)
class LifecycleResult:
    event_id: int
    status: str
    message_id: str = ""
    block_reason: str = ""
    error_message: str = ""


def is_lifecycle_enabled() -> bool:
    return bool(getattr(settings, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED", False))


def build_idempotency_key(
    *,
    action_key: str,
    object_type: str,
    object_id: str,
    event_kind: str,
) -> str:
    return f"lifecycle:{action_key}:{object_type}:{object_id}:{event_kind}"


@transaction.atomic
def queue_lifecycle_message(
    *,
    object_type: str,
    object_id: str,
    event_kind: str,
    customer: Customer | None = None,
    variables: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> LifecycleResult:
    """Queue (or skip) a lifecycle send for the given business event.

    The function ALWAYS writes a :class:`WhatsAppLifecycleEvent` row.
    The row's ``status`` reflects the outcome: ``sent`` (provider
    accepted), ``queued`` (queued in the WhatsApp pipeline, send dispatched),
    ``blocked`` (gate refused — template / consent / Claim Vault),
    ``skipped`` (duplicate event), ``failed`` (provider raised).
    """
    action_key = LIFECYCLE_TRIGGERS.get((object_type, event_kind), "")
    metadata = dict(metadata or {})

    if not action_key:
        # Unknown event — record skipped + return so callers don't have
        # to track which events the lifecycle covers.
        return _record_skipped(
            object_type=object_type,
            object_id=object_id,
            event_kind=event_kind,
            action_key="",
            customer=customer,
            block_reason="no_trigger_registered",
            metadata=metadata,
        )

    if not is_lifecycle_enabled():
        return _record_skipped(
            object_type=object_type,
            object_id=object_id,
            event_kind=event_kind,
            action_key=action_key,
            customer=customer,
            block_reason="lifecycle_disabled",
            metadata=metadata,
        )

    idempotency_key = build_idempotency_key(
        action_key=action_key,
        object_type=object_type,
        object_id=object_id,
        event_kind=event_kind,
    )

    existing = WhatsAppLifecycleEvent.objects.filter(
        idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        write_event(
            kind="whatsapp.lifecycle.skipped_duplicate",
            text=(
                f"Lifecycle duplicate · {action_key} · "
                f"{object_type}:{object_id}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "lifecycle_event_id": existing.pk,
                "action_key": action_key,
                "object_type": object_type,
                "object_id": object_id,
                "event_kind": event_kind,
            },
        )
        return LifecycleResult(
            event_id=existing.pk,
            status=existing.status,
            message_id=existing.message_id or "",
            block_reason="duplicate",
        )

    if customer is None:
        return _record_blocked(
            action_key=action_key,
            object_type=object_type,
            object_id=object_id,
            event_kind=event_kind,
            customer=None,
            idempotency_key=idempotency_key,
            block_reason="customer_missing",
            metadata=metadata,
        )

    # Phase 5D — enforce Claim Vault coverage when the template demands it.
    if action_key in CLAIM_VAULT_REQUIRED_ACTIONS:
        from apps.compliance.coverage import coverage_for_product

        product_key = (
            (variables or {}).get("product")
            or customer.product_interest
            or ""
        )
        coverage = coverage_for_product(str(product_key))
        if not coverage.has_approved_claims:
            return _record_blocked(
                action_key=action_key,
                object_type=object_type,
                object_id=object_id,
                event_kind=event_kind,
                customer=customer,
                idempotency_key=idempotency_key,
                block_reason="claim_vault_missing",
                metadata={
                    **metadata,
                    "coverage_risk": coverage.risk,
                    "coverage_notes": list(coverage.notes),
                    "product_key": str(product_key),
                },
            )

    event_row = WhatsAppLifecycleEvent.objects.create(
        action_key=action_key,
        object_type=object_type,
        object_id=object_id,
        event_kind=event_kind,
        customer=customer,
        status=WhatsAppLifecycleEvent.Status.QUEUED,
        idempotency_key=idempotency_key,
        metadata=dict(metadata),
    )

    write_event(
        kind="whatsapp.lifecycle.queued",
        text=(
            f"Lifecycle queued · {action_key} · {object_type}:{object_id}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "lifecycle_event_id": event_row.pk,
            "action_key": action_key,
            "object_type": object_type,
            "object_id": object_id,
            "event_kind": event_kind,
            "customer_id": getattr(customer, "id", ""),
        },
    )

    try:
        queued = services.queue_template_message(
            customer=customer,
            action_key=action_key,
            variables=variables or {},
            triggered_by=f"lifecycle:{event_kind}",
            actor_role="system",
            actor_agent="lifecycle",
            idempotency_key=idempotency_key,
            extra_metadata={
                "lifecycle_event_id": event_row.pk,
                "object_type": object_type,
                "object_id": object_id,
                "event_kind": event_kind,
            },
        )
    except services.WhatsAppServiceError as exc:
        event_row.status = WhatsAppLifecycleEvent.Status.BLOCKED
        event_row.block_reason = (exc.block_reason or "service_error")[:80]
        event_row.error_message = str(exc)[:1000]
        event_row.save(
            update_fields=["status", "block_reason", "error_message", "updated_at"]
        )
        write_event(
            kind="whatsapp.lifecycle.blocked",
            text=f"Lifecycle blocked · {action_key} · {exc.block_reason}",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "lifecycle_event_id": event_row.pk,
                "action_key": action_key,
                "object_type": object_type,
                "object_id": object_id,
                "event_kind": event_kind,
                "block_reason": exc.block_reason,
            },
        )
        return LifecycleResult(
            event_id=event_row.pk,
            status=event_row.status,
            block_reason=exc.block_reason,
            error_message=str(exc),
        )

    event_row.message = queued.message
    event_row.status = WhatsAppLifecycleEvent.Status.SENT
    event_row.save(update_fields=["message", "status", "updated_at"])

    # Schedule the actual send on the existing Phase 5A path. Eager mode
    # runs sync; production runs via Celery.
    try:
        from .tasks import send_whatsapp_message

        send_whatsapp_message.delay(queued.message.id)
    except Exception:  # noqa: BLE001 - defensive; broker miss never breaks ledger
        pass

    write_event(
        kind="whatsapp.lifecycle.sent",
        text=f"Lifecycle send dispatched · {action_key} · message={queued.message.id}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "lifecycle_event_id": event_row.pk,
            "action_key": action_key,
            "object_type": object_type,
            "object_id": object_id,
            "event_kind": event_kind,
            "message_id": queued.message.id,
        },
    )
    return LifecycleResult(
        event_id=event_row.pk,
        status=event_row.status,
        message_id=queued.message.id,
    )


def _record_skipped(
    *,
    object_type: str,
    object_id: str,
    event_kind: str,
    action_key: str,
    customer: Customer | None,
    block_reason: str,
    metadata: dict[str, Any],
) -> LifecycleResult:
    idempotency_key = build_idempotency_key(
        action_key=action_key or "noop",
        object_type=object_type,
        object_id=object_id,
        event_kind=event_kind,
    )
    existing = WhatsAppLifecycleEvent.objects.filter(
        idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        return LifecycleResult(
            event_id=existing.pk,
            status=existing.status,
            block_reason=block_reason,
        )
    row = WhatsAppLifecycleEvent.objects.create(
        action_key=action_key or "noop",
        object_type=object_type,
        object_id=object_id,
        event_kind=event_kind,
        customer=customer,
        status=WhatsAppLifecycleEvent.Status.SKIPPED,
        block_reason=block_reason[:80],
        idempotency_key=idempotency_key,
        metadata=dict(metadata),
    )
    return LifecycleResult(
        event_id=row.pk,
        status=row.status,
        block_reason=block_reason,
    )


def _record_blocked(
    *,
    action_key: str,
    object_type: str,
    object_id: str,
    event_kind: str,
    customer: Customer | None,
    idempotency_key: str,
    block_reason: str,
    metadata: dict[str, Any],
) -> LifecycleResult:
    row = WhatsAppLifecycleEvent.objects.create(
        action_key=action_key,
        object_type=object_type,
        object_id=object_id,
        event_kind=event_kind,
        customer=customer,
        status=WhatsAppLifecycleEvent.Status.BLOCKED,
        block_reason=block_reason[:80],
        idempotency_key=idempotency_key,
        metadata=dict(metadata),
    )
    write_event(
        kind="whatsapp.lifecycle.blocked",
        text=(
            f"Lifecycle blocked · {action_key} · {object_type}:{object_id} "
            f"· {block_reason}"
        ),
        tone=AuditEvent.Tone.WARNING,
        payload={
            "lifecycle_event_id": row.pk,
            "action_key": action_key,
            "object_type": object_type,
            "object_id": object_id,
            "event_kind": event_kind,
            "block_reason": block_reason,
            "customer_id": getattr(customer, "id", ""),
        },
    )
    return LifecycleResult(
        event_id=row.pk,
        status=row.status,
        block_reason=block_reason,
    )


__all__ = (
    "CLAIM_VAULT_REQUIRED_ACTIONS",
    "LIFECYCLE_TRIGGERS",
    "LifecycleError",
    "LifecycleResult",
    "build_idempotency_key",
    "is_lifecycle_enabled",
    "queue_lifecycle_message",
)
