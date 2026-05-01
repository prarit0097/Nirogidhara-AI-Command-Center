"""``python manage.py inspect_whatsapp_internal_cohort --json``.

Phase 5F-Gate Internal Allowed-Number Cohort Tooling.

Read-only inspector for the entire ``WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS``
allow-list. For each number it reports whether the corresponding
``Customer`` row exists, whether ``WhatsAppConsent`` is granted, and
whether the latest conversation has activity. Defaults to masked
output — full phone numbers only when ``--show-full-numbers`` is
explicitly passed (operator-only flag, never paste publicly).

LOCKED rules:

- Read-only. No DB write, no audit row, no provider call.
- No tokens / verify token / app secret in output.
- Phone numbers masked by default.
- Gracefully handles empty allow-list, missing Customer / Consent /
  Conversation, missing Meta credentials.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.whatsapp.meta_one_number_test import (
    _digits_only,
    _normalize_phone,
    check_waba_subscription,
    get_allowed_test_numbers,
    is_number_allowed_for_live_meta_test,
    verify_provider_and_credentials,
)
from apps.whatsapp.models import (
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
)


def _mask_phone(digits: str) -> str:
    """``919000099001`` → ``+91*****99001``."""
    if not digits:
        return ""
    if len(digits) <= 4:
        return "*" * len(digits)
    suffix = digits[-4:]
    if len(digits) >= 12:
        # ``+91*****99001`` shape so country code stays visible but
        # the middle stays masked.
        return f"+{digits[:2]}{'*' * 5}{suffix}"
    return f"{'*' * (len(digits) - 4)}{suffix}"


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _find_customer(digits: str) -> Customer | None:
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


class Command(BaseCommand):
    help = (
        "Read-only inspector for the WhatsApp internal allowed-number "
        "cohort. Reports per-number readiness for controlled scenario "
        "tests without sending messages or mutating DB."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")
        parser.add_argument(
            "--show-full-numbers",
            action="store_true",
            help=(
                "Operator-only: include full phone numbers in the report. "
                "Default off. Do not paste output publicly."
            ),
        )

    def handle(self, *args, **options) -> None:
        show_full = bool(options.get("show_full_numbers"))
        verification = verify_provider_and_credentials()

        report: dict[str, Any] = {
            "provider": verification.provider,
            "limitedTestMode": verification.limited_test_mode,
            "autoReplyEnabled": False,
            "callHandoffEnabled": False,
            "lifecycleEnabled": False,
            "rescueDiscountEnabled": False,
            "rtoRescueEnabled": False,
            "reorderEnabled": False,
            "allowedListSize": 0,
            "showFullNumbers": show_full,
            "cohort": [],
            "wabaSubscription": {},
            "warnings": [],
            "errors": [],
            "nextAction": "",
        }

        # Global automation flag snapshot. Helps the operator confirm
        # that the broad rollout flags are still off before the
        # cohort tests fire.
        from django.conf import settings

        report["autoReplyEnabled"] = bool(
            getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
        )
        report["callHandoffEnabled"] = bool(
            getattr(settings, "WHATSAPP_CALL_HANDOFF_ENABLED", False)
        )
        report["lifecycleEnabled"] = bool(
            getattr(settings, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED", False)
        )
        report["rescueDiscountEnabled"] = bool(
            getattr(settings, "WHATSAPP_RESCUE_DISCOUNT_ENABLED", False)
        )
        report["rtoRescueEnabled"] = bool(
            getattr(settings, "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED", False)
        )
        report["reorderEnabled"] = bool(
            getattr(settings, "WHATSAPP_REORDER_DAY20_ENABLED", False)
        )

        allow_list = get_allowed_test_numbers()
        report["allowedListSize"] = len(allow_list)

        # WABA subscription (best-effort — never raises).
        waba = check_waba_subscription()
        report["wabaSubscription"] = {
            "checked": waba.checked,
            "active": waba.active,
            "subscribedAppCount": waba.subscribed_app_count,
            "warning": waba.warning,
            "error": waba.error,
        }
        if waba.warning:
            report["warnings"].append(waba.warning)
        if waba.error:
            report["errors"].append(waba.error)

        # Per-number readiness.
        for digits in allow_list:
            entry: dict[str, Any] = {
                "maskedPhone": _mask_phone(digits),
                "suffix": digits[-4:] if digits else "",
                "normalizedDigits": digits,
                "customerFound": False,
                "customerId": "",
                "customerPhoneMasked": "",
                "consentFound": False,
                "consentState": "",
                "consentSource": "",
                "conversationFound": False,
                "latestInboundId": "",
                "latestOutboundId": "",
                "latestOutboundStatus": "",
                "latestOutboundAt": None,
                "latestAuditAt": None,
                "readyForControlledTest": False,
                "missingSetup": [],
            }
            if show_full:
                entry["fullPhone"] = f"+{digits}" if digits else ""
                entry["operatorOnlyNote"] = (
                    "Full phone visible because --show-full-numbers was passed; "
                    "do not paste this output publicly."
                )

            customer = _find_customer(digits)
            if customer is not None:
                entry["customerFound"] = True
                entry["customerId"] = customer.id
                entry["customerPhoneMasked"] = _mask_phone(
                    _digits_only(customer.phone)
                )
                if show_full:
                    entry["customerPhoneFull"] = customer.phone
                consent = (
                    WhatsAppConsent.objects.filter(customer=customer).first()
                )
                if consent is not None:
                    entry["consentFound"] = True
                    entry["consentState"] = consent.consent_state
                    entry["consentSource"] = consent.source
                else:
                    entry["missingSetup"].append("whatsapp_consent_row")
                convo = (
                    WhatsAppConversation.objects.filter(customer=customer)
                    .order_by("-updated_at")
                    .first()
                )
                if convo is not None:
                    entry["conversationFound"] = True
                    latest_in = (
                        WhatsAppMessage.objects.filter(
                            customer=customer,
                            direction=WhatsAppMessage.Direction.INBOUND,
                        )
                        .order_by("-created_at")
                        .first()
                    )
                    if latest_in is not None:
                        entry["latestInboundId"] = latest_in.id
                    latest_out = (
                        WhatsAppMessage.objects.filter(
                            customer=customer,
                            direction=WhatsAppMessage.Direction.OUTBOUND,
                        )
                        .order_by("-created_at")
                        .first()
                    )
                    if latest_out is not None:
                        entry["latestOutboundId"] = latest_out.id
                        entry["latestOutboundStatus"] = latest_out.status
                        entry["latestOutboundAt"] = _iso(latest_out.sent_at or latest_out.created_at)
                latest_audit = (
                    AuditEvent.objects.filter(
                        kind__startswith="whatsapp.",
                        payload__customer_id=customer.id,
                    )
                    .order_by("-occurred_at")
                    .first()
                )
                if latest_audit is not None:
                    entry["latestAuditAt"] = _iso(latest_audit.occurred_at)
            else:
                entry["missingSetup"].append("customer_row")
                entry["missingSetup"].append("whatsapp_consent_row")

            ready = (
                is_number_allowed_for_live_meta_test(f"+{digits}")
                and entry["customerFound"]
                and entry["consentState"] == "granted"
            )
            entry["readyForControlledTest"] = ready
            if not ready and "consent_state_granted" not in entry["missingSetup"]:
                if entry["customerFound"] and entry["consentState"] != "granted":
                    entry["missingSetup"].append("consent_state_granted")
            report["cohort"].append(entry)

        # Suggest the most-blocking next action.
        if not allow_list:
            report["nextAction"] = "add_numbers_to_allowed_list"
        elif waba.checked and waba.active is False:
            report["nextAction"] = "fix_waba_subscription"
        elif report["autoReplyEnabled"]:
            report["nextAction"] = "keep_global_auto_reply_off"
            report["warnings"].append(
                "WHATSAPP_AI_AUTO_REPLY_ENABLED is true; the controlled "
                "harness will refuse to run while the global flag is on."
            )
        elif any(not e["readyForControlledTest"] for e in report["cohort"]):
            report["nextAction"] = "register_missing_customers_or_consent"
        else:
            report["nextAction"] = "cohort_ready_for_manual_scenario_tests"

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self._render_text(report, show_full=show_full)

    def _render_text(self, report: dict[str, Any], *, show_full: bool) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING("WhatsApp internal cohort inspector")
        )
        self.stdout.write(f"  provider              : {report['provider']}")
        self.stdout.write(f"  limitedTestMode       : {report['limitedTestMode']}")
        self.stdout.write(f"  autoReplyEnabled      : {report['autoReplyEnabled']}")
        self.stdout.write(f"  callHandoffEnabled    : {report['callHandoffEnabled']}")
        self.stdout.write(f"  lifecycleEnabled      : {report['lifecycleEnabled']}")
        self.stdout.write(f"  rescueDiscountEnabled : {report['rescueDiscountEnabled']}")
        self.stdout.write(f"  rtoRescueEnabled      : {report['rtoRescueEnabled']}")
        self.stdout.write(f"  reorderEnabled        : {report['reorderEnabled']}")
        self.stdout.write(f"  allowedListSize       : {report['allowedListSize']}")
        sub = report["wabaSubscription"]
        self.stdout.write(
            f"  wabaActive            : {sub.get('active')} "
            f"(count={sub.get('subscribedAppCount')})"
        )
        for entry in report["cohort"]:
            self.stdout.write(
                f"  - {entry['maskedPhone']} · ready={entry['readyForControlledTest']} "
                f"· customer={entry['customerFound']} · consent={entry['consentState']}"
            )
            if entry["missingSetup"]:
                self.stdout.write(
                    f"      missing: {', '.join(entry['missingSetup'])}"
                )
        if report["warnings"]:
            self.stdout.write(self.style.WARNING("warnings:"))
            for w in report["warnings"]:
                self.stdout.write(f"  - {w}")
        if report["errors"]:
            self.stdout.write(self.style.ERROR("errors:"))
            for e in report["errors"]:
                self.stdout.write(f"  - {e}")
        self.stdout.write(f"nextAction: {report['nextAction']}")
        if show_full:
            self.stdout.write(
                self.style.WARNING(
                    "Full phone numbers were included because --show-full-numbers "
                    "was passed. Do not paste this output publicly."
                )
            )
