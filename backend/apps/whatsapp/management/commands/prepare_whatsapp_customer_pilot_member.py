from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.whatsapp.pilot import (
    prepare_whatsapp_customer_pilot_member,
    get_whatsapp_pilot_readiness_summary,
)


class Command(BaseCommand):
    help = "Prepare an approved customer pilot member without sending WhatsApp messages."

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument(
            "--source",
            default="approved_customer_pilot",
        )
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        try:
            member, created_customer, created_member = (
                prepare_whatsapp_customer_pilot_member(
                    phone=options["phone"],
                    name=options["name"],
                    source=options.get("source") or "approved_customer_pilot",
                )
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        report = {
            "passed": True,
            "customerId": member.customer_id,
            "phoneMasked": member.phone_masked,
            "phoneSuffix": member.phone_suffix,
            "status": member.status,
            "consentVerified": member.consent_verified,
            "createdCustomer": created_customer,
            "createdPilotMember": created_member,
            "dailyCap": member.max_auto_replies_per_day,
            "auditEvents": ["whatsapp.pilot.member_prepared"],
            "nextAction": get_whatsapp_pilot_readiness_summary()["nextAction"],
        }
        if options.get("as_json"):
            self.stdout.write(json.dumps(report, default=str))
            return
        self.stdout.write("WhatsApp pilot member prepared")
        self.stdout.write(f"  customerId      : {report['customerId']}")
        self.stdout.write(f"  phone           : {report['phoneMasked']}")
        self.stdout.write(f"  status          : {report['status']}")
        self.stdout.write(f"  consentVerified : {report['consentVerified']}")
        self.stdout.write(f"  nextAction      : {report['nextAction']}")
