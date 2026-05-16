"""Phase 11B — Score ingested Vapi transcripts.

CLI-only. Never sends WhatsApp, makes a call, dispatches a shipment,
or mutates `Customer` / `Order` / `Payment` / `Lead` / `Shipment`.
The only mutation is `CallQualityScore` row creation/update.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.calls.quality_scorer import score_backlog, score_call


class Command(BaseCommand):
    help = (
        "Phase 11B — Deterministically score ingested call transcripts. "
        "Defaults to backlog mode (up to --limit calls). Pass --call-id "
        "to score one specific call. NEVER sends WhatsApp / makes a "
        "call / dispatches a shipment."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--call-id",
            default="",
            help="If set, score this single Call.id only.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max number of backlog calls to score in one run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute scores but do not persist any CallQualityScore rows.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON instead of pretty output.",
        )

    def handle(self, *args, **options) -> None:
        call_id = (options.get("call_id") or "").strip()
        dry_run = bool(options.get("dry_run"))
        if call_id:
            result = score_call(call_id, dry_run=dry_run)
            if options.get("json"):
                self.stdout.write(json.dumps(result, default=str))
                return
            self.stdout.write(
                f"Phase 11B — score call {call_id} (dry_run={dry_run}):"
            )
            self.stdout.write(f"  ok                       : {result.get('ok')}")
            self.stdout.write(f"  skipped                  : {result.get('skipped')}")
            if result.get("reason"):
                self.stdout.write(f"  reason                   : {result.get('reason')}")
            if result.get("ok"):
                self.stdout.write(
                    f"  connection_score         : {result.get('connection_score', 0)}"
                )
                self.stdout.write(
                    f"  product_knowledge_score  : {result.get('product_knowledge_score', 0)}"
                )
                self.stdout.write(
                    f"  compliance_score         : {result.get('compliance_score', 0)}"
                )
                self.stdout.write(
                    f"  objection_handling_score : {result.get('objection_handling_score', 0)}"
                )
                self.stdout.write(
                    f"  tonality_score           : {result.get('tonality_score', 0)}"
                )
                self.stdout.write(
                    f"  composite_score          : {result.get('composite_score', 0)}"
                )
                flags = ", ".join(result.get("flags") or []) or "none"
                self.stdout.write(f"  flags                    : {flags}")
            return

        summary = score_backlog(
            limit=int(options.get("limit") or 50),
            dry_run=dry_run,
        )
        if options.get("json"):
            self.stdout.write(json.dumps(summary, default=str))
            return
        self.stdout.write(
            f"Phase 11B — backlog scoring (dry_run={dry_run}):"
        )
        self.stdout.write(f"  total                : {summary['total']}")
        self.stdout.write(f"  scored               : {summary['scored']}")
        self.stdout.write(f"  skipped_already      : {summary['skipped_already']}")
        self.stdout.write(f"  skipped_no_call      : {summary['skipped_no_call']}")
        self.stdout.write(f"  errors               : {summary['errors']}")
        self.stdout.write(
            f"  avg_composite_score  : {summary['avg_composite_score']}"
        )
        self.stdout.write(f"  duration_ms          : {summary['duration_ms']}")
