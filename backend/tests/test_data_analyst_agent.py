from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from apps.agents.data_analyst.models import DataAnalystSnapshot
from apps.agents.data_analyst.service import (
    AGENT_NAME,
    MODEL_USED,
    AnalystSignals,
    build_snapshot,
    compute_conversion_rates,
    compute_day_of_week_counts_30d,
    compute_funnel_counts,
    compute_signals,
    compute_top_states_30d,
    detect_anomalies,
)
from apps.agents.data_analyst.tasks import (
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_COMPLETED,
    AUDIT_KIND_SNAPSHOT,
    run_data_analyst_agent_daily,
)
from apps.ai_governance.models import AgentRun
from apps.ai_governance.sandbox import set_sandbox_enabled
from apps.audit.models import AuditEvent
from apps.calls.models import Call
from apps.crm.models import Customer, Lead
from apps.orders.models import Order
from apps.saas.models import RuntimeKillSwitch


pytestmark = pytest.mark.django_db


def _make_lead(*, lead_id: str, phone: str) -> Lead:
    return Lead.objects.create(
        id=lead_id,
        name="Test Lead",
        phone=phone,
        state="Delhi",
        city="Delhi",
        language="Hindi",
        source="Meta",
        campaign="Test",
        product_interest="Nirogidhara",
    )


def _make_call(*, call_id: str, lead_id: str, phone: str) -> Call:
    return Call.objects.create(
        id=call_id,
        lead_id=lead_id,
        customer="Test",
        phone=phone,
        agent="AI",
        language="Hindi",
    )


def _make_order(
    *,
    order_id: str,
    phone: str,
    stage: str = Order.Stage.CONFIRMED.value,
    amount: int = 3000,
    state: str = "Delhi",
    created_offset_days: int = 1,
) -> Order:
    order = Order.objects.create(
        id=order_id,
        customer_name="Test",
        phone=phone,
        product="Nirogidhara",
        quantity=1,
        amount=amount,
        state=state,
        city="Delhi",
        stage=stage,
    )
    if created_offset_days:
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(days=created_offset_days)
        )
        order.refresh_from_db()
    return order


# ---------------------------------------------------------------------------
# Funnel counts
# ---------------------------------------------------------------------------


def test_funnel_counts_basic_fixture():
    _make_lead(lead_id="LD-1", phone="+919999992001")
    _make_lead(lead_id="LD-2", phone="+919999992002")
    _make_call(call_id="CL-1", lead_id="LD-1", phone="+919999992001")
    _make_order(
        order_id="NRG-DA-1",
        phone="+919999992001",
        stage=Order.Stage.CONFIRMED.value,
    )
    _make_order(
        order_id="NRG-DA-2",
        phone="+919999992001",
        stage=Order.Stage.DELIVERED.value,
    )
    # Older delivered order so the same phone has >= 2 orders => reorder.
    _make_order(
        order_id="NRG-DA-OLD",
        phone="+919999992001",
        stage=Order.Stage.DELIVERED.value,
        created_offset_days=100,
    )
    counts = compute_funnel_counts()
    assert counts["lead_count_30d"] == 2
    assert counts["call_count_30d"] == 1
    # Both in-window orders are confirmed-or-beyond.
    assert counts["confirmed_order_count_30d"] == 2
    assert counts["delivered_order_count_30d"] == 1
    # phone has 3 total orders. In-window=2, total-1=2. min(2,2)=2 reorder.
    assert counts["reorder_count_30d"] == 2


def test_funnel_counts_excludes_outside_window():
    _make_lead(lead_id="LD-OLD", phone="+919999992011")
    Lead.objects.filter(pk="LD-OLD").update(
        created_at=timezone.now() - timedelta(days=60)
    )
    counts = compute_funnel_counts()
    assert counts["lead_count_30d"] == 0


# ---------------------------------------------------------------------------
# Conversion rates
# ---------------------------------------------------------------------------


def test_conversion_rates_happy_path():
    counts = {
        "lead_count_30d": 100,
        "call_count_30d": 80,
        "confirmed_order_count_30d": 40,
        "delivered_order_count_30d": 30,
        "reorder_count_30d": 6,
    }
    rates = compute_conversion_rates(counts)
    assert rates["lead_to_call_rate"] == 0.8
    assert rates["call_to_confirmed_rate"] == 0.5
    assert rates["confirmed_to_delivered_rate"] == 0.75
    assert rates["delivered_to_reorder_rate"] == 0.2


def test_conversion_rates_zero_denominator_guards():
    counts = {
        "lead_count_30d": 0,
        "call_count_30d": 0,
        "confirmed_order_count_30d": 0,
        "delivered_order_count_30d": 0,
        "reorder_count_30d": 0,
    }
    rates = compute_conversion_rates(counts)
    assert rates["lead_to_call_rate"] == 0.0
    assert rates["call_to_confirmed_rate"] == 0.0
    assert rates["confirmed_to_delivered_rate"] == 0.0
    assert rates["delivered_to_reorder_rate"] == 0.0


# ---------------------------------------------------------------------------
# Top states
# ---------------------------------------------------------------------------


def test_top_states_30d_orders_and_revenue_grouped_by_state():
    _make_order(
        order_id="NRG-S-1", phone="+919999992020", state="Delhi", amount=3000
    )
    _make_order(
        order_id="NRG-S-2", phone="+919999992020", state="Delhi", amount=3000
    )
    _make_order(
        order_id="NRG-S-3", phone="+919999992021", state="Mumbai", amount=4000
    )
    top = compute_top_states_30d(n=5)
    assert top[0]["state"] == "Delhi"
    assert top[0]["order_count"] == 2
    assert top[0]["revenue"] == "6000"
    assert top[1]["state"] == "Mumbai"
    assert top[1]["order_count"] == 1
    assert top[1]["revenue"] == "4000"


def test_top_states_30d_limits_to_n():
    for i, state in enumerate(
        ("Delhi", "Mumbai", "Bengaluru", "Pune", "Chennai", "Jaipur")
    ):
        _make_order(
            order_id=f"NRG-LMT-{i}",
            phone=f"+91999999204{i}",
            state=state,
        )
    top = compute_top_states_30d(n=3)
    assert len(top) == 3


# ---------------------------------------------------------------------------
# Day of week counts
# ---------------------------------------------------------------------------


def test_day_of_week_counts_30d_buckets_every_weekday():
    now = timezone.now()
    for offset in range(7):
        order = _make_order(
            order_id=f"NRG-DOW-{offset}",
            phone=f"+91999999203{offset}",
        )
        Order.objects.filter(pk=order.pk).update(
            created_at=now - timedelta(days=offset)
        )
    buckets = compute_day_of_week_counts_30d()
    assert set(buckets.keys()) == {
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    }
    assert sum(buckets.values()) == 7


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------


def test_detect_anomalies_lead_volume_drop():
    s = AnalystSignals(snapshot_at=timezone.now())
    assert "lead_volume_drop" in detect_anomalies(s)


def test_detect_anomalies_conversion_drop_only_for_large_samples():
    # Upstream <= threshold => no alert.
    small = AnalystSignals(
        snapshot_at=timezone.now(),
        lead_count_30d=5,
        call_count_30d=0,
        lead_to_call_rate=0.0,
    )
    assert "conversion_drop" not in detect_anomalies(small)
    # Upstream above threshold AND rate < 0.10 => alert fires.
    big = AnalystSignals(
        snapshot_at=timezone.now(),
        lead_count_30d=100,
        call_count_30d=5,
        lead_to_call_rate=0.05,
    )
    assert "conversion_drop" in detect_anomalies(big)


def test_detect_anomalies_geographic_concentration_shift():
    s = AnalystSignals(
        snapshot_at=timezone.now(),
        lead_count_30d=10,
        call_count_30d=10,
        top_states=[
            {"state": "Delhi", "order_count": 12, "revenue": "0"},
            {"state": "Mumbai", "order_count": 2, "revenue": "0"},
        ],
    )
    assert (
        "geographic_concentration_shift" in detect_anomalies(s)
    )


def test_detect_anomalies_dead_end_calls():
    s = AnalystSignals(
        snapshot_at=timezone.now(),
        lead_count_30d=10,
        call_count_30d=20,
        call_to_confirmed_rate=0.01,
    )
    assert "dead_end_calls" in detect_anomalies(s)


def test_detect_anomalies_all_clear_when_no_signal():
    s = AnalystSignals(
        snapshot_at=timezone.now(),
        lead_count_30d=100,
        call_count_30d=70,
        confirmed_order_count_30d=40,
        delivered_order_count_30d=35,
        reorder_count_30d=8,
        lead_to_call_rate=0.7,
        call_to_confirmed_rate=0.57,
        confirmed_to_delivered_rate=0.875,
        delivered_to_reorder_rate=0.23,
        top_states=[
            {"state": "Delhi", "order_count": 10, "revenue": "0"},
            {"state": "Mumbai", "order_count": 8, "revenue": "0"},
        ],
    )
    assert detect_anomalies(s) == ["all_clear"]


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_daily_task_happy_path_persists_one_snapshot():
    _make_lead(lead_id="LD-T1", phone="+919999992100")
    _make_call(call_id="CL-T1", lead_id="LD-T1", phone="+919999992100")
    _make_order(
        order_id="NRG-T1",
        phone="+919999992100",
        stage=Order.Stage.DELIVERED.value,
    )
    result = run_data_analyst_agent_daily(triggered_by="pytest")
    assert result["status"] == "completed"
    assert result["snapshot"]["lead_count_30d"] == 1
    assert result["snapshot"]["call_count_30d"] == 1
    assert DataAnalystSnapshot.objects.count() == 1
    run = AgentRun.objects.get(agent=AgentRun.Agent.DATA_ANALYST)
    assert run.model == MODEL_USED
    assert run.dry_run is True
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_SNAPSHOT).count() == 1
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_COMPLETED).count() == 1


def test_daily_task_kill_switch_off_exits_cleanly():
    RuntimeKillSwitch.objects.create(scope="global", enabled=False)
    result = run_data_analyst_agent_daily(triggered_by="pytest")
    assert result["status"] == "blocked"
    assert result["reason"] == "runtime_kill_switch_disabled"
    assert DataAnalystSnapshot.objects.count() == 0
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_BLOCKED).exists()


def test_daily_task_sandbox_flag_propagates_to_snapshot():
    set_sandbox_enabled(enabled=True)
    try:
        run_data_analyst_agent_daily(triggered_by="pytest")
    finally:
        set_sandbox_enabled(enabled=False)
    snap = DataAnalystSnapshot.objects.get()
    assert snap.sandbox is True
    assert snap.agent_run is not None
    assert snap.agent_run.sandbox_mode is True


def test_daily_task_does_not_send_whatsapp_or_call_or_mutate_business():
    _make_lead(lead_id="LD-S", phone="+919999992110")
    _make_call(call_id="CL-S", lead_id="LD-S", phone="+919999992110")
    _make_order(order_id="NRG-S-SAFE", phone="+919999992110")
    pre_lead = Lead.objects.count()
    pre_call = Call.objects.count()
    pre_order = Order.objects.count()
    pre_customer = Customer.objects.count()
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
        run_data_analyst_agent_daily(triggered_by="pytest")
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    assert Lead.objects.count() == pre_lead
    assert Call.objects.count() == pre_call
    assert Order.objects.count() == pre_order
    assert Customer.objects.count() == pre_customer
    assert DataAnalystSnapshot.objects.count() == 1
    assert AGENT_NAME == "data_analyst_v1"


def test_compute_signals_empty_db_is_all_clear_with_lead_drop():
    signals = compute_signals()
    # Empty DB triggers lead_volume_drop (lead_count_30d == 0).
    assert "lead_volume_drop" in signals.alerts


def test_build_snapshot_propagates_fields():
    s = AnalystSignals(
        snapshot_at=timezone.now(),
        lead_count_30d=5,
        top_states=[
            {"state": "Delhi", "order_count": 5, "revenue": "1000"}
        ],
        day_of_week_counts={
            "mon": 1, "tue": 0, "wed": 0, "thu": 0, "fri": 0, "sat": 0, "sun": 0,
        },
    )
    s.alerts = detect_anomalies(s)
    snap = build_snapshot(s, sandbox=True)
    assert snap.lead_count_30d == 5
    assert snap.top_states[0]["state"] == "Delhi"
    assert snap.day_of_week_counts["mon"] == 1
    assert snap.sandbox is True
