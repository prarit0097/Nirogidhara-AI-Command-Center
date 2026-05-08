"""``python manage.py execute_delhivery_courier_one_shot \\
    --attempt-id <ID> \\
    --confirm-one-shot-courier-execution \\
    --director-signoff "..." \\
    --operator-name "..." \\
    --mode-acknowledgement "mock|test" \\
    --rollback-record-only-acknowledged \\
    --json``.

Phase 7G - **CLI-only one-shot Delhivery TEST/MOCK courier execution**.
This is the only callable in the Phase 7G layer that may issue a
real Delhivery TEST/MOCK API request, and it refuses unless every
safety gate is green:

* ``PHASE7G_COURIER_EXECUTION_ENABLED=true`` AND
  ``PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION=true`` AND
  ``PHASE7G_ALLOW_DELHIVERY_TEST_AWB=true``.
* The attempt status is
  ``approved_for_one_shot_courier_test_or_live_review``.
* The director sign-off text is non-empty AND mentions the source
  Phase 7F gate id.
* ``--operator-name`` is a non-empty string.
* ``--mode-acknowledgement`` matches the live ``DELHIVERY_MODE``
  (must be ``mock`` or ``test``; live is refused).
* ``--rollback-record-only-acknowledged`` is set (operator
  acknowledges that rollback is record-only and never calls
  Delhivery cancel).
* The shared kill switch is enabled.
* The full source chain Phase 7F -> 7E -> 7D -> 7B -> 6T is green.
* No prior provider call has been recorded for this attempt.

It NEVER creates a Shipment row; NEVER books a courier pickup
separately; NEVER generates / prints a courier label; NEVER sends
or queues WhatsApp; NEVER calls Meta Cloud / Razorpay / Vapi;
NEVER sends a customer notification; NEVER mutates real Order /
Payment / Customer / Lead / DiscountOfferLog rows; NEVER edits
any ``.env*`` file. Single-shot: if the underlying call fails,
the attempt is marked failed and cannot be re-executed.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_execution import (
    PHASE_7G_ALLOWED_DELHIVERY_MODES,
    execute_phase7g_courier_one_shot,
)


class Command(BaseCommand):
    help = (
        "Phase 7G - one-shot Delhivery TEST/MOCK courier execution "
        "(CLI only). Refuses unless every safety flag is true and "
        "the director sign-off mentions the source Phase 7F gate id. "
        "Never creates a Shipment, never books a pickup separately, "
        "never generates a label, never sends WhatsApp, never "
        "notifies the customer, never mutates business tables."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument(
            "--confirm-one-shot-courier-execution",
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
                "mention the source Phase 7F gate id."
            ),
        )
        parser.add_argument(
            "--operator-name",
            default="",
            type=str,
            help="Required non-empty operator name (e.g. 'Prarit Sidana').",
        )
        parser.add_argument(
            "--mode-acknowledgement",
            default="",
            type=str,
            help=(
                "Operator acknowledgement of the live "
                "``DELHIVERY_MODE``. Must be one of "
                f"{sorted(PHASE_7G_ALLOWED_DELHIVERY_MODES)} and must "
                "match the live setting at runtime."
            ),
        )
        parser.add_argument(
            "--rollback-record-only-acknowledged",
            action="store_true",
            help=(
                "Operator acknowledges that rollback is record-only "
                "and never calls Delhivery cancel."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError(
                "--attempt-id must be a positive integer"
            )
        if not options.get("confirm_one_shot_courier_execution"):
            raise CommandError(
                "Refusing to dispatch without "
                "--confirm-one-shot-courier-execution. This is the "
                "Phase 7G one-shot Delhivery TEST/MOCK execution "
                "gate."
            )
        signoff = (options.get("director_signoff") or "").strip()
        if not signoff:
            raise CommandError(
                "--director-signoff must be a non-empty string and "
                "must mention the source Phase 7F gate id."
            )
        operator = (options.get("operator_name") or "").strip()
        if not operator:
            raise CommandError(
                "--operator-name must be a non-empty string."
            )
        mode_ack = (options.get("mode_acknowledgement") or "").strip()
        if mode_ack.lower() not in PHASE_7G_ALLOWED_DELHIVERY_MODES:
            raise CommandError(
                "--mode-acknowledgement must be one of "
                f"{sorted(PHASE_7G_ALLOWED_DELHIVERY_MODES)}."
            )
        if not options.get("rollback_record_only_acknowledged"):
            raise CommandError(
                "Refusing to dispatch without "
                "--rollback-record-only-acknowledged. Phase 7G "
                "rollback is record-only - it NEVER calls Delhivery "
                "cancel."
            )
        report = execute_phase7g_courier_one_shot(
            attempt_id,
            confirmed_by=None,
            director_signoff=signoff,
            operator_name=operator,
            mode_acknowledgement=mode_ack,
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7G courier one-shot executed "
                    f"attempt_id={attempt['id']} "
                    f"awb={attempt.get('providerObjectId')} "
                    f"status={attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Execution blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
