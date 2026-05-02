"""``python manage.py request_live_execution_approval --operation <type>``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.saas.context import get_default_organization
from apps.saas.live_gate import (
    _serialize_request,
    create_live_execution_request,
)
from apps.saas.models import Organization


class Command(BaseCommand):
    help = "Create an audit-only live execution approval request."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--operation", required=True)
        parser.add_argument("--reason", default="")
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
        if options.get("reason"):
            payload = {**payload, "reason": options["reason"]}
        code = (options.get("organization_code") or "").strip()
        org = (
            Organization.objects.filter(code=code).first()
            if code
            else get_default_organization()
        )
        row = create_live_execution_request(
            options["operation"],
            organization=org,
            payload=payload,
            live_requested=True,
        )
        report = _serialize_request(row)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            f"Created request {row.id}; externalCallWillBeMade=false"
        )
