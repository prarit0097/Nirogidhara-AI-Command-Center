"""``python manage.py approve_razorpay_whatsapp_internal_notification_gate \\
    --gate-id <ID> --reason "..." --director-signoff "..." \\
    [--acknowledge-source-phase7d-window-violation] --json``.

Phase 7E - approve a notification gate **for future Phase 7F or
Phase 7E-Live send review only**. NEVER sends or queues WhatsApp;
NEVER calls a provider; NEVER mutates real business rows; NEVER
edits any ``.env*`` file.

Refuses unless:
- ``--reason`` non-empty.
- Gate ``dry_run_passed=True`` AND ``rollback_dry_run_passed=True``.
- ``claim_vault_grounded=True``.
- ``--director-signoff`` parses a structured Phase 7E review window
  via ``apps.saas.utc_window.parse_director_signoff_window``
  (window length <= 24h, recent).
- The sign-off body literally references the source Phase 7D
  attempt id (``phase7d_attempt_id_<ID>``).
- If the source Phase 7D attempt's sign-off is legacy free-text:
  ``--acknowledge-source-phase7d-window-violation`` is set AND
  ``--reason`` body literally contains
  ``acknowledged_phase7d_window_violation_ref_attempt_<ID>``.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_whatsapp_internal_notification import (
    approve_phase7e_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 7E - approve a WhatsApp internal notification gate for "
        "future Phase 7F or Phase 7E-Live send review. No provider "
        "call; no WhatsApp send / queue; no business mutation; reason "
        "+ structured director sign-off window required."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument(
            "--director-signoff", default="", type=str
        )
        parser.add_argument(
            "--acknowledge-source-phase7d-window-violation",
            action="store_true",
            help=(
                "Required when the source Phase 7D attempt's "
                "recorded signoff is legacy free-text "
                "(failed_or_legacy_free_text)."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError(
                "--reason must be a non-empty string for Phase 7E approval"
            )
        signoff = (options.get("director_signoff") or "").strip()
        if not signoff:
            raise CommandError(
                "--director-signoff must be non-empty and contain "
                "structured BEGIN_UTC=... / END_UTC=... markers plus "
                "the source Phase 7D attempt id reference."
            )
        report = approve_phase7e_gate(
            gate_id,
            reviewed_by=None,
            reason=reason,
            director_signoff=signoff,
            acknowledge_source_phase7d_window_violation=bool(
                options.get(
                    "acknowledge_source_phase7d_window_violation"
                )
            ),
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if report.get("ok"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Gate {report['gate']['id']} -> "
                    f"{report['gate']['status']}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Approval blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
