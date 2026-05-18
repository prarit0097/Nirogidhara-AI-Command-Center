"""Phase 12C - Skip a queued follow-up.

Permanently marks the row as skipped (cannot be re-prepared). Never
sends WhatsApp, never mutates Order / Payment / Shipment / Customer /
Lead, never calls a provider.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.calls.post_call_followup import (
    PostCallFollowUpStateError,
    skip_follow_up,
)


class Command(BaseCommand):
    help = (
        "Phase 12C - Skip a queued PostCallFollowUpQueue row (mark as "
        "skipped permanently)."
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
            help="Operator skipping the follow-up.",
        )
        parser.add_argument(
            "--reason",
            default="",
            help="Optional free-text reason for the skip.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        follow_up_id = int(options["follow_up_id"])
        operator_name = (options.get("operator_name") or "").strip()
        reason = (options.get("reason") or "").strip()
        try:
            entry = skip_follow_up(
                follow_up_id=follow_up_id,
                operator_name=operator_name,
                reason=reason,
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
            "skipped_by": entry.dispatched_by,
            "reason_excerpt": (
                (entry.metadata or {}).get("skip_reason") or ""
            ),
        }
        if options.get("json"):
            self.stdout.write(json.dumps(result, default=str))
            return
        self.stdout.write(
            f"Phase 12C: follow-up #{entry.pk} skipped by "
            f"{entry.dispatched_by}."
        )
