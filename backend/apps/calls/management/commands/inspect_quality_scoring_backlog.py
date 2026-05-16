"""Phase 11B — Read-only inspector for the call quality scoring backlog.

Never mutates any row, never calls a provider, never sends WhatsApp.
Pure read of `Call` + `CallQualityScore` for Director / operator
review.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.calls.quality_scorer import get_scoring_overview


class Command(BaseCommand):
    help = (
        "Phase 11B — Read-only inspector for call quality scoring "
        "backlog. Reports total scored, avg composite, top 5 flagged "
        "issues, low-compliance count, per-agent averages. Read-only."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--window-days",
            type=int,
            default=30,
            help="Rolling window for the scoring summary. Default 30.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON instead of pretty output.",
        )

    def handle(self, *args, **options) -> None:
        overview = get_scoring_overview(
            window_days=int(options.get("window_days") or 30)
        )
        if options.get("json"):
            self.stdout.write(json.dumps(overview, default=str))
            return
        self.stdout.write(
            f"Phase 11B — Call quality scoring overview "
            f"(window_days={overview['window_days']}):"
        )
        self.stdout.write(
            f"  total scored         : {overview['total_scored']}"
        )
        self.stdout.write(
            f"  backlog count        : {overview['backlog_count']}"
        )
        self.stdout.write(
            f"  avg composite        : {overview['avg_composite']}"
        )
        self.stdout.write(
            f"  low compliance count : {overview['low_compliance_count']}"
        )
        if overview["top_flags"]:
            self.stdout.write("  top flags:")
            for row in overview["top_flags"]:
                self.stdout.write(
                    f"    - {row['flag_code']:<28} count={row['count']}"
                )
        else:
            self.stdout.write("  top flags            : none")
        if overview["avg_by_agent"]:
            self.stdout.write("  avg by agent (top 10):")
            for row in overview["avg_by_agent"][:10]:
                self.stdout.write(
                    f"    - {row['agent_label']:<30} "
                    f"calls={row['call_count']:<4} "
                    f"composite={row['avg_composite']:<6} "
                    f"compliance={row['avg_compliance']}"
                )
        else:
            self.stdout.write("  avg by agent (top 10): none")
