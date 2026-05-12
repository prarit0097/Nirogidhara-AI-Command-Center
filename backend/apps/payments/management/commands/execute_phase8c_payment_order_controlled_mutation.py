"""``python manage.py execute_phase8c_payment_order_controlled_mutation \\
    --attempt-id N \\
    --confirm-one-shot-mutation \\
    --director-signoff "phase8c_attempt_id_N phase8b_gate_id_M BEGIN_UTC=2026-05-12T12:00:00Z END_UTC=2026-05-12T12:10:00Z" \\
    --operator-name "Director Prarit Sidana" --json``.

Phase 8C one-shot CLI-only execute. Refuses unless three env flags
are all true, kill switch is enabled, a structured Director sign-off
UTC window (<= 15 min) is supplied, AND the target Order + Payment
pair is still proven internal/sandbox/test. The only mutation
performed is writing the target Order.payment_status and target
Payment.status to "Paid". NEVER calls a provider; NEVER sends
WhatsApp; NEVER sends a customer notification; NEVER creates a
Shipment / AWB / payment link; NEVER captures / refunds; NEVER
edits any .env file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8c_payment_order_controlled_mutation import (
    execute_phase8c_payment_order_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8C — one-shot CLI-only execute against an approved "
        "controlled-mutation attempt. Refuses unless every safety "
        "gate is satisfied."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--attempt-id", required=True, type=int
        )
        parser.add_argument(
            "--confirm-one-shot-mutation",
            action="store_true",
            help="Mandatory positive confirmation switch.",
        )
        parser.add_argument(
            "--director-signoff",
            default="",
            type=str,
            help=(
                "Structured Director sign-off text. MUST contain "
                "phase8c_attempt_id_<ID>, phase8b_gate_id_<ID>, "
                "BEGIN_UTC=<ISO-Z>, END_UTC=<ISO-Z>."
            ),
        )
        parser.add_argument(
            "--operator-name",
            default="",
            type=str,
            help="Non-empty operator display name.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError(
                "--attempt-id must be a positive integer"
            )
        signoff = (
            options.get("director_signoff") or ""
        ).strip()
        operator = (options.get("operator_name") or "").strip()
        confirm = bool(options.get("confirm_one_shot_mutation"))
        if not confirm:
            raise CommandError(
                "--confirm-one-shot-mutation must be supplied."
            )
        if not signoff:
            raise CommandError(
                "--director-signoff must be a non-empty structured "
                "string with BEGIN_UTC=/END_UTC= markers."
            )
        if not operator:
            raise CommandError(
                "--operator-name must be a non-empty string."
            )
        report = execute_phase8c_payment_order_controlled_mutation(
            attempt_id,
            director_signoff=signoff,
            operator_name=operator,
            confirm_one_shot_mutation=confirm,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 8C executed attempt_id={attempt['id']} "
                    f"status={attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Execute blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
