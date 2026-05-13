"""``python manage.py inspect_phase8e_real_customer_candidate_pool --json``.

Phase 8E-Hotfix-1 - read-only candidate pool inspector. Classifies
every ``Order`` + ``Payment`` row pair currently in the system by
Phase 8E eligibility reason (strict Pending/Pending, Partial/Pending
review-only, or blocked-with-reason). NEVER mutates business rows,
NEVER calls a provider, NEVER sends WhatsApp / Meta Cloud /
Delhivery / Vapi, NEVER sends a customer notification, NEVER edits
any ``.env*`` file. Phones masked to last-4 only; raw provider
payloads / full gateway_reference_id / customer names / addresses
NEVER appear in the output.
"""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.payments.phase8e_real_customer_payment_order_pilot import (
    emit_pool_inspected_audit,
    inspect_phase8e_real_customer_candidate_pool,
)


class Command(BaseCommand):
    help = (
        "Phase 8E-Hotfix-1 - read-only candidate pool inspector. "
        "Classifies real-customer Order + Payment pairs by Phase "
        "8E eligibility reason. No provider call, no business "
        "mutation, no .env edit."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help=(
                "Maximum number of Payment rows to classify "
                "(default 50, max 500)."
            ),
        )
        parser.add_argument(
            "--include-blocked",
            action="store_true",
            help=(
                "Include blocked candidate rows in the masked "
                "recommendation table (default off; blocked "
                "counts are always returned)."
            ),
        )
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--no-audit",
            action="store_true",
            help="Skip emitting the pool-inspected AuditEvent.",
        )

    def handle(self, *args, **options) -> None:
        report = inspect_phase8e_real_customer_candidate_pool(
            limit=int(options.get("limit") or 50),
            include_blocked=bool(options.get("include_blocked")),
        )
        if not options.get("no_audit"):
            emit_pool_inspected_audit(report)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8E Real Customer Candidate Pool"
            )
        )
        self.stdout.write(
            f"  totalLinkedPairs               : "
            f"{report['totalLinkedPairs']}"
        )
        self.stdout.write(
            f"  strict Pending/Pending count   : "
            f"{report['eligibleStrictPendingPendingCount']}"
        )
        self.stdout.write(
            f"  Partial/Pending review-only    : "
            f"{report['eligiblePartialPendingReviewOnlyCount']}"
        )
        if report["blockedCountsByReason"]:
            self.stdout.write("blocked counts by reason:")
            for reason, count in sorted(
                report["blockedCountsByReason"].items()
            ):
                self.stdout.write(f"  - {reason:<52}: {count}")
        if report["recommendedCandidates"]:
            self.stdout.write("recommended candidates (masked):")
            for row in report["recommendedCandidates"]:
                self.stdout.write(
                    f"  - order={row['orderId']:<28} "
                    f"payment={row['paymentId']:<28} "
                    f"orderPayStatus={row['orderPaymentStatus']:<8} "
                    f"paymentStatus={row['paymentStatus']:<8} "
                    f"stage={row['stage']:<22} "
                    f"phoneLast4={row['phoneLast4']:<6} "
                    f"recommendation={row['recommendation']}"
                )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "No eligible real-customer candidate found in "
                    "the inspected window."
                )
            )
        self.stdout.write(
            f"  nextAction                     : "
            f"{report['nextAction']}"
        )
