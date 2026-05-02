"""``python manage.py disable_runtime_kill_switch --scope global``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.live_gate import set_runtime_kill_switch


class Command(BaseCommand):
    help = (
        "Disable a runtime kill switch. Phase 6H still never executes "
        "external provider calls."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--scope", default="global")
        parser.add_argument("--provider-type", default="")
        parser.add_argument("--operation-type", default="")
        parser.add_argument("--reason", default="")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        switch = set_runtime_kill_switch(
            enabled=False,
            scope=options["scope"],
            provider_type=options.get("provider_type") or "",
            operation_type=options.get("operation_type") or "",
            reason=options.get("reason")
            or "Operator disabled kill switch for future gate simulation.",
        )
        report = {
            "id": switch.id,
            "scope": switch.scope,
            "enabled": switch.enabled,
            "reason": switch.reason,
            "externalCallWillBeMade": False,
            "warning": "Phase 6H approval still does not execute external calls.",
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            f"Kill switch disabled for {switch.scope}; no external call executed"
        )
