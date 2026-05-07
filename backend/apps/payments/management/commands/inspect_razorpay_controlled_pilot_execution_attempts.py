"""``python manage.py inspect_razorpay_controlled_pilot_execution_attempts \\
    [--limit N] [--json]``.

Phase 7D - read-only summary of recent Razorpay controlled pilot
execution attempts. NEVER mutates anything; NEVER calls Razorpay;
NEVER sends WhatsApp; NEVER edits any ``.env*`` file.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_controlled_pilot_execution import (
    summarize_phase7d_attempts,
)


class Command(BaseCommand):
    help = (
        "Phase 7D - read-only list of recent controlled pilot "
        "execution attempts (no provider call; no business mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        limit = max(1, int(options.get("limit") or 25))
        report = summarize_phase7d_attempts(limit=limit)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        c = report["counts"]
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7D Controlled Pilot Execution Attempts"
            )
        )
        self.stdout.write(f"  draft                 : {c['draft']}")
        self.stdout.write(
            f"  pendingDirectorSignoff: {c['pendingDirectorSignoff']}"
        )
        self.stdout.write(
            f"  approvedForOneShotRun : {c['approvedForOneShotRun']}"
        )
        self.stdout.write(f"  executed              : {c['executed']}")
        self.stdout.write(f"  failed                : {c['failed']}")
        self.stdout.write(f"  rolledBack            : {c['rolledBack']}")
        self.stdout.write(f"  archived              : {c['archived']}")
        self.stdout.write(f"  blocked               : {c['blocked']}")
        for item in report["items"]:
            self.stdout.write(
                f"  - id={item['id']} status={item['status']} "
                f"phase7b_gate={item.get('sourcePhase7BGateId')} "
                f"phase6t_lock={item.get('sourcePhase6TLockId')} "
                f"provider_object_id={item.get('providerObjectId') or '-'}"
            )
