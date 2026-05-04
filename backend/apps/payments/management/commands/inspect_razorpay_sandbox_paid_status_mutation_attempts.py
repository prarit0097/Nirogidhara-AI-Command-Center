"""``python manage.py inspect_razorpay_sandbox_paid_status_mutation_attempts --json``.

Phase 6P — read-only summary of attempts + ledger rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_sandbox_paid_status_mutation import (
    summarize_phase6p_paid_status_mutation_attempts,
)


class Command(BaseCommand):
    help = (
        "Phase 6P — read-only summary of sandbox paid-status mutation "
        "attempts + ledger rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        limit = max(1, min(int(options.get("limit") or 25), 200))
        report = summarize_phase6p_paid_status_mutation_attempts(limit=limit)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6P attempts + ledger summary"
            )
        )
        c = report["counts"]
        self.stdout.write(
            f"  attempts prepared    : {c['prepared']}"
        )
        self.stdout.write(
            f"  attempts executed    : {c['executed']}"
        )
        self.stdout.write(
            f"  attempts rolled back : {c['rolledBack']}"
        )
        self.stdout.write(
            f"  attempts archived    : {c['archived']}"
        )
        l = report["ledgerCounts"]
        self.stdout.write(
            f"  total ledger rows    : {l['totalLedgers']}"
        )
        self.stdout.write(
            f"  rolled back ledgers  : {l['rolledBackLedgers']}"
        )
