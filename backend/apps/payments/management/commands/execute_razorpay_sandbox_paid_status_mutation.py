"""``python manage.py execute_razorpay_sandbox_paid_status_mutation \\
    --review-id <ID> --confirm-sandbox-paid-status-mutation \\
    --director-signoff "..." --json``.

Phase 6P — controlled CLI execution of one sandbox paid-status
mutation attempt. Refuses unless ``RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=true``
AND ``--confirm-sandbox-paid-status-mutation`` is provided AND
``--director-signoff`` is non-empty AND the source Phase 6O review
is eligible. NEVER mutates real ``Order`` / ``Payment`` /
``Shipment`` / ``DiscountOfferLog`` / ``Customer`` / ``Lead``.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_sandbox_paid_status_mutation import (
    execute_phase6p_paid_status_mutation_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 6P — execute a sandbox paid-status mutation attempt "
        "against the Phase 6P ledger only. CLI-only; no API endpoint "
        "may dispatch this. Never mutates real business tables."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--review-id", required=True, type=int)
        parser.add_argument(
            "--confirm-sandbox-paid-status-mutation",
            action="store_true",
            help=(
                "Operator confirmation that this is a sandbox-only "
                "ledger mutation and that no real business row will "
                "be touched."
            ),
        )
        parser.add_argument(
            "--director-signoff",
            default="",
            type=str,
            help=(
                "Director sign-off text recorded on the attempt row. "
                "Required and must be non-empty."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        review_id = options["review_id"]
        if review_id <= 0:
            raise CommandError("--review-id must be a positive integer")

        report = execute_phase6p_paid_status_mutation_attempt(
            review_id,
            confirmed=bool(
                options.get("confirm_sandbox_paid_status_mutation")
            ),
            director_signoff_text=options.get("director_signoff") or "",
            executed_by=None,
        )

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        if report.get("executed"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Executed attempt id={report['attempt']['id']} "
                    f"ledger_state={report['ledger']['currentState']}"
                )
            )
        elif report.get("executedAgain"):
            self.stdout.write(
                self.style.WARNING(
                    "Attempt already executed. State already at target."
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Execute blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
