"""``python manage.py execute_single_razorpay_test_order --plan-id <PLAN_ID> --confirm-test-execution --json``.

Phase 6K-B — the ONE manual command that may dispatch a real
Razorpay TEST-MODE ``create_order`` call. Refuses to dispatch unless
EVERY precondition is satisfied:

1. Approved Phase 6J plan.
2. ``PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED=true`` env flag.
3. ``--confirm-test-execution`` CLI flag.
4. ``RAZORPAY_KEY_ID`` starts with ``rzp_test``.
5. No prior successful execution exists for the plan.
6. Plan amount = 100 paise, currency = INR.
7. Plan payload carries no customer PII.
8. Global runtime kill switch enabled.

Never logs the API key. Never creates a payment link. Never captures
a payment. Never sends a customer notification. Never mutates a
business row.

**This command must NEVER run automatically during deployment,
tests, migrations, health checks, page loads, or API listings.**
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.saas.models import (
    RuntimeProviderExecutionAttempt,
    RuntimeProviderTestPlan,
)
from apps.saas.provider_execution import (
    execute_single_razorpay_test_order,
    serialize_execution_attempt,
)


class Command(BaseCommand):
    help = (
        "Execute ONE Razorpay test-mode create_order against an "
        "approved Phase 6J plan. CLI-only. Requires "
        "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED=true env flag AND "
        "--confirm-test-execution. Never sends a payment link, never "
        "captures, never notifies a customer, never mutates a "
        "business row."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--plan-id", required=True, help="Approved Phase 6J plan id"
        )
        parser.add_argument(
            "--confirm-test-execution",
            action="store_true",
            default=False,
            help=(
                "Required. Without this flag the command refuses to "
                "dispatch."
            ),
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        plan_id = options["plan_id"]
        confirm = bool(options.get("confirm_test_execution"))
        if not RuntimeProviderTestPlan.objects.filter(plan_id=plan_id).exists():
            raise CommandError(
                f"Provider test plan not found: {plan_id}"
            )
        attempt = execute_single_razorpay_test_order(
            plan_id, confirm=confirm
        )
        Status = RuntimeProviderExecutionAttempt.Status
        report = {
            "passed": attempt.status == Status.SUCCEEDED,
            "warning": (
                "Phase 6K Razorpay test-mode call. No real money / no "
                "customer / no business mutation."
            ),
            **serialize_execution_attempt(attempt),
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        if attempt.status == Status.SUCCEEDED:
            self.stdout.write(
                self.style.SUCCESS(
                    "Phase 6K Razorpay test order created"
                )
            )
            self.stdout.write(
                f"  providerObjectId: {attempt.provider_object_id}"
            )
            self.stdout.write(f"  status:           {attempt.provider_status}")
            self.stdout.write(f"  amount:           {attempt.amount_paise} paise")
            self.stdout.write(f"  currency:         {attempt.currency}")
            self.stdout.write(
                f"  business mutation: {attempt.business_mutation_was_made}"
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Phase 6K execution status: {attempt.status}"
                )
            )
            for blocker in attempt.blockers or []:
                self.stdout.write(f"  - {blocker}")
        self.stdout.write(f"  nextAction:       {report['nextAction']}")
