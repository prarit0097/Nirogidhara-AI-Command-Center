"""``python manage.py inspect_razorpay_webhook_events --json``.

Phase 6M — read-only event browser. Returns safe summaries only;
NEVER returns the raw payload, raw signature, or raw secret.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.models import RazorpayWebhookEvent


def _serialize(row: RazorpayWebhookEvent) -> dict:
    return {
        "id": row.id,
        "sourceEventId": row.source_event_id,
        "eventId": row.event_id,
        "eventName": row.event_name,
        "environment": row.environment,
        "signaturePresent": row.signature_present,
        "signatureValid": row.signature_valid,
        "replayWindowValid": row.replay_window_valid,
        "idempotencyStatus": row.idempotency_status,
        "processingStatus": row.processing_status,
        "processingMode": row.processing_mode,
        "providerOrderId": row.provider_order_id,
        "providerPaymentId": row.provider_payment_id,
        "providerRefundId": row.provider_refund_id,
        "amountPaise": row.amount_paise,
        "currency": row.currency,
        "paymentStatus": row.payment_status,
        "orderStatus": row.order_status,
        "businessMutationAttempted": row.business_mutation_attempted,
        "businessMutationWasMade": row.business_mutation_was_made,
        "customerNotificationAttempted": row.customer_notification_attempted,
        "customerNotificationSent": row.customer_notification_sent,
        "rawSecretExposed": row.raw_secret_exposed,
        "fullPiiExposed": row.full_pii_exposed,
        "duplicateCount": row.duplicate_count,
        "deniedReason": row.denied_reason,
        "blockers": list(row.blockers or []),
        "warnings": list(row.warnings or []),
        "scrubbedKeys": list(row.scrubbed_keys or []),
        "receivedAt": row.received_at.isoformat(),
    }


class Command(BaseCommand):
    help = (
        "List recent Razorpay webhook events (Phase 6M). Read-only. "
        "Never returns the raw payload."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=25,
            help="Limit (1..200, default 25).",
        )
        parser.add_argument("--event-name", default="", help="Optional event filter.")
        parser.add_argument("--status", default="", help="Optional status filter.")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        limit = int(options.get("limit") or 25)
        limit = max(1, min(limit, 200))
        qs = RazorpayWebhookEvent.objects.all().order_by("-received_at")
        event_name = (options.get("event_name") or "").strip()
        if event_name:
            qs = qs.filter(event_name=event_name)
        status_filter = (options.get("status") or "").strip()
        if status_filter:
            qs = qs.filter(processing_status=status_filter)
        rows = list(qs[:limit])
        report = {
            "limit": limit,
            "count": len(rows),
            "eventName": event_name,
            "status": status_filter,
            "events": [_serialize(row) for row in rows],
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Razorpay webhook events ({report['count']})"
            )
        )
        for row in rows:
            self.stdout.write(
                f"  {row.received_at.isoformat()} {row.event_name:<28} "
                f"{row.processing_status:<10} dup={row.duplicate_count} "
                f"sig={row.signature_valid} mut={row.business_mutation_was_made}"
            )
