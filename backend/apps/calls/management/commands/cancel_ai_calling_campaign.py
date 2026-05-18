"""Phase 12A - Cancel an AI Calling Campaign Gate before execution.

Allowed from draft or approved. Refuses if the gate is already in
executing / completed / failed / cancelled state.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.calls.ai_calling_gate import (
    AiCallCampaignGateError,
    cancel_campaign_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 12A - Cancel an AiCallCampaignGate. Allowed from draft "
        "or approved; refused after execution starts."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("gate_id", type=int)
        parser.add_argument(
            "--operator-name",
            required=True,
            help="Director name.",
        )
        parser.add_argument(
            "--reason",
            default="",
            help="Free-form cancellation reason recorded on the gate metadata.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        try:
            result = cancel_campaign_gate(
                gate_id=int(options["gate_id"]),
                operator_name=options["operator_name"],
                reason=options.get("reason") or "",
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
            f"Phase 12A - AiCallCampaignGate {result['gate_id']} cancelled."
        )
        if result.get("reason"):
            self.stdout.write(f"  reason : {result['reason']}")
