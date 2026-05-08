"""``python manage.py approve_delhivery_courier_readiness_gate \\
    --gate-id <ID> --reason "..." --json``.

Phase 7F - approve a courier readiness gate **for future Phase 7G
or courier execution review only**. NEVER calls Delhivery; NEVER
creates a Shipment / AWB / pickup / label; NEVER sends WhatsApp;
NEVER mutates real business rows; NEVER edits any ``.env*`` file.

**No ``--director-signoff`` argument.** Phase 7F approval is a
status transition only. Live courier dispatch requires Phase 7G +
a future execute-window guard reusing
``apps.saas.utc_window.validate_within_director_window``.

Refuses unless:

- Gate is in ``pending_manual_review``.
- ``dry_run_passed=True`` AND ``rollback_dry_run_passed=True``.
- ``phase7d_hotfix_1_present=True`` (re-checked at approve time).
- ``--reason`` is non-empty.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.razorpay_courier_readiness import approve_phase7f_gate


class Command(BaseCommand):
    help = (
        "Phase 7F - approve a courier readiness gate for future "
        "Phase 7G or courier execution review. No provider call; "
        "no Delhivery call; no Shipment / AWB / pickup / label "
        "creation; no WhatsApp send; no business mutation; reason "
        "required. Approval is a status transition only - it does "
        "NOT enable any provider call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--gate-id", required=True, type=int)
        parser.add_argument("--reason", default="", type=str)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        gate_id = int(options["gate_id"])
        if gate_id <= 0:
            raise CommandError("--gate-id must be a positive integer")
        reason = (options.get("reason") or "").strip()
        if not reason:
            raise CommandError(
                "--reason must be a non-empty string for Phase 7F approval"
            )
        report = approve_phase7f_gate(
            gate_id, reviewed_by=None, reason=reason
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
