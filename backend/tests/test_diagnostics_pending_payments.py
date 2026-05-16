from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.calls.models import Call
from apps.crm.models import Customer
from apps.diagnostics.service import (
    DEFAULT_LIMIT,
    list_pending_payments_drilldown,
)
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConversation,
    WhatsAppMessage,
)


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_customer(*, customer_id: str, phone: str) -> Customer:
    return Customer.objects.create(
        id=customer_id,
        name=f"Customer {customer_id}",
        phone=phone,
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
    )


def _make_order(
    *,
    order_id: str,
    phone: str,
    stage: str = Order.Stage.CONFIRMED.value,
    state: str = "Delhi",
    amount: int = 3000,
) -> Order:
    return Order.objects.create(
        id=order_id,
        customer_name="Test Customer",
        phone=phone,
        product="Nirogidhara",
        quantity=1,
        amount=amount,
        state=state,
        city="Delhi",
        stage=stage,
    )


def _make_payment(
    *,
    payment_id: str,
    order_id: str,
    phone: str = "",
    customer_name: str | None = None,
    status: str = Payment.Status.PENDING.value,
    amount: int = 3000,
    payment_url: str = "https://rzp.io/test/pending-001",
    created_offset_days: int = 1,
) -> Payment:
    label = customer_name or (
        f"Customer {phone[-4:]}" if phone else "Customer"
    )
    payment = Payment.objects.create(
        id=payment_id,
        order_id=order_id,
        customer=label,
        customer_phone=phone,
        amount=amount,
        status=status,
        payment_url=payment_url,
        gateway=Payment.Gateway.RAZORPAY,
    )
    if created_offset_days:
        Payment.objects.filter(pk=payment.pk).update(
            created_at=timezone.now() - timedelta(days=created_offset_days)
        )
        payment.refresh_from_db()
    return payment


def _make_call(
    *,
    call_id: str,
    phone: str,
    status: str = Call.Status.COMPLETED.value,
    created_offset_hours: float = 1.0,
) -> Call:
    call = Call.objects.create(
        id=call_id,
        lead_id="LD-DIAG",
        customer="Customer",
        phone=phone,
        agent="AI-Agent",
        language="Hindi",
        status=status,
    )
    if created_offset_hours:
        Call.objects.filter(pk=call.pk).update(
            created_at=timezone.now()
            - timedelta(hours=created_offset_hours)
        )
        call.refresh_from_db()
    return call


def _get_or_create_connection() -> WhatsAppConnection:
    connection, _ = WhatsAppConnection.objects.get_or_create(
        id="WAC-DIAG-001",
        defaults={
            "provider": WhatsAppConnection.Provider.MOCK,
            "display_name": "Diagnostics Test",
            "phone_number": "+91 9000099000",
            "status": WhatsAppConnection.Status.CONNECTED,
        },
    )
    return connection


def _make_outbound_whatsapp(
    *,
    customer: Customer,
    message_id: str,
    created_offset_hours: float = 2.0,
) -> WhatsAppMessage:
    connection = _get_or_create_connection()
    conversation, _ = WhatsAppConversation.objects.get_or_create(
        customer=customer,
        defaults={
            "id": f"WACV-{customer.id}",
            "connection": connection,
        },
    )
    msg = WhatsAppMessage.objects.create(
        id=message_id,
        conversation=conversation,
        customer=customer,
        direction=WhatsAppMessage.Direction.OUTBOUND.value,
        status=WhatsAppMessage.Status.SENT.value,
        type=WhatsAppMessage.Type.TEMPLATE.value,
        body="reminder",
    )
    if created_offset_hours:
        WhatsAppMessage.objects.filter(pk=msg.pk).update(
            created_at=timezone.now()
            - timedelta(hours=created_offset_hours)
        )
        msg.refresh_from_db()
    return msg


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


def test_drilldown_returns_only_pending_when_partial_excluded():
    _make_order(order_id="NRG-DIAG-1", phone="+919999990001")
    _make_payment(
        payment_id="PAY-DIAG-1",
        order_id="NRG-DIAG-1",
        phone="+919999990001",
        status=Payment.Status.PENDING.value,
    )
    _make_order(order_id="NRG-DIAG-2", phone="+919999990002")
    _make_payment(
        payment_id="PAY-DIAG-2",
        order_id="NRG-DIAG-2",
        phone="+919999990002",
        status=Payment.Status.PARTIAL.value,
    )
    _make_order(order_id="NRG-DIAG-3", phone="+919999990003")
    _make_payment(
        payment_id="PAY-DIAG-3",
        order_id="NRG-DIAG-3",
        phone="+919999990003",
        status=Payment.Status.PAID.value,
    )
    pending_only = list_pending_payments_drilldown(include_partial=False)
    assert {row["payment_id"] for row in pending_only} == {"PAY-DIAG-1"}
    both = list_pending_payments_drilldown(include_partial=True)
    assert {row["payment_id"] for row in both} == {"PAY-DIAG-1", "PAY-DIAG-2"}


def test_drilldown_sorted_oldest_first():
    _make_order(order_id="NRG-DIAG-OLD", phone="+919999990010")
    _make_order(order_id="NRG-DIAG-NEW", phone="+919999990011")
    _make_payment(
        payment_id="PAY-OLD",
        order_id="NRG-DIAG-OLD",
        phone="+919999990010",
        created_offset_days=30,
    )
    _make_payment(
        payment_id="PAY-NEW",
        order_id="NRG-DIAG-NEW",
        phone="+919999990011",
        created_offset_days=1,
    )
    rows = list_pending_payments_drilldown()
    assert [r["payment_id"] for r in rows] == ["PAY-OLD", "PAY-NEW"]
    assert rows[0]["days_since_creation"] >= rows[1]["days_since_creation"]


def test_drilldown_days_since_creation_matches_offset():
    _make_order(order_id="NRG-DIAG-DAY", phone="+919999990020")
    _make_payment(
        payment_id="PAY-DAY",
        order_id="NRG-DIAG-DAY",
        phone="+919999990020",
        created_offset_days=7,
    )
    rows = list_pending_payments_drilldown()
    assert rows[0]["days_since_creation"] == 7


def test_drilldown_populates_last_whatsapp_and_call_metadata():
    customer = _make_customer(
        customer_id="C-DIAG-WA", phone="+919999990030"
    )
    _make_order(order_id="NRG-DIAG-WA", phone=customer.phone)
    _make_payment(
        payment_id="PAY-DIAG-WA",
        order_id="NRG-DIAG-WA",
        phone=customer.phone,
    )
    _make_outbound_whatsapp(
        customer=customer,
        message_id="WAM-DIAG-1",
        created_offset_hours=4,
    )
    _make_call(
        call_id="CL-DIAG-1",
        phone=customer.phone,
        status=Call.Status.COMPLETED.value,
        created_offset_hours=12,
    )
    rows = list_pending_payments_drilldown()
    assert rows[0]["last_whatsapp_at"] is not None
    assert rows[0]["last_call_at"] is not None
    assert rows[0]["last_call_outcome"] == Call.Status.COMPLETED.value


def test_drilldown_last_communication_metadata_null_when_no_history():
    _make_order(order_id="NRG-DIAG-NO-HIST", phone="+919999990040")
    _make_payment(
        payment_id="PAY-DIAG-NO-HIST",
        order_id="NRG-DIAG-NO-HIST",
        phone="+919999990040",
    )
    rows = list_pending_payments_drilldown()
    assert rows[0]["last_whatsapp_at"] is None
    assert rows[0]["last_call_at"] is None
    assert rows[0]["last_call_outcome"] is None


def test_drilldown_limit_param_respected():
    for i in range(5):
        _make_order(
            order_id=f"NRG-DIAG-L{i}", phone=f"+91999999005{i}"
        )
        _make_payment(
            payment_id=f"PAY-DIAG-L{i}",
            order_id=f"NRG-DIAG-L{i}",
            phone=f"+91999999005{i}",
            created_offset_days=i + 1,
        )
    rows = list_pending_payments_drilldown(limit=3)
    assert len(rows) == 3


def test_drilldown_state_filter():
    _make_order(
        order_id="NRG-DIAG-DEL",
        phone="+919999990060",
        state="Delhi",
    )
    _make_order(
        order_id="NRG-DIAG-MUM",
        phone="+919999990061",
        state="Mumbai",
    )
    _make_payment(
        payment_id="PAY-DEL",
        order_id="NRG-DIAG-DEL",
        phone="+919999990060",
    )
    _make_payment(
        payment_id="PAY-MUM",
        order_id="NRG-DIAG-MUM",
        phone="+919999990061",
    )
    rows = list_pending_payments_drilldown(state_filter="delhi")
    assert {row["payment_id"] for row in rows} == {"PAY-DEL"}


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


def test_api_requires_authentication(auth_client):
    client = auth_client(None)
    response = client.get(reverse("diagnostics:pending-payments"))
    assert response.status_code in {401, 403}


def test_api_non_admin_forbidden(auth_client, operations_user):
    client = auth_client(operations_user)
    response = client.get(reverse("diagnostics:pending-payments"))
    assert response.status_code == 403


def test_api_admin_can_read(auth_client, admin_user):
    _make_order(order_id="NRG-DIAG-API", phone="+919999990070")
    _make_payment(
        payment_id="PAY-DIAG-API",
        order_id="NRG-DIAG-API",
        phone="+919999990070",
    )
    client = auth_client(admin_user)
    response = client.get(reverse("diagnostics:pending-payments"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["results"][0]["payment_id"] == "PAY-DIAG-API"
    assert payload["filters"]["include_partial"] is True


def test_api_include_partial_false(auth_client, admin_user):
    _make_order(order_id="NRG-DIAG-PEND", phone="+919999990080")
    _make_payment(
        payment_id="PAY-PEND",
        order_id="NRG-DIAG-PEND",
        phone="+919999990080",
        status=Payment.Status.PENDING.value,
    )
    _make_order(order_id="NRG-DIAG-PART", phone="+919999990081")
    _make_payment(
        payment_id="PAY-PART",
        order_id="NRG-DIAG-PART",
        phone="+919999990081",
        status=Payment.Status.PARTIAL.value,
    )
    client = auth_client(admin_user)
    response = client.get(
        reverse("diagnostics:pending-payments"),
        {"include_partial": "false"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert {row["payment_id"] for row in payload["results"]} == {"PAY-PEND"}


def test_api_rejects_post_patch_delete(auth_client, admin_user):
    client = auth_client(admin_user)
    url = reverse("diagnostics:pending-payments")
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(url, {})
        assert response.status_code == 405


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


def test_cli_command_runs_and_lists_pending_payments():
    _make_order(order_id="NRG-DIAG-CLI", phone="+919999990090")
    _make_payment(
        payment_id="PAY-CLI",
        order_id="NRG-DIAG-CLI",
        phone="+919999990090",
    )
    out = StringIO()
    call_command("inspect_pending_payments", stdout=out)
    output = out.getvalue()
    assert "PAY-CLI" in output
    assert "NRG-DIAG-CLI" in output
    assert "Total: 1" in output


def test_cli_command_json_output_parses():
    _make_order(order_id="NRG-DIAG-CLIJ", phone="+919999990091")
    _make_payment(
        payment_id="PAY-CLIJ",
        order_id="NRG-DIAG-CLIJ",
        phone="+919999990091",
    )
    out = StringIO()
    call_command("inspect_pending_payments", "--json", stdout=out)
    rows = json.loads(out.getvalue())
    assert any(row["payment_id"] == "PAY-CLIJ" for row in rows)


def test_cli_command_empty_db_message():
    out = StringIO()
    call_command("inspect_pending_payments", stdout=out)
    assert "No pending payments" in out.getvalue()


# ---------------------------------------------------------------------------
# Defensive: no outbound, no mutations
# ---------------------------------------------------------------------------


def test_diagnostics_does_not_send_or_mutate(auth_client, admin_user):
    customer = _make_customer(
        customer_id="C-DIAG-SAFE", phone="+919999990100"
    )
    _make_order(order_id="NRG-DIAG-SAFE", phone=customer.phone)
    _make_payment(
        payment_id="PAY-DIAG-SAFE",
        order_id="NRG-DIAG-SAFE",
        phone=customer.phone,
    )
    _make_outbound_whatsapp(
        customer=customer, message_id="WAM-DIAG-SAFE"
    )
    _make_call(call_id="CL-DIAG-SAFE", phone=customer.phone)
    pre_payments = Payment.objects.count()
    pre_orders = Order.objects.count()
    pre_customers = Customer.objects.count()
    pre_calls = Call.objects.count()
    pre_messages = WhatsAppMessage.objects.count()
    with (
        mock.patch(
            "apps.whatsapp.services.queue_template_message"
        ) as wa_queue,
        mock.patch(
            "apps.whatsapp.services.send_freeform_text_message"
        ) as wa_freeform,
        mock.patch(
            "apps.calls.services.trigger_call_for_lead"
        ) as call_trigger,
        mock.patch(
            "apps.shipments.services.create_shipment"
        ) as ship_create,
    ):
        client = auth_client(admin_user)
        response = client.get(reverse("diagnostics:pending-payments"))
        assert response.status_code == 200
        out = StringIO()
        call_command("inspect_pending_payments", stdout=out)
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    assert Payment.objects.count() == pre_payments
    assert Order.objects.count() == pre_orders
    assert Customer.objects.count() == pre_customers
    assert Call.objects.count() == pre_calls
    assert WhatsAppMessage.objects.count() == pre_messages


def test_service_default_limit_constant_is_safe():
    assert DEFAULT_LIMIT == 100


# ---------------------------------------------------------------------------
# Phase 10A Hotfix-1: phone fallback chain
# ---------------------------------------------------------------------------


def test_phone_source_is_payment_when_payment_phone_present():
    _make_order(order_id="NRG-FB-P", phone="+919999991100")
    _make_payment(
        payment_id="PAY-FB-P",
        order_id="NRG-FB-P",
        phone="+919999991100",
    )
    rows = list_pending_payments_drilldown()
    assert rows[0]["customer_phone"] == "+919999991100"
    assert rows[0]["phone_source"] == "payment"


def test_phone_source_falls_back_to_order_phone_when_payment_phone_empty():
    _make_order(order_id="NRG-FB-O", phone="+919999991200")
    _make_payment(
        payment_id="PAY-FB-O",
        order_id="NRG-FB-O",
        phone="",  # empty payment_phone forces fallback
    )
    rows = list_pending_payments_drilldown()
    assert rows[0]["customer_phone"] == "+919999991200"
    assert rows[0]["phone_source"] == "order"


def test_phone_source_falls_back_to_customer_phone_via_name_match():
    # Order has no phone, Payment has no phone, but the customer
    # name resolves to a crm.Customer record that does have a phone.
    Customer.objects.create(
        id="C-FB-CUST",
        name="Fallback Customer",
        phone="+919999991300",
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
    )
    _make_order(order_id="NRG-FB-C", phone="")
    _make_payment(
        payment_id="PAY-FB-C",
        order_id="NRG-FB-C",
        phone="",
        customer_name="Fallback Customer",
    )
    rows = list_pending_payments_drilldown()
    assert rows[0]["customer_phone"] == "+919999991300"
    assert rows[0]["phone_source"] == "customer"


def test_phone_source_none_when_no_chain_match():
    _make_order(order_id="NRG-FB-N", phone="")
    _make_payment(
        payment_id="PAY-FB-N",
        order_id="NRG-FB-N",
        phone="",
        customer_name="Ghost Customer",
    )
    rows = list_pending_payments_drilldown()
    assert rows[0]["customer_phone"] is None
    assert rows[0]["phone_source"] == "none"


def test_phone_source_communication_lookup_uses_resolved_phone():
    # Payment.customer_phone is empty; Order.phone supplies the phone.
    # The last-call lookup must still find the call against that phone.
    _make_order(order_id="NRG-FB-COMM", phone="+919999991400")
    _make_payment(
        payment_id="PAY-FB-COMM",
        order_id="NRG-FB-COMM",
        phone="",
    )
    _make_call(
        call_id="CL-FB-COMM",
        phone="+919999991400",
        status=Call.Status.COMPLETED.value,
        created_offset_hours=3,
    )
    rows = list_pending_payments_drilldown()
    assert rows[0]["phone_source"] == "order"
    assert rows[0]["last_call_at"] is not None
    assert rows[0]["last_call_outcome"] == Call.Status.COMPLETED.value


def test_api_response_includes_phone_source(auth_client, admin_user):
    _make_order(order_id="NRG-FB-API", phone="+919999991500")
    _make_payment(
        payment_id="PAY-FB-API",
        order_id="NRG-FB-API",
        phone="",  # forces order fallback
    )
    client = auth_client(admin_user)
    response = client.get(reverse("diagnostics:pending-payments"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    row = payload["results"][0]
    assert row["customer_phone"] == "+919999991500"
    assert row["phone_source"] == "order"


def test_cli_command_shows_phone_source_caption():
    _make_order(order_id="NRG-FB-CLI", phone="+919999991600")
    _make_payment(
        payment_id="PAY-FB-CLI",
        order_id="NRG-FB-CLI",
        phone="",
    )
    out = StringIO()
    call_command("inspect_pending_payments", stdout=out)
    output = out.getvalue()
    assert "+919999991600 (order)" in output


def test_no_outbound_when_phone_fallback_active(
    auth_client, admin_user
):
    Customer.objects.create(
        id="C-FB-SAFE",
        name="Fallback Safe",
        phone="+919999991700",
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
    )
    _make_order(order_id="NRG-FB-SAFE", phone="")
    _make_payment(
        payment_id="PAY-FB-SAFE",
        order_id="NRG-FB-SAFE",
        phone="",
        customer_name="Fallback Safe",
    )
    pre_payments = Payment.objects.count()
    pre_orders = Order.objects.count()
    pre_customers = Customer.objects.count()
    with (
        mock.patch(
            "apps.whatsapp.services.queue_template_message"
        ) as wa_queue,
        mock.patch(
            "apps.whatsapp.services.send_freeform_text_message"
        ) as wa_freeform,
        mock.patch(
            "apps.calls.services.trigger_call_for_lead"
        ) as call_trigger,
        mock.patch(
            "apps.shipments.services.create_shipment"
        ) as ship_create,
    ):
        client = auth_client(admin_user)
        response = client.get(reverse("diagnostics:pending-payments"))
        assert response.status_code == 200
        out = StringIO()
        call_command("inspect_pending_payments", stdout=out)
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    assert Payment.objects.count() == pre_payments
    assert Order.objects.count() == pre_orders
    assert Customer.objects.count() == pre_customers
    payload = response.json()
    assert payload["results"][0]["phone_source"] == "customer"
