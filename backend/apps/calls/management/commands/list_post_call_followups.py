"""Phase 12C - Read-only listing of PostCallFollowUpQueue rows.

NEVER mutates anything. Director uses this to scan pending follow-ups
before preparing the Phase 7E-Live-B gate via a separate command.
"""
from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.calls.models import PostCallFollowUpQueue


class Command(BaseCommand):
    help = (
        "Phase 12C - Read-only listing of PostCallFollowUpQueue rows. "
        "Filters by --status, --type, and --hours."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--status",
            default="",
            help=(
                "Filter by status (e.g. pending / gate_prepared / "
                "dispatched / skipped). Default: all."
            ),
        )
        parser.add_argument(
            "--type",
            dest="follow_up_type",
            default="",
            help=(
                "Filter by follow_up_type (payment_reminder / "
                "callback_confirmation). Default: all."
            ),
        )
        parser.add_argument(
            "--hours",
            type=int,
            default=72,
            help="Only show rows created in the last N hours. Default 72.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Max rows to print. Default 100.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        qs = PostCallFollowUpQueue.objects.all()
        status = (options.get("status") or "").strip()
        if status:
            qs = qs.filter(status=status)
        follow_up_type = (options.get("follow_up_type") or "").strip()
        if follow_up_type:
            qs = qs.filter(follow_up_type=follow_up_type)
        hours = max(1, int(options.get("hours") or 72))
        cutoff = timezone.now() - timedelta(hours=hours)
        qs = qs.filter(created_at__gte=cutoff)

        limit = max(1, min(500, int(options.get("limit") or 100)))
        rows = list(qs.order_by("-created_at")[:limit])

        if options.get("json"):
            self.stdout.write(
                json.dumps(
                    [
                        {
                            "id": r.pk,
                            "call_outcome_id": r.call_outcome_id,
                            "lead_id": r.lead_id,
                            "phone_last4": r.lead_phone_last4,
                            "follow_up_type": r.follow_up_type,
                            "status": r.status,
                            "customer_found": r.customer_found,
                            "phase7e_gate_id": r.phase7e_gate_id,
                            "dispatched_at": (
                                r.dispatched_at.isoformat()
                                if r.dispatched_at
                                else None
                            ),
                            "dispatched_by": r.dispatched_by,
                            "created_at": r.created_at.isoformat(),
                        }
                        for r in rows
                    ],
                    default=str,
                )
            )
            return

        self.stdout.write(
            f"Phase 12C - PostCallFollowUpQueue listing "
            f"({len(rows)} row(s); status={status or 'any'}; "
            f"type={follow_up_type or 'any'}; window={hours}h):"
        )
        if not rows:
            self.stdout.write("  (none)")
            return
        for r in rows:
            gate = (
                f"gate={r.phase7e_gate_id}"
                if r.phase7e_gate_id
                else "gate=-"
            )
            self.stdout.write(
                f"  #{r.pk:<5} lead={r.lead_id:<10} "
                f"***{r.lead_phone_last4} {r.follow_up_type:<24} "
                f"{r.status:<22} cust={r.customer_found!s:<5} {gate}"
            )
