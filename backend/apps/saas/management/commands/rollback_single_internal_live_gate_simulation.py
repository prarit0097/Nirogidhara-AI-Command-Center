"""Rollback a Phase 6I internal simulation marker."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.live_gate_simulation import (
    rollback_single_internal_live_gate_simulation,
    serialize_live_gate_simulation,
)


class Command(BaseCommand):
    help = "Rollback a Phase 6I simulation. No business state is reverted."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--simulation-id", type=int, required=True)
        parser.add_argument("--reason", default="")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        row = rollback_single_internal_live_gate_simulation(
            options["simulation_id"],
            reason=options.get("reason") or "",
        )
        report = serialize_live_gate_simulation(row)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            f"Rolled back simulation {row.id}; externalCallWasMade=false"
        )
