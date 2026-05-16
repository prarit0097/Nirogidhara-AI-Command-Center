"""Phase 10B — Targeted Payment Reminder Preparer.

Stage-aware wrapper that prepares a Phase 7E-Live-B real-customer
WhatsApp send gate pre-filled with payment-reminder template params.
Phase 10B itself NEVER sends — it only creates an optional CRM Customer
bridge row for Payment/Order phone fallback plus the controlled gate row.
The existing Phase 7E-Live-B approve / execute commands remain the only
path to a live send (full Director directive + structured UTC window +
explicit confirmation + runtime env prefix all stay mandatory).

Discovery notes (read from apps/whatsapp/phase7e_live_b_real_customer_send.py
on 2026-05-15 before writing this module):

- Gate model: ``Phase7ELiveBRealCustomerSendGate``
- Approved Phase 5A template names include ``"payment_reminder"``,
  so it is the right default for this workflow.
- ``prepare_gate(*, target_phone, target_customer_name,
  template_name, template_params, operator_name)`` returns a dict
  with ``ok``, ``gateId``, ``status``, ``templateName``,
  ``targetMasked``, ``blockers``, ``nextAction``.

Whether the Meta WABA carries an approved ``payment_reminder``
template at execute time is an operational question the Phase
7E-Live-B execute path checks separately. Phase 10B only sets the
template name; the gate refuses to execute against an unapproved
template name.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from apps._id import next_id
from apps.orders.models import Order
from apps.payments.models import Payment

from .service import list_pending_payments_drilldown


PHASE = "10B"
DEFAULT_TEMPLATE_NAME = "payment_reminder"
SANDBOX_PHONE_PLACEHOLDER = "0000000000"
logger = logging.getLogger(__name__)

ALLOWED_STAGES: frozenset[str] = frozenset(
    {
        Order.Stage.CONFIRMED.value,
        Order.Stage.ORDER_PUNCHED.value,
    }
)
WARN_STAGES: frozenset[str] = frozenset(
    {
        Order.Stage.INTERESTED.value,
        Order.Stage.CONFIRMATION_PENDING.value,
    }
)
BLOCKED_STAGES: frozenset[str] = frozenset(
    {
        Order.Stage.RTO.value,
        Order.Stage.OUT_FOR_DELIVERY.value,
        Order.Stage.CANCELLED.value,
        Order.Stage.DELIVERED.value,
        Order.Stage.DISPATCHED.value,
        Order.Stage.PAYMENT_LINK_SENT.value,
        Order.Stage.NEW_LEAD.value,
        # Phase 8C internal sandbox rows leak as ``internal_sandbox``;
        # treat as blocked so the operator can't accidentally target one.
        "internal_sandbox",
    }
)
PROCEEDABLE_PAYMENT_STATUSES: frozenset[str] = frozenset(
    {
        Payment.Status.PENDING.value,
        Payment.Status.PARTIAL.value,
    }
)


class PaymentReminderValidationError(Exception):
    """Raised when Phase 10B refuses to prepare a 7E-Live-B attempt."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class PreparedReminder:
    """Successful Phase 10B preparation result."""

    gate_id: int
    payment_id: str
    order_id: str
    stage: str
    template_name: str
    target_phone: str
    target_customer_name: str
    phone_source: str
    forced: bool
    warning_emitted: bool
    crm_customer_auto_created: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "phase": PHASE,
            "ok": True,
            "gate_id": self.gate_id,
            "payment_id": self.payment_id,
            "order_id": self.order_id,
            "stage": self.stage,
            "template_name": self.template_name,
            "target_phone_last4": (
                self.target_phone[-4:] if self.target_phone else ""
            ),
            "target_customer_name": self.target_customer_name,
            "phone_source": self.phone_source,
            "forced": self.forced,
            "warning_emitted": self.warning_emitted,
            "crm_customer_auto_created": self.crm_customer_auto_created,
            "next_action": (
                "Director runs: python manage.py "
                "approve_phase7e_live_b_real_customer_gate "
                f"--gate-id {self.gate_id} --director-signoff '<STRUCTURED>' "
                "--operator-name '<NAME>' "
                "--confirm-phase7e-live-b-real-customer-send"
            ),
        }


def _resolve_drilldown_row(payment_id: str) -> dict[str, Any] | None:
    """Reuse the Phase 10A fallback chain so phone resolution is shared."""
    rows = list_pending_payments_drilldown(
        include_partial=True, limit=None
    )
    for row in rows:
        if row.get("payment_id") == payment_id:
            return row
    return None


def _ensure_crm_customer(
    *,
    phone: str,
    name: str,
    phone_source: str,
    payment_id: str,
) -> tuple[bool, bool]:
    """Idempotently ensure a Customer exists for 7E-Live-B execute.

    Returns ``(existed_or_created, was_new)``. Unexpected create failures
    are non-fatal because Phase 10B must still prepare the controlled gate;
    the later execute gate remains the final blocker if the Customer is
    still absent.
    """
    if phone_source == "customer":
        return True, False

    try:
        from apps.audit.models import AuditEvent
        from apps.audit.signals import write_event
        from apps.crm.models import Customer

        _customer, created = Customer.objects.get_or_create(
            phone=phone,
            defaults={
                "id": next_id("CU", Customer, base=5100),
                "name": name,
                "state": "",
                "city": "",
                "language": "",
                "product_interest": "",
            },
        )
        if created:
            write_event(
                kind="phase10b.crm_customer.auto_created",
                text=(
                    "Phase 10B auto-created CRM customer for payment "
                    f"{payment_id} phone suffix {phone[-4:]}."
                ),
                tone=AuditEvent.Tone.INFO,
                payload={
                    "phase": PHASE,
                    "phone_last4": phone[-4:],
                    "name": name,
                    "phone_source": phone_source,
                    "payment_id": payment_id,
                },
            )
        return True, bool(created)
    except Exception as exc:  # noqa: BLE001 - non-fatal safety fallback
        logger.warning(
            "phase10b: crm customer auto-create failed for %s: %s",
            phone[-4:],
            exc,
        )
        return False, False


def build_payment_reminder_attempt(
    *,
    payment_id: str,
    template_id: str = DEFAULT_TEMPLATE_NAME,
    force: bool = False,
    operator_note: str = "",
    operator_name: str = "phase10b_preparer",
) -> PreparedReminder:
    """Validate + prepare a Phase 7E-Live-B gate. Never sends.

    Returns the prepared attempt on success; raises
    :class:`PaymentReminderValidationError` on refusal. The Phase
    7E-Live-B gate row IS created on success; sending still requires
    the existing Phase 7E-Live-B approve + execute commands with
    Director directive + structured UTC window + all env flags.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.signals import write_event

    payment_id = (payment_id or "").strip()
    if not payment_id:
        raise PaymentReminderValidationError(
            "payment_id_required",
            "payment_id is required.",
        )

    payment = Payment.objects.filter(pk=payment_id).first()
    if payment is None:
        raise PaymentReminderValidationError(
            "payment_not_found",
            f"Payment '{payment_id}' not found.",
        )
    if payment.status not in PROCEEDABLE_PAYMENT_STATUSES:
        raise PaymentReminderValidationError(
            "payment_status_not_proceedable",
            (
                f"Payment '{payment_id}' has status '{payment.status}'; "
                "only Pending or Partial payments may be prepared for a "
                "reminder."
            ),
        )
    if not payment.amount or payment.amount <= 0:
        raise PaymentReminderValidationError(
            "payment_amount_invalid",
            f"Payment '{payment_id}' has non-positive amount.",
        )
    if not (payment.payment_url or "").strip():
        raise PaymentReminderValidationError(
            "payment_url_missing",
            (
                f"Payment '{payment_id}' has no payment_url; a reminder "
                "without a link is useless."
            ),
        )

    order = Order.objects.filter(pk=payment.order_id).first()
    if order is None:
        raise PaymentReminderValidationError(
            "order_not_found",
            (
                f"Payment '{payment_id}' references order "
                f"'{payment.order_id}' which is missing."
            ),
        )
    stage = (order.stage or "").strip()
    warning_emitted = False
    if stage in BLOCKED_STAGES:
        raise PaymentReminderValidationError(
            "stage_blocked",
            (
                f"Order '{order.id}' is in stage '{stage}', which is "
                "blocked for payment-reminder sends. RTO / Delivered / "
                "Cancelled / sandbox orders never receive payment reminders."
            ),
        )
    if stage in WARN_STAGES and not force:
        raise PaymentReminderValidationError(
            "stage_requires_force",
            (
                f"Order '{order.id}' is in stage '{stage}'. Pass --force to "
                "proceed; this stage typically warrants a confirmation call "
                "before a payment reminder."
            ),
        )
    if stage not in ALLOWED_STAGES and stage not in WARN_STAGES:
        raise PaymentReminderValidationError(
            "stage_unknown",
            (
                f"Order '{order.id}' is in stage '{stage}', which is not in "
                "the allow/warn list. Refusing for safety."
            ),
        )
    if stage in WARN_STAGES:
        warning_emitted = True
        write_event(
            kind="phase10b.payment_reminder.warn_forced",
            text=(
                f"Phase 10B prepared payment reminder for "
                f"{payment.id} (order {order.id}) at warn stage "
                f"{stage} with --force."
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "phase": PHASE,
                "payment_id": payment.id,
                "order_id": order.id,
                "stage": stage,
                "operator_note": (operator_note or "")[:240],
            },
        )

    row = _resolve_drilldown_row(payment.id)
    if row is None:
        raise PaymentReminderValidationError(
            "drilldown_row_missing",
            (
                f"Payment '{payment.id}' could not be resolved via the "
                "Phase 10A drilldown service (joined order/customer "
                "lookup failed)."
            ),
        )
    target_phone = (row.get("customer_phone") or "").strip()
    phone_source = row.get("phone_source") or "none"
    if not target_phone:
        raise PaymentReminderValidationError(
            "target_phone_missing",
            (
                f"Payment '{payment.id}' has no resolvable phone across "
                "Payment / Order / Customer fallbacks."
            ),
        )
    if target_phone == SANDBOX_PHONE_PLACEHOLDER:
        raise PaymentReminderValidationError(
            "target_phone_sandbox_placeholder",
            (
                f"Payment '{payment.id}' resolves to the internal sandbox "
                f"placeholder '{SANDBOX_PHONE_PLACEHOLDER}'; refusing to "
                "prepare a real-customer reminder."
            ),
        )

    target_customer_name = (
        (order.customer_name or "").strip()
        or (payment.customer or "").strip()
        or (row.get("customer_name") or "").strip()
    )
    if not target_customer_name:
        raise PaymentReminderValidationError(
            "target_customer_name_missing",
            f"Payment '{payment.id}' has no resolvable customer name.",
        )

    _, crm_customer_auto_created = _ensure_crm_customer(
        phone=target_phone,
        name=target_customer_name,
        phone_source=phone_source,
        payment_id=payment.id,
    )

    template_name = (template_id or DEFAULT_TEMPLATE_NAME).strip()

    template_params = {
        "customer_name": target_customer_name,
        # Phase 10B Hotfix-2: nrg_payment_reminder body is "{{1}} {{2}}" with
        # variables_schema.order = [customer_name, context]. The previous
        # three-key dict ({customer_name, amount, payment_url}) triggered Meta
        # error #132001 because the {{2}} positional slot resolved to the
        # wrong key. Collapsed amount + payment_url into the single ``context``
        # string the template actually renders.
        "context": (
            f"ji, aapka ₹{payment.amount} ka payment pending hai. "
            f"Isi link se pay karein: "
            f"{(payment.payment_url or '').strip()}"
        ),
    }

    # Lazy import keeps the static-import surface of this module tiny
    # and guarantees the unit tests' patches still apply.
    from apps.whatsapp.phase7e_live_b_real_customer_send import (
        prepare_gate,
    )

    result = prepare_gate(
        target_phone=target_phone,
        target_customer_name=target_customer_name,
        template_name=template_name,
        template_params=template_params,
        operator_name=operator_name,
    )

    if not result.get("ok"):
        blockers = result.get("blockers") or []
        raise PaymentReminderValidationError(
            "phase7e_live_b_prepare_blocked",
            (
                "Phase 7E-Live-B prepare refused: "
                + ", ".join(blockers or ["unknown"])
            ),
        )

    gate_id = int(result.get("gateId") or 0)
    if gate_id <= 0:
        raise PaymentReminderValidationError(
            "phase7e_live_b_gate_id_missing",
            "Phase 7E-Live-B prepare returned no gate_id.",
        )

    # Defence-in-depth: the prepare path does NOT mutate Payment /
    # Order rows; we record the operator note as a separate audit row
    # so the Director can trace the Phase 10B intent later.
    write_event(
        kind="phase10b.payment_reminder.prepared",
        text=(
            f"Phase 10B prepared payment reminder gate {gate_id} for "
            f"payment {payment.id} (order {order.id}, stage {stage})."
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "phase": PHASE,
            "payment_id": payment.id,
            "order_id": order.id,
            "stage": stage,
            "template_name": template_name,
            "phone_source": phone_source,
            "crm_customer_auto_created": crm_customer_auto_created,
            "phase7e_live_b_gate_id": gate_id,
            "forced": bool(force),
            "operator_note": (operator_note or "")[:240],
        },
    )

    return PreparedReminder(
        gate_id=gate_id,
        payment_id=payment.id,
        order_id=order.id,
        stage=stage,
        template_name=template_name,
        target_phone=target_phone,
        target_customer_name=target_customer_name,
        phone_source=phone_source,
        forced=bool(force),
        warning_emitted=warning_emitted,
        crm_customer_auto_created=crm_customer_auto_created,
    )
