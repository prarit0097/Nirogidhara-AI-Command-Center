"""``python manage.py archive_single_provider_execution_attempt --execution-id <ID> --reason "..." --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand, CommandError

from apps.saas.models import RuntimeProviderExecutionAttempt
from apps.saas.provider_execution import (
    archive_single_provider_execution_attempt,
    serialize_execution_attempt,
)


class Command(BaseCommand):
    help = "Archive a Phase 6K execution attempt. No provider call."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--execution-id", required=True, help="Execution id"
        )
        parser.add_argument("--reason", default="", help="Audit reason")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        execution_id = options["execution_id"]
        if not RuntimeProviderExecutionAttempt.objects.filter(
            execution_id=execution_id
        ).exists():
            raise CommandError(
                f"Provider execution attempt not found: {execution_id}"
            )
        attempt = archive_single_provider_execution_attempt(
            execution_id, reason=options.get("reason") or ""
        )
        Status = RuntimeProviderExecutionAttempt.Status
        report = {
            "passed": attempt.status == Status.ARCHIVED,
            **serialize_execution_attempt(attempt),
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(self.style.MIGRATE_HEADING("Phase 6K archive"))
        self.stdout.write(f"  status:    {attempt.status}")
