"""``python manage.py inspect_razorpay_webhook_handler_readiness --json``.

Phase 6M — read-only readiness inspector for the Razorpay test-mode
webhook handler. Never calls Razorpay, never mutates business
records, never returns the raw webhook secret.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_webhook_readiness import (
    get_razorpay_webhook_handler_readiness,
)


class Command(BaseCommand):
    help = (
        "Read-only Phase 6M Razorpay webhook handler readiness "
        "report. Reports env flags + registry counters. No external "
        "call. No raw secrets returned."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        report = get_razorpay_webhook_handler_readiness()
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6M Razorpay webhook handler readiness"
            )
        )
        for key in (
            "webhookTestModeEnabled",
            "webhookSecretPresent",
            "businessMutationEnabled",
            "customerNotificationEnabled",
            "storeRawPayload",
            "replayWindowSeconds",
            "eventCount",
            "verifiedEventCount",
            "duplicateEventCount",
            "blockedEventCount",
            "businessMutationCount",
            "customerNotificationCount",
            "rawSecretExposureCount",
            "fullPiiExposureCount",
            "safeToReceiveTestWebhooks",
            "safeToStartPhase6N",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<32}: {report.get(key)}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
