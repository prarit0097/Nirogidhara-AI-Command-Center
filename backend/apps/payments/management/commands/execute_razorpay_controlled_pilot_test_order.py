"""``python manage.py execute_razorpay_controlled_pilot_test_order \\
    --attempt-id <ID> \\
    --confirm-one-shot-test-execution \\
    --director-signoff "..." \\
    --json``.

Phase 7D - **CLI-only one-shot Razorpay TEST order execution**. This
is the only callable in the Phase 7D layer that may issue a real
Razorpay TEST API request, and it refuses unless every safety gate
is green:

* ``PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED=true`` AND
  ``PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION=true`` AND
  ``PHASE7D_ALLOW_RAZORPAY_TEST_ORDER=true``.
* The attempt status is ``approved_for_one_shot_run``.
* The director sign-off text is non-empty AND mentions the exact
  Phase 7B gate id of the source.
* ``RAZORPAY_KEY_ID`` starts with ``rzp_test_`` (live keys refused).
* The shared kill switch is enabled.
* Locked amount = 100 paise / INR.
* Source chain Phase 7B -> 6T -> 6S -> 6R -> 6Q -> 6P -> 6O -> 6M
  is green.
* No prior provider call has been recorded for this attempt.

It NEVER creates a payment link; NEVER captures a payment; NEVER
sends a customer notification; NEVER calls WhatsApp / Meta Cloud /
Delhivery / Vapi; NEVER mutates Order / Payment / Shipment /
DiscountOfferLog / Customer / Lead; NEVER edits any ``.env*`` file.
Single-shot: if the SDK call fails, the attempt is marked failed
and cannot be re-executed.

Director approval text required at runtime via
``--director-signoff``.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_controlled_pilot_execution import (
    execute_phase7d_razorpay_test_order,
)


class Command(BaseCommand):
    help = (
        "Phase 7D - one-shot Razorpay TEST order execution (CLI "
        "only). Refuses unless every safety flag is true and the "
        "director sign-off mentions the source Phase 7B gate id. "
        "Never creates a payment link, never captures, never sends "
        "a customer notification, never mutates business tables."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument(
            "--confirm-one-shot-test-execution",
            action="store_true",
            help=(
                "Required gate flag. Without it, this command "
                "refuses to dispatch."
            ),
        )
        parser.add_argument(
            "--director-signoff",
            default="",
            type=str,
            help=(
                "Director sign-off text. Must be non-empty AND must "
                "mention the exact Phase 7B gate id of the source."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError("--attempt-id must be a positive integer")
        if not options.get("confirm_one_shot_test_execution"):
            raise CommandError(
                "Refusing to dispatch without "
                "--confirm-one-shot-test-execution. This is the "
                "Phase 7D one-shot Razorpay TEST execution gate."
            )
        signoff = (options.get("director_signoff") or "").strip()
        if not signoff:
            raise CommandError(
                "--director-signoff must be a non-empty string and "
                "must mention the exact Phase 7B gate id of the "
                "attempt."
            )
        report = execute_phase7d_razorpay_test_order(
            attempt_id,
            confirmed_by=None,
            director_signoff=signoff,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7D test order executed "
                    f"attempt_id={attempt['id']} "
                    f"provider_object_id={attempt.get('providerObjectId')} "
                    f"status={attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Execution blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
