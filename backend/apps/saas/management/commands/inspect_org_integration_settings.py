"""``python manage.py inspect_org_integration_settings --json``."""
from __future__ import annotations

import json as _json

from django.core.management.base import BaseCommand

from apps.saas.integration_settings import get_org_integration_readiness
from apps.saas.selectors import get_default_organization


class Command(BaseCommand):
    help = "Read-only Phase 6E per-org integration settings diagnostic."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        org = get_default_organization()
        readiness = get_org_integration_readiness(org)
        providers = [
            {
                "organization": readiness["organization"],
                "provider_type": provider["providerType"],
                "status": provider["status"],
                "is_active": provider["isActive"],
                "secretRefsPresent": provider["secretRefsPresent"],
                "validation_status": provider["validationStatus"],
                "runtimeEnabled": False,
                "warnings": provider["warnings"],
                "nextAction": provider["nextAction"],
            }
            for provider in readiness["providers"]
        ]
        report = {
            "organization": readiness["organization"],
            "providers": providers,
            "runtimeUsesPerOrgSettings": False,
            "warnings": readiness["warnings"],
            "nextAction": readiness["nextAction"],
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 6E integration settings")
        )
        self.stdout.write(f"organization: {report['organization']}")
        for provider in providers:
            self.stdout.write(
                "  {provider_type}: status={status} active={is_active} "
                "secretRefsPresent={secretRefsPresent} runtimeEnabled=False"
                .format(**provider)
            )
        self.stdout.write(f"nextAction: {report['nextAction']}")
