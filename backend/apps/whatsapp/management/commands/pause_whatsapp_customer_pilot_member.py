from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.whatsapp.pilot import pause_whatsapp_customer_pilot_member


class Command(BaseCommand):
    help = "Pause an approved customer pilot member without sending messages."

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        try:
            member = pause_whatsapp_customer_pilot_member(
                phone=options["phone"],
                reason=options["reason"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        report = {
            "passed": True,
            "customerId": member.customer_id,
            "phoneMasked": member.phone_masked,
            "phoneSuffix": member.phone_suffix,
            "status": member.status,
            "reason": options["reason"],
            "auditEvents": ["whatsapp.pilot.member_paused"],
            "nextAction": "pilot_member_paused_review_before_resume",
        }
        if options.get("as_json"):
            self.stdout.write(json.dumps(report, default=str))
            return
        self.stdout.write("WhatsApp pilot member paused")
        self.stdout.write(f"  customerId : {report['customerId']}")
        self.stdout.write(f"  phone      : {report['phoneMasked']}")
        self.stdout.write(f"  status     : {report['status']}")
        self.stdout.write(f"  reason     : {report['reason']}")
