"""``python manage.py inspect_razorpay_payment_dispatch_readiness_gates --json``.

Phase 6R — read-only summary of dispatch readiness gate review rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_payment_dispatch_readiness import (
    summarize_phase6r_payment_dispatch_readiness_gates,
)


class Command(BaseCommand):
    help = (
        "Phase 6R — read-only summary of Payment → WhatsApp / Courier "
        "dispatch readiness gate review rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        limit = max(1, min(int(options.get("limit") or 25), 200))
        report = summarize_phase6r_payment_dispatch_readiness_gates(limit=limit)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        c = report["counts"]
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6R dispatch readiness gate summary"
            )
        )
        self.stdout.write(f"  draft               : {c['draft']}")
        self.stdout.write(f"  pendingManualReview : {c['pendingManualReview']}")
        self.stdout.write(
            f"  approvedFor6S       : {c['approvedForFuturePhase6S']}"
        )
        self.stdout.write(f"  rejected            : {c['rejected']}")
        self.stdout.write(f"  archived            : {c['archived']}")
        self.stdout.write(f"  blocked             : {c['blocked']}")
        self.stdout.write("safety counters (must all be 0):")
        for key in (
            "realOrderMutationWasMade",
            "realPaymentMutationWasMade",
            "shipmentMutationWasMade",
            "shipmentCreated",
            "whatsAppMessageCreated",
            "whatsAppMessageQueued",
            "customerNotificationSent",
            "metaCloudCallAttempted",
            "delhiveryCallAttempted",
            "providerCallAttempted",
        ):
            self.stdout.write(f"  {key:30} : {c.get(key, 0)}")
