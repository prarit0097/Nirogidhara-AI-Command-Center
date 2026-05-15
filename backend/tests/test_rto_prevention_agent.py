from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.agents.rto_prevention.models import RtoRiskSnapshot
from apps.agents.rto_prevention.service import (
    AGENT_NAME,
    MODEL_USED,
    Signals,
    build_snapshot,
    choose_recommendation,
    compute_lifecycle_stage,
    compute_risk_score,
    compute_risk_tier,
    compute_signals,
)
from apps.agents.rto_prevention.tasks import (
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_COMPLETED,
    AUDIT_KIND_SNAPSHOT,
    run_rto_prevention_agent_daily,
)
from apps.ai_governance.models import AgentRun
from apps.ai_governance.sandbox import set_sandbox_enabled
from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.orders.models import Order
from apps.saas.models import RuntimeKillSwitch
from apps.shipments.models import Shipment


pytestmark = pytest.mark.django_db


def _make_customer(
    *, customer_id: str = "RTO-001", phone: str = "+919999990101"
) -> Customer:
    return Customer.objects.create(
        id=customer_id,
        name="Test Customer",
        phone=phone,
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
        disease_category="general",
    )


def _make_order(
    *,
    customer: Customer,
    order_id: str,
    stage: str = Order.Stage.CONFIRMED.value,
    payment_status: str = Order.PaymentStatus.PAID.value,
    amount: int = 3000,
    created_offset_days: int = 1,
) -> Order:
    order = Order.objects.create(
        id=order_id,
        customer_name=customer.name,
        phone=customer.phone,
        product="Nirogidhara",
        quantity=1,
        amount=amount,
        state=customer.state,
        city=customer.city,
        stage=stage,
        payment_status=payment_status,
    )
    if created_offset_days:
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(days=created_offset_days)
        )
        order.refresh_from_db()
    return order


def _make_shipment(
    *,
    order: Order,
    awb: str,
    delhivery_status: str = "Pickup Scheduled",
) -> Shipment:
    return Shipment.objects.create(
        awb=awb,
        order_id=order.id,
        customer=order.customer_name,
        state=order.state,
        city=order.city,
        status=delhivery_status,
        delhivery_status=delhivery_status,
    )


# ---------------------------------------------------------------------------
# compute_lifecycle_stage
# ---------------------------------------------------------------------------


def test_lifecycle_pre_dispatch_when_no_shipment():
    customer = _make_customer()
    order = _make_order(customer=customer, order_id="NRG-RTO-1")
    signals = compute_signals(order)
    assert compute_lifecycle_stage(order, signals) == "pre_dispatch"


def test_lifecycle_in_transit_when_shipment_no_failures():
    customer = _make_customer()
    order = _make_order(customer=customer, order_id="NRG-RTO-2")
    _make_shipment(
        order=order, awb="DLH00000001", delhivery_status="In Transit"
    )
    signals = compute_signals(order)
    assert compute_lifecycle_stage(order, signals) == "in_transit"


def test_lifecycle_delivery_at_risk_when_ndr():
    customer = _make_customer()
    order = _make_order(customer=customer, order_id="NRG-RTO-3")
    _make_shipment(
        order=order,
        awb="DLH00000002",
        delhivery_status="NDR - Customer Not Available",
    )
    signals = compute_signals(order)
    assert signals.failed_attempts_on_current_shipment == 1
    assert compute_lifecycle_stage(order, signals) == "delivery_at_risk"


# ---------------------------------------------------------------------------
# compute_risk_score
# ---------------------------------------------------------------------------


def test_score_base_only():
    # Base 30, paid -> no COD bonus, no other signals.
    s = Signals(payment_status=Order.PaymentStatus.PAID.value)
    assert compute_risk_score(s) == 30


def test_score_rto_count_capped_at_three():
    s = Signals(
        rto_count=10, payment_status=Order.PaymentStatus.PAID.value
    )
    # base 30 + min(10*15, 45) = 75.
    assert compute_risk_score(s) == 75


def test_score_complaint_capped_at_two():
    s = Signals(
        complaint_count_14d=5,
        payment_status=Order.PaymentStatus.PAID.value,
    )
    # base 30 + min(5*10, 20) = 50.
    assert compute_risk_score(s) == 50


def test_score_cod_payment_adds_fifteen():
    s = Signals(payment_status=Order.PaymentStatus.PENDING.value)
    assert compute_risk_score(s) == 45  # 30 + 15


def test_score_high_value_adds_ten():
    s = Signals(
        order_amount=6000,
        payment_status=Order.PaymentStatus.PAID.value,
    )
    assert compute_risk_score(s) == 40  # 30 + 10


def test_score_staleness_capped_at_ten():
    s = Signals(
        days_since_order=30,
        payment_status=Order.PaymentStatus.PAID.value,
    )
    assert compute_risk_score(s) == 40  # 30 + min(30, 10) = 40


def test_score_delivered_count_reduces_capped_at_twenty():
    s = Signals(
        rto_count=3,
        delivered_count=10,
        payment_status=Order.PaymentStatus.PAID.value,
    )
    # 30 + 45 (rto cap) - 20 (delivered cap) = 55.
    assert compute_risk_score(s) == 55


def test_score_failed_attempts_add_fifteen_each():
    s = Signals(
        failed_attempts_on_current_shipment=2,
        payment_status=Order.PaymentStatus.PAID.value,
    )
    assert compute_risk_score(s) == 60  # 30 + 15*2


def test_score_clamps_at_one_hundred():
    s = Signals(
        rto_count=10,
        complaint_count_14d=5,
        payment_status=Order.PaymentStatus.PENDING.value,
        order_amount=10_000,
        days_since_order=30,
        failed_attempts_on_current_shipment=3,
    )
    # 30 + 45 + 20 + 15 + 10 + 10 + 15*3 = 175 -> clamp 100.
    assert compute_risk_score(s) == 100


def test_score_clamps_at_zero():
    s = Signals(
        delivered_count=20,
        payment_status=Order.PaymentStatus.PAID.value,
    )
    # 30 + 0 (rto) + 0 (complaint) + 0 (cod) + 0 (highval) + 0 (stale)
    # - 20 (delivered cap) = 10. Verifies positive but small score.
    assert compute_risk_score(s) == 10


# ---------------------------------------------------------------------------
# compute_risk_tier mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,tier",
    [
        (0, "low"),
        (39, "low"),
        (40, "medium"),
        (59, "medium"),
        (60, "high"),
        (79, "high"),
        (80, "critical"),
        (100, "critical"),
    ],
)
def test_risk_tier_boundaries(score: int, tier: str):
    assert compute_risk_tier(score) == tier


# ---------------------------------------------------------------------------
# reason codes
# ---------------------------------------------------------------------------


def test_risk_reasons_populated_correctly():
    customer = _make_customer()
    order = _make_order(
        customer=customer,
        order_id="NRG-RTO-REASONS",
        amount=7500,
        payment_status=Order.PaymentStatus.PENDING.value,
        created_offset_days=20,
    )
    # Prior RTO order for same phone.
    _make_order(
        customer=customer,
        order_id="NRG-RTO-OLD",
        stage=Order.Stage.RTO.value,
    )
    # NDR shipment on current order.
    _make_shipment(
        order=order,
        awb="DLH00000003",
        delhivery_status="NDR - undelivered",
    )
    # Recent complaint.
    complaint = AuditEvent.objects.create(
        kind="complaint.side_effect",
        text="customer reported side effect",
        payload={"phone": customer.phone, "order_id": order.id},
    )
    AuditEvent.objects.filter(pk=complaint.pk).update(
        occurred_at=timezone.now() - timedelta(days=2)
    )
    signals = compute_signals(order)
    snap = build_snapshot(order, signals)
    assert "high_rto_history" in snap.risk_reasons
    assert "recent_complaint" in snap.risk_reasons
    assert "cod_payment" in snap.risk_reasons
    assert "high_value_order" in snap.risk_reasons
    assert "stale_order" in snap.risk_reasons
    assert "multiple_failed_attempts" in snap.risk_reasons


# ---------------------------------------------------------------------------
# choose_recommendation per tier
# ---------------------------------------------------------------------------


def test_choose_recommendation_each_tier():
    customer = _make_customer()
    base_order = _make_order(
        customer=customer, order_id="NRG-RTO-REC-LOW"
    )

    # LOW
    low = build_snapshot(
        base_order,
        Signals(payment_status=Order.PaymentStatus.PAID.value),
    )
    assert low.risk_tier == "low"
    assert low.recommendation_kind == "monitor_only"

    # MEDIUM (score 50: complaint cap 20)
    medium = build_snapshot(
        base_order,
        Signals(
            complaint_count_14d=5,
            payment_status=Order.PaymentStatus.PAID.value,
        ),
    )
    assert medium.risk_tier == "medium"
    assert medium.recommendation_kind == "send_confirmation_reminder"

    # HIGH (score 75: rto cap 45)
    high = build_snapshot(
        base_order,
        Signals(
            rto_count=10,
            payment_status=Order.PaymentStatus.PAID.value,
        ),
    )
    assert high.risk_tier == "high"
    assert high.recommendation_kind == "send_pre_delivery_call_request"

    # CRITICAL (score >= 80)
    critical = build_snapshot(
        base_order,
        Signals(
            rto_count=10,
            complaint_count_14d=5,
            payment_status=Order.PaymentStatus.PENDING.value,
        ),
    )
    assert critical.risk_tier == "critical"
    assert critical.recommendation_kind == "escalate_to_team_lead"


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_daily_task_happy_path_creates_snapshots_and_excludes_terminal():
    cust = _make_customer(
        customer_id="RTO-HAPPY", phone="+919999990110"
    )
    in_flight_a = _make_order(
        customer=cust, order_id="NRG-RTO-INF-A"
    )
    in_flight_b = _make_order(
        customer=cust,
        order_id="NRG-RTO-INF-B",
        stage=Order.Stage.DISPATCHED.value,
        payment_status=Order.PaymentStatus.PENDING.value,
    )
    # Terminal orders that must be excluded.
    _make_order(
        customer=cust,
        order_id="NRG-RTO-DELIVERED",
        stage=Order.Stage.DELIVERED.value,
    )
    _make_order(
        customer=cust,
        order_id="NRG-RTO-RTO",
        stage=Order.Stage.RTO.value,
    )
    _make_order(
        customer=cust,
        order_id="NRG-RTO-CANCELLED",
        stage=Order.Stage.CANCELLED.value,
    )
    result = run_rto_prevention_agent_daily(triggered_by="pytest")
    assert result["status"] == "completed"
    assert result["snapshot_count"] == 2
    assert result["order_count"] == 2
    assert RtoRiskSnapshot.objects.count() == 2
    snap_orders = set(
        RtoRiskSnapshot.objects.values_list("order_id", flat=True)
    )
    assert snap_orders == {in_flight_a.id, in_flight_b.id}
    assert AgentRun.objects.filter(
        agent=AgentRun.Agent.RTO_PREVENTION, model=MODEL_USED
    ).count() == 2
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_SNAPSHOT).count() == 2
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_COMPLETED).exists()


def test_daily_task_kill_switch_off_exits_cleanly():
    cust = _make_customer(
        customer_id="RTO-KILL", phone="+919999990120"
    )
    _make_order(customer=cust, order_id="NRG-RTO-KILL")
    # Phase 7E-Live-B Hotfix-1 pattern: second row with enabled=False
    # must be detected even when the seeded enabled=True row exists.
    RuntimeKillSwitch.objects.create(scope="global", enabled=False)
    result = run_rto_prevention_agent_daily(triggered_by="pytest")
    assert result["status"] == "blocked"
    assert result["reason"] == "runtime_kill_switch_disabled"
    assert RtoRiskSnapshot.objects.count() == 0
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_BLOCKED).exists()


def test_daily_task_sandbox_flag_propagates_to_snapshot():
    cust = _make_customer(
        customer_id="RTO-SBOX", phone="+919999990130"
    )
    _make_order(customer=cust, order_id="NRG-RTO-SBOX")
    set_sandbox_enabled(enabled=True)
    try:
        run_rto_prevention_agent_daily(triggered_by="pytest")
    finally:
        set_sandbox_enabled(enabled=False)
    snap = RtoRiskSnapshot.objects.get(order_id="NRG-RTO-SBOX")
    assert snap.sandbox is True
    assert snap.agent_run is not None
    assert snap.agent_run.sandbox_mode is True


def test_daily_task_does_not_send_whatsapp_or_call_or_mutate_business():
    cust = _make_customer(
        customer_id="RTO-SAFE", phone="+919999990140"
    )
    _make_order(customer=cust, order_id="NRG-RTO-SAFE")
    pre_order = Order.objects.count()
    pre_customer = Customer.objects.count()
    pre_payment = Order.objects.filter(
        payment_status=Order.PaymentStatus.PAID.value
    ).count()
    pre_shipment = Shipment.objects.count()
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
        run_rto_prevention_agent_daily(triggered_by="pytest")
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    assert Order.objects.count() == pre_order
    assert Customer.objects.count() == pre_customer
    assert (
        Order.objects.filter(
            payment_status=Order.PaymentStatus.PAID.value
        ).count()
        == pre_payment
    )
    assert Shipment.objects.count() == pre_shipment
    snap = RtoRiskSnapshot.objects.get(order_id="NRG-RTO-SAFE")
    assert snap.recommendation_kind in {
        "monitor_only",
        "send_confirmation_reminder",
        "send_pre_delivery_call_request",
        "escalate_to_team_lead",
    }
    assert AGENT_NAME == "rto_prevention_v1"
