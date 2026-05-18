"""Phase 12B - Approve a CallOutcomeRecord (Director CLI).

NEVER mutates Lead.status. This only flips the record's review_status
from pending -> approved. Lead.status mutation happens via the
separate apply_call_outcome_updates command.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.calls.outcome_classifier import approve_record


class Command(BaseCommand):
    help = (
        "Phase 12B - Director approve a CallOutcomeRecord. Flips "
        "review_status from pending to approved. NEVER mutates "
        "Lead.status; use apply_call_outcome_updates separately."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("outcome_record_id", type=int)
        parser.add_argument(
            "--operator-name",
            required=True,
            help="Director name (recorded on the audit row).",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        try:
            record = approve_record(
                outcome_record_id=int(options["outcome_record_id"]),
                operator_name=options["operator_name"],
            )
        except ValueError as exc:
            payload = {"ok": False, "error": str(exc)}
            if options.get("json"):
                self.stdout.write(json.dumps(payload, default=str))
            else:
                self.stderr.write(f"REFUSED: {exc}")
            sys.exit(1)
        payload = {
            "ok": True,
            "outcome_record_id": record.pk,
            "review_status": record.review_status,
            "lead_id": record.lead_id,
            "suggested_lead_status": record.suggested_lead_status,
        }
        if options.get("json"):
            self.stdout.write(json.dumps(payload, default=str))
            return
        self.stdout.write(
            f"Phase 12B - CallOutcomeRecord {record.pk} {record.review_status}."
        )
        self.stdout.write(f"  lead_id                : {record.lead_id}")
        self.stdout.write(
            f"  suggested_lead_status  : "
            f"{record.suggested_lead_status or '(no change)'}"
        )
        self.stdout.write("")
        self.stdout.write(
            "Next: python manage.py apply_call_outcome_updates "
            f"--outcome-record-id {record.pk} --operator-name '<NAME>' "
            "--confirm-outcome-apply"
        )
