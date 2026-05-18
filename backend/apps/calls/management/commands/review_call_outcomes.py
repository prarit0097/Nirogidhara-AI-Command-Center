"""Phase 12B - Read-only Director review surface for classified outcomes.

NEVER mutates anything. Director uses this to scan suggestions before
approving / applying via separate CLI commands.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.calls.models import CallOutcomeRecord


class Command(BaseCommand):
    help = (
        "Phase 12B - Read-only review surface for CallOutcomeRecord "
        "rows. Filters by --status (default pending) and --campaign-id."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--status",
            default="pending",
            help=(
                "Filter by review_status. Default 'pending'. Pass 'all' "
                "to show every status."
            ),
        )
        parser.add_argument(
            "--campaign-id",
            type=int,
            default=0,
            help="Filter to records linked to this Phase 12A campaign gate.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max rows to show. Default 50.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        qs = CallOutcomeRecord.objects.all()
        status = (options.get("status") or "").strip()
        if status and status != "all":
            qs = qs.filter(review_status=status)
        if options.get("campaign_id"):
            qs = qs.filter(campaign_gate_id=int(options["campaign_id"]))
        limit = max(1, min(200, int(options.get("limit") or 50)))
        rows = list(qs.order_by("-classified_at")[:limit])

        if options.get("json"):
            self.stdout.write(
                json.dumps(
                    [
                        {
                            "id": r.pk,
                            "call_id": r.call_id,
                            "lead_id": r.lead_id,
                            "current_lead_status": r.current_lead_status,
                            "detected_outcome": r.detected_outcome,
                            "suggested_lead_status": (
                                r.suggested_lead_status
                            ),
                            "confidence": r.confidence,
                            "review_status": r.review_status,
                            "classified_at": r.classified_at.isoformat(),
                            "evidence_excerpt": {
                                "conversion_signals_found": (
                                    r.evidence.get(
                                        "conversion_signals_found"
                                    )
                                    or []
                                ),
                                "callback_signals_found": (
                                    r.evidence.get(
                                        "callback_signals_found"
                                    )
                                    or []
                                ),
                                "rejection_signals_found": (
                                    r.evidence.get(
                                        "rejection_signals_found"
                                    )
                                    or []
                                ),
                                "transcript_line_count": (
                                    r.evidence.get(
                                        "transcript_line_count"
                                    )
                                    or 0
                                ),
                            },
                        }
                        for r in rows
                    ],
                    default=str,
                )
            )
            return

        self.stdout.write(
            f"Phase 12B - CallOutcomeRecord listing ({len(rows)} row(s); "
            f"status={status}; campaign_id={options.get('campaign_id') or 'any'}):"
        )
        if not rows:
            self.stdout.write("  (none)")
            return
        for r in rows:
            signals = (
                "conv=" + str(
                    len(r.evidence.get("conversion_signals_found") or [])
                )
                + " cb=" + str(
                    len(r.evidence.get("callback_signals_found") or [])
                )
                + " rej=" + str(
                    len(r.evidence.get("rejection_signals_found") or [])
                )
            )
            self.stdout.write(
                f"  #{r.pk:<5} call={r.call_id:<12} lead={r.lead_id:<10} "
                f"{r.detected_outcome:<26} -> "
                f"{r.suggested_lead_status or '(no change)':<22} "
                f"[{r.confidence:<6}] {r.review_status:<10} {signals}"
            )
