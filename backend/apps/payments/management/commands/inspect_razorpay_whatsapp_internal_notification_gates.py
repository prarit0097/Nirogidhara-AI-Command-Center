"""``python manage.py inspect_razorpay_whatsapp_internal_notification_gates \\
    [--limit N] [--json]``.

Phase 7E - read-only summary of recent gates. NEVER sends, NEVER
queues, NEVER calls a provider, NEVER mutates real business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_whatsapp_internal_notification import (
    summarize_phase7e_gates,
)


class Command(BaseCommand):
    help = (
        "Phase 7E - list recent WhatsApp internal notification gates "
        "(read-only; no provider call; no WhatsApp send; no business "
        "mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        limit = max(1, int(options.get("limit") or 25))
        report = summarize_phase7e_gates(limit=limit)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7E WhatsApp Internal Notification Gates"
            )
        )
        for status, count in report["counts"].items():
            self.stdout.write(f"  {status:<48}: {count}")
        for item in report["items"]:
            self.stdout.write(
                f"  - id={item['id']} status={item['status']} "
                f"phase7d_attempt={item.get('sourcePhase7DAttemptId')} "
                f"dryRun={item.get('dryRunPassed')} "
                f"rbDryRun={item.get('rollbackDryRunPassed')} "
                f"claimVault={item.get('claimVaultGrounded')}"
            )
