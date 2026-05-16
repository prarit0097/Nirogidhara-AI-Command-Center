from __future__ import annotations

from io import StringIO
from unittest import mock

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.diagnostics.payment_reminder_service import (
    DEFAULT_TEMPLATE_NAME,
    PaymentReminderValidationError,
    build_payment_reminder_attempt,
)
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.whatsapp.models import Phase7ELiveBRealCustomerSendGate


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_order(
    *,
    order_id: str = "NRG-P10B",
    phone: str = "+919999998800",
    stage: str = Order.Stage.CONFIRMED.value,
    amount: int = 3000,
) -> Order:
    return Order.objects.create(
        id=order_id,
        customer_name="P10B Customer",
        phone=phone,
        product="Nirogidhara",
        quantity=1,
        amount=amount,
        state="Delhi",
        city="Delhi",
        stage=stage,
    )


def _make_payment(
    *,
    payment_id: str = "PAY-P10B",
    order_id: str = "NRG-P10B",
    customer_phone: str = "+919999998800",
    amount: int = 3000,
    status: str = Payment.Status.PENDING.value,
    payment_url: str = "https://rzp.io/test/p10b",
) -> Payment:
    return Payment.objects.create(
        id=payment_id,
        order_id=order_id,
        customer="P10B Customer",
        customer_phone=customer_phone,
        amount=amount,
        status=status,
        payment_url=payment_url,
        gateway=Payment.Gateway.RAZORPAY,
    )


def _seed_happy_pair(stage: str = Order.Stage.CONFIRMED.value) -> tuple[Order, Payment]:
    order = _make_order(stage=stage)
    payment = _make_payment()
    return order, payment


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_confirmed_stage_creates_attempt_no_outbound():
    _seed_happy_pair(stage=Order.Stage.CONFIRMED.value)
    pre_gates = Phase7ELiveBRealCustomerSendGate.objects.count()
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
        prepared = build_payment_reminder_attempt(payment_id="PAY-P10B")
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    # No outbound or Payment / Order mutation. The hotfix may create the
    # missing CRM Customer needed by the later 7E-Live-B execute gate.
    assert Payment.objects.count() == pre_payments
    assert Order.objects.count() == pre_orders
    assert Customer.objects.count() == pre_customers + 1
    # Controlled gate row IS created (that's the entire point).
    assert Phase7ELiveBRealCustomerSendGate.objects.count() == pre_gates + 1
    gate = Phase7ELiveBRealCustomerSendGate.objects.get(pk=prepared.gate_id)
    assert gate.template_name == DEFAULT_TEMPLATE_NAME
    assert gate.status == Phase7ELiveBRealCustomerSendGate.Status.DRAFT
    assert gate.template_params["payment_url"] == "https://rzp.io/test/p10b"
    assert gate.template_params["amount"] == "3000"
    assert gate.target_customer_name == "P10B Customer"
    assert prepared.phone_source == "payment"
    assert prepared.forced is False
    assert prepared.warning_emitted is False
    assert prepared.crm_customer_auto_created is True
    assert AuditEvent.objects.filter(
        kind="phase10b.payment_reminder.prepared"
    ).exists()
    assert AuditEvent.objects.filter(
        kind="phase10b.crm_customer.auto_created"
    ).exists()


def test_happy_path_order_punched_stage():
    _make_order(stage=Order.Stage.ORDER_PUNCHED.value)
    _make_payment()
    prepared = build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert prepared.stage == "Order Punched"
    assert Phase7ELiveBRealCustomerSendGate.objects.filter(
        pk=prepared.gate_id
    ).exists()


# ---------------------------------------------------------------------------
# Blocked stages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage",
    [
        Order.Stage.RTO.value,
        Order.Stage.OUT_FOR_DELIVERY.value,
        Order.Stage.CANCELLED.value,
        Order.Stage.DELIVERED.value,
        Order.Stage.DISPATCHED.value,
        Order.Stage.NEW_LEAD.value,
        "internal_sandbox",
    ],
)
def test_blocked_stages_refused_no_attempt(stage: str):
    _make_order(stage=stage)
    _make_payment()
    with pytest.raises(PaymentReminderValidationError) as exc:
        build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert exc.value.code == "stage_blocked"
    assert Phase7ELiveBRealCustomerSendGate.objects.count() == 0


# ---------------------------------------------------------------------------
# Warn stages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage",
    [
        Order.Stage.INTERESTED.value,
        Order.Stage.CONFIRMATION_PENDING.value,
    ],
)
def test_warn_stage_without_force_refused(stage: str):
    _make_order(stage=stage)
    _make_payment()
    with pytest.raises(PaymentReminderValidationError) as exc:
        build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert exc.value.code == "stage_requires_force"
    assert Phase7ELiveBRealCustomerSendGate.objects.count() == 0


def test_warn_stage_with_force_creates_attempt_and_writes_warning_audit():
    _make_order(stage=Order.Stage.INTERESTED.value)
    _make_payment()
    prepared = build_payment_reminder_attempt(
        payment_id="PAY-P10B", force=True
    )
    assert prepared.forced is True
    assert prepared.warning_emitted is True
    assert AuditEvent.objects.filter(
        kind="phase10b.payment_reminder.warn_forced"
    ).exists()
    assert Phase7ELiveBRealCustomerSendGate.objects.filter(
        pk=prepared.gate_id
    ).exists()


# ---------------------------------------------------------------------------
# Payment / Order validation
# ---------------------------------------------------------------------------


def test_missing_payment_refused():
    with pytest.raises(PaymentReminderValidationError) as exc:
        build_payment_reminder_attempt(payment_id="PAY-DOES-NOT-EXIST")
    assert exc.value.code == "payment_not_found"


@pytest.mark.parametrize(
    "status",
    [
        Payment.Status.PAID.value,
        Payment.Status.FAILED.value,
        Payment.Status.REFUNDED.value,
        Payment.Status.CANCELLED.value,
        Payment.Status.EXPIRED.value,
    ],
)
def test_payment_status_not_proceedable_refused(status: str):
    _make_order()
    _make_payment(status=status)
    with pytest.raises(PaymentReminderValidationError) as exc:
        build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert exc.value.code == "payment_status_not_proceedable"


def test_payment_url_missing_refused():
    _make_order()
    _make_payment(payment_url="")
    with pytest.raises(PaymentReminderValidationError) as exc:
        build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert exc.value.code == "payment_url_missing"


def test_payment_amount_zero_refused():
    _make_order()
    _make_payment(amount=0)
    with pytest.raises(PaymentReminderValidationError) as exc:
        build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert exc.value.code == "payment_amount_invalid"


def test_missing_order_refused():
    _make_payment(order_id="NRG-DOES-NOT-EXIST")
    with pytest.raises(PaymentReminderValidationError) as exc:
        build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert exc.value.code == "order_not_found"


# ---------------------------------------------------------------------------
# Phone validation
# ---------------------------------------------------------------------------


def test_phone_missing_across_all_fallbacks_refused():
    _make_order(phone="")
    _make_payment(customer_phone="")
    with pytest.raises(PaymentReminderValidationError) as exc:
        build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert exc.value.code == "target_phone_missing"


def test_phone_sandbox_placeholder_refused():
    _make_order(phone="0000000000")
    _make_payment(customer_phone="")
    with pytest.raises(PaymentReminderValidationError) as exc:
        build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert exc.value.code == "target_phone_sandbox_placeholder"


def test_phone_fallback_via_order_when_payment_empty():
    _make_order(phone="+919999998801")
    _make_payment(customer_phone="")
    prepared = build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert prepared.target_phone == "+919999998801"
    assert prepared.phone_source == "order"
    assert prepared.crm_customer_auto_created is True


def test_phone_fallback_via_customer_name_match():
    Customer.objects.create(
        id="C-P10B-CUST",
        name="P10B Customer",
        phone="+919999998802",
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
    )
    _make_order(phone="")
    _make_payment(customer_phone="")
    prepared = build_payment_reminder_attempt(payment_id="PAY-P10B")
    assert prepared.target_phone == "+919999998802"
    assert prepared.phone_source == "customer"
    assert prepared.crm_customer_auto_created is False


def test_crm_customer_auto_created_when_phone_from_order():
    phone = "+919559991203"
    _make_order(phone=phone)
    _make_payment(customer_phone="")

    prepared = build_payment_reminder_attempt(payment_id="PAY-P10B")

    assert Customer.objects.filter(phone=phone).count() == 1
    customer = Customer.objects.get(phone=phone)
    assert customer.name == "P10B Customer"
    assert prepared.phone_source == "order"
    assert prepared.crm_customer_auto_created is True
    assert AuditEvent.objects.filter(
        kind="phase10b.crm_customer.auto_created",
        payload__payment_id="PAY-P10B",
        payload__phone_source="order",
    ).exists()


def test_no_duplicate_crm_customer_when_already_exists():
    phone = "+919559991204"
    Customer.objects.create(
        id="C-P10B-EXISTING",
        name="Existing Customer",
        phone=phone,
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
    )
    _make_order(phone=phone)
    _make_payment(customer_phone="")

    prepared = build_payment_reminder_attempt(payment_id="PAY-P10B")

    assert Customer.objects.filter(phone=phone).count() == 1
    assert prepared.phone_source == "order"
    assert prepared.crm_customer_auto_created is False
    assert not AuditEvent.objects.filter(
        kind="phase10b.crm_customer.auto_created",
        payload__payment_id="PAY-P10B",
    ).exists()


def test_skip_crm_create_when_phone_source_is_customer():
    Customer.objects.create(
        id="C-P10B-CUSTOMER-SOURCE",
        name="P10B Customer",
        phone="+919559991205",
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
    )
    _make_order(phone="")
    _make_payment(customer_phone="")

    with mock.patch(
        "apps.crm.models.Customer.objects.get_or_create"
    ) as get_or_create:
        prepared = build_payment_reminder_attempt(payment_id="PAY-P10B")

    get_or_create.assert_not_called()
    assert prepared.phone_source == "customer"
    assert prepared.crm_customer_auto_created is False


def test_crm_create_failure_is_nonfatal():
    _make_order(phone="+919559991206")
    _make_payment(customer_phone="")

    with mock.patch(
        "apps.crm.models.Customer.objects.get_or_create",
        side_effect=Exception("database temporarily unavailable"),
    ):
        prepared = build_payment_reminder_attempt(payment_id="PAY-P10B")

    assert prepared.phone_source == "order"
    assert prepared.crm_customer_auto_created is False
    assert Phase7ELiveBRealCustomerSendGate.objects.filter(
        pk=prepared.gate_id
    ).exists()


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


def test_cli_happy_path_exits_clean_with_attempt_summary():
    _seed_happy_pair()
    out = StringIO()
    call_command("prepare_payment_reminder_send", "PAY-P10B", stdout=out)
    output = out.getvalue()
    assert "Phase 10B" in output
    assert "Phase 7E-Live-B gate id" in output
    assert "CRM customer auto-created" in output
    # Gate row exists.
    assert Phase7ELiveBRealCustomerSendGate.objects.count() == 1


def test_cli_refused_blocked_stage_exits_nonzero():
    _make_order(stage=Order.Stage.RTO.value)
    _make_payment()
    err = StringIO()
    with pytest.raises(SystemExit) as exit_info:
        call_command(
            "prepare_payment_reminder_send", "PAY-P10B", stderr=err
        )
    assert exit_info.value.code == 1
    assert "stage_blocked" in err.getvalue()
    assert Phase7ELiveBRealCustomerSendGate.objects.count() == 0


def test_cli_json_output_for_happy_path():
    _seed_happy_pair()
    out = StringIO()
    call_command(
        "prepare_payment_reminder_send", "PAY-P10B", "--json", stdout=out
    )
    import json

    payload = json.loads(out.getvalue())
    assert payload["ok"] is True
    assert payload["phase"] == "10B"
    assert payload["gate_id"] > 0
    assert payload["template_name"] == DEFAULT_TEMPLATE_NAME
    assert payload["crm_customer_auto_created"] is True


def test_cli_json_output_for_refusal():
    _make_order(stage=Order.Stage.RTO.value)
    _make_payment()
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command(
            "prepare_payment_reminder_send",
            "PAY-P10B",
            "--json",
            stdout=out,
        )
    import json

    payload = json.loads(out.getvalue())
    assert payload["ok"] is False
    assert payload["error_code"] == "stage_blocked"


# ---------------------------------------------------------------------------
# Defensive: no outbound under any path
# ---------------------------------------------------------------------------


def test_no_outbound_under_cli_happy_path():
    _seed_happy_pair()
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
        out = StringIO()
        call_command(
            "prepare_payment_reminder_send", "PAY-P10B", stdout=out
        )
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    assert Payment.objects.count() == pre_payments
    assert Order.objects.count() == pre_orders
    assert Customer.objects.count() == pre_customers + 1
    # Phase 7E-Live-B gate row plus the CRM customer bridge are the only new
    # artefacts; no outbound/provider path is touched.
    assert Phase7ELiveBRealCustomerSendGate.objects.count() == 1
    gate = Phase7ELiveBRealCustomerSendGate.objects.get()
    # Gate is still DRAFT — Phase 10B never approves or executes it.
    assert gate.status == Phase7ELiveBRealCustomerSendGate.Status.DRAFT
    assert gate.executed_at is None
    assert gate.customer_notification_sent is False
