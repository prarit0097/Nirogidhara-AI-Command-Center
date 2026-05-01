"""``python manage.py prepare_whatsapp_internal_test_number``.

Phase 5F-Gate Internal Allowed-Number Cohort Tooling.

Safely registers an internal staff / test number in the DB so the
controlled WhatsApp AI auto-reply harness can run against it. The
operator must have already added the number to
``WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`` in ``.env.production``
before running this command.

LOCKED rules:

- REFUSES outright if the phone is not in
  ``WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS``.
- Creates / reuses a ``Customer`` row and grants
  ``WhatsAppConsent.consent_state = "granted"`` with the supplied
  source (default: ``"internal_cohort_test"``).
- NEVER sends a WhatsApp message.
- NEVER creates / mutates ``Order`` / ``Payment`` / ``Shipment`` /
  ``DiscountOfferLog`` rows.
- Writes one ``whatsapp.internal_cohort.number_prepared`` audit row.
  Audit payload carries phone last-4 only (never the full number),
  no tokens, no secrets.
- JSON output also masks the full phone — only the suffix is exposed
  by default.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer
from apps.whatsapp.meta_one_number_test import (
    _digits_only,
    _normalize_phone,
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
        "Register a Customer + grant WhatsAppConsent for an internal "
        "test number that is already on WHATSAPP_LIVE_META_ALLOWED_TEST_"
        "NUMBERS. Never sends, never mutates business state."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--phone",
            required=True,
            help="MSISDN (E.164 or digits) — must be on the allow-list.",
        )
        parser.add_argument(
            "--name",
            default="Internal Cohort Test",
            help="Display name for the Customer row.",
        )
        parser.add_argument(
            "--source",
            default="internal_cohort_test",
            help="WhatsAppConsent.source value.",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        phone_input = options.get("phone") or ""
        name = (options.get("name") or "Internal Cohort Test").strip()
        source = (options.get("source") or "internal_cohort_test").strip()
        normalized = _normalize_phone(phone_input)
        digits = _digits_only(phone_input)

        report: dict[str, Any] = {
            "passed": False,
            "phoneMasked": _mask_phone(digits),
            "suffix": digits[-4:] if digits else "",
            "toAllowed": False,
            "customerId": "",
            "consentState": "",
            "createdCustomer": False,
            "createdConsent": False,
            "auditEvents": [],
            "warnings": [],
            "errors": [],
            "nextAction": "",
        }

        if not phone_input:
            report["errors"].append("--phone is required.")
            report["nextAction"] = "supply_destination_number"
            self._emit(report, options)
            return

        # Provider + limited-mode preflight (defence in depth — the
        # allow-list guard fires below regardless, but this surfaces
        # config drift early in the JSON output).
        verification = verify_provider_and_credentials()
        if verification.provider != "meta_cloud":
            report["warnings"].append(
                f"WHATSAPP_PROVIDER={verification.provider!r} (not meta_cloud); "
                "the cohort send path will refuse until provider is meta_cloud."
            )
        if not verification.limited_test_mode:
            report["warnings"].append(
                "WHATSAPP_LIVE_META_LIMITED_TEST_MODE is not true; the "
                "limited-mode guard will allow non-allow-list sends until flipped."
            )

        # Allow-list gate — the only hard refusal in this command.
        report["toAllowed"] = is_number_allowed_for_live_meta_test(phone_input)
        if not report["toAllowed"]:
            report["errors"].append(
                "Destination is not on WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS. "
                "Refusing to register this number. Update .env.production "
                "and re-run."
            )
            report["nextAction"] = "add_number_to_allowed_list"
            self._emit(report, options)
            return

        # Find or create the Customer row.
        customer = self._find_customer(phone_input, digits, normalized)
        if customer is None:
            customer = Customer.objects.create(
                id=next_id("NRG-CUST", Customer, base=900001),
                name=name,
                phone=normalized or phone_input,
                state="",
                city="",
                language="hi",
                product_interest="",
                consent_whatsapp=True,
            )
            report["createdCustomer"] = True
        else:
            # Reuse the row but make sure consent_whatsapp is set so
            # the existing consent helpers see "granted".
            if not customer.consent_whatsapp:
                customer.consent_whatsapp = True
                customer.save(update_fields=["consent_whatsapp"])
        report["customerId"] = customer.id

        # Grant WhatsAppConsent (idempotent — update if it already
        # exists). Source / metadata documents the cohort test.
        consent, created = WhatsAppConsent.objects.get_or_create(
            customer=customer,
            defaults={
                "consent_state": WhatsAppConsent.State.GRANTED,
                "granted_at": timezone.now(),
                "source": source,
                "metadata": {
                    "reason": "Internal allowed-number WhatsApp AI cohort test",
                    "approved_by": "Prarit",
                    "limited_test_mode": True,
                    "phone_suffix": digits[-4:] if digits else "",
                },
            },
        )
        if not created:
            # Re-grant: ensure state is granted, refresh source +
            # granted_at, clear revoked_at if previously revoked.
            consent.consent_state = WhatsAppConsent.State.GRANTED
            consent.granted_at = timezone.now()
            consent.revoked_at = None
            consent.source = source or consent.source
            md = dict(consent.metadata or {})
            md.update(
                {
                    "reason": "Internal allowed-number WhatsApp AI cohort test",
                    "approved_by": "Prarit",
                    "limited_test_mode": True,
                    "phone_suffix": digits[-4:] if digits else "",
                }
            )
            consent.metadata = md
            consent.save(
                update_fields=[
                    "consent_state",
                    "granted_at",
                    "revoked_at",
                    "source",
                    "metadata",
                    "updated_at",
                ]
            )
        report["createdConsent"] = bool(created)
        report["consentState"] = consent.consent_state

        # Audit row — phone last-4 only, no full number, no tokens.
        write_event(
            kind="whatsapp.internal_cohort.number_prepared",
            text=(
                f"Internal cohort number prepared · "
                f"phone_suffix={digits[-4:] if digits else ''} · "
                f"customer={customer.id} · created_customer="
                f"{report['createdCustomer']} · created_consent="
                f"{report['createdConsent']}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "phone_suffix": digits[-4:] if digits else "",
                "customer_id": customer.id,
                "consent_state": consent.consent_state,
                "consent_source": consent.source,
                "created_customer": report["createdCustomer"],
                "created_consent": report["createdConsent"],
                "approved_by": "Prarit",
                "limited_test_mode": True,
            },
        )
        report["auditEvents"].append("whatsapp.internal_cohort.number_prepared")
        report["passed"] = True
        report["nextAction"] = "ready_for_controlled_scenario_test"
        self._emit(report, options)

    # ------------------------------------------------------------------

    def _find_customer(
        self, phone_input: str, digits: str, normalized: str
    ) -> Customer | None:
        candidates = [normalized, digits, phone_input]
        if digits:
            candidates.append(digits[-10:])
        seen: set[str] = set()
        for needle in candidates:
            if not needle or needle in seen:
                continue
            seen.add(needle)
            match = Customer.objects.filter(phone__iexact=needle).first()
            if match is not None:
                return match
        if digits:
            return Customer.objects.filter(
                phone__icontains=digits[-10:]
            ).first()
        return None

    def _emit(self, report: dict[str, Any], options) -> None:
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING("Prepare WhatsApp internal test number")
        )
        self.stdout.write(f"  passed         : {report['passed']}")
        self.stdout.write(f"  phoneMasked    : {report['phoneMasked']}")
        self.stdout.write(f"  toAllowed      : {report['toAllowed']}")
        self.stdout.write(f"  customerId     : {report['customerId']}")
        self.stdout.write(f"  consentState   : {report['consentState']}")
        self.stdout.write(f"  createdCustomer: {report['createdCustomer']}")
        self.stdout.write(f"  createdConsent : {report['createdConsent']}")
        if report["warnings"]:
            self.stdout.write(self.style.WARNING("warnings:"))
            for w in report["warnings"]:
                self.stdout.write(f"  - {w}")
        if report["errors"]:
            self.stdout.write(self.style.ERROR("errors:"))
            for e in report["errors"]:
                self.stdout.write(f"  - {e}")
        self.stdout.write(f"nextAction: {report['nextAction']}")
