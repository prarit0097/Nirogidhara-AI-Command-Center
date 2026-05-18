"""Phase 12A - Execute an approved AI Calling Campaign Gate.

THIS is the only CLI in Phase 12A that may dispatch Vapi calls (and
only when AI_CALLING_ENABLED=true + --confirm-ai-calling-campaign +
inside the approved UTC window + kill switch on + VAPI_MODE=live).
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.calls.ai_calling_gate import (
    AiCallCampaignGateError,
    execute_campaign_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 12A - Execute an approved AiCallCampaignGate. Dispatches "
        "Vapi calls only when every guard passes (AI_CALLING_ENABLED=true "
        "+ --confirm-ai-calling-campaign + inside the approved UTC window "
        "+ runtime kill switch on + VAPI_MODE=live). sandbox / mock / test "
        "modes record per-lead skip audits instead of dispatching."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("gate_id", type=int)
        parser.add_argument(
            "--operator-name",
            required=True,
            help="Director name.",
        )
        parser.add_argument(
            "--confirm-ai-calling-campaign",
            action="store_true",
            help=(
                "Required explicit confirmation flag. Without this the "
                "execute path refuses."
            ),
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        try:
            result = execute_campaign_gate(
                gate_id=int(options["gate_id"]),
                operator_name=options["operator_name"],
                confirm_ai_calling=bool(
                    options.get("confirm_ai_calling_campaign")
                ),
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
            f"  calls_attempted        : {result['calls_attempted']}"
        )
        self.stdout.write(
            f"  calls_dispatched       : {result['calls_dispatched']}"
        )
        self.stdout.write(f"  calls_skipped          : {result['calls_skipped']}")
        self.stdout.write(
            f"  vapi_mode_at_execute   : {result['vapi_mode_at_execute']}"
        )
        self.stdout.write(f"  sandbox                : {result['sandbox']}")
        self.stdout.write(f"  duration_ms            : {result['duration_ms']}")
        if result.get("skip_reasons"):
            self.stdout.write("  skip reasons:")
            for reason, count in result["skip_reasons"].items():
                self.stdout.write(f"    - {reason}: {count}")
