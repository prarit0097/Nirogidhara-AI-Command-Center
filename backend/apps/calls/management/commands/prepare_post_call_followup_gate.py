"""Phase 12C - Prepare a Phase 7E-Live-B gate for a queued follow-up.

The Phase 7E-Live-B gate row is created in draft status only. The actual
send still requires the Director to run the existing
`approve_phase7e_live_b_real_customer_gate` + `execute_phase7e_live_b_
real_customer_send` commands. This command itself NEVER sends WhatsApp,
makes a call, dispatches a shipment, or mutates Order / Payment.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.ai_governance.sandbox import is_sandbox_enabled
from apps.calls.post_call_followup import (
    PostCallFollowUpStateError,
    prepare_gate_for_follow_up,
)


class Command(BaseCommand):
    help = (
        "Phase 12C - Prepare a Phase 7E-Live-B gate for a queued "
        "PostCallFollowUpQueue row. Director must still approve + "
        "execute the gate separately."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "follow_up_id",
            type=int,
            help="PostCallFollowUpQueue id.",
        )
        parser.add_argument(
            "--operator-name",
            required=True,
            help="Operator preparing the gate (recorded on the gate row).",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        follow_up_id = int(options["follow_up_id"])
        operator_name = (options.get("operator_name") or "").strip()
        sandbox = is_sandbox_enabled()
        try:
            result = prepare_gate_for_follow_up(
                follow_up_id=follow_up_id,
                operator_name=operator_name,
                sandbox=sandbox,
            )
        except PostCallFollowUpStateError as exc:
            if options.get("json"):
                self.stdout.write(
                    json.dumps(
                        {"ok": False, "error": str(exc)}, default=str
                    )
                )
            self.stderr.write(f"REFUSED: {exc}")
            raise SystemExit(1) from exc

        if options.get("json"):
            self.stdout.write(json.dumps(result, default=str))
            return

        if result.get("ok"):
            self.stdout.write(
                f"Phase 12C: prepared Phase 7E-Live-B gate "
                f"{result.get('phase7e_gate_id')} for follow-up "
                f"#{follow_up_id} (status={result.get('status')}, "
                f"template={result.get('template_name')})."
            )
            self.stdout.write(
                "Next: approve_phase7e_live_b_real_customer_gate "
                f"--gate-id {result.get('phase7e_gate_id')} ..."
            )
        else:
            reason = result.get("reason") or "unknown"
            self.stdout.write(
                f"Phase 12C: gate NOT prepared for follow-up "
                f"#{follow_up_id} (status={result.get('status')}, "
                f"reason={reason})."
            )
            blockers = result.get("blockers")
            if blockers:
                self.stdout.write(f"  blockers: {blockers}")
            error_excerpt = result.get("error_excerpt")
            if error_excerpt:
                self.stdout.write(f"  error: {error_excerpt}")
