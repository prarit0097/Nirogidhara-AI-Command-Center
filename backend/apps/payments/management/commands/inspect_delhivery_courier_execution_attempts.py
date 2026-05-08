"""``python manage.py inspect_delhivery_courier_execution_attempts --limit N --json``.

Phase 7G - read-only listing of Phase 7G attempts with a per-status
counter and a recent sample. NEVER calls Delhivery; NEVER mutates
real business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_courier_execution import (
    summarize_phase7g_attempts,
)


class Command(BaseCommand):
    help = (
        "Phase 7G - read-only listing of Phase 7G attempts. No "
        "Delhivery call, no business mutation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=25,
            help="Cap on the number of returned items (1-200).",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        limit = max(1, min(int(options.get("limit") or 25), 200))
        report = summarize_phase7g_attempts(limit=limit)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 7G Courier Execution Attempts (limit={limit})"
            )
        )
        for status, count in report["counts"].items():
            self.stdout.write(f"  {status:<40} : {count}")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Recent ({len(report['items'])}):"
            )
        )
        for row in report["items"]:
            self.stdout.write(
                f"  id={row['id']:<5} status={row['status']:<46} "
                f"phase7f={row['sourcePhase7FGateId']} "
                f"awb={row['providerObjectId'] or '-'}"
            )
