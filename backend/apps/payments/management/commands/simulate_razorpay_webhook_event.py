"""``python manage.py simulate_razorpay_webhook_event --event payment.captured --json``.

Phase 6M — internal-only synthetic webhook simulator. Builds a
Razorpay-shaped payload, signs it with ``RAZORPAY_WEBHOOK_SECRET``,
and routes it through the same :func:`process_razorpay_webhook`
service the public endpoint uses. NEVER calls Razorpay, NEVER
mutates business records.
"""
from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_webhooks import (
    compute_razorpay_signature,
    process_razorpay_webhook,
)


_DEFAULT_AMOUNT_PAISE = 100
_DEFAULT_ORDER_ID = "order_Sks3KPf0vntKhf"  # Phase 6K-B artefact
_DEFAULT_PAYMENT_ID = "pay_test_phase6m"
_DEFAULT_REFUND_ID = "rfnd_test_phase6m"
_DEFAULT_PAYMENT_LINK_ID = "plink_test_phase6m"


def _build_payment_entity(
    *,
    payment_id: str,
    order_id: str,
    amount_paise: int,
    status: str,
) -> dict[str, Any]:
    return {
        "id": payment_id,
        "entity": "payment",
        "amount": amount_paise,
        "currency": "INR",
        "status": status,
        "order_id": order_id,
        "method": "card",
        "captured": status == "captured",
    }


def _build_order_entity(
    *,
    order_id: str,
    amount_paise: int,
    status: str,
) -> dict[str, Any]:
    return {
        "id": order_id,
        "entity": "order",
        "amount": amount_paise,
        "amount_paid": amount_paise if status == "paid" else 0,
        "amount_due": 0 if status == "paid" else amount_paise,
        "currency": "INR",
        "status": status,
        "receipt": "phase6k_internal_test_plan",
    }


def _build_refund_entity(
    *,
    refund_id: str,
    payment_id: str,
    amount_paise: int,
    status: str,
) -> dict[str, Any]:
    return {
        "id": refund_id,
        "entity": "refund",
        "amount": amount_paise,
        "currency": "INR",
        "payment_id": payment_id,
        "status": status,
    }


def _build_payment_link_entity(
    *,
    payment_link_id: str,
    order_id: str,
    amount_paise: int,
    status: str,
) -> dict[str, Any]:
    return {
        "id": payment_link_id,
        "entity": "payment_link",
        "amount": amount_paise,
        "amount_paid": amount_paise if status == "paid" else 0,
        "currency": "INR",
        "order_id": order_id,
        "status": status,
    }


def _build_payload(
    *,
    event_name: str,
    amount_paise: int,
    order_id: str,
    payment_id: str,
    refund_id: str,
    payment_link_id: str,
    created_at_epoch: int,
) -> dict[str, Any]:
    contains: list[str] = []
    payload_block: dict[str, Any] = {}
    if event_name in {"payment.authorized", "payment.captured", "payment.failed"}:
        contains.append("payment")
        payload_block["payment"] = {
            "entity": _build_payment_entity(
                payment_id=payment_id,
                order_id=order_id,
                amount_paise=amount_paise,
                status="captured" if event_name == "payment.captured" else (
                    "authorized" if event_name == "payment.authorized" else "failed"
                ),
            )
        }
    if event_name == "order.paid":
        contains.append("order")
        contains.append("payment")
        payload_block["order"] = {
            "entity": _build_order_entity(
                order_id=order_id,
                amount_paise=amount_paise,
                status="paid",
            )
        }
        payload_block["payment"] = {
            "entity": _build_payment_entity(
                payment_id=payment_id,
                order_id=order_id,
                amount_paise=amount_paise,
                status="captured",
            )
        }
    if event_name in {"refund.created", "refund.processed"}:
        contains.append("refund")
        payload_block["refund"] = {
            "entity": _build_refund_entity(
                refund_id=refund_id,
                payment_id=payment_id,
                amount_paise=amount_paise,
                status="processed" if event_name == "refund.processed" else "created",
            )
        }
        payload_block["payment"] = {
            "entity": _build_payment_entity(
                payment_id=payment_id,
                order_id=order_id,
                amount_paise=amount_paise,
                status="refunded",
            )
        }
    if event_name in {
        "payment_link.paid",
        "payment_link.cancelled",
        "payment_link.expired",
    }:
        link_status = (
            "paid"
            if event_name == "payment_link.paid"
            else "cancelled"
            if event_name == "payment_link.cancelled"
            else "expired"
        )
        contains.append("payment_link")
        payload_block["payment_link"] = {
            "entity": _build_payment_link_entity(
                payment_link_id=payment_link_id,
                order_id=order_id,
                amount_paise=amount_paise,
                status=link_status,
            )
        }
    return {
        "entity": "event",
        "account_id": "acc_test_phase6m",
        "event": event_name,
        "contains": contains or [event_name.split(".", 1)[0]],
        "payload": payload_block,
        "created_at": created_at_epoch,
    }


class Command(BaseCommand):
    help = (
        "Simulate ONE Razorpay test-mode webhook event end-to-end "
        "through the Phase 6M handler. Never calls Razorpay; never "
        "mutates business records."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--event",
            required=True,
            help=(
                "Event name (payment.captured, order.paid, "
                "refund.processed, payment_link.paid, etc)."
            ),
        )
        parser.add_argument(
            "--event-id",
            default="",
            help="Optional X-Razorpay-Event-Id; auto-generated when omitted.",
        )
        parser.add_argument(
            "--amount-paise",
            type=int,
            default=_DEFAULT_AMOUNT_PAISE,
            help="Amount in paise (default 100).",
        )
        parser.add_argument(
            "--order-id",
            default=_DEFAULT_ORDER_ID,
            help=f"Provider order id (default {_DEFAULT_ORDER_ID}).",
        )
        parser.add_argument(
            "--payment-id",
            default=_DEFAULT_PAYMENT_ID,
            help=f"Provider payment id (default {_DEFAULT_PAYMENT_ID}).",
        )
        parser.add_argument(
            "--refund-id",
            default=_DEFAULT_REFUND_ID,
            help=f"Provider refund id (default {_DEFAULT_REFUND_ID}).",
        )
        parser.add_argument(
            "--payment-link-id",
            default=_DEFAULT_PAYMENT_LINK_ID,
            help=f"Provider payment link id (default {_DEFAULT_PAYMENT_LINK_ID}).",
        )
        parser.add_argument(
            "--created-at",
            default="",
            help="Optional ISO timestamp; auto-now when omitted.",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "") or ""
        if not secret:
            raise CommandError(
                "RAZORPAY_WEBHOOK_SECRET env not set; cannot sign synthetic event."
            )

        created_at_iso = options.get("created_at") or ""
        if created_at_iso:
            try:
                created_at_dt = datetime.fromisoformat(created_at_iso)
            except ValueError as exc:
                raise CommandError(f"Invalid --created-at: {exc}") from exc
            if created_at_dt.tzinfo is None:
                created_at_dt = created_at_dt.replace(tzinfo=timezone.utc)
        else:
            created_at_dt = datetime.now(tz=timezone.utc)
        created_at_epoch = int(created_at_dt.timestamp())

        event_id = options.get("event_id") or f"evt_test_{uuid4().hex[:16]}"
        payload = _build_payload(
            event_name=options["event"],
            amount_paise=int(options.get("amount_paise") or _DEFAULT_AMOUNT_PAISE),
            order_id=options.get("order_id") or _DEFAULT_ORDER_ID,
            payment_id=options.get("payment_id") or _DEFAULT_PAYMENT_ID,
            refund_id=options.get("refund_id") or _DEFAULT_REFUND_ID,
            payment_link_id=(
                options.get("payment_link_id") or _DEFAULT_PAYMENT_LINK_ID
            ),
            created_at_epoch=created_at_epoch,
        )

        body = _json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = compute_razorpay_signature(body, secret)
        headers = {
            "x-razorpay-signature": signature,
            "x-razorpay-event-id": event_id,
            "content-type": "application/json",
            "user-agent": "razorpay-simulator/phase6m",
        }
        result = process_razorpay_webhook(
            raw_body=body,
            headers=headers,
            request_meta={"source": "manage.py simulate_razorpay_webhook_event"},
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(result, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Razorpay webhook simulation: {options['event']}"
            )
        )
        for key in (
            "passed",
            "statusCode",
            "eventName",
            "sourceEventId",
            "signatureValid",
            "idempotencyStatus",
            "processingStatus",
            "businessMutationWasMade",
            "customerNotificationSent",
            "providerCallAttempted",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<28}: {result.get(key)}")
        if result.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in result["blockers"]:
                self.stdout.write(f"  - {blocker}")
