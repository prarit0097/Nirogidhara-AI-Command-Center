"""``python manage.py inspect_delhivery_courier_readiness_gates \\
    [--limit N] [--json]``.

Phase 7F - read-only summary of recent courier readiness gates.
NEVER calls Delhivery; NEVER mutates real business rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_courier_readiness import (
    summarize_phase7f_gates,
)


class Command(BaseCommand):
    help = (
        "Phase 7F - list recent courier readiness gates "
        "(read-only; no provider call; no Delhivery call; no "
        "business mutation)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        limit = max(1, int(options.get("limit") or 25))
        report = summarize_phase7f_gates(limit=limit)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 7F Courier Readiness Gates"
            )
        )
        for status, count in report["counts"].items():
            self.stdout.write(f"  {status:<58}: {count}")
        for item in report["items"]:
            self.stdout.write(
                f"  - id={item['id']} status={item['status']} "
                f"phase7e={item.get('sourcePhase7EGateId')} "
                f"dryRun={item.get('dryRunPassed')} "
                f"rbDryRun={item.get('rollbackDryRunPassed')} "
                f"hotfix1={item.get('phase7DHotfix1Present')}"
            )
