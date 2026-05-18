"""Phase 12A - Prepare an AI Calling Campaign Gate (Director CLI).

CLI-only. NEVER calls a provider; only selects eligible Leads + creates
a draft `AiCallCampaignGate` row.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.calls.ai_calling_gate import (
    AiCallCampaignGateError,
    prepare_campaign_gate,
)


class Command(BaseCommand):
    help = (
        "Phase 12A - Prepare an AI Calling Campaign Gate. Selects "
        "eligible Leads (stage filter + frequency limit) and creates a "
        "draft gate row. NEVER calls Vapi or any provider."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--stage",
            action="append",
            default=[],
            help=(
                "Lead.status value to include. Pass multiple --stage "
                "args to add more. Default: New / AI Calling Started / "
                "Interested / Callback Required."
            ),
        )
        parser.add_argument(
            "--max-leads",
            type=int,
            default=0,
            help="Max leads in the campaign. 0 = use AI_CALLING_MAX_PER_CAMPAIGN.",
        )
        parser.add_argument(
            "--assistant-id",
            default="",
            help="Vapi assistant id override. Default: settings.VAPI_ASSISTANT_ID.",
        )
        parser.add_argument(
            "--operator-name",
            required=True,
            help="Director / operator name.",
        )
        parser.add_argument(
            "--operator-note",
            default="",
            help="Free-form note recorded on the gate.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        try:
            result = prepare_campaign_gate(
                operator_name=options["operator_name"],
                stage_filter=options.get("stage") or None,
                max_leads=(
                    int(options.get("max_leads") or 0) or None
                ),
                ai_assistant_id=options.get("assistant_id") or "",
                operator_note=options.get("operator_note") or "",
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
        self.stdout.write("Phase 12A - AI calling campaign prepared.")
        self.stdout.write(f"  gate_id                : {result['gate_id']}")
        self.stdout.write(f"  status                 : {result['status']}")
        self.stdout.write(
            f"  stage_filter           : {', '.join(result['stage_filter'])}"
        )
        self.stdout.write(f"  max_leads              : {result['max_leads']}")
        self.stdout.write(
            f"  leads_selected_count   : {result['leads_selected_count']}"
        )
        self.stdout.write(
            f"  ai_assistant_id_present: {result['ai_assistant_id_present']}"
        )
        self.stdout.write("")
        self.stdout.write(result["next_action"])
