"""Phase 11A — Pull Vapi transcripts for backlogged Call rows.

CLI-only. Never sends WhatsApp, makes a call, dispatches a shipment,
or mutates `Order` / `Payment` / `Customer` / `Lead` / `Shipment`
rows. The only mutation is `CallTranscriptLine` row creation +
`Call.transcript_ingested_at` / `Call.transcript_line_count`.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.calls.transcript_ingestion import (
    ingest_backlog,
    ingest_call_transcript,
)


class Command(BaseCommand):
    help = (
        "Phase 11A — Pull Vapi transcripts for backlogged Call rows. "
        "Defaults to backlog mode (up to --limit calls). Pass --call-id "
        "to ingest one specific call. NEVER sends WhatsApp / makes a "
        "call / dispatches a shipment."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--call-id",
            default="",
            help=(
                "If set, ingest the transcript for this single Call.id "
                "instead of running the backlog."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max number of backlog calls to process in one run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch transcripts but do not persist any rows.",
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
            result = ingest_call_transcript(call_id, dry_run=dry_run)
            if options.get("json"):
                self.stdout.write(json.dumps(result, default=str))
                return
            self.stdout.write(
                f"Phase 11A — ingest call {call_id} "
                f"(dry_run={dry_run}):"
            )
            self.stdout.write(f"  ok           : {result.get('ok')}")
            self.stdout.write(f"  skipped      : {result.get('skipped')}")
            self.stdout.write(f"  reason       : {result.get('reason', '')}")
            self.stdout.write(
                f"  line_count   : {result.get('line_count', 0)}"
            )
            return

        summary = ingest_backlog(
            limit=int(options.get("limit") or 50),
            dry_run=dry_run,
        )
        if options.get("json"):
            self.stdout.write(json.dumps(summary, default=str))
            return
        self.stdout.write(
            f"Phase 11A — backlog ingest (dry_run={dry_run}):"
        )
        self.stdout.write(f"  total                  : {summary['total']}")
        self.stdout.write(f"  ingested               : {summary['ingested']}")
        self.stdout.write(
            f"  skipped_no_id          : {summary['skipped_no_id']}"
        )
        self.stdout.write(
            f"  skipped_already_done   : {summary['skipped_already_done']}"
        )
        self.stdout.write(
            f"  skipped_no_transcript  : {summary['skipped_no_transcript']}"
        )
        self.stdout.write(f"  errors                 : {summary['errors']}")
        self.stdout.write(
            f"  duration_ms            : {summary['duration_ms']}"
        )
