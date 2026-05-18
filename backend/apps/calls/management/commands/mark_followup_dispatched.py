"""Phase 12C - Mark a follow-up as dispatched.

The Director runs this AFTER the Phase 7E-Live-B gate has been
approved + executed. Phase 12C never executes WhatsApp itself; this
command only flips status from gate_prepared -> dispatched and records
who dispatched. It does NOT send WhatsApp, call a courier, mutate
Order / Payment / Shipment, or invoke any provider.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.calls.post_call_followup import (
    PostCallFollowUpStateError,
    mark_dispatched,
)


class Command(BaseCommand):
    help = (
        "Phase 12C - Mark a PostCallFollowUpQueue entry as dispatched "
        "(after Phase 7E-Live-B gate has been executed separately)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "follow_up_id",
            type=int,
            help="PostCallFollowUpQueue id.",
        )
        parser.add_argument(
            "--operator-name",
            required=True,
            help="Operator confirming dispatch.",
        )
        parser.add_argument(
            "--note",
            default="",
            help="Optional free-text note (recorded on the queue row).",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        follow_up_id = int(options["follow_up_id"])
        operator_name = (options.get("operator_name") or "").strip()
        note = (options.get("note") or "").strip()
        try:
            entry = mark_dispatched(
                follow_up_id=follow_up_id,
                operator_name=operator_name,
                note=note,
            )
        except PostCallFollowUpStateError as exc:
            if options.get("json"):
                self.stdout.write(
                    json.dumps(
                        {"ok": False, "error": str(exc)}, default=str
                    )
                )
            self.stderr.write(f"REFUSED: {exc}")
            raise SystemExit(1) from exc

        result = {
            "ok": True,
            "follow_up_id": entry.pk,
            "status": entry.status,
            "follow_up_type": entry.follow_up_type,
            "phase7e_gate_id": entry.phase7e_gate_id,
            "dispatched_at": (
                entry.dispatched_at.isoformat()
                if entry.dispatched_at
                else None
            ),
            "dispatched_by": entry.dispatched_by,
        }
        if options.get("json"):
            self.stdout.write(json.dumps(result, default=str))
            return
        self.stdout.write(
            f"Phase 12C: follow-up #{entry.pk} marked dispatched "
            f"by {entry.dispatched_by} (type={entry.follow_up_type}, "
            f"phase7e_gate={entry.phase7e_gate_id})."
        )
