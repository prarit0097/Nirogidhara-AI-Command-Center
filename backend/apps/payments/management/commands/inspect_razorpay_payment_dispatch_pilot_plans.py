"""``python manage.py inspect_razorpay_payment_dispatch_pilot_plans --json``.

Phase 6S — read-only summary of pilot plan review rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_payment_dispatch_pilot_plan import (
    summarize_phase6s_payment_dispatch_pilot_plans,
)


class Command(BaseCommand):
    help = (
        "Phase 6S — read-only summary of Limited Internal Dispatch "
        "Pilot Plan review rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        limit = max(1, min(int(options.get("limit") or 25), 200))
        report = summarize_phase6s_payment_dispatch_pilot_plans(limit=limit)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        c = report["counts"]
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6S Limited Internal Dispatch Pilot Plan summary"
            )
        )
        self.stdout.write(f"  draft               : {c['draft']}")
        self.stdout.write(f"  pendingManualReview : {c['pendingManualReview']}")
        self.stdout.write(
            f"  approvedFor6T       : {c['approvedForFuturePhase6T']}"
        )
        self.stdout.write(f"  rejected            : {c['rejected']}")
        self.stdout.write(f"  archived            : {c['archived']}")
        self.stdout.write(f"  blocked             : {c['blocked']}")
        self.stdout.write("safety counters (must all be 0):")
        for key in (
            "pilotExecutionAllowedInPhase6S",
            "realOrderMutationWasMade",
            "realPaymentMutationWasMade",
            "shipmentMutationWasMade",
            "shipmentCreated",
            "awbCreated",
            "whatsAppMessageCreated",
            "whatsAppMessageQueued",
            "customerNotificationSent",
            "metaCloudCallAttempted",
            "delhiveryCallAttempted",
            "providerCallAttempted",
        ):
            self.stdout.write(f"  {key:32} : {c.get(key, 0)}")
