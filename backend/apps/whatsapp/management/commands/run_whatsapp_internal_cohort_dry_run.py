"""``python manage.py run_whatsapp_internal_cohort_dry_run --json``.

Phase 5F-Gate Internal Allowed-Number Cohort Tooling.

Loops the entire ``WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`` allow-list
and reports per-number readiness for the five controlled scenarios
(normal product info / discount objection / safety block / legal
block / human request) — without sending a single message and without
mutating any DB row.

Use this between deploys to confirm the cohort is wired up before
running ``run_controlled_ai_auto_reply_test`` per number.

LOCKED rules:

- Read-only. No DB write, no audit row, no provider call, no LLM
  dispatch.
- No tokens / verify token / app secret in output.
- Phone numbers masked by default.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand

from apps.crm.models import Customer
from apps.whatsapp.meta_one_number_test import (
    _digits_only,
    get_allowed_test_numbers,
    is_number_allowed_for_live_meta_test,
    verify_provider_and_credentials,
)
from apps.whatsapp.models import WhatsAppConsent


def _mask_phone(digits: str) -> str:
    if not digits:
        return ""
    if len(digits) <= 4:
        return "*" * len(digits)
    suffix = digits[-4:]
    if len(digits) >= 12:
        return f"+{digits[:2]}{'*' * 5}{suffix}"
    return f"{'*' * (len(digits) - 4)}{suffix}"


class Command(BaseCommand):
    help = (
        "Loop the WhatsApp allowed-number cohort and report per-number "
        "scenario readiness. Read-only — no sends, no DB writes."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        verification = verify_provider_and_credentials()
        allow_list = get_allowed_test_numbers()

        report: dict[str, Any] = {
            "provider": verification.provider,
            "limitedTestMode": verification.limited_test_mode,
            "allowedListSize": len(allow_list),
            "cohort": [],
            "warnings": [],
            "errors": [],
            "nextAction": "",
        }

        if not allow_list:
            report["warnings"].append(
                "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS is empty — add "
                "internal staff numbers in .env.production first."
            )
            report["nextAction"] = "add_numbers_to_allowed_list"
            self._emit(report, options)
            return

        for digits in allow_list:
            entry = {
                "maskedPhone": _mask_phone(digits),
                "suffix": digits[-4:] if digits else "",
                "toAllowed": is_number_allowed_for_live_meta_test(
                    f"+{digits}"
                ),
                "customerFound": False,
                "consentGranted": False,
                "scenarioReadiness": {
                    "normal_product_info_ready": False,
                    "discount_objection_ready": False,
                    "safety_block_ready": False,
                    "legal_block_ready": False,
                    "human_request_ready": False,
                },
                "missingSetup": [],
            }

            customer = self._find_customer(digits)
            if customer is not None:
                entry["customerFound"] = True
                consent = (
                    WhatsAppConsent.objects.filter(customer=customer).first()
                )
                if consent is not None and consent.consent_state == "granted":
                    entry["consentGranted"] = True
                else:
                    entry["missingSetup"].append("whatsapp_consent_granted")
            else:
                entry["missingSetup"].append("customer_row")
                entry["missingSetup"].append("whatsapp_consent_granted")

            base_ready = (
                entry["toAllowed"]
                and entry["customerFound"]
                and entry["consentGranted"]
            )
            # All five scenarios share the same backend gates: allow-
            # list + Customer + granted consent. Safety / legal /
            # human scenarios additionally rely on the inbound
            # vocabulary, which the operator supplies at run time.
            entry["scenarioReadiness"] = {
                "normal_product_info_ready": bool(base_ready),
                "discount_objection_ready": bool(base_ready),
                "safety_block_ready": bool(base_ready),
                "legal_block_ready": bool(base_ready),
                "human_request_ready": bool(base_ready),
            }
            report["cohort"].append(entry)

        all_ready = all(
            entry["scenarioReadiness"]["normal_product_info_ready"]
            for entry in report["cohort"]
        )
        report["nextAction"] = (
            "cohort_ready_for_manual_scenario_tests"
            if all_ready
            else "register_missing_customers_or_consent"
        )

        self._emit(report, options)

    def _find_customer(self, digits: str) -> Customer | None:
        if not digits:
            return None
        candidates = {f"+{digits}", digits, digits[-10:] if len(digits) >= 10 else digits}
        for needle in candidates:
            if not needle:
                continue
            match = Customer.objects.filter(phone__iexact=needle).first()
            if match is not None:
                return match
        return Customer.objects.filter(phone__icontains=digits[-10:]).first()

    def _emit(self, report: dict[str, Any], options) -> None:
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("WhatsApp internal cohort dry-run")
        )
        self.stdout.write(f"  provider        : {report['provider']}")
        self.stdout.write(f"  limitedTestMode : {report['limitedTestMode']}")
        self.stdout.write(f"  allowedListSize : {report['allowedListSize']}")
        for entry in report["cohort"]:
            self.stdout.write(
                f"  - {entry['maskedPhone']} · customer={entry['customerFound']} "
                f"· consent_granted={entry['consentGranted']}"
            )
        if report["warnings"]:
            self.stdout.write(self.style.WARNING("warnings:"))
            for w in report["warnings"]:
                self.stdout.write(f"  - {w}")
        self.stdout.write(f"nextAction: {report['nextAction']}")
