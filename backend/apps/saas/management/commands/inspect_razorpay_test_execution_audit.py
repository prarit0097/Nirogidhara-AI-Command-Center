"""``python manage.py inspect_razorpay_test_execution_audit --execution-id <ID> --json``.

Phase 6L — read-only audit-review of one Phase 6K
:class:`RuntimeProviderExecutionAttempt`. NEVER calls Razorpay,
NEVER mutates DB rows, NEVER returns raw secrets, NEVER returns the
raw provider response.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.razorpay_audit_review import (
    review_razorpay_test_execution_audit,
)


class Command(BaseCommand):
    help = (
        "Read-only Phase 6L audit review of one Phase 6K Razorpay "
        "test-mode execution attempt. No external call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--execution-id", required=True, help="Phase 6K execution id"
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        execution_id = options["execution_id"]
        report = review_razorpay_test_execution_audit(execution_id)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6L Razorpay test execution audit review"
            )
        )
        for key in (
            "executionId",
            "planId",
            "status",
            "providerObjectId",
            "providerStatus",
            "amountPaise",
            "currency",
            "rollbackStatus",
            "auditEventCount",
            "rawSecretLeakDetected",
            "passed",
            "nextAction",
        ):
            self.stdout.write(f"  {key:<28}: {report.get(key)}")
        if report.get("invariantResults"):
            self.stdout.write(self.style.MIGRATE_LABEL("invariants:"))
            for inv in report["invariantResults"]:
                tone = self.style.SUCCESS if inv["passed"] else self.style.ERROR
                self.stdout.write(
                    tone(
                        f"    {inv['key']:<26} expected={inv['expected']} "
                        f"actual={inv['actual']} → {inv['passed']}"
                    )
                )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
