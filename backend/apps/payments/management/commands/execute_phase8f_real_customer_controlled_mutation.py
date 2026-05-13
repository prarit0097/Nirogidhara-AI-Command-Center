"""``python manage.py execute_phase8f_real_customer_controlled_mutation
--attempt-id <ID> --director-signoff "phase8f_attempt_id_<ID>
phase8f_gate_id_<ID> phase8e_gate_id_1
target_order_<ORDER_ID> target_payment_<PAYMENT_ID>
BEGIN_UTC=<ISO-Z> END_UTC=<ISO-Z>" --operator-name "..."
--confirm-one-shot-real-mutation [--json]``.

Phase 8F - one-shot CLI-only execute of the controlled real
customer payment-order mutation. The ONLY path that may write
``Order.payment_status`` and ``Payment.status`` to ``Paid`` for the
approved candidate. Refuses unless every safety gate is satisfied
(three env flags ALL true, structured 15-min Director UTC window,
kill switch enabled, ``--confirm-one-shot-real-mutation``, non-empty
``--operator-name``, signoff text references phase8f_attempt_id /
phase8f_gate_id / phase8e_gate_id / target_order_<ID> /
target_payment_<ID>, current Order.payment_status / Payment.status
still match the approved snapshot). NEVER calls Razorpay / Meta
Cloud / Delhivery / Vapi, NEVER sends WhatsApp, NEVER creates a
Shipment / AWB / payment link, NEVER captures / refunds, NEVER
mutates Order.state / Customer / Lead / Shipment /
DiscountOfferLog / WhatsAppMessage rows, NEVER edits any
``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase8f_real_customer_controlled_mutation import (
    execute_phase8f_real_customer_controlled_mutation,
)


class Command(BaseCommand):
    help = (
        "Phase 8F - CLI-only one-shot controlled real customer "
        "payment-order mutation execute. Refuses unless every "
        "safety gate is satisfied. Never calls a provider, never "
        "sends WhatsApp, never sends a customer notification, "
        "never creates a Shipment / AWB / payment link, never "
        "captures, never refunds, never mutates Order.state. The "
        "only mutation is writing Order.payment_status + "
        "Payment.status to Paid on the named target rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--attempt-id",
            type=int,
            required=True,
            help="Phase 8F attempt id to execute.",
        )
        parser.add_argument(
            "--director-signoff",
            type=str,
            required=True,
            help=(
                "Director sign-off text. Must reference "
                "phase8f_attempt_id_<ID>, phase8f_gate_id_<ID>, "
                "phase8e_gate_id_<ID>, target_order_<ID>, "
                "target_payment_<ID>, and a structured "
                "BEGIN_UTC=<ISO-Z> END_UTC=<ISO-Z> 15-min window."
            ),
        )
        parser.add_argument(
            "--operator-name",
            type=str,
            required=True,
            help="Non-empty name of the human operator running this.",
        )
        parser.add_argument(
            "--confirm-one-shot-real-mutation",
            action="store_true",
            help=(
                "Confirms the operator has Director approval to "
                "run the ONE-SHOT real customer payment-order "
                "mutation. Required to proceed."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options.get("attempt_id") or 0)
        if attempt_id <= 0:
            raise CommandError(
                "attempt_id must be a positive integer."
            )
        if not bool(options.get("confirm_one_shot_real_mutation")):
            raise CommandError(
                "--confirm-one-shot-real-mutation is required."
            )
        signoff = (options.get("director_signoff") or "").strip()
        if not signoff:
            raise CommandError(
                "--director-signoff cannot be empty."
            )
        operator = (options.get("operator_name") or "").strip()
        if not operator:
            raise CommandError(
                "--operator-name cannot be empty."
            )
        report = execute_phase8f_real_customer_controlled_mutation(
            attempt_id,
            director_signoff=signoff,
            operator_name=operator,
            confirm_one_shot_real_mutation=True,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8F controlled real customer mutation execute"
            )
        )
        self.stdout.write(f"  ok        : {report['ok']}")
        self.stdout.write(
            f"  nextAction: {report.get('nextAction')}"
        )
        if report.get("attempt"):
            self.stdout.write(
                f"  attemptId : {report['attempt']['id']}"
            )
            self.stdout.write(
                f"  status    : {report['attempt']['status']}"
            )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
