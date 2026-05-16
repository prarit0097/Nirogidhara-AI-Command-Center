"""Phase 10B — CLI: Targeted Payment Reminder Preparer.

Stage-aware preparer that creates a Phase 7E-Live-B real-customer
send gate row pre-filled with payment-reminder template params.
This command NEVER sends WhatsApp or makes a call. It may idempotently
create a missing CRM Customer bridge row for Payment/Order phone fallback;
Director still has to run the existing Phase 7E-Live-B approve + execute
commands (with structured UTC window + runtime env flags) for an actual
send.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.diagnostics.payment_reminder_service import (
    DEFAULT_TEMPLATE_NAME,
    PaymentReminderValidationError,
    build_payment_reminder_attempt,
)


class Command(BaseCommand):
    help = (
        "Phase 10B — Prepare a Phase 7E-Live-B payment-reminder send gate "
        "for a single pending payment. Stage-aware validation. NEVER sends; "
        "Director must still run the existing 7E-Live-B approve + execute "
        "commands separately."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "payment_id",
            help="Payment.id (e.g. PAY-30121) to prepare a reminder for.",
        )
        parser.add_argument(
            "--template-id",
            default=DEFAULT_TEMPLATE_NAME,
            help=(
                "Phase 5A template name. Defaults to "
                f"'{DEFAULT_TEMPLATE_NAME}'. Must be in the Phase 7E-Live-B "
                "approved template allowlist."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Required for WARN-listed stages (Interested / "
                "Confirmation Pending). Refused for BLOCKED stages."
            ),
        )
        parser.add_argument(
            "--operator-note",
            default="",
            help=(
                "Free-form note recorded on the Phase 10B audit row "
                "(NOT sent to the customer)."
            ),
        )
        parser.add_argument(
            "--operator-name",
            default="phase10b_preparer",
            help=(
                "Operator name forwarded to the Phase 7E-Live-B prepare "
                "step. Real Director name must be used in production."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        try:
            prepared = build_payment_reminder_attempt(
                payment_id=options["payment_id"],
                template_id=options.get("template_id") or DEFAULT_TEMPLATE_NAME,
                force=bool(options.get("force")),
                operator_note=options.get("operator_note", ""),
                operator_name=options.get("operator_name", "phase10b_preparer"),
            )
        except PaymentReminderValidationError as exc:
            error_payload = {
                "phase": "10B",
                "ok": False,
                "error_code": exc.code,
                "error_message": exc.message,
            }
            if options.get("json"):
                self.stdout.write(json.dumps(error_payload, default=str))
            else:
                self.stderr.write(
                    f"REFUSED [{exc.code}]: {exc.message}"
                )
            sys.exit(1)

        payload = prepared.to_payload()
        if options.get("json"):
            self.stdout.write(json.dumps(payload, default=str))
            return

        self.stdout.write("Phase 10B — Payment reminder prepared.")
        self.stdout.write(f"  Phase 7E-Live-B gate id : {prepared.gate_id}")
        self.stdout.write(f"  Payment                 : {prepared.payment_id}")
        self.stdout.write(f"  Order                   : {prepared.order_id}")
        self.stdout.write(f"  Stage                   : {prepared.stage}")
        self.stdout.write(f"  Template                : {prepared.template_name}")
        self.stdout.write(
            f"  Phone (last 4 only)     : ***{prepared.target_phone[-4:]} "
            f"(source: {prepared.phone_source})"
        )
        self.stdout.write(
            f"  Customer name           : {prepared.target_customer_name}"
        )
        if prepared.crm_customer_auto_created:
            self.stdout.write(
                "  CRM customer auto-created : Yes "
                f"(phone_source={prepared.phone_source})"
            )
        else:
            self.stdout.write(
                "  CRM customer              : already registered"
            )
        if prepared.warning_emitted:
            self.stdout.write(
                "  WARNING                 : --force used at WARN stage; "
                "warning audit row written."
            )
        self.stdout.write("")
        self.stdout.write("Next steps (Director / VPS shell):")
        self.stdout.write(
            f"  1. python manage.py inspect_phase7e_live_b_real_customer_gate"
        )
        self.stdout.write(
            "  2. python manage.py approve_phase7e_live_b_real_customer_gate"
            f" --gate-id {prepared.gate_id}"
            " --director-signoff '<phase7e_live_b_gate_id_"
            f"{prepared.gate_id} target_phone_"
            f"{prepared.target_phone[-4:]} template_{prepared.template_name}"
            " phase7eLiveBApproval BEGIN_UTC=... END_UTC=...>'"
            " --operator-name '<NAME>'"
            " --confirm-phase7e-live-b-real-customer-send"
        )
        self.stdout.write(
            "  3. python manage.py execute_phase7e_live_b_real_customer_send"
            f" --gate-id {prepared.gate_id}"
            " --director-signoff '<same structured signoff>'"
            " --operator-name '<NAME>'"
            " --confirm-phase7e-live-b-real-customer-send"
        )
        self.stdout.write("")
        self.stdout.write(
            "Phase 10B itself sent NOTHING. The gate row is in 'draft' "
            "status until Director approves + executes."
        )
