"""``python manage.py preview_live_gate_decision --operation <type> --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.saas.context import get_default_organization
from apps.saas.live_gate import evaluate_live_execution_gate
from apps.saas.models import Organization


class Command(BaseCommand):
    help = "Preview a Phase 6H live gate decision. No provider call is made."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--operation", required=True)
        parser.add_argument("--live-requested", action="store_true")
        parser.add_argument("--organization-code", default="")
        parser.add_argument("--payload", default="{}")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        try:
            payload = _json.loads(options.get("payload") or "{}")
        except ValueError as exc:
            raise CommandError(f"Invalid JSON payload: {exc}") from exc
        if not isinstance(payload, dict):
            raise CommandError("--payload must be a JSON object")
        code = (options.get("organization_code") or "").strip()
        org = (
            Organization.objects.filter(code=code).first()
            if code
            else get_default_organization()
        )
        report = evaluate_live_execution_gate(
            options["operation"],
            organization=org,
            payload=payload,
            live_requested=bool(options.get("live_requested")),
            audit_preview=True,
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(self.style.MIGRATE_HEADING(report["operationType"]))
        for key in (
            "providerType",
            "dryRun",
            "liveExecutionRequested",
            "liveExecutionAllowed",
            "externalCallWillBeMade",
            "approvalRequired",
            "killSwitchActive",
            "gateDecision",
            "nextAction",
        ):
            self.stdout.write(f"{key:<28}: {report.get(key)}")
