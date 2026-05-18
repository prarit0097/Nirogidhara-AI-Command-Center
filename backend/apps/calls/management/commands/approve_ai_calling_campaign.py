"""Phase 12A - Director approve an AI Calling Campaign Gate.

Requires structured BEGIN_UTC/END_UTC markers and a non-empty intent.
NEVER dispatches a call - approval just records Director sign-off.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.calls.ai_calling_gate import (
    AiCallCampaignGateError,
    approve_campaign_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 12A - Director approve an AiCallCampaignGate. Records "
        "intent + structured 30-min UTC window. NEVER dispatches a call."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("gate_id", type=int)
        parser.add_argument(
            "--operator-name",
            required=True,
            help="Director name.",
        )
        parser.add_argument(
            "--intent",
            required=True,
            help="Director's stated purpose (e.g. 'first Tier-4 live batch').",
        )
        parser.add_argument(
            "--director-signoff",
            required=True,
            help=(
                "Director sign-off text. MUST contain BEGIN_UTC=<ISO-Z> "
                "and END_UTC=<ISO-Z> markers; window length <= 30 min."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        try:
            result = approve_campaign_gate(
                gate_id=int(options["gate_id"]),
                operator_name=options["operator_name"],
                intent=options["intent"],
                director_signoff=options["director_signoff"],
            )
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
            f"{result['status']}."
        )
        self.stdout.write(
            f"  window_start_utc : {result['window_start_utc']}"
        )
        self.stdout.write(
            f"  window_end_utc   : {result['window_end_utc']}"
        )
        self.stdout.write(
            f"  window valid     : {result['recorded_signoff_window_valid']}"
        )
        self.stdout.write("")
        self.stdout.write(result["next_action"])
