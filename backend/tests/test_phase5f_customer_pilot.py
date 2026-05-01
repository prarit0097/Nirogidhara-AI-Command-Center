from __future__ import annotations

import io
import json
from typing import Any

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment
from apps.whatsapp.models import (
    WhatsAppConsent,
    WhatsAppMessage,
    WhatsAppPilotCohortMember,
)
from apps.whatsapp.pilot import get_whatsapp_pilot_readiness_summary


META_CREDS = dict(
    WHATSAPP_PROVIDER="meta_cloud",
    WHATSAPP_LIVE_META_LIMITED_TEST_MODE=True,
    WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS="+91 90000 99001",
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


def _customer(
    *,
    id: str = "NRG-CUST-PILOT-1",
    phone: str = "+919000099001",
    consent: bool = False,
) -> Customer:
    return Customer.objects.create(
        id=id,
        name="Pilot Customer",
        phone=phone,
        state="MH",
        city="Pune",
        language="Hinglish",
        product_interest="Weight Management",
        consent_whatsapp=consent,
    )


def _grant_consent(customer: Customer) -> None:
    customer.consent_whatsapp = True
    customer.save(update_fields=["consent_whatsapp"])
    WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={
            "consent_state": WhatsAppConsent.State.GRANTED,
            "granted_at": timezone.now(),
            "source": "approved_customer_pilot",
        },
    )


def _counts() -> dict[str, int]:
    return {
        "orders": Order.objects.count(),
        "payments": Payment.objects.count(),
        "shipments": Shipment.objects.count(),
        "discounts": DiscountOfferLog.objects.count(),
        "messages": WhatsAppMessage.objects.count(),
    }


@override_settings(**META_CREDS)
def test_pilot_inspect_command_is_read_only(db) -> None:
    before = {
        **_counts(),
        "customers": Customer.objects.count(),
        "members": WhatsAppPilotCohortMember.objects.count(),
        "audits": AuditEvent.objects.count(),
    }
    report = _run("inspect_whatsapp_customer_pilot")
    after = {
        **_counts(),
        "customers": Customer.objects.count(),
        "members": WhatsAppPilotCohortMember.objects.count(),
        "audits": AuditEvent.objects.count(),
    }
    assert report["totalPilotMembers"] == 0
    assert before == after


@override_settings(**META_CREDS)
def test_prepare_pilot_member_creates_customer_pending_without_consent(db) -> None:
    before = _counts()
    report = _run(
        "prepare_whatsapp_customer_pilot_member",
        phone="+919000099001",
        name="Approved Pilot Customer",
        source="approved_customer_pilot",
    )
    assert report["createdCustomer"] is True
    assert report["createdPilotMember"] is True
    assert report["status"] == "pending"
    assert report["consentVerified"] is False
    assert WhatsAppPilotCohortMember.objects.count() == 1
    assert _counts() == before


@override_settings(**META_CREDS)
def test_prepare_pilot_member_reuses_customer_and_approves_when_consent_exists(db) -> None:
    customer = _customer(consent=True)
    _grant_consent(customer)
    report = _run(
        "prepare_whatsapp_customer_pilot_member",
        phone="+919000099001",
        name="Approved Pilot Customer",
        source="approved_customer_pilot",
    )
    assert report["createdCustomer"] is False
    assert report["status"] == "approved"
    assert report["consentVerified"] is True
    assert WhatsAppPilotCohortMember.objects.get(customer=customer).status == "approved"


@override_settings(**META_CREDS)
def test_consent_missing_blocks_ready_state(db) -> None:
    _run(
        "prepare_whatsapp_customer_pilot_member",
        phone="+919000099001",
        name="No Consent",
    )
    report = get_whatsapp_pilot_readiness_summary(hours=1)
    assert report["consentMissingCount"] == 1
    assert report["readyForPilotCount"] == 0
    assert report["members"][0]["ready"] is False
    assert "consent_not_verified" in report["members"][0]["blockers"]


@override_settings(**META_CREDS)
def test_approved_consent_member_becomes_ready(db) -> None:
    customer = _customer(consent=True)
    _grant_consent(customer)
    _run(
        "prepare_whatsapp_customer_pilot_member",
        phone="+919000099001",
        name="Ready Customer",
    )
    report = get_whatsapp_pilot_readiness_summary(hours=1)
    assert report["readyForPilotCount"] == 1
    assert report["members"][0]["ready"] is True


@override_settings(**META_CREDS)
def test_pause_member_makes_not_ready(db) -> None:
    customer = _customer(consent=True)
    _grant_consent(customer)
    _run(
        "prepare_whatsapp_customer_pilot_member",
        phone="+919000099001",
        name="Ready Customer",
    )
    report = _run(
        "pause_whatsapp_customer_pilot_member",
        phone="+919000099001",
        reason="pilot paused by director",
    )
    assert report["status"] == "paused"
    summary = get_whatsapp_pilot_readiness_summary(hours=1)
    assert summary["pausedCount"] == 1
    assert summary["readyForPilotCount"] == 0


@override_settings(**META_CREDS)
def test_pilot_json_never_exposes_full_phone(db) -> None:
    customer = _customer(consent=True)
    _grant_consent(customer)
    _run(
        "prepare_whatsapp_customer_pilot_member",
        phone="+919000099001",
        name="Masked Customer",
    )
    inspect_report = _run("inspect_whatsapp_customer_pilot")
    prepare_report = _run(
        "prepare_whatsapp_customer_pilot_member",
        phone="+919000099001",
        name="Masked Customer",
    )
    blob = json.dumps({"inspect": inspect_report, "prepare": prepare_report})
    assert "+919000099001" not in blob
    assert "9001" in blob


@override_settings(**META_CREDS)
def test_pilot_api_returns_masked_phones(admin_user, auth_client, db) -> None:
    customer = _customer(consent=True)
    _grant_consent(customer)
    _run(
        "prepare_whatsapp_customer_pilot_member",
        phone="+919000099001",
        name="Masked Customer",
    )
    client = auth_client(admin_user)
    res = client.get(reverse("v1-whatsapp-monitoring-pilot"))
    assert res.status_code == 200
    body = res.json()
    blob = json.dumps(body)
    assert body["totalPilotMembers"] == 1
    assert "+919000099001" not in blob
    assert "9001" in blob


@override_settings(**META_CREDS)
def test_monitoring_overview_includes_pilot_summary(admin_user, auth_client, db) -> None:
    client = auth_client(admin_user)
    res = client.get(reverse("v1-whatsapp-monitoring-overview"))
    assert res.status_code == 200
    assert "pilot" in res.json()


@override_settings(**META_CREDS)
def test_pilot_prepare_and_pause_write_audit_events(db) -> None:
    _run(
        "prepare_whatsapp_customer_pilot_member",
        phone="+919000099001",
        name="Audited Customer",
    )
    _run(
        "pause_whatsapp_customer_pilot_member",
        phone="+919000099001",
        reason="pause",
    )
    assert AuditEvent.objects.filter(kind="whatsapp.pilot.member_prepared").exists()
    assert AuditEvent.objects.filter(kind="whatsapp.pilot.member_paused").exists()
    blob = json.dumps(
        list(
            AuditEvent.objects.filter(kind__startswith="whatsapp.pilot").values_list(
                "payload", flat=True
            )
        )
    )
    assert "+919000099001" not in blob


@override_settings(**META_CREDS)
def test_pilot_no_send_or_business_mutation(db) -> None:
    before = _counts()
    _run(
        "prepare_whatsapp_customer_pilot_member",
        phone="+919000099001",
        name="No Send",
    )
    _run(
        "pause_whatsapp_customer_pilot_member",
        phone="+919000099001",
        reason="no send",
    )
    assert _counts() == before


@override_settings(**META_CREDS)
def test_pilot_api_blocks_non_admin(operations_user, auth_client, db) -> None:
    client = auth_client(operations_user)
    res = client.get(reverse("v1-whatsapp-monitoring-pilot"))
    assert res.status_code in (401, 403)


@override_settings(**META_CREDS)
def test_pilot_api_rejects_post(admin_user, auth_client, db) -> None:
    client = auth_client(admin_user)
    res = client.post(reverse("v1-whatsapp-monitoring-pilot"), {})
    assert res.status_code == 405
