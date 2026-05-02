"""``python manage.py inspect_runtime_live_audit_gate --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.context import get_default_organization
from apps.saas.live_gate import summarize_live_gate_readiness
from apps.saas.models import Organization


class Command(BaseCommand):
    help = "Inspect the Phase 6H controlled runtime live audit gate."

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
        report = summarize_live_gate_readiness(org)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 6H runtime live audit gate")
        )
        self.stdout.write(f"organization      : {(report.get('organization') or {}).get('code')}")
        self.stdout.write(f"runtimeSource     : {report['runtimeSource']}")
        self.stdout.write(f"killSwitch.global : {report['killSwitch']['globalEnabled']}")
        self.stdout.write(f"safeToStart6I     : {report['safeToStartPhase6I']}")
        self.stdout.write(f"nextAction        : {report['nextAction']}")
