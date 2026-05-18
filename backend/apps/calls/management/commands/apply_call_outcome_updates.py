"""Phase 12B - Apply approved CallOutcomeRecord suggestions to Lead.status.

THIS is the ONLY CLI in Phase 12B that may mutate Lead.status, and
ONLY for records already in `review_status=approved`. Requires
--confirm-outcome-apply (enforced at the CLI layer) and a non-empty
--operator-name.

NEVER sends WhatsApp / makes a call / dispatches a shipment / mutates
Order / Payment / Shipment / Customer / DiscountOfferLog.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.calls.outcome_classifier import apply_outcome_updates


def _sandbox_active() -> bool:
    try:
        from apps.ai_governance.sandbox import is_sandbox_enabled

        return bool(is_sandbox_enabled())
    except Exception:  # noqa: BLE001
        return False


class Command(BaseCommand):
    help = (
        "Phase 12B - Apply Director-approved CallOutcomeRecord rows to "
        "Lead.status. Requires --confirm-outcome-apply. Only records in "
        "review_status=approved with non-blank suggested_lead_status "
        "are applied; pending / skipped / applied / blank are no-ops. "
        "Sandbox mode skips the Lead.status update and records the "
        "intent."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--outcome-record-id",
            action="append",
            type=int,
            default=[],
            help=(
                "Specific record id(s) to apply. Pass multiple "
                "--outcome-record-id args. Default: all approved rows."
            ),
        )
        parser.add_argument(
            "--operator-name",
            required=True,
            help="Director name. Recorded on each applied row + audit.",
        )
        parser.add_argument(
            "--confirm-outcome-apply",
            action="store_true",
            help=(
                "REQUIRED explicit confirmation flag. Without this the "
                "command refuses with exit 1."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        if not options.get("confirm_outcome_apply"):
            err = (
                "REFUSED: --confirm-outcome-apply is required. This "
                "command mutates Lead.status."
            )
            if options.get("json"):
                self.stdout.write(
                    json.dumps({"ok": False, "error": err}, default=str)
                )
            else:
                self.stderr.write(err)
            sys.exit(1)

        record_ids = options.get("outcome_record_id") or None
        try:
            summary = apply_outcome_updates(
                operator_name=options["operator_name"],
                outcome_record_ids=record_ids,
                sandbox=_sandbox_active(),
            )
        except ValueError as exc:
            payload = {"ok": False, "error": str(exc)}
            if options.get("json"):
                self.stdout.write(json.dumps(payload, default=str))
            else:
                self.stderr.write(f"REFUSED: {exc}")
            sys.exit(1)

        if options.get("json"):
            self.stdout.write(json.dumps(summary, default=str))
            return
        self.stdout.write("Phase 12B - apply summary:")
        self.stdout.write(
            f"  total_applied          : {summary['total_applied']}"
        )
        self.stdout.write(
            f"  skipped_blank          : {summary['skipped_blank']}"
        )
        self.stdout.write(
            f"  skipped_sandbox        : {summary['skipped_sandbox']}"
        )
        self.stdout.write(f"  errors                 : {summary['errors']}")
        if summary.get("applied_record_ids"):
            self.stdout.write(
                f"  applied_record_ids     : "
                f"{summary['applied_record_ids']}"
            )
