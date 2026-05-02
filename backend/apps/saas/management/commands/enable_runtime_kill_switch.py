"""``python manage.py enable_runtime_kill_switch --scope global``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.live_gate import set_runtime_kill_switch


class Command(BaseCommand):
    help = "Enable a runtime live-execution kill switch."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--scope", default="global")
        parser.add_argument("--provider-type", default="")
        parser.add_argument("--operation-type", default="")
        parser.add_argument("--reason", default="")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        switch = set_runtime_kill_switch(
            enabled=True,
            scope=options["scope"],
            provider_type=options.get("provider_type") or "",
            operation_type=options.get("operation_type") or "",
            reason=options.get("reason") or "Operator enabled kill switch.",
        )
        report = {
            "id": switch.id,
            "scope": switch.scope,
            "enabled": switch.enabled,
            "reason": switch.reason,
            "externalCallWillBeMade": False,
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(f"Kill switch enabled for {switch.scope}")
