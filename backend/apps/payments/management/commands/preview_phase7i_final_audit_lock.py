"""``python manage.py preview_phase7i_final_audit_lock \\
    --phase7g-attempt-id N \\
    --phase7h-evidence-lock-id N \\
    [--phase7e-live-attempt-id N] \\
    [--phase7d-attempt-id N] --json``.

Phase 7I — read-only preview of the Final Phase 7 Payment +
WhatsApp + Courier Audit Lock. NEVER creates rows; NEVER calls
any provider; NEVER mutates business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase7_final_audit_lock import (
    preview_phase7i_final_audit_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 7I — read-only preview of the Final Phase 7 audit "
        "lock derived from Phase 7G + Phase 7H + (auto-resolved or "
        "explicit) Phase 7E-Live-A + Phase 7D."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--phase7g-attempt-id", required=True, type=int,
        )
        parser.add_argument(
            "--phase7h-evidence-lock-id", required=True, type=int,
        )
        parser.add_argument(
            "--phase7e-live-attempt-id", type=int, default=None,
            help=(
                "Optional. If omitted, the latest "
                "rollback_recorded Phase 7E-Live-A attempt with a "
                "provider_message_id on the same Phase 7E gate is "
                "used."
            ),
        )
        parser.add_argument(
            "--phase7d-attempt-id", type=int, default=None,
            help=(
                "Optional. If omitted, derived from the supplied "
                "Phase 7G attempt's source chain."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        g_id = int(options["phase7g_attempt_id"])
        h_id = int(options["phase7h_evidence_lock_id"])
        if g_id <= 0 or h_id <= 0:
            raise CommandError(
                "--phase7g-attempt-id and --phase7h-evidence-lock-id "
                "must be positive integers"
            )
        report = preview_phase7i_final_audit_lock(
            phase7g_attempt_id=g_id,
            phase7h_evidence_lock_id=h_id,
            phase7e_live_attempt_id=options.get(
                "phase7e_live_attempt_id"
            ),
            phase7d_attempt_id=options.get("phase7d_attempt_id"),
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7I Final Audit Lock Preview"
            )
        )
        self.stdout.write(f"  eligible        : {report['eligible']}")
        self.stdout.write(
            f"  phase 7D attempt: {report['phase7DAttemptId']}"
        )
        self.stdout.write(
            f"  phase 7E-live   : {report['phase7ELiveAttemptId']}"
        )
        self.stdout.write(
            f"  phase 7G attempt: {report['phase7GAttemptId']}"
        )
        self.stdout.write(
            f"  phase 7H lock   : {report['phase7HEvidenceLockId']}"
        )
        self.stdout.write(f"  nextAction      : {report['nextAction']}")
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
