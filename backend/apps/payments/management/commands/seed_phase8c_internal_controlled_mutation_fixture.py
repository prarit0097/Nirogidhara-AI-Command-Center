"""``python manage.py seed_phase8c_internal_controlled_mutation_fixture [--apply] [--json]``.

Phase 8C-Hotfix-1 — seed exactly ONE safe internal sandbox
``Order`` + ``Payment`` pair for Phase 8C dry-run and controlled
mutation testing. CLI-only, idempotent, audit-logged. Defaults to
dry-run; pass ``--apply`` to actually create the rows.

Hard rules (matches the Phase 8C contract):

- NEVER calls Razorpay / Meta Cloud / Delhivery / Vapi.
- NEVER sends or queues WhatsApp.
- NEVER sends a customer notification.
- NEVER creates a ``Shipment`` / AWB / ``WorkflowStep`` /
  ``RescueAttempt`` / ``DiscountOfferLog``.
- NEVER creates real customer data — the seeded ``Order`` /
  ``Payment`` pair carries the explicit sandbox markers required by
  Phase 8C's ``_order_is_internal_sandbox`` /
  ``_payment_is_internal_sandbox`` safety proof:
  - ``Order.id == "phase8c-controlled-order-001"`` (contains
    ``phase8c-controlled-``).
  - ``Payment.id == "phase8c-controlled-payment-001"`` (contains
    ``phase8c-controlled-``).
  - ``Payment.raw_response["phase8c_sandbox"] is True``.
- NEVER edits any ``.env*`` file.
- Idempotent: a rerun reuses the existing pair and does not
  duplicate rows.
- Writes one ``phase8c.fixture.seeded`` / ``.dry_run`` /
  ``.blocked`` audit event per run.
"""
from __future__ import annotations

import json as _json
from typing import Any, Optional

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import RescueAttempt, Shipment, WorkflowStep
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)


_PHASE8C_FIXTURE_ORDER_ID = "phase8c-controlled-order-001"
_PHASE8C_FIXTURE_PAYMENT_ID = "phase8c-controlled-payment-001"
_PHASE8C_FIXTURE_GATEWAY_REF = "phase8c-controlled-gateway-ref-001"
_PHASE8C_FIXTURE_WARNING = (
    "Phase 8C-Hotfix-1 fixture: this is a CLI-only, idempotent, "
    "internal sandbox seed for Phase 8C dry-run testing only. The "
    "seeded Order + Payment pair carries explicit sandbox markers "
    "(`phase8c-controlled-` in both PKs + "
    "`raw_response.phase8c_sandbox=true`) so Phase 8C's runtime "
    "safety proof accepts it. No provider call, no WhatsApp, no "
    "customer notification, no Shipment / AWB, no .env edit."
)


def _business_row_counts() -> dict[str, int]:
    """Snapshot the protected tables. Phase 8C-Hotfix-1 is allowed
    to grow Order +1 and Payment +1 on the first ``--apply`` only;
    every other table must stay constant."""
    return {
        "order": Order.objects.count(),
        "payment": Payment.objects.count(),
        "shipment": Shipment.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "customer": Customer.objects.count(),
        "lead": Lead.objects.count(),
        "whatsapp_message": WhatsAppMessage.objects.count(),
        "whatsapp_lifecycle_event": (
            WhatsAppLifecycleEvent.objects.count()
        ),
        "whatsapp_handoff": WhatsAppHandoffToCall.objects.count(),
        "workflow_step": WorkflowStep.objects.count(),
        "rescue_attempt": RescueAttempt.objects.count(),
    }


def _lookup_existing() -> tuple[Optional[Order], Optional[Payment]]:
    order = Order.objects.filter(
        pk=_PHASE8C_FIXTURE_ORDER_ID
    ).first()
    payment = Payment.objects.filter(
        pk=_PHASE8C_FIXTURE_PAYMENT_ID
    ).first()
    return order, payment


def _proposed_order_payload() -> dict[str, Any]:
    return {
        "id": _PHASE8C_FIXTURE_ORDER_ID,
        "customer_name": "Phase 8C Internal Test",
        "phone": "0000000000",
        "product": "Phase 8C Internal Sandbox Product",
        "quantity": 1,
        "amount": 100,
        "discount_pct": 0,
        "advance_paid": False,
        "advance_amount": 0,
        "payment_status": Order.PaymentStatus.PENDING,
        "state": "internal_sandbox",
        "city": "internal_sandbox",
        "rto_risk": Order.RtoRisk.LOW,
        "rto_score": 0,
        "agent": "Phase8C",
        "stage": "internal_sandbox",
        "created_at_label": "Phase 8C Sandbox",
        "confirmation_checklist": {},
        "risk_reasons": [],
        "rescue_status": "",
        "confirmation_notes": (
            "phase8c-controlled-order internal sandbox fixture"
        ),
    }


def _proposed_payment_payload() -> dict[str, Any]:
    return {
        "id": _PHASE8C_FIXTURE_PAYMENT_ID,
        "order_id": _PHASE8C_FIXTURE_ORDER_ID,
        "customer": "Phase 8C Internal Test",
        "customer_email": "",
        "customer_phone": "0000000000",
        "amount": 100,
        "gateway": Payment.Gateway.RAZORPAY,
        "status": Payment.Status.PENDING,
        "type": Payment.Type.ADVANCE,
        "time": "Phase 8C Sandbox",
        "gateway_reference_id": _PHASE8C_FIXTURE_GATEWAY_REF,
        "payment_url": "",
        "raw_response": {
            "phase8c_sandbox": True,
            "internal_test": True,
            "created_by": (
                "seed_phase8c_internal_controlled_mutation_fixture"
            ),
            "real_customer": False,
            "provider_call": False,
        },
    }


def _safe_audit_payload(extra: dict[str, Any]) -> dict[str, Any]:
    forbidden = {
        "token",
        "phone",
        "customer_phone",
        "email",
        "address",
        "address_line",
        "card",
        "vpa",
        "upi",
        "bank_account",
        "wallet",
        "verify_token",
        "app_secret",
        "META_WA_TOKEN",
        "META_WA_APP_SECRET",
        "RAZORPAY_KEY_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
        "raw_payload",
        "raw_signature",
        "raw_secret",
    }
    safe: dict[str, Any] = {"phase": "8C", "fixture": "phase8c_hotfix_1"}
    for key, value in extra.items():
        if key in forbidden:
            continue
        safe[key] = value
    return safe


def _build_report(
    *,
    apply: bool,
    created_order: bool,
    created_payment: bool,
    reused_order: bool,
    reused_payment: bool,
    before: dict[str, int],
    after: dict[str, int],
    safe_for_phase8c: bool,
) -> dict[str, Any]:
    deltas: dict[str, int] = {}
    for key, count_before in before.items():
        count_after = after.get(key, count_before)
        if count_after != count_before:
            deltas[key] = count_after - count_before
    if apply:
        if created_order or created_payment:
            next_action = "run_phase8c_dry_run"
        else:
            next_action = "reused_existing_phase8c_fixture_run_dry_run"
    else:
        next_action = "rerun_with_apply_to_create_phase8c_fixture"
    return {
        "phase": "8C",
        "fixture": "phase8c_hotfix_1",
        "mode": "apply" if apply else "dry_run",
        "orderId": _PHASE8C_FIXTURE_ORDER_ID,
        "paymentId": _PHASE8C_FIXTURE_PAYMENT_ID,
        "createdOrder": bool(created_order),
        "createdPayment": bool(created_payment),
        "reusedOrder": bool(reused_order),
        "reusedPayment": bool(reused_payment),
        "beforeCounts": before,
        "afterCounts": after,
        "countDeltas": deltas,
        "safeForPhase8C": bool(safe_for_phase8c),
        "warnings": [_PHASE8C_FIXTURE_WARNING],
        "nextAction": next_action,
    }


class Command(BaseCommand):
    help = (
        "Phase 8C-Hotfix-1 — seed exactly ONE safe internal sandbox "
        "Order + Payment pair for Phase 8C dry-run and controlled "
        "mutation testing. CLI-only, idempotent, audit-logged. "
        "Defaults to dry-run; pass --apply to actually create the "
        "rows. NEVER calls a provider; NEVER sends WhatsApp; NEVER "
        "sends a customer notification; NEVER creates a Shipment / "
        "AWB / DiscountOfferLog; NEVER edits any .env file."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help=(
                "Actually create the rows. Without --apply this is "
                "a dry-run (no DB write)."
            ),
        )
        parser.add_argument("--json", action="store_true")

    # ------------------------------------------------------------------
    # Dry-run path
    # ------------------------------------------------------------------
    def _dry_run(self) -> dict[str, Any]:
        before = _business_row_counts()
        existing_order, existing_payment = _lookup_existing()
        after = before  # no write happened
        report = _build_report(
            apply=False,
            created_order=False,
            created_payment=False,
            reused_order=existing_order is not None,
            reused_payment=existing_payment is not None,
            before=before,
            after=after,
            safe_for_phase8c=(
                existing_order is not None
                and existing_payment is not None
            ),
        )
        write_event(
            kind="phase8c.fixture.dry_run",
            text=(
                "Phase 8C-Hotfix-1 fixture seed dry-run "
                f"order_present={existing_order is not None} "
                f"payment_present={existing_payment is not None}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload=_safe_audit_payload(
                {
                    "mode": "dry_run",
                    "order_present": existing_order is not None,
                    "payment_present": existing_payment is not None,
                    "order_id": _PHASE8C_FIXTURE_ORDER_ID,
                    "payment_id": _PHASE8C_FIXTURE_PAYMENT_ID,
                }
            ),
        )
        return report

    # ------------------------------------------------------------------
    # Apply path (idempotent)
    # ------------------------------------------------------------------
    def _apply(self) -> dict[str, Any]:
        before = _business_row_counts()
        try:
            with transaction.atomic():
                order = Order.objects.filter(
                    pk=_PHASE8C_FIXTURE_ORDER_ID
                ).first()
                created_order = False
                if order is None:
                    payload = _proposed_order_payload()
                    # Build via constructor so signal-driven org /
                    # branch auto-assignment fires on save (Phase 6D
                    # signal). The Phase 5D
                    # `apps.whatsapp.signals.post_save` listener
                    # auto-creates a `WhatsAppLifecycleEvent` row on
                    # Order.save() for observability only -- the
                    # actual `queue_template_message` is gated by
                    # env flags that are locked OFF.
                    order = Order(**payload)
                    order.save()
                    created_order = True
                payment = Payment.objects.filter(
                    pk=_PHASE8C_FIXTURE_PAYMENT_ID
                ).first()
                created_payment = False
                if payment is None:
                    payment_payload = _proposed_payment_payload()
                    payment = Payment(**payment_payload)
                    payment.save()
                    created_payment = True

                # Defensive invariant: only Order and Payment row
                # counts may have grown -- and at most by +1 each.
                # The lifecycle_event row is observability-only and
                # may grow by at most the same delta as Order. The
                # *truly* customer-facing tables (`whatsapp_message`,
                # `customer`, `lead`, `shipment`,
                # `discount_offer_log`, `workflow_step`,
                # `rescue_attempt`, `whatsapp_handoff`) must stay
                # at delta=0. If any guard fails the transaction
                # rolls back cleanly via the raised exception.
                mid_atomic = _business_row_counts()
                order_delta = (
                    mid_atomic.get("order", before["order"])
                    - before["order"]
                )
                unexpected_deltas: dict[str, int] = {}
                for key, count_before in before.items():
                    count_after = mid_atomic.get(key, count_before)
                    delta = count_after - count_before
                    if key == "order":
                        if delta not in (0, 1):
                            unexpected_deltas[key] = delta
                    elif key == "payment":
                        if delta not in (0, 1):
                            unexpected_deltas[key] = delta
                    elif key == "whatsapp_lifecycle_event":
                        if (
                            delta < 0
                            or delta > max(order_delta, 0)
                        ):
                            unexpected_deltas[key] = delta
                    elif delta != 0:
                        unexpected_deltas[key] = delta
                if unexpected_deltas:
                    write_event(
                        kind="phase8c.fixture.blocked",
                        text=(
                            "Phase 8C-Hotfix-1 fixture seed "
                            "blocked: unexpected row count drift."
                        ),
                        tone=AuditEvent.Tone.DANGER,
                        payload=_safe_audit_payload(
                            {
                                "mode": "apply",
                                "unexpected_row_count_deltas": (
                                    unexpected_deltas
                                ),
                                "before_counts": before,
                                "after_counts_mid_atomic": (
                                    mid_atomic
                                ),
                            }
                        ),
                    )
                    raise RuntimeError(
                        "Phase 8C-Hotfix-1 fixture seed blocked: "
                        f"unexpected row count drift "
                        f"{unexpected_deltas}"
                    )
        except RuntimeError as exc:
            raise SystemExit(str(exc))
        after = _business_row_counts()

        report = _build_report(
            apply=True,
            created_order=created_order,
            created_payment=created_payment,
            reused_order=(not created_order),
            reused_payment=(not created_payment),
            before=before,
            after=after,
            safe_for_phase8c=True,
        )
        write_event(
            kind="phase8c.fixture.seeded",
            text=(
                "Phase 8C-Hotfix-1 fixture seeded "
                f"order_created={created_order} "
                f"payment_created={created_payment}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload=_safe_audit_payload(
                {
                    "mode": "apply",
                    "order_id": _PHASE8C_FIXTURE_ORDER_ID,
                    "payment_id": _PHASE8C_FIXTURE_PAYMENT_ID,
                    "created_order": created_order,
                    "created_payment": created_payment,
                    "reused_order": not created_order,
                    "reused_payment": not created_payment,
                    "count_deltas": report["countDeltas"],
                }
            ),
        )
        return report

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def handle(self, *args, **options) -> None:
        apply = bool(options.get("apply"))
        if apply:
            report = self._apply()
        else:
            report = self._dry_run()

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8C-Hotfix-1 Internal Sandbox Fixture Seed"
            )
        )
        self.stdout.write(f"  mode             : {report['mode']}")
        self.stdout.write(
            f"  orderId          : {report['orderId']}"
        )
        self.stdout.write(
            f"  paymentId        : {report['paymentId']}"
        )
        self.stdout.write(
            f"  createdOrder     : {report['createdOrder']}"
        )
        self.stdout.write(
            f"  createdPayment   : {report['createdPayment']}"
        )
        self.stdout.write(
            f"  reusedOrder      : {report['reusedOrder']}"
        )
        self.stdout.write(
            f"  reusedPayment    : {report['reusedPayment']}"
        )
        self.stdout.write(
            f"  safeForPhase8C   : {report['safeForPhase8C']}"
        )
        self.stdout.write(
            f"  countDeltas      : {report['countDeltas']}"
        )
        self.stdout.write(
            f"  nextAction       : {report['nextAction']}"
        )
        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run only: pass --apply to actually create "
                    "the fixture rows."
                )
            )
