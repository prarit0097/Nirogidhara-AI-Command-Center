"""Phase 12A - Read-only inspector for an AI Calling Campaign Gate."""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.calls.ai_calling_gate import (
    AiCallCampaignGateError,
    inspect_campaign_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 12A - Read-only inspector for an AiCallCampaignGate. "
        "Shows gate details + per-lead phone (masked last-4) + stage + "
        "frequency-limit status. Never mutates anything."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("gate_id", type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        try:
            result = inspect_campaign_gate(int(options["gate_id"]))
        except AiCallCampaignGateError as exc:
            payload = {"ok": False, "error_code": exc.code, "error": exc.message}
            if options.get("json"):
                self.stdout.write(json.dumps(payload, default=str))
            else:
                self.stderr.write(f"REFUSED [{exc.code}]: {exc.message}")
            sys.exit(1)

        if options.get("json"):
            self.stdout.write(json.dumps(result, default=str))
            return
        self.stdout.write(
            f"Phase 12A - AiCallCampaignGate {result['gate_id']} "
            f"(status={result['status']}):"
        )
        self.stdout.write(f"  operator_name          : {result['operator_name']}")
        self.stdout.write(
            f"  stage_filter           : {', '.join(result['stage_filter'])}"
        )
        self.stdout.write(f"  max_leads              : {result['max_leads']}")
        self.stdout.write(
            f"  leads_selected_count   : {result['leads_selected_count']}"
        )
        self.stdout.write(
            f"  leads_attempted_count  : {result['leads_attempted_count']}"
        )
        self.stdout.write(
            f"  calls_dispatched       : {result['calls_dispatched']}"
        )
        self.stdout.write(f"  calls_skipped          : {result['calls_skipped']}")
        self.stdout.write(f"  prepared_at            : {result['prepared_at']}")
        self.stdout.write(f"  approved_at            : {result['approved_at']}")
        self.stdout.write(f"  executed_at            : {result['executed_at']}")
        self.stdout.write(f"  completed_at           : {result['completed_at']}")
        self.stdout.write(f"  cancelled_at           : {result['cancelled_at']}")
        self.stdout.write(
            f"  window (UTC)           : "
            f"{result['recorded_signoff_window_start_utc']} -> "
            f"{result['recorded_signoff_window_end_utc']}"
        )
        self.stdout.write(
            f"  window valid           : {result['recorded_signoff_window_valid']}"
        )
        self.stdout.write(
            f"  vapi_mode_at_execute   : {result['vapi_mode_at_execute'] or '-'}"
        )
        self.stdout.write(f"  sandbox                : {result['sandbox']}")
        self.stdout.write(
            f"  assistant_id (last 4)  : {result['ai_assistant_id_last4']}"
        )
        if result["leads"]:
            self.stdout.write("  leads:")
            for row in result["leads"]:
                phone = row.get("phone_last4", "")
                phone_str = f"***{phone}" if phone else "***"
                self.stdout.write(
                    f"    - {row['lead_id']:<14} "
                    f"stage={row['status']:<20} "
                    f"phone={phone_str:<8} "
                    f"recently_called={row['recently_called']}"
                )
        else:
            self.stdout.write("  leads                  : (none)")
