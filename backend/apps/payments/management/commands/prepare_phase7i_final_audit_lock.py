"""``python manage.py prepare_phase7i_final_audit_lock \\
    --phase7g-attempt-id N \\
    --phase7h-evidence-lock-id N \\
    [--phase7e-live-attempt-id N] \\
    [--phase7d-attempt-id N] --json``.

Phase 7I — prepare a Final Phase 7 audit-lock row that snapshots
Phase 7D + 7E-Live-A + 7G + 7H. Atomic + idempotent on the source
Phase 7H lock id. NEVER calls any provider; NEVER mutates business
rows; NEVER edits any `.env*` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.payments.phase7_final_audit_lock import (
    prepare_phase7i_final_audit_lock,
)


class Command(BaseCommand):
    help = (
        "Phase 7I — prepare a Final Phase 7 audit-lock row. Snapshots "
        "Phase 7D + 7E-Live-A + 7G + 7H. No provider call, no "
        "business mutation, no .env edit."
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
        )
        parser.add_argument(
            "--phase7d-attempt-id", type=int, default=None,
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
        report = prepare_phase7i_final_audit_lock(
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
        if report.get("created") or report.get("reused"):
            lock = report.get("lock") or {}
            label = (
                "created" if report.get("created") else "reused"
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Phase 7I final audit lock {label} lock_id="
                    f"{lock.get('id')} status={lock.get('status')}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Prepare blocked."))
            for b in report.get("blockers") or []:
                self.stdout.write(f"  - {b}")
        self.stdout.write(f"  nextAction: {report['nextAction']}")
