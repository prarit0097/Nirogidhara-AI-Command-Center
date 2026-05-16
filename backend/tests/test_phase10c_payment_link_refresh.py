from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.orders.models import Order
from apps.payments.integrations.razorpay_client import PaymentLinkResult
from apps.payments.models import Payment, Phase10CPaymentLinkRefreshGate
from apps.payments.phase10c_payment_link_refresh import (
    AUDIT_APPROVED,
    AUDIT_CANCELLED,
    AUDIT_EXECUTE_FAILED,
    AUDIT_EXECUTE_SUCCESS,
    AUDIT_LIVE_REFUSED,
    AUDIT_PREPARED,
    AUDIT_ROLLBACK_FAILED,
    AUDIT_ROLLBACK_SUCCESS,
    ENV_FLAG,
    approve_gate,
    cancel_gate,
    execute_gate,
    inspect_gate,
    prepare_gate,
    rollback_gate,
)
from apps.saas.models import RuntimeKillSwitch


pytestmark = pytest.mark.django_db


REFRESH_TARGET = (
    "apps.payments.phase10c_payment_link_refresh.create_payment_link_for_refresh"
)
CANCEL_TARGET = (
    "apps.payments.phase10c_payment_link_refresh.cancel_payment_link"
)


def _make_order(
    *,
    order_id: str = "NRG-P10C",
    phone: str = "+919999997700",
    stage: str = Order.Stage.CONFIRMED.value,
    amount: int = 3000,
) -> Order:
    return Order.objects.create(
        id=order_id,
        customer_name="P10C Customer",
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
    payment_id: str = "PAY-P10C",
    order_id: str = "NRG-P10C",
    customer_phone: str = "+919999997700",
    amount: int = 3000,
    status: str = Payment.Status.PENDING.value,
    payment_url: str = "",
    gateway_reference_id: str = "",
) -> Payment:
    return Payment.objects.create(
        id=payment_id,
        order_id=order_id,
        customer="P10C Customer",
        customer_phone=customer_phone,
        amount=amount,
        status=status,
        payment_url=payment_url,
        gateway_reference_id=gateway_reference_id,
        gateway=Payment.Gateway.RAZORPAY,
    )


def _seed_pair(stage: str = Order.Stage.CONFIRMED.value):
    return _make_order(stage=stage), _make_payment()


def _fake_refresh_result(*args, **kwargs) -> PaymentLinkResult:
    payment_id = kwargs.get("payment_id", "PAY")
    return PaymentLinkResult(
        plink_id=f"plink_fresh_{payment_id}",
        short_url=f"https://razorpay.example/pay/plink_fresh_{payment_id}",
        status="created",
        raw={"id": f"plink_fresh_{payment_id}", "mock": True},
    )


def _structured_signoff(*, before_min: int = 1, after_min: int = 10) -> str:
    start = (timezone.now() - timedelta(minutes=before_min)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end = (timezone.now() + timedelta(minutes=after_min)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return f"phase10c_payment_link_refresh BEGIN_UTC={start} END_UTC={end}"


# ---------------------------------------------------------------------------
# prepare_gate
# ---------------------------------------------------------------------------


def test_prepare_test_mode_happy_path():
    _seed_pair()
    result = prepare_gate(
        payment_id="PAY-P10C",
        mode="test",
        operator_name="Director",
    )
    assert result.ok is True
    assert result.mode == "test"
    gate = Phase10CPaymentLinkRefreshGate.objects.get(pk=result.gate_id)
    assert gate.status == Phase10CPaymentLinkRefreshGate.Status.DRAFT
    assert gate.force_replace is False
    assert AuditEvent.objects.filter(kind=AUDIT_PREPARED).exists()


def test_prepare_refuses_missing_payment():
    result = prepare_gate(
        payment_id="PAY-MISSING", operator_name="Director"
    )
    assert result.ok is False
    assert any(b.startswith("payment_not_found") for b in result.blockers)
    assert Phase10CPaymentLinkRefreshGate.objects.count() == 0


def test_prepare_refuses_when_payment_url_already_present_without_force():
    _make_order()
    _make_payment(payment_url="https://razorpay.example/old")
    result = prepare_gate(payment_id="PAY-P10C", operator_name="Director")
    assert result.ok is False
    assert (
        "payment_url_already_present_use_force_replace"
        in result.blockers
    )


def test_prepare_with_force_replace_when_url_present():
    _make_order()
    _make_payment(payment_url="https://razorpay.example/old")
    result = prepare_gate(
        payment_id="PAY-P10C",
        operator_name="Director",
        force_replace=True,
    )
    assert result.ok is True
    gate = Phase10CPaymentLinkRefreshGate.objects.get(pk=result.gate_id)
    assert gate.force_replace is True


@pytest.mark.parametrize(
    "stage",
    [
        Order.Stage.RTO.value,
        Order.Stage.OUT_FOR_DELIVERY.value,
        Order.Stage.CANCELLED.value,
        Order.Stage.DELIVERED.value,
        Order.Stage.DISPATCHED.value,
        "internal_sandbox",
    ],
)
def test_prepare_refuses_blocked_stage(stage: str):
    _make_order(stage=stage)
    _make_payment()
    result = prepare_gate(payment_id="PAY-P10C", operator_name="Director")
    assert result.ok is False
    assert any(b.startswith("stage_blocked") for b in result.blockers)


@pytest.mark.parametrize(
    "status",
    [
        Payment.Status.PAID.value,
        Payment.Status.FAILED.value,
        Payment.Status.REFUNDED.value,
        Payment.Status.CANCELLED.value,
    ],
)
def test_prepare_refuses_payment_status_not_proceedable(status: str):
    _make_order()
    _make_payment(status=status)
    result = prepare_gate(payment_id="PAY-P10C", operator_name="Director")
    assert result.ok is False
    assert any(
        b.startswith("payment_status_not_proceedable")
        for b in result.blockers
    )


def test_prepare_refuses_missing_operator_name():
    _seed_pair()
    result = prepare_gate(payment_id="PAY-P10C", operator_name="")
    assert result.ok is False
    assert "operator_name_required" in result.blockers


# ---------------------------------------------------------------------------
# approve_gate
# ---------------------------------------------------------------------------


def _prepared_gate(mode: str = "test") -> Phase10CPaymentLinkRefreshGate:
    _seed_pair()
    result = prepare_gate(
        payment_id="PAY-P10C", mode=mode, operator_name="Director"
    )
    return Phase10CPaymentLinkRefreshGate.objects.get(pk=result.gate_id)


def test_approve_test_mode_with_free_text_signoff():
    gate = _prepared_gate("test")
    result = approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="Refresh stale payment link for VPS rollout test.",
        director_signoff="director approves refresh for VPS test",
    )
    assert result.ok is True
    gate.refresh_from_db()
    assert gate.status == Phase10CPaymentLinkRefreshGate.Status.APPROVED
    assert gate.recorded_signoff_window_valid is False
    assert AuditEvent.objects.filter(kind=AUDIT_APPROVED).exists()


def test_approve_live_mode_requires_structured_window():
    gate = _prepared_gate("live")
    result = approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="Live refresh",
        director_signoff="missing markers",
    )
    assert result.ok is False
    assert any("director_signoff" in b for b in result.blockers)


def test_approve_live_mode_with_valid_window_records_it():
    gate = _prepared_gate("live")
    signoff = _structured_signoff()
    result = approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="Live refresh",
        director_signoff=signoff,
    )
    assert result.ok is True, result.blockers
    gate.refresh_from_db()
    assert gate.recorded_signoff_window_valid is True
    assert gate.recorded_signoff_window_start_utc is not None


def test_approve_live_mode_refuses_stale_window():
    gate = _prepared_gate("live")
    start = (timezone.now() - timedelta(minutes=20)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end = (timezone.now() - timedelta(minutes=10)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    signoff = f"phase10c BEGIN_UTC={start} END_UTC={end}"
    result = approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="Live refresh",
        director_signoff=signoff,
    )
    assert result.ok is False
    assert any("phase10c_" in b for b in result.blockers)


def test_approve_refuses_when_gate_not_in_draft():
    gate = _prepared_gate("test")
    approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="test",
        director_signoff="ok",
    )
    # Second approve should refuse.
    result = approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="again",
        director_signoff="ok",
    )
    assert result.ok is False
    assert any("not_draft" in b for b in result.blockers)


# ---------------------------------------------------------------------------
# execute_gate — test mode
# ---------------------------------------------------------------------------


@override_settings(RAZORPAY_MODE="mock")
def test_execute_test_mode_happy_path_updates_payment_url():
    gate = _prepared_gate("test")
    approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="test refresh",
        director_signoff="ok",
    )
    with mock.patch(REFRESH_TARGET, side_effect=_fake_refresh_result) as refresh_mock:
        result = execute_gate(
            gate_id=gate.pk, operator_name="Director"
        )
    assert result.ok is True, result.blockers
    refresh_mock.assert_called_once()
    gate.refresh_from_db()
    assert gate.status == Phase10CPaymentLinkRefreshGate.Status.EXECUTED
    assert gate.new_payment_url.startswith("https://razorpay.example/pay/")
    assert gate.razorpay_link_id == "plink_fresh_PAY-P10C"
    payment = Payment.objects.get(pk="PAY-P10C")
    assert payment.payment_url == gate.new_payment_url
    assert payment.gateway_reference_id == gate.razorpay_link_id
    assert payment.raw_response["phase10c_payment_link_refresh"] == {
        "gate_id": gate.pk,
        "razorpay_link_id": gate.razorpay_link_id,
        "razorpay_short_url": gate.razorpay_short_url,
        "razorpay_status": "created",
    }
    assert AuditEvent.objects.filter(kind=AUDIT_EXECUTE_SUCCESS).exists()


@override_settings(RAZORPAY_MODE="live")
def test_execute_test_mode_refused_when_runtime_is_live():
    gate = _prepared_gate("test")
    approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="test refresh",
        director_signoff="ok",
    )
    result = execute_gate(gate_id=gate.pk, operator_name="Director")
    assert result.ok is False
    assert any(
        "razorpay_mode_runtime_live_but_gate_mode_test" in b
        for b in result.blockers
    )


@override_settings(RAZORPAY_MODE="mock")
def test_execute_archives_previous_payment_url():
    _make_order()
    _make_payment(
        payment_url="https://razorpay.example/old",
        gateway_reference_id="plink_old",
    )
    prep = prepare_gate(
        payment_id="PAY-P10C",
        operator_name="Director",
        force_replace=True,
    )
    approve_gate(
        gate_id=prep.gate_id,
        operator_name="Director",
        intent="archive prev",
        director_signoff="ok",
    )
    with mock.patch(REFRESH_TARGET, side_effect=_fake_refresh_result):
        execute_gate(gate_id=prep.gate_id, operator_name="Director")
    gate = Phase10CPaymentLinkRefreshGate.objects.get(pk=prep.gate_id)
    assert gate.previous_payment_url == "https://razorpay.example/old"
    assert gate.metadata["previous_gateway_reference_id"] == "plink_old"
    payment = Payment.objects.get(pk="PAY-P10C")
    assert payment.payment_url == gate.new_payment_url
    assert payment.gateway_reference_id == gate.razorpay_link_id


# ---------------------------------------------------------------------------
# execute_gate — live mode
# ---------------------------------------------------------------------------


def test_execute_live_mode_refused_without_env_flag():
    gate = _prepared_gate("live")
    signoff = _structured_signoff()
    approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="Live",
        director_signoff=signoff,
    )
    result = execute_gate(
        gate_id=gate.pk,
        operator_name="Director",
        confirm_live=True,
    )
    assert result.ok is False
    assert f"{ENV_FLAG}_must_be_true" in result.blockers
    assert AuditEvent.objects.filter(kind=AUDIT_LIVE_REFUSED).exists()


@override_settings(
    PHASE10C_PAYMENT_LINK_REFRESH_ENABLED=True,
    RAZORPAY_MODE="live",
)
def test_execute_live_mode_refused_without_confirm_flag():
    gate = _prepared_gate("live")
    signoff = _structured_signoff()
    approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="Live",
        director_signoff=signoff,
    )
    result = execute_gate(
        gate_id=gate.pk,
        operator_name="Director",
        confirm_live=False,
    )
    assert result.ok is False
    assert (
        "confirm_phase10c_payment_link_refresh_live_required"
        in result.blockers
    )


@override_settings(
    PHASE10C_PAYMENT_LINK_REFRESH_ENABLED=True,
    RAZORPAY_MODE="live",
)
def test_execute_live_mode_refused_when_kill_switch_off():
    gate = _prepared_gate("live")
    signoff = _structured_signoff()
    approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="Live",
        director_signoff=signoff,
    )
    RuntimeKillSwitch.objects.create(scope="global", enabled=False)
    result = execute_gate(
        gate_id=gate.pk,
        operator_name="Director",
        confirm_live=True,
    )
    assert result.ok is False
    assert "runtime_kill_switch_disabled" in result.blockers


@override_settings(
    PHASE10C_PAYMENT_LINK_REFRESH_ENABLED=True,
    RAZORPAY_MODE="live",
)
def test_execute_live_mode_happy_path_updates_payment_url():
    gate = _prepared_gate("live")
    signoff = _structured_signoff()
    approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="Live refresh proof",
        director_signoff=signoff,
    )
    with mock.patch(REFRESH_TARGET, side_effect=_fake_refresh_result):
        result = execute_gate(
            gate_id=gate.pk,
            operator_name="Director",
            confirm_live=True,
        )
    assert result.ok is True, result.blockers
    gate.refresh_from_db()
    assert gate.status == Phase10CPaymentLinkRefreshGate.Status.EXECUTED


@override_settings(RAZORPAY_MODE="mock")
def test_execute_marks_failed_when_razorpay_raises():
    gate = _prepared_gate("test")
    approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="t",
        director_signoff="ok",
    )
    from apps.payments.integrations.razorpay_client import RazorpayClientError

    with mock.patch(
        REFRESH_TARGET,
        side_effect=RazorpayClientError("API down"),
    ):
        result = execute_gate(
            gate_id=gate.pk, operator_name="Director"
        )
    assert result.ok is False
    gate.refresh_from_db()
    assert gate.status == Phase10CPaymentLinkRefreshGate.Status.FAILED
    assert AuditEvent.objects.filter(kind=AUDIT_EXECUTE_FAILED).exists()


def test_execute_refuses_when_gate_not_approved():
    gate = _prepared_gate("test")
    result = execute_gate(gate_id=gate.pk, operator_name="Director")
    assert result.ok is False
    assert any("not_approved" in b for b in result.blockers)


# ---------------------------------------------------------------------------
# rollback_gate
# ---------------------------------------------------------------------------


@override_settings(RAZORPAY_MODE="mock")
def test_rollback_happy_path_restores_previous_url():
    _make_order()
    _make_payment(
        payment_url="https://razorpay.example/original",
        gateway_reference_id="plink_original",
    )
    prep = prepare_gate(
        payment_id="PAY-P10C",
        operator_name="Director",
        force_replace=True,
    )
    approve_gate(
        gate_id=prep.gate_id,
        operator_name="Director",
        intent="t",
        director_signoff="ok",
    )
    with mock.patch(REFRESH_TARGET, side_effect=_fake_refresh_result):
        execute_gate(gate_id=prep.gate_id, operator_name="Director")
    with mock.patch(
        CANCEL_TARGET,
        return_value={"status": "cancelled", "raw": {"ok": True}},
    ) as cancel_mock:
        result = rollback_gate(
            gate_id=prep.gate_id, operator_name="Director"
        )
    assert result.ok is True
    cancel_mock.assert_called_once()
    gate = Phase10CPaymentLinkRefreshGate.objects.get(pk=prep.gate_id)
    assert gate.status == Phase10CPaymentLinkRefreshGate.Status.ROLLED_BACK
    payment = Payment.objects.get(pk="PAY-P10C")
    assert payment.payment_url == "https://razorpay.example/original"
    assert payment.gateway_reference_id == "plink_original"
    assert AuditEvent.objects.filter(kind=AUDIT_ROLLBACK_SUCCESS).exists()


@override_settings(RAZORPAY_MODE="mock")
def test_rollback_restores_url_even_when_razorpay_refuses():
    _make_order()
    _make_payment(payment_url="https://razorpay.example/original")
    prep = prepare_gate(
        payment_id="PAY-P10C",
        operator_name="Director",
        force_replace=True,
    )
    approve_gate(
        gate_id=prep.gate_id,
        operator_name="Director",
        intent="t",
        director_signoff="ok",
    )
    with mock.patch(REFRESH_TARGET, side_effect=_fake_refresh_result):
        execute_gate(gate_id=prep.gate_id, operator_name="Director")
    with mock.patch(
        CANCEL_TARGET,
        return_value={"status": "rejected", "raw": {"already_paid": True}},
    ):
        result = rollback_gate(
            gate_id=prep.gate_id, operator_name="Director"
        )
    assert result.ok is True
    gate = Phase10CPaymentLinkRefreshGate.objects.get(pk=prep.gate_id)
    assert gate.status == Phase10CPaymentLinkRefreshGate.Status.ROLLED_BACK
    payment = Payment.objects.get(pk="PAY-P10C")
    assert payment.payment_url == "https://razorpay.example/original"
    assert AuditEvent.objects.filter(kind=AUDIT_ROLLBACK_FAILED).exists()


def test_rollback_refused_when_gate_not_executed():
    gate = _prepared_gate("test")
    result = rollback_gate(gate_id=gate.pk, operator_name="Director")
    assert result.ok is False


# ---------------------------------------------------------------------------
# cancel_gate
# ---------------------------------------------------------------------------


def test_cancel_draft_gate_ok():
    gate = _prepared_gate("test")
    result = cancel_gate(
        gate_id=gate.pk, operator_name="Director", reason="not needed"
    )
    assert result.ok is True
    gate.refresh_from_db()
    assert gate.status == Phase10CPaymentLinkRefreshGate.Status.CANCELLED
    assert AuditEvent.objects.filter(kind=AUDIT_CANCELLED).exists()


@override_settings(RAZORPAY_MODE="mock")
def test_cancel_executed_gate_refused_use_rollback():
    gate = _prepared_gate("test")
    approve_gate(
        gate_id=gate.pk,
        operator_name="Director",
        intent="t",
        director_signoff="ok",
    )
    with mock.patch(REFRESH_TARGET, side_effect=_fake_refresh_result):
        execute_gate(gate_id=gate.pk, operator_name="Director")
    result = cancel_gate(gate_id=gate.pk, operator_name="Director")
    assert result.ok is False
    assert any("not_cancellable_use_rollback" in b for b in result.blockers)


# ---------------------------------------------------------------------------
# inspect_gate + CLI
# ---------------------------------------------------------------------------


def test_inspect_gate_returns_runtime_flags():
    gate = _prepared_gate("test")
    report = inspect_gate(gate_id=gate.pk)
    assert report["ok"] is True
    assert report["gate_id"] == gate.pk
    assert "runtime_razorpay_mode" in report
    assert "env_flag_enabled" in report


def test_cli_prepare_command_test_mode():
    _seed_pair()
    out = StringIO()
    call_command(
        "prepare_phase10c_payment_link_refresh_gate",
        "PAY-P10C",
        "--operator-name",
        "Director",
        "--json",
        stdout=out,
    )
    payload = json.loads(out.getvalue())
    assert payload["ok"] is True
    assert payload["mode"] == "test"


# ---------------------------------------------------------------------------
# DEFENSIVE: no outbound, no business mutation beyond Payment.payment_url
# ---------------------------------------------------------------------------


@override_settings(RAZORPAY_MODE="mock")
def test_no_outbound_under_prepare_approve_execute_chain():
    _seed_pair()
    Customer.objects.create(
        id="C-P10C-DEF",
        name="P10C Defensive",
        phone="+919999997711",
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
    )
    pre_orders = Order.objects.count()
    pre_customers = Customer.objects.count()
    pre_payments = Payment.objects.count()
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
        mock.patch(REFRESH_TARGET, side_effect=_fake_refresh_result) as refresh_mock,
    ):
        prep = prepare_gate(
            payment_id="PAY-P10C", operator_name="Director"
        )
        approve_gate(
            gate_id=prep.gate_id,
            operator_name="Director",
            intent="defensive happy path",
            director_signoff="ok",
        )
        execute_gate(gate_id=prep.gate_id, operator_name="Director")
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    refresh_mock.assert_called_once()
    # Row counts unchanged (Phase 10C never creates new business rows).
    assert Order.objects.count() == pre_orders
    assert Customer.objects.count() == pre_customers
    assert Payment.objects.count() == pre_payments
    # Only Payment.payment_url is touched on the existing row.
    payment = Payment.objects.get(pk="PAY-P10C")
    assert payment.payment_url != ""
    # Only ONE gate row added.
    assert Phase10CPaymentLinkRefreshGate.objects.count() == 1


@override_settings(RAZORPAY_MODE="mock")
def test_sandbox_flag_propagates_to_gate():
    _seed_pair()
    from apps.ai_governance.sandbox import set_sandbox_enabled

    set_sandbox_enabled(enabled=True)
    try:
        result = prepare_gate(
            payment_id="PAY-P10C", operator_name="Director"
        )
    finally:
        set_sandbox_enabled(enabled=False)
    gate = Phase10CPaymentLinkRefreshGate.objects.get(pk=result.gate_id)
    assert gate.sandbox is True
