"""Inspect Phase 6I single internal live-gate simulations."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.context import get_default_organization
from apps.saas.live_gate_simulation import (
    inspect_single_internal_live_gate_simulation,
)
from apps.saas.models import Organization


class Command(BaseCommand):
    help = "Inspect Phase 6I simulation readiness and latest rows."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--organization-code", default="")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        code = (options.get("organization_code") or "").strip()
        org = (
            Organization.objects.filter(code=code).first()
            if code
            else get_default_organization()
        )
        report = inspect_single_internal_live_gate_simulation(
            organization=org
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 6I single internal live-gate simulation"
            )
        )
        self.stdout.write(f"defaultOperation : {report['defaultOperation']}")
        self.stdout.write(f"simulations      : {report['simulationCount']}")
        self.stdout.write(f"killSwitchActive : {report['killSwitchActive']}")
        self.stdout.write(f"providerCall     : {report['providerCallAttempted']}")
        self.stdout.write(f"nextAction       : {report['nextAction']}")
