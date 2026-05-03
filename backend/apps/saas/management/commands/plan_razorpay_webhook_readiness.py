"""``python manage.py plan_razorpay_webhook_readiness --json``.

Phase 6L — emit the canonical Razorpay webhook readiness plan as
JSON. Pure policy; NEVER activates a webhook receiver, NEVER calls
Razorpay, NEVER mutates DB rows, NEVER returns raw secrets.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.razorpay_audit_review import (
    plan_razorpay_webhook_readiness,
)


class Command(BaseCommand):
    help = (
        "Emit the Phase 6L Razorpay webhook readiness plan. Pure "
        "planning policy — Phase 6M will own the actual handler."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        plan = plan_razorpay_webhook_readiness()
        if options.get("json"):
            self.stdout.write(_json.dumps(plan, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 6L Razorpay webhook plan")
        )
        self.stdout.write(f"  policyVersion: {plan['policyVersion']}")
        self.stdout.write(
            f"  endpoint     : {plan['endpointDesign']['method']} "
            f"{plan['endpointDesign']['path']}"
        )
        self.stdout.write(
            "  signature    : "
            f"{plan['signatureVerificationDesign']['algorithm']} on "
            f"{plan['signatureVerificationDesign']['header']}"
        )
        self.stdout.write(
            "  idempotency  : "
            f"key={plan['idempotencyDesign']['key']} fallback="
            f"{plan['idempotencyDesign']['fallbackKey']}"
        )
        self.stdout.write(
            "  replay window: "
            f"{plan['replayProtection']['windowSeconds']}s"
        )
        self.stdout.write(
            f"  allowlist    : {len(plan['eventAllowlist'])} events"
        )
        self.stdout.write(
            f"  denylist     : {len(plan['eventDenylist'])} events"
        )
        self.stdout.write(f"  nextAction   : {plan['nextAction']}")
        self.stdout.write(f"  nextPhase    : {plan['nextPhase']}")
        if plan.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in plan["blockers"]:
                self.stdout.write(f"  - {blocker}")
