"""``python manage.py sync_whatsapp_templates``.

Phase 5A entrypoint for refreshing the local mirror of Meta-approved
templates. With no ``--from-file`` argument the command seeds the
canonical lifecycle templates so dev / CI runs always have working rows.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.whatsapp.services import get_active_connection
from apps.whatsapp.template_registry import sync_templates_from_provider


class Command(BaseCommand):
    help = (
        "Sync WhatsApp templates from Meta (or seed defaults). "
        "Phase 5A reads a JSON file when --from-file is supplied; otherwise "
        "seeds the canonical lifecycle templates."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--from-file",
            dest="from_file",
            default=None,
            help="Path to a JSON file shaped like Meta's GET /message_templates response.",
        )
        parser.add_argument(
            "--actor",
            dest="actor",
            default="cli",
            help="Audit actor token (default: cli).",
        )

    def handle(self, *args, **options) -> None:
        connection = get_active_connection()
        payload = None
        from_file = options.get("from_file")
        if from_file:
            path = Path(from_file)
            if not path.exists():
                raise CommandError(f"File not found: {from_file}")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise CommandError(f"Invalid JSON in {from_file}: {exc}") from exc

        result = sync_templates_from_provider(
            connection=connection,
            payload=payload,
            actor=options.get("actor") or "cli",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"WhatsApp template sync complete: created={result['createdCount']} "
                f"updated={result['updatedCount']} total={result['totalProcessed']}"
            )
        )
