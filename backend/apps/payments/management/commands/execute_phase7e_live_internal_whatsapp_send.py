"""``python manage.py execute_phase7e_live_internal_whatsapp_send \\
    --attempt-id N \\
    --confirm-internal-whatsapp-send \\
    --operator-name "..." \\
    --director-signoff "...BEGIN_UTC=YYYY-MM-DDTHH:MM:SSZ END_UTC=YYYY-MM-DDTHH:MM:SSZ..." \\
    --json``.

Phase 7E-Live-A - **CLI-only one-shot Meta Cloud WhatsApp template
send** to an allow-list recipient. Refuses unless every safety
gate is green:

* ``PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED=true``.
* ``WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true``.
* Attempt status == ``approved_for_internal_one_shot_send``.
* Attempt recipient scope == ``internal_staff_allow_list``.
* Recipient last-4 still resolves to an allow-list entry.
* Director sign-off has structured ``BEGIN_UTC=`` / ``END_UTC=``
  markers; window ≤ 15 minutes; window not stale > 24h; ``now`` in
  ``[window_start, window_end]``.
* Operator name non-empty; ``--confirm-internal-whatsapp-send``
  set.
* Kill switch enabled; all six broad WhatsApp automation flags
  off; no prior provider call (idempotency lock).

It NEVER sends to a real customer phone; NEVER queues broad
automation; NEVER calls Delhivery / Razorpay / Vapi; NEVER mutates
``Order`` / ``Payment`` / ``Customer`` / ``Lead`` /
``DiscountOfferLog`` rows; NEVER edits any ``.env*`` file. Single-
shot: on SDK failure the attempt is marked failed and cannot be
re-executed.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_send import (
    execute_phase7e_live_internal_send,
)


class Command(BaseCommand):
    help = (
        "Phase 7E-Live-A - one-shot internal allowed-list WhatsApp "
        "send (CLI only). Refuses unless every safety flag is true, "
        "the Director sign-off has structured BEGIN_UTC/END_UTC "
        "markers within a 15-minute window, the recipient is on "
        "the allow-list, and no prior provider call exists. Never "
        "sends to a real customer phone; never mutates business rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--attempt-id", required=True, type=int)
        parser.add_argument(
            "--confirm-internal-whatsapp-send",
            action="store_true",
            help=(
                "Required gate flag. Without it, this command "
                "refuses to dispatch."
            ),
        )
        parser.add_argument(
            "--operator-name", default="", type=str,
            help="Required non-empty operator name.",
        )
        parser.add_argument(
            "--director-signoff", default="", type=str,
            help=(
                "Director sign-off text. Must include literal "
                "BEGIN_UTC=<ISO-8601-UTC-Z> and END_UTC=<ISO-8601-"
                "UTC-Z> markers; parsed window length must be <= 15 "
                "minutes; window must be fresh; now must fall "
                "inside [window_start, window_end]. Free-text-only "
                "sign-off is refused."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options["attempt_id"])
        if attempt_id <= 0:
            raise CommandError(
                "--attempt-id must be a positive integer"
            )
        if not options.get("confirm_internal_whatsapp_send"):
            raise CommandError(
                "Refusing to dispatch without "
                "--confirm-internal-whatsapp-send. This is the "
                "Phase 7E-Live-A one-shot internal send gate."
            )
        operator = (options.get("operator_name") or "").strip()
        if not operator:
            raise CommandError(
                "--operator-name must be a non-empty string."
            )
        signoff = (options.get("director_signoff") or "").strip()
        if not signoff:
            raise CommandError(
                "--director-signoff must be a non-empty string and "
                "must include literal BEGIN_UTC=<...> and END_UTC=<...> "
                "markers."
            )
        report = execute_phase7e_live_internal_send(
            attempt_id,
            confirmed_by=None,
            director_signoff=signoff,
            operator_name=operator,
            confirm_internal_whatsapp_send=True,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            attempt = report["attempt"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7E-Live-A send executed attempt_id="
                    f"{attempt['id']} provider_message_id="
                    f"{attempt.get('providerMessageId')} "
                    f"status={attempt['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Execution blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
