from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from apps.agents.cfo.models import CfoFinancialSnapshot
from apps.agents.cfo.service import (
    AGENT_NAME,
    MODEL_USED,
    FinancialSignals,
    build_snapshot,
    compute_aov_30d,
    compute_customer_mix_30d,
    compute_payment_breakdown,
    compute_rolling_order_count,
    compute_rolling_revenue,
    compute_rto_impact_30d,
    compute_signals,
    detect_anomalies,
)
from apps.agents.cfo.tasks import (
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_COMPLETED,
    AUDIT_KIND_SNAPSHOT,
    run_cfo_agent_daily,
)
from apps.ai_governance.models import AgentRun
from apps.ai_governance.sandbox import set_sandbox_enabled
from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.saas.models import RuntimeKillSwitch


pytestmark = pytest.mark.django_db


def _make_customer(
    *, customer_id: str, phone: str
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
    order_id: str,
    phone: str,
    stage: str = Order.Stage.CONFIRMED.value,
    amount: int = 3000,
    created_offset_days: int = 1,
) -> Order:
    order = Order.objects.create(
        id=order_id,
        customer_name="Test Customer",
        phone=phone,
        product="Nirogidhara",
        quantity=1,
        amount=amount,
        state="Delhi",
        city="Delhi",
        stage=stage,
    )
    if created_offset_days:
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(days=created_offset_days)
        )
        order.refresh_from_db()
    return order


def _make_payment(
    *,
    payment_id: str,
    order_id: str,
    amount: int,
    status: str,
    created_offset_days: int = 1,
) -> Payment:
    payment = Payment.objects.create(
        id=payment_id,
        order_id=order_id,
        customer="Test Customer",
        amount=amount,
        status=status,
    )
    if created_offset_days:
        Payment.objects.filter(pk=payment.pk).update(
            created_at=timezone.now() - timedelta(days=created_offset_days)
        )
        payment.refresh_from_db()
    return payment


# ---------------------------------------------------------------------------
# Rolling revenue + order count
# ---------------------------------------------------------------------------


def test_rolling_revenue_includes_only_paid_within_window():
    _make_customer(customer_id="CFO-C1", phone="+919999991001")
    order = _make_order(
        order_id="NRG-CFO-1", phone="+919999991001", amount=3000
    )
    _make_payment(
        payment_id="PAY-CFO-1",
        order_id=order.id,
        amount=3000,
        status=Payment.Status.PAID.value,
        created_offset_days=0,
    )
    # Outside 24h window.
    _make_payment(
        payment_id="PAY-CFO-OLD",
        order_id=order.id,
        amount=5000,
        status=Payment.Status.PAID.value,
        created_offset_days=10,
    )
    # Non-paid never counts.
    _make_payment(
        payment_id="PAY-CFO-PEND",
        order_id=order.id,
        amount=999,
        status=Payment.Status.PENDING.value,
        created_offset_days=0,
    )
    rev_24h = compute_rolling_revenue(window_days=1)
    rev_30d = compute_rolling_revenue(window_days=30)
    assert rev_24h == Decimal("3000")
    assert rev_30d == Decimal("8000")


def test_rolling_order_count_respects_window():
    _make_customer(customer_id="CFO-C2", phone="+919999991002")
    _make_order(
        order_id="NRG-CFO-W1",
        phone="+919999991002",
        created_offset_days=0,
    )
    _make_order(
        order_id="NRG-CFO-W2",
        phone="+919999991002",
        created_offset_days=5,
    )
    _make_order(
        order_id="NRG-CFO-W3",
        phone="+919999991002",
        created_offset_days=40,
    )
    assert compute_rolling_order_count(window_days=1) == 1
    assert compute_rolling_order_count(window_days=7) == 2
    assert compute_rolling_order_count(window_days=30) == 2


# ---------------------------------------------------------------------------
# Payment breakdown
# ---------------------------------------------------------------------------


def test_payment_breakdown_counts_and_amounts():
    _make_customer(customer_id="CFO-PB", phone="+919999991010")
    order = _make_order(order_id="NRG-CFO-PB", phone="+919999991010")
    _make_payment(
        payment_id="PAY-PB-1",
        order_id=order.id,
        amount=2000,
        status=Payment.Status.PAID.value,
    )
    _make_payment(
        payment_id="PAY-PB-2",
        order_id=order.id,
        amount=499,
        status=Payment.Status.PARTIAL.value,
    )
    _make_payment(
        payment_id="PAY-PB-3",
        order_id=order.id,
        amount=3500,
        status=Payment.Status.PENDING.value,
    )
    breakdown = compute_payment_breakdown()
    assert breakdown["paid_count"] == 1
    assert breakdown["partial_count"] == 1
    assert breakdown["pending_count"] == 1
    assert breakdown["paid_amount"] == Decimal("2000")
    assert breakdown["partial_amount"] == Decimal("499")
    assert breakdown["pending_amount"] == Decimal("3500")


# ---------------------------------------------------------------------------
# AOV
# ---------------------------------------------------------------------------


def test_aov_zero_when_no_orders():
    assert compute_aov_30d() == Decimal("0")


def test_aov_average_of_amounts():
    _make_customer(customer_id="CFO-AOV", phone="+919999991020")
    _make_order(
        order_id="NRG-CFO-AOV1", phone="+919999991020", amount=2000
    )
    _make_order(
        order_id="NRG-CFO-AOV2", phone="+919999991020", amount=4000
    )
    assert compute_aov_30d() == Decimal("3000.00")


# ---------------------------------------------------------------------------
# RTO impact
# ---------------------------------------------------------------------------


def test_rto_impact_sums_amount_and_count():
    _make_customer(customer_id="CFO-RTO", phone="+919999991030")
    _make_order(
        order_id="NRG-CFO-RTO1",
        phone="+919999991030",
        stage=Order.Stage.RTO.value,
        amount=3000,
    )
    _make_order(
        order_id="NRG-CFO-RTO2",
        phone="+919999991030",
        stage=Order.Stage.RTO.value,
        amount=2500,
    )
    # Non-RTO orders must NOT contribute to loss.
    _make_order(
        order_id="NRG-CFO-OK",
        phone="+919999991030",
        stage=Order.Stage.DELIVERED.value,
        amount=10_000,
    )
    rto = compute_rto_impact_30d()
    assert rto["rto_count_30d"] == 2
    assert rto["rto_loss_amount_30d"] == Decimal("5500")


# ---------------------------------------------------------------------------
# Customer mix
# ---------------------------------------------------------------------------


def test_customer_mix_buckets_new_vs_returning():
    new = _make_customer(customer_id="CFO-NEW", phone="+919999991040")
    returning = _make_customer(
        customer_id="CFO-RET", phone="+919999991041"
    )
    # Returning: order before AND after the 30d cutoff.
    _make_order(
        order_id="NRG-CFO-OLD",
        phone=returning.phone,
        created_offset_days=60,
    )
    _make_order(
        order_id="NRG-CFO-RECENT",
        phone=returning.phone,
        created_offset_days=2,
    )
    # New: order only inside the window.
    _make_order(
        order_id="NRG-CFO-NEW",
        phone=new.phone,
        created_offset_days=2,
    )
    mix = compute_customer_mix_30d()
    assert mix["new_customer_count_30d"] == 1
    assert mix["returning_customer_count_30d"] == 1


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------


def test_detect_anomalies_revenue_drop_24h():
    s = FinancialSignals(
        snapshot_at=timezone.now(),
        revenue_24h=Decimal("100"),
        revenue_7d=Decimal("7000"),  # avg 1000/day; 100 < 500.
    )
    assert "revenue_drop_24h" in detect_anomalies(s)


def test_detect_anomalies_rto_spike():
    s = FinancialSignals(
        snapshot_at=timezone.now(),
        order_count_30d=10,
        rto_count_30d=2,  # 20% > 15%
    )
    assert "rto_spike" in detect_anomalies(s)


def test_detect_anomalies_high_pending_payments():
    s = FinancialSignals(
        snapshot_at=timezone.now(),
        paid_count=2,
        pending_count=5,
    )
    assert "high_pending_payments" in detect_anomalies(s)


def test_detect_anomalies_low_order_volume():
    s = FinancialSignals(
        snapshot_at=timezone.now(),
        order_count_24h=0,
        order_count_7d=5,
    )
    assert "low_order_volume" in detect_anomalies(s)


def test_detect_anomalies_all_clear_when_no_signal():
    s = FinancialSignals(
        snapshot_at=timezone.now(),
        revenue_24h=Decimal("1000"),
        revenue_7d=Decimal("7000"),
        order_count_24h=5,
        order_count_7d=30,
        order_count_30d=100,
        rto_count_30d=5,  # 5% < 15%
        paid_count=10,
        pending_count=1,
    )
    alerts = detect_anomalies(s)
    assert alerts == ["all_clear"]


# ---------------------------------------------------------------------------
# build_snapshot composition
# ---------------------------------------------------------------------------


def test_build_snapshot_propagates_all_fields():
    s = FinancialSignals(
        snapshot_at=timezone.now(),
        revenue_24h=Decimal("100"),
        revenue_30d=Decimal("3000"),
        order_count_30d=10,
        rto_count_30d=3,
        rto_loss_amount_30d=Decimal("9000"),
        new_customer_count_30d=4,
        returning_customer_count_30d=2,
    )
    s.alerts = detect_anomalies(s)
    snap = build_snapshot(s, sandbox=True)
    assert snap.revenue_24h == Decimal("100")
    assert snap.revenue_30d == Decimal("3000")
    assert snap.order_count_30d == 10
    assert snap.rto_count_30d == 3
    assert snap.new_customer_count_30d == 4
    assert snap.returning_customer_count_30d == 2
    assert "rto_spike" in snap.alerts
    assert snap.sandbox is True


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_daily_task_happy_path_persists_one_snapshot():
    _make_customer(customer_id="CFO-HAPPY", phone="+919999991060")
    order = _make_order(
        order_id="NRG-CFO-HAPPY",
        phone="+919999991060",
        amount=3000,
    )
    _make_payment(
        payment_id="PAY-CFO-HAPPY",
        order_id=order.id,
        amount=3000,
        status=Payment.Status.PAID.value,
        created_offset_days=0,
    )
    result = run_cfo_agent_daily(triggered_by="pytest")
    assert result["status"] == "completed"
    assert "snapshot" in result
    assert result["snapshot"]["revenue_24h"] == "3000"
    assert CfoFinancialSnapshot.objects.count() == 1
    snap = CfoFinancialSnapshot.objects.get()
    assert snap.alerts  # at least "all_clear" or a real alert
    run = AgentRun.objects.get(agent=AgentRun.Agent.CFO)
    assert run.model == MODEL_USED
    assert run.dry_run is True
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_SNAPSHOT).count() == 1
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_COMPLETED).count() == 1


def test_daily_task_kill_switch_off_exits_cleanly():
    # Phase 7E-Live-B Hotfix-1 pattern: a SECOND row with enabled=False
    # must be detected even when the seeded enabled=True row exists.
    RuntimeKillSwitch.objects.create(scope="global", enabled=False)
    result = run_cfo_agent_daily(triggered_by="pytest")
    assert result["status"] == "blocked"
    assert result["reason"] == "runtime_kill_switch_disabled"
    assert CfoFinancialSnapshot.objects.count() == 0
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_BLOCKED).exists()


def test_daily_task_sandbox_flag_propagates_to_snapshot():
    set_sandbox_enabled(enabled=True)
    try:
        run_cfo_agent_daily(triggered_by="pytest")
    finally:
        set_sandbox_enabled(enabled=False)
    snap = CfoFinancialSnapshot.objects.get()
    assert snap.sandbox is True
    assert snap.agent_run is not None
    assert snap.agent_run.sandbox_mode is True


def test_daily_task_does_not_send_whatsapp_or_call_or_mutate_business():
    _make_customer(customer_id="CFO-SAFE", phone="+919999991070")
    order = _make_order(order_id="NRG-CFO-SAFE", phone="+919999991070")
    _make_payment(
        payment_id="PAY-CFO-SAFE",
        order_id=order.id,
        amount=3000,
        status=Payment.Status.PAID.value,
        created_offset_days=0,
    )
    pre_order = Order.objects.count()
    pre_customer = Customer.objects.count()
    pre_payment = Payment.objects.count()
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
        run_cfo_agent_daily(triggered_by="pytest")
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    assert Order.objects.count() == pre_order
    assert Customer.objects.count() == pre_customer
    assert Payment.objects.count() == pre_payment
    assert CfoFinancialSnapshot.objects.count() == 1
    assert AGENT_NAME == "cfo_v1"


def test_compute_signals_handles_empty_db():
    signals = compute_signals()
    assert signals.revenue_24h == Decimal("0")
    assert signals.order_count_30d == 0
    # Empty DB → all_clear because no signal triggers.
    assert "all_clear" in signals.alerts
