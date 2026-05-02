"""Prepare a Phase 6I single internal live-gate simulation."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.saas.context import get_default_organization
from apps.saas.live_gate_simulation import (
    DEFAULT_SIMULATION_OPERATION,
    prepare_single_internal_live_gate_simulation,
    serialize_live_gate_simulation,
)
from apps.saas.models import Organization


class Command(BaseCommand):
    help = "Prepare a Phase 6I simulation without provider calls."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--operation", default=DEFAULT_SIMULATION_OPERATION)
        parser.add_argument("--organization-code", default="")
        parser.add_argument("--payload", default="")
        parser.add_argument("--reason", default="")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        payload = None
        if options.get("payload"):
            try:
                payload = _json.loads(options["payload"])
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
        try:
            row = prepare_single_internal_live_gate_simulation(
                operation_type=options["operation"],
                organization=org,
                payload=payload,
                reason=options.get("reason") or "",
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        report = serialize_live_gate_simulation(row)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            f"Prepared simulation {row.id}; providerCallAttempted=false"
        )
