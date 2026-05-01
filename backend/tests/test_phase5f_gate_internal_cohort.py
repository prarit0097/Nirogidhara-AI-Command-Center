"""Phase 5F-Gate Internal Allowed-Number Cohort Tooling tests.

Covers the three new management commands:

- ``inspect_whatsapp_internal_cohort`` — masks phones by default,
  reports per-number readiness, surfaces missing setup, never
  mutates the DB.
- ``prepare_whatsapp_internal_test_number`` — refuses non-allowed
  numbers, creates / reuses Customer, grants WhatsAppConsent, never
  sends, never creates Order/Payment/Shipment, writes one
  ``whatsapp.internal_cohort.number_prepared`` audit row.
- ``run_whatsapp_internal_cohort_dry_run`` — read-only loop that
  reports scenario readiness without sending or mutating anything.

Plus regression assertions:

- Existing final-send limited-mode guard still refuses non-allowed
  numbers.
"""
from __future__ import annotations

import io
import json
from typing import Any
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment
from apps.whatsapp import services as whatsapp_services
from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
)


META_CREDS = dict(
    WHATSAPP_PROVIDER="meta_cloud",
    WHATSAPP_LIVE_META_LIMITED_TEST_MODE=True,
    WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS=(
        "+91 89498 79990, +91 90000 99002, +91 90000 99003"
    ),
    META_WA_ACCESS_TOKEN="dummy-meta-token-not-real",
    META_WA_PHONE_NUMBER_ID="123456789",
    META_WA_BUSINESS_ACCOUNT_ID="987654321",
    META_WA_VERIFY_TOKEN="dummy-verify-token",
    META_WA_APP_SECRET="dummy-app-secret",
    WHATSAPP_AI_AUTO_REPLY_ENABLED=False,
    WHATSAPP_CALL_HANDOFF_ENABLED=False,
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=False,
    WHATSAPP_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_REORDER_DAY20_ENABLED=False,
)


def _run(command_name: str, **kwargs: Any) -> dict[str, Any]:
    out = io.StringIO()
    call_command(command_name, "--json", stdout=out, **kwargs)
    return json.loads(out.getvalue().strip().splitlines()[-1])


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-COHORT-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Cohort Test",
        phone_number="+91 9000099000",
        phone_number_id="meta-phone-number-id-1",
        business_account_id="meta-waba-id-1",
        status=WhatsAppConnection.Status.CONNECTED,
    )


@pytest.fixture
def first_allowed_customer(db):
    customer = Customer.objects.create(
        id="NRG-CUST-COHORT-1",
        name="First Allowed",
        phone="+918949879990",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=True,
    )
    WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={
            "consent_state": WhatsAppConsent.State.GRANTED,
            "granted_at": timezone.now(),
            "source": "test",
        },
    )
    return customer


# ---------------------------------------------------------------------------
# inspect_whatsapp_internal_cohort
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_inspect_cohort_masks_phones_by_default(connection, first_allowed_customer) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_internal_cohort.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_internal_cohort")
    assert report["showFullNumbers"] is False
    assert report["allowedListSize"] == 3
    blob = json.dumps(report)
    # Full E.164 must NEVER appear in the report when masked.
    assert "+918949879990" not in blob
    assert "+919000099002" not in blob
    assert "+919000099003" not in blob
    # Suffix appears so the operator can identify the entry.
    assert "9990" in blob
    assert "9002" in blob


@override_settings(**META_CREDS)
def test_inspect_cohort_reports_readiness_for_prepared_number(
    connection, first_allowed_customer
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_internal_cohort.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_internal_cohort")
    entries_by_suffix = {e["suffix"]: e for e in report["cohort"]}
    ready_entry = entries_by_suffix["9990"]
    assert ready_entry["customerFound"] is True
    assert ready_entry["consentState"] == "granted"
    assert ready_entry["readyForControlledTest"] is True
    assert ready_entry["missingSetup"] == []


@override_settings(**META_CREDS)
def test_inspect_cohort_handles_missing_customer(connection) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_internal_cohort.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_internal_cohort")
    not_ready = next(e for e in report["cohort"] if e["suffix"] == "9002")
    assert not_ready["customerFound"] is False
    assert not_ready["readyForControlledTest"] is False
    assert "customer_row" in not_ready["missingSetup"]
    assert report["nextAction"] == "register_missing_customers_or_consent"


@override_settings(**META_CREDS)
def test_inspect_cohort_handles_missing_consent_row(connection, db) -> None:
    customer = Customer.objects.create(
        id="NRG-CUST-COHORT-NOCONSENT",
        name="No Consent",
        phone="+919000099003",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=False,
    )
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_internal_cohort.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_internal_cohort")
    entry = next(e for e in report["cohort"] if e["suffix"] == "9003")
    assert entry["customerFound"] is True
    assert entry["consentFound"] is False
    assert entry["readyForControlledTest"] is False
    assert "whatsapp_consent_row" in entry["missingSetup"]


@override_settings(**META_CREDS)
def test_inspect_cohort_show_full_numbers_flag_exposes_full_phone(
    connection, first_allowed_customer
) -> None:
    out = io.StringIO()
    call_command(
        "inspect_whatsapp_internal_cohort",
        "--show-full-numbers",
        "--json",
        stdout=out,
    )
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert report["showFullNumbers"] is True
    blob = json.dumps(report)
    # Full phone now appears for the operator-only flag path.
    assert "+918949879990" in blob


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_inspect_cohort_warns_when_global_auto_reply_on(
    connection, first_allowed_customer
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_internal_cohort.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_internal_cohort")
    assert report["autoReplyEnabled"] is True
    assert report["nextAction"] == "keep_global_auto_reply_off"


@override_settings(
    **{**META_CREDS, "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS": ""}
)
def test_inspect_cohort_handles_empty_allow_list(connection) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_internal_cohort.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_internal_cohort")
    assert report["allowedListSize"] == 0
    assert report["cohort"] == []
    assert report["nextAction"] == "add_numbers_to_allowed_list"


@override_settings(**META_CREDS)
def test_inspect_cohort_does_not_mutate_db(connection, first_allowed_customer) -> None:
    audit_before = AuditEvent.objects.count()
    customer_before = Customer.objects.count()
    consent_before = WhatsAppConsent.objects.count()
    msg_before = WhatsAppMessage.objects.count()
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_internal_cohort.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        _run("inspect_whatsapp_internal_cohort")
    assert AuditEvent.objects.count() == audit_before
    assert Customer.objects.count() == customer_before
    assert WhatsAppConsent.objects.count() == consent_before
    assert WhatsAppMessage.objects.count() == msg_before


@override_settings(**META_CREDS)
def test_inspect_cohort_output_omits_secrets(connection, first_allowed_customer) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_internal_cohort.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_internal_cohort")
    blob = json.dumps(report).lower()
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob


# ---------------------------------------------------------------------------
# prepare_whatsapp_internal_test_number
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_prepare_refuses_non_allowed_number(connection, db) -> None:
    customer_before = Customer.objects.count()
    consent_before = WhatsAppConsent.objects.count()
    report = _run(
        "prepare_whatsapp_internal_test_number",
        phone="+919999999999",
        name="Outside Allow-list",
    )
    assert report["passed"] is False
    assert report["toAllowed"] is False
    assert report["nextAction"] == "add_number_to_allowed_list"
    # NO Customer / WhatsAppConsent created for a non-allowed number.
    assert Customer.objects.count() == customer_before
    assert WhatsAppConsent.objects.count() == consent_before


@override_settings(**META_CREDS)
def test_prepare_creates_customer_and_consent_for_allowed_number(
    connection, db
) -> None:
    customer_before = Customer.objects.count()
    consent_before = WhatsAppConsent.objects.count()
    report = _run(
        "prepare_whatsapp_internal_test_number",
        phone="+919000099002",
        name="Internal Staff Two",
    )
    assert report["passed"] is True
    assert report["toAllowed"] is True
    assert report["createdCustomer"] is True
    assert report["createdConsent"] is True
    assert report["consentState"] == "granted"
    assert Customer.objects.count() == customer_before + 1
    assert WhatsAppConsent.objects.count() == consent_before + 1
    customer = Customer.objects.get(pk=report["customerId"])
    assert customer.consent_whatsapp is True
    consent = WhatsAppConsent.objects.get(customer=customer)
    assert consent.consent_state == "granted"
    assert consent.source == "internal_cohort_test"


@override_settings(**META_CREDS)
def test_prepare_reuses_existing_customer_and_grants_consent(
    connection, first_allowed_customer
) -> None:
    consent = WhatsAppConsent.objects.get(customer=first_allowed_customer)
    consent.consent_state = WhatsAppConsent.State.REVOKED
    consent.revoked_at = timezone.now()
    consent.save(update_fields=["consent_state", "revoked_at"])
    customer_before = Customer.objects.count()
    consent_before = WhatsAppConsent.objects.count()
    report = _run(
        "prepare_whatsapp_internal_test_number",
        phone="+918949879990",
        name="Re-registered",
    )
    assert report["passed"] is True
    assert report["createdCustomer"] is False
    assert report["createdConsent"] is False
    # Counts unchanged (reuse path).
    assert Customer.objects.count() == customer_before
    assert WhatsAppConsent.objects.count() == consent_before
    consent.refresh_from_db()
    # Consent flipped back to granted, revoked_at cleared.
    assert consent.consent_state == "granted"
    assert consent.revoked_at is None


@override_settings(**META_CREDS)
def test_prepare_does_not_send_whatsapp_message(connection, db) -> None:
    msg_before = WhatsAppMessage.objects.count()
    convo_before = WhatsAppConversation.objects.count()
    _run(
        "prepare_whatsapp_internal_test_number",
        phone="+919000099002",
        name="Internal Staff Two",
    )
    assert WhatsAppMessage.objects.count() == msg_before
    assert WhatsAppConversation.objects.count() == convo_before


@override_settings(**META_CREDS)
def test_prepare_does_not_create_order_payment_shipment_discount(
    connection, db
) -> None:
    discount_before = DiscountOfferLog.objects.count()
    order_before = Order.objects.count()
    payment_before = Payment.objects.count()
    shipment_before = Shipment.objects.count()
    _run(
        "prepare_whatsapp_internal_test_number",
        phone="+919000099002",
        name="Internal Staff Two",
    )
    assert DiscountOfferLog.objects.count() == discount_before
    assert Order.objects.count() == order_before
    assert Payment.objects.count() == payment_before
    assert Shipment.objects.count() == shipment_before


@override_settings(**META_CREDS)
def test_prepare_writes_audit_event(connection, db) -> None:
    _run(
        "prepare_whatsapp_internal_test_number",
        phone="+919000099002",
        name="Internal Staff Two",
    )
    audit = AuditEvent.objects.filter(
        kind="whatsapp.internal_cohort.number_prepared"
    ).first()
    assert audit is not None
    payload = audit.payload
    assert payload["phone_suffix"] == "9002"
    assert payload["consent_state"] == "granted"
    assert payload["limited_test_mode"] is True
    # Audit payload must NOT contain the full phone number.
    assert "+919000099002" not in json.dumps(payload)
    # Audit payload must NEVER carry tokens / secrets.
    for key in payload.keys():
        assert "token" not in key.lower()
        assert "secret" not in key.lower()


@override_settings(**META_CREDS)
def test_prepare_output_masks_phone_and_omits_secrets(connection, db) -> None:
    report = _run(
        "prepare_whatsapp_internal_test_number",
        phone="+919000099002",
        name="Internal Staff Two",
    )
    blob = json.dumps(report)
    assert "9002" in report["phoneMasked"]
    assert "+919000099002" not in blob  # full phone not exposed
    assert META_CREDS["META_WA_ACCESS_TOKEN"] not in blob
    assert META_CREDS["META_WA_VERIFY_TOKEN"] not in blob
    assert META_CREDS["META_WA_APP_SECRET"] not in blob


# ---------------------------------------------------------------------------
# run_whatsapp_internal_cohort_dry_run
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_cohort_dry_run_reports_per_number_readiness(
    connection, first_allowed_customer
) -> None:
    report = _run("run_whatsapp_internal_cohort_dry_run")
    assert report["allowedListSize"] == 3
    entries = {e["suffix"]: e for e in report["cohort"]}
    ready = entries["9990"]
    assert ready["customerFound"] is True
    assert ready["consentGranted"] is True
    assert ready["scenarioReadiness"]["normal_product_info_ready"] is True
    not_ready = entries["9002"]
    assert not_ready["customerFound"] is False
    assert not_ready["scenarioReadiness"]["discount_objection_ready"] is False
    assert report["nextAction"] == "register_missing_customers_or_consent"


@override_settings(**META_CREDS)
def test_cohort_dry_run_does_not_send_or_mutate(
    connection, first_allowed_customer
) -> None:
    msg_before = WhatsAppMessage.objects.count()
    audit_before = AuditEvent.objects.count()
    _run("run_whatsapp_internal_cohort_dry_run")
    assert WhatsAppMessage.objects.count() == msg_before
    assert AuditEvent.objects.count() == audit_before


# ---------------------------------------------------------------------------
# Defence-in-depth: existing limited-mode guard still blocks non-allowed
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_existing_limited_mode_guard_still_blocks_non_allowed_after_cohort_changes(
    connection,
) -> None:
    customer = Customer.objects.create(
        id="NRG-CUST-COHORT-OUT",
        name="Outside Allow-list",
        phone="+919999999999",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=True,
    )
    WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={
            "consent_state": WhatsAppConsent.State.GRANTED,
            "granted_at": timezone.now(),
            "source": "test",
        },
    )
    convo = WhatsAppConversation.objects.create(
        id="WCV-COHORT-OUT",
        customer=customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
    )
    with pytest.raises(whatsapp_services.WhatsAppServiceError) as excinfo:
        whatsapp_services.send_freeform_text_message(
            customer=customer,
            conversation=convo,
            body="grounded reply",
            actor_role="ai_chat",
            actor_agent="ai_chat",
        )
    assert excinfo.value.block_reason == "limited_test_number_not_allowed"
