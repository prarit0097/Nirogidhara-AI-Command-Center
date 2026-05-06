"""``python manage.py inspect_razorpay_payment_order_workflow_gates --json``.

Phase 6Q — read-only summary of workflow gate review rows.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.razorpay_payment_order_workflow_gate import (
    summarize_phase6q_payment_order_workflow_gates,
)


class Command(BaseCommand):
    help = (
        "Phase 6Q — read-only summary of Payment → Order workflow "
        "safety gate review rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        limit = max(1, min(int(options.get("limit") or 25), 200))
        report = summarize_phase6q_payment_order_workflow_gates(limit=limit)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        c = report["counts"]
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 6Q workflow gate summary")
        )
        self.stdout.write(f"  draft               : {c['draft']}")
        self.stdout.write(f"  pendingManualReview : {c['pendingManualReview']}")
        self.stdout.write(
            f"  approvedFor6R       : {c['approvedForFuturePhase6R']}"
        )
        self.stdout.write(f"  rejected            : {c['rejected']}")
        self.stdout.write(f"  archived            : {c['archived']}")
