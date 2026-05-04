"""``python manage.py purge_razorpay_webhook_test_events [--apply] --json``.

Phase 6M — defaults to dry-run. Refuses to delete any row that
declares a business mutation or customer notification was made,
even if a future row is mutated to claim so.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.models import RazorpayWebhookEvent


class Command(BaseCommand):
    help = (
        "Purge Phase 6M Razorpay test webhook events. Defaults to "
        "dry-run; refuses to delete rows that declare a business "
        "mutation or customer notification."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Actually delete the events. Defaults to dry-run.",
        )
        parser.add_argument(
            "--event-name",
            default="",
            help="Optional event filter.",
        )
        parser.add_argument(
            "--keep-last",
            type=int,
            default=0,
            help="Keep the most recent N events; delete only the older ones.",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        qs = RazorpayWebhookEvent.objects.filter(
            environment=RazorpayWebhookEvent.Environment.TEST,
            business_mutation_was_made=False,
            customer_notification_sent=False,
        )
        event_name = (options.get("event_name") or "").strip()
        if event_name:
            qs = qs.filter(event_name=event_name)
        candidates = list(qs.order_by("-received_at"))
        keep_last = max(0, int(options.get("keep_last") or 0))
        if keep_last:
            candidates = candidates[keep_last:]
        candidate_ids = [row.id for row in candidates]
        apply = bool(options.get("apply"))
        deleted = 0
        if apply and candidate_ids:
            deleted, _ = RazorpayWebhookEvent.objects.filter(
                id__in=candidate_ids,
                business_mutation_was_made=False,
                customer_notification_sent=False,
            ).delete()
            # ``deleted`` from queryset.delete() returns total rows
            # deleted across all tables; convert to int for safety.
            deleted = int(deleted)
        report = {
            "passed": True,
            "dryRun": not apply,
            "eventNameFilter": event_name,
            "keepLast": keep_last,
            "candidateCount": len(candidate_ids),
            "deletedCount": deleted if apply else 0,
            "businessMutationProtectedCount": (
                RazorpayWebhookEvent.objects.filter(
                    business_mutation_was_made=True
                ).count()
            ),
            "customerNotificationProtectedCount": (
                RazorpayWebhookEvent.objects.filter(
                    customer_notification_sent=True
                ).count()
            ),
            "nextAction": (
                "rerun_with_apply_to_purge"
                if not apply and candidate_ids
                else "no_op"
            ),
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Razorpay webhook test purge"
                + (" [DRY RUN]" if not apply else "")
            )
        )
        for key in (
            "candidateCount",
            "deletedCount",
            "businessMutationProtectedCount",
            "customerNotificationProtectedCount",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<32}: {report.get(key)}")
