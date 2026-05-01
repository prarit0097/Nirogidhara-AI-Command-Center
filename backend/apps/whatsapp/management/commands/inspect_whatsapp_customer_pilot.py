from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.whatsapp.pilot import get_whatsapp_pilot_readiness_summary


class Command(BaseCommand):
    help = "Read-only approved customer pilot readiness report."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument("--hours", type=float, default=2.0)

    def handle(self, *args, **options):
        report = get_whatsapp_pilot_readiness_summary(
            hours=options.get("hours") or 2.0
        )
        if options.get("as_json"):
            self.stdout.write(json.dumps(report, default=str))
            return
        self.stdout.write("WhatsApp approved customer pilot readiness")
        self.stdout.write(f"  totalPilotMembers : {report['totalPilotMembers']}")
        self.stdout.write(f"  approved          : {report['approvedCount']}")
        self.stdout.write(f"  pending           : {report['pendingCount']}")
        self.stdout.write(f"  paused            : {report['pausedCount']}")
        self.stdout.write(f"  consentMissing    : {report['consentMissingCount']}")
        self.stdout.write(f"  ready             : {report['readyForPilotCount']}")
        self.stdout.write(f"  nextAction        : {report['nextAction']}")
        for member in report["members"]:
            self.stdout.write(
                "  - "
                f"{member['maskedPhone']} {member['status']} "
                f"ready={member['ready']} cap={member['dailyCap']}"
            )
