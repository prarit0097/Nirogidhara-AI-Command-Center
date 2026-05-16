"""Phase 11A — Read-only inspector for the transcript ingestion backlog.

Never mutates any row, never calls Vapi, never sends WhatsApp. Pure
read of `Call` + `CallTranscriptLine` for Director / operator review.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.calls.transcript_ingestion import (
    DEFAULT_WINDOW_DAYS,
    get_backlog_overview,
)


class Command(BaseCommand):
    help = (
        "Phase 11A — Read-only inspector for transcript ingestion "
        "backlog. Reports total calls in window, ingested count, "
        "backlog count + ratio, oldest/newest backlog ids. Read-only."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--window-days",
            type=int,
            default=DEFAULT_WINDOW_DAYS,
            help=(
                "Rolling window for the backlog summary. Default 30 "
                "matches the Phase 9E Calling Team Leader window."
            ),
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON instead of pretty output.",
        )

    def handle(self, *args, **options) -> None:
        overview = get_backlog_overview(
            window_days=int(options.get("window_days") or DEFAULT_WINDOW_DAYS)
        )
        if options.get("json"):
            self.stdout.write(json.dumps(overview, default=str))
            return
        self.stdout.write(
            f"Phase 11A — Transcript backlog overview "
            f"(window_days={overview['window_days']}):"
        )
        self.stdout.write(
            f"  total calls in window  : {overview['total_calls_in_window']}"
        )
        self.stdout.write(
            f"  ingested count         : {overview['ingested_count']}"
        )
        self.stdout.write(
            f"  backlog count          : {overview['backlog_count']}"
        )
        self.stdout.write(
            f"  backlog ratio          : {overview['backlog_ratio']:.4f}"
        )
        self.stdout.write(
            f"  oldest backlog at      : {overview['oldest_backlog_at']}"
        )
        self.stdout.write(
            f"  newest backlog at      : {overview['newest_backlog_at']}"
        )
        if overview["top_backlog"]:
            self.stdout.write("  top backlog (up to 10):")
            for row in overview["top_backlog"]:
                self.stdout.write(
                    f"    - {row['call_id']:<10} "
                    f"created={row['created_at']} "
                    f"vapi…{row['provider_call_id_last4']}"
                )
        else:
            self.stdout.write("  top backlog (up to 10) : none")
