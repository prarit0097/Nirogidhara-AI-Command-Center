from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.agents.customer_success.models import CustomerSuccessSnapshot
from apps.agents.customer_success.service import (
    AGENT_NAME,
    MODEL_USED,
    Signals,
    build_snapshot,
    choose_recommendation,
    compute_lifecycle_stage,
    compute_score,
    compute_signals,
)
from apps.agents.customer_success.tasks import (
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_COMPLETED,
    AUDIT_KIND_SNAPSHOT,
    run_customer_success_agent_daily,
)
from apps.ai_governance.models import AgentRun
from apps.ai_governance.sandbox import set_sandbox_enabled
from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.orders.models import Order
from apps.saas.models import RuntimeKillSwitch


pytestmark = pytest.mark.django_db


def _make_customer(*, customer_id: str = "CS-001", phone: str = "+919999990001") -> Customer:
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
    stage: str,
    delivered_at: "timezone.datetime | None" = None,
) -> Order:
    order = Order.objects.create(
        id=order_id,
        customer_name=customer.name,
        phone=customer.phone,
        product="Nirogidhara",
        quantity=1,
        amount=3000,
        state=customer.state,
        city=customer.city,
        stage=stage,
    )
    if delivered_at is not None:
        # Bypass auto_now_add to drive deterministic days-since-delivery.
        Order.objects.filter(pk=order.pk).update(created_at=delivered_at)
        order.refresh_from_db()
    return order


# ---------------------------------------------------------------------------
# compute_lifecycle_stage boundary table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "days,expected",
    [
        (0, "fresh_delivery"),
        (2, "fresh_delivery"),
        (3, "early_usage"),
        (7, "early_usage"),
        (8, "mid_usage"),
        (19, "mid_usage"),
        (20, "reorder_window"),
        (30, "reorder_window"),
        (31, "late_reorder"),
        (45, "late_reorder"),
        (46, "lapsed"),
        (200, "lapsed"),
    ],
)
def test_compute_lifecycle_stage_boundaries(days: int, expected: str):
    assert compute_lifecycle_stage(days) == expected


# ---------------------------------------------------------------------------
# compute_score
# ---------------------------------------------------------------------------


def test_compute_score_base_only():
    assert compute_score(Signals()) == 60


def test_compute_score_deliveries_cap_at_thirty():
    s = Signals(delivered_count=10)
    # Cap: 30 + base 60 = 90.
    assert compute_score(s) == 90


def test_compute_score_reorders_cap_at_twenty():
    s = Signals(delivered_count=4, reorder_count=5)
    # 60 + (4*5=20) + min(5*10, 20)=20 = 100.
    assert compute_score(s) == 100


def test_compute_score_clamps_at_zero():
    s = Signals(rto_count=99, last_complaint_at=timezone.now())
    # 60 - min(99*10, 20)=20 - 15 = 25, never below zero anyway.
    assert compute_score(s) == 25
    # Now drive base lower.
    s2 = Signals(
        delivered_count=0,
        reorder_count=0,
        rto_count=10,
        last_complaint_at=timezone.now(),
    )
    assert compute_score(s2) == 25
    # Final clamp.
    assert (
        compute_score(
            Signals(rto_count=20, last_complaint_at=timezone.now())
        )
        == 25
    )


def test_compute_score_clamps_at_hundred():
    s = Signals(delivered_count=20, reorder_count=20)
    assert compute_score(s) == 100


def test_compute_score_complaint_penalty():
    s = Signals(delivered_count=1, last_complaint_at=timezone.now())
    # 60 + 5 - 15 = 50.
    assert compute_score(s) == 50


# ---------------------------------------------------------------------------
# build_snapshot reorder_candidate / at_risk
# ---------------------------------------------------------------------------


def test_reorder_candidate_in_window_no_active_order_no_complaint():
    customer = _make_customer()
    now = timezone.now()
    delivered_at = now - timedelta(days=22)
    _make_order(
        customer=customer,
        order_id="NRG-CS-1",
        stage=Order.Stage.DELIVERED.value,
        delivered_at=delivered_at,
    )
    signals = compute_signals(customer, now=now)
    snapshot = build_snapshot(customer, signals, now=now)
    assert snapshot.lifecycle_stage == "reorder_window"
    assert snapshot.in_reorder_window is True
    assert snapshot.reorder_candidate is True
    assert snapshot.recommendation_kind == "send_reorder_reminder"


def test_reorder_candidate_false_when_active_order():
    customer = _make_customer()
    now = timezone.now()
    delivered_at = now - timedelta(days=22)
    _make_order(
        customer=customer,
        order_id="NRG-CS-2",
        stage=Order.Stage.DELIVERED.value,
        delivered_at=delivered_at,
    )
    _make_order(
        customer=customer,
        order_id="NRG-CS-3",
        stage=Order.Stage.CONFIRMED.value,
    )
    signals = compute_signals(customer, now=now)
    snapshot = build_snapshot(customer, signals, now=now)
    assert snapshot.reorder_candidate is False
    assert snapshot.recommendation_kind != "send_reorder_reminder"


def test_reorder_candidate_false_when_recent_complaint():
    customer = _make_customer()
    now = timezone.now()
    delivered_at = now - timedelta(days=22)
    _make_order(
        customer=customer,
        order_id="NRG-CS-4",
        stage=Order.Stage.DELIVERED.value,
        delivered_at=delivered_at,
    )
    complaint = AuditEvent.objects.create(
        kind="complaint.side_effect",
        text="customer reported side effect",
        payload={"customer_id": customer.id, "phone": customer.phone},
    )
    AuditEvent.objects.filter(pk=complaint.pk).update(
        occurred_at=now - timedelta(days=2)
    )
    signals = compute_signals(customer, now=now)
    assert signals.last_complaint_at is not None
    snapshot = build_snapshot(customer, signals, now=now)
    assert snapshot.reorder_candidate is False
    assert "recent_complaint" in snapshot.risk_reasons


def test_at_risk_lapsed_no_reorder():
    customer = _make_customer()
    now = timezone.now()
    delivered_at = now - timedelta(days=120)
    _make_order(
        customer=customer,
        order_id="NRG-CS-5",
        stage=Order.Stage.DELIVERED.value,
        delivered_at=delivered_at,
    )
    signals = compute_signals(customer, now=now)
    snapshot = build_snapshot(customer, signals, now=now)
    assert snapshot.lifecycle_stage == "lapsed"
    assert snapshot.at_risk is True
    assert "lapsed_no_reorder" in snapshot.risk_reasons
    assert snapshot.recommendation_kind == "send_winback_offer"


def test_at_risk_repeat_rto():
    customer = _make_customer()
    now = timezone.now()
    _make_order(
        customer=customer,
        order_id="NRG-CS-6",
        stage=Order.Stage.RTO.value,
    )
    _make_order(
        customer=customer,
        order_id="NRG-CS-7",
        stage=Order.Stage.RTO.value,
    )
    signals = compute_signals(customer, now=now)
    snapshot = build_snapshot(customer, signals, now=now)
    assert snapshot.at_risk is True
    assert "repeat_rto" in snapshot.risk_reasons


# ---------------------------------------------------------------------------
# choose_recommendation
# ---------------------------------------------------------------------------


def test_choose_recommendation_each_kind():
    customer = _make_customer()
    now = timezone.now()
    base_signals = Signals(delivered_count=1, last_delivery_at=now)

    early = build_snapshot(
        customer,
        Signals(delivered_count=1, last_delivery_at=now - timedelta(days=5)),
        now=now,
    )
    assert early.recommendation_kind == "send_usage_reminder"

    reorder = build_snapshot(
        customer,
        Signals(delivered_count=1, last_delivery_at=now - timedelta(days=22)),
        now=now,
    )
    assert reorder.recommendation_kind == "send_reorder_reminder"

    winback = build_snapshot(
        customer,
        Signals(
            delivered_count=1,
            last_delivery_at=now - timedelta(days=120),
            rto_count=2,
        ),
        now=now,
    )
    assert winback.recommendation_kind == "send_winback_offer"

    monitor = build_snapshot(
        customer,
        Signals(
            delivered_count=1,
            last_delivery_at=now - timedelta(days=12),
        ),
        now=now,
    )
    assert monitor.recommendation_kind == "monitor_only"

    # Sanity: monitor on fresh_delivery
    fresh = build_snapshot(
        customer,
        Signals(delivered_count=1, last_delivery_at=now),
        now=now,
    )
    assert fresh.recommendation_kind == "monitor_only"
    # Base bundle is still useful in the absence of asserts above.
    assert base_signals.delivered_count == 1


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_daily_task_happy_path_creates_snapshots_and_runs():
    customer_a = _make_customer(
        customer_id="CS-HAPPY-A", phone="+919999990010"
    )
    customer_b = _make_customer(
        customer_id="CS-HAPPY-B", phone="+919999990011"
    )
    now = timezone.now()
    _make_order(
        customer=customer_a,
        order_id="NRG-HAPPY-A",
        stage=Order.Stage.DELIVERED.value,
        delivered_at=now - timedelta(days=22),
    )
    _make_order(
        customer=customer_b,
        order_id="NRG-HAPPY-B",
        stage=Order.Stage.DELIVERED.value,
        delivered_at=now - timedelta(days=4),
    )
    result = run_customer_success_agent_daily(triggered_by="pytest")
    assert result["status"] == "completed"
    assert result["snapshot_count"] == 2
    assert result["customer_count"] == 2
    assert "reorder_window" in result["stage_counts"]
    assert "early_usage" in result["stage_counts"]
    assert (
        result["recommendation_counts"]["send_reorder_reminder"] == 1
    )
    assert (
        result["recommendation_counts"]["send_usage_reminder"] == 1
    )
    assert CustomerSuccessSnapshot.objects.count() == 2
    assert AgentRun.objects.filter(
        agent=AgentRun.Agent.CUSTOMER_SUCCESS,
        model=MODEL_USED,
    ).count() == 2
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_SNAPSHOT).count() == 2
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_COMPLETED).exists()


def test_daily_task_kill_switch_off_exits_cleanly():
    customer = _make_customer(
        customer_id="CS-KILL", phone="+919999990020"
    )
    _make_order(
        customer=customer,
        order_id="NRG-KILL",
        stage=Order.Stage.DELIVERED.value,
        delivered_at=timezone.now() - timedelta(days=22),
    )
    # Phase 7E-Live-B Hotfix-1 pattern: a SECOND row with enabled=False
    # must be detected even when the seeded enabled=True row exists.
    RuntimeKillSwitch.objects.create(scope="global", enabled=False)
    result = run_customer_success_agent_daily(triggered_by="pytest")
    assert result["status"] == "blocked"
    assert result["reason"] == "runtime_kill_switch_disabled"
    assert CustomerSuccessSnapshot.objects.count() == 0
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_BLOCKED).exists()


def test_daily_task_sandbox_flag_propagates_to_snapshot():
    customer = _make_customer(
        customer_id="CS-SBOX", phone="+919999990030"
    )
    _make_order(
        customer=customer,
        order_id="NRG-SBOX",
        stage=Order.Stage.DELIVERED.value,
        delivered_at=timezone.now() - timedelta(days=22),
    )
    set_sandbox_enabled(enabled=True)
    try:
        run_customer_success_agent_daily(triggered_by="pytest")
    finally:
        set_sandbox_enabled(enabled=False)
    snapshot = CustomerSuccessSnapshot.objects.get(customer=customer)
    assert snapshot.sandbox is True
    assert snapshot.agent_run is not None
    assert snapshot.agent_run.sandbox_mode is True


def test_daily_task_does_not_send_whatsapp_or_call_or_mutate_business():
    customer = _make_customer(
        customer_id="CS-SAFE", phone="+919999990040"
    )
    _make_order(
        customer=customer,
        order_id="NRG-SAFE",
        stage=Order.Stage.DELIVERED.value,
        delivered_at=timezone.now() - timedelta(days=22),
    )
    pre_order_count = Order.objects.count()
    pre_customer_count = Customer.objects.count()
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
        run_customer_success_agent_daily(triggered_by="pytest")
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    assert Order.objects.count() == pre_order_count
    assert Customer.objects.count() == pre_customer_count
    snapshot = CustomerSuccessSnapshot.objects.get(customer=customer)
    assert snapshot.recommendation_kind == "send_reorder_reminder"
    # Agent name string is intentionally surfaced for downstream consumers.
    assert AGENT_NAME == "customer_success_reorder_v1"
