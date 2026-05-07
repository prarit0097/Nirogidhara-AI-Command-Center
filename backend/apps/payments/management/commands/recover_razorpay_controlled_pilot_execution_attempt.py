"""``python manage.py recover_razorpay_controlled_pilot_execution_attempt \\
    --idempotency-key <KEY> --provider-object-id <ORDER_ID> --json``.

Phase 7D - reconcile an orphan provider call. NEVER calls Razorpay
again; NEVER mutates Order / Payment / Shipment /
DiscountOfferLog / Customer / Lead; NEVER edits any ``.env*`` file.
Used only when the provider call succeeded but the local DB write
failed mid-call. Records the orphan ``provider_object_id`` on the
attempt row and writes a recovery audit row.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_controlled_pilot_execution import (
    recover_phase7d_razorpay_test_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 7D - reconcile an orphan provider call without re-"
        "calling Razorpay (no provider call; no business mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--idempotency-key",
            required=True,
            type=str,
        )
        parser.add_argument(
            "--provider-object-id",
            required=True,
            type=str,
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        idempotency_key = (options.get("idempotency_key") or "").strip()
        provider_object_id = (
            options.get("provider_object_id") or ""
        ).strip()
        if not idempotency_key:
            raise CommandError("--idempotency-key must be non-empty")
        if not provider_object_id:
            raise CommandError("--provider-object-id must be non-empty")
        report = recover_phase7d_razorpay_test_execution_attempt(
            idempotency_key=idempotency_key,
            provider_object_id=provider_object_id,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Attempt {attempt['id']} reconciled "
                    f"provider_object_id={attempt.get('providerObjectId')}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Recovery blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
