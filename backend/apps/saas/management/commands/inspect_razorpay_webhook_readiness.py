"""``python manage.py inspect_razorpay_webhook_readiness --json``.

Phase 6L — read-only env + Phase 6K artefact sanity check that tells
the operator whether the Razorpay webhook readiness plan can be
authored.

Reports:

- Razorpay key mode (test / live / unknown / missing) — masked id only.
- ``RAZORPAY_WEBHOOK_SECRET`` presence (boolean only — never the
  value).
- Latest Phase 6K succeeded execution id + provider object id +
  rollback status.
- Typed ``nextAction``.

NEVER calls Razorpay. NEVER returns the raw webhook secret value.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.razorpay_audit_review import (
    inspect_razorpay_webhook_readiness,
)


class Command(BaseCommand):
    help = (
        "Read-only Phase 6L Razorpay webhook readiness check. "
        "Reports presence only; raw secrets never returned."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        report = inspect_razorpay_webhook_readiness()
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6L Razorpay webhook readiness"
            )
        )
        for key in (
            "razorpayKeyMode",
            "razorpayKeyIdMasked",
            "razorpayKeyIdPresent",
            "razorpayKeySecretPresent",
            "razorpayWebhookSecretPresent",
            "envFlagEnabled",
            "isTestKey",
            "isLiveKey",
            "latestSucceededExecutionId",
            "latestSucceededProviderObjectId",
            "latestSucceededRollbackStatus",
            "phase6KSucceededExecutionCount",
            "safeToPlanWebhookReadiness",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<32}: {report.get(key)}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
