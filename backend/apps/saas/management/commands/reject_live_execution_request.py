"""``python manage.py reject_live_execution_request --request-id <id>``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.live_gate import (
    _serialize_request,
    reject_live_execution_request,
)


class Command(BaseCommand):
    help = "Reject a live gate request. No provider call is made."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--request-id", required=True, type=int)
        parser.add_argument("--reason", default="")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        row = reject_live_execution_request(
            options["request_id"], rejector=None, reason=options.get("reason")
        )
        report = _serialize_request(row)
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(f"Rejected request {row.id}")
