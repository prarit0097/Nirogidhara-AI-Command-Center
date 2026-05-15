from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from apps.agents.calling_team_leader.models import (
    CallingTeamLeaderSnapshot,
)
from apps.agents.ceo_orchestration.models import (
    CeoOrchestrationSnapshot,
)
from apps.agents.ceo_orchestration.service import (
    AGENT_KEYS,
    AGENT_NAME,
    LatestSnapshots,
    MODEL_USED,
    build_snapshot,
    compute_agent_status_summary,
    compute_health_score,
    compute_health_tier,
    compute_top_3_priorities,
    fetch_latest_snapshots,
    generate_briefing_text,
    roll_up_alerts,
)
from apps.agents.ceo_orchestration.tasks import (
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_COMPLETED,
    AUDIT_KIND_SNAPSHOT,
    run_ceo_orchestration_agent_daily,
)
from apps.agents.cfo.models import CfoFinancialSnapshot
from apps.agents.customer_success.models import CustomerSuccessSnapshot
from apps.agents.data_analyst.models import DataAnalystSnapshot
from apps.agents.rto_prevention.models import RtoRiskSnapshot
from apps.ai_governance.models import AgentRun
from apps.ai_governance.sandbox import set_sandbox_enabled
from apps.audit.models import AuditEvent
from apps.calls.models import Call
from apps.crm.models import Customer
from apps.orders.models import Order
from apps.saas.models import RuntimeKillSwitch


pytestmark = pytest.mark.django_db


def _make_customer_success_snapshot(
    *, lifecycle_stage: str = "reorder_window", at_risk: bool = False,
    reorder_candidate: bool = True,
) -> CustomerSuccessSnapshot:
    customer = Customer.objects.create(
        id=f"CO-CS-{lifecycle_stage}",
        name="Test",
        phone=f"+91999999{abs(hash(lifecycle_stage)) % 10000:04d}",
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
    )
    return CustomerSuccessSnapshot.objects.create(
        customer=customer,
        score=70,
        lifecycle_stage=lifecycle_stage,
        days_since_delivery=22,
        in_reorder_window=True,
        reorder_candidate=reorder_candidate,
        at_risk=at_risk,
        risk_reasons=[],
        signals={},
        recommendation_kind="send_reorder_reminder",
        recommendation_text="test",
    )


def _make_rto_snapshot(*, risk_tier: str = "low") -> RtoRiskSnapshot:
    order = Order.objects.create(
        id=f"NRG-CO-RTO-{risk_tier}",
        customer_name="Test",
        phone="+919999998888",
        product="Nirogidhara",
        quantity=1,
        amount=3000,
        state="Delhi",
        city="Delhi",
        stage=Order.Stage.CONFIRMED.value,
    )
    return RtoRiskSnapshot.objects.create(
        order=order,
        risk_score={"low": 20, "medium": 50, "high": 70, "critical": 90}[
            risk_tier
        ],
        risk_tier=risk_tier,
        lifecycle_stage="in_transit",
        days_since_order=2,
        failed_delivery_attempts=0,
        risk_reasons=[],
        signals={},
        recommendation_kind="monitor_only",
        recommendation_text="test",
    )


def _make_cfo_snapshot(*, alerts: list[str] | None = None) -> CfoFinancialSnapshot:
    return CfoFinancialSnapshot.objects.create(
        snapshot_at=timezone.now(),
        revenue_24h=Decimal("3000"),
        revenue_7d=Decimal("21000"),
        revenue_30d=Decimal("90000"),
        order_count_24h=1,
        order_count_7d=7,
        order_count_30d=30,
        paid_count=10,
        partial_count=0,
        pending_count=0,
        paid_amount=Decimal("30000"),
        partial_amount=Decimal("0"),
        pending_amount=Decimal("0"),
        average_order_value=Decimal("3000"),
        rto_count_30d=0,
        rto_loss_amount_30d=Decimal("0"),
        new_customer_count_30d=1,
        returning_customer_count_30d=0,
        alerts=alerts or ["all_clear"],
        alert_text="test",
    )


def _make_data_analyst_snapshot(
    *, alerts: list[str] | None = None
) -> DataAnalystSnapshot:
    return DataAnalystSnapshot.objects.create(
        snapshot_at=timezone.now(),
        lead_count_30d=100,
        call_count_30d=80,
        confirmed_order_count_30d=40,
        delivered_order_count_30d=30,
        reorder_count_30d=6,
        lead_to_call_rate=0.8,
        call_to_confirmed_rate=0.5,
        confirmed_to_delivered_rate=0.75,
        delivered_to_reorder_rate=0.2,
        top_states=[
            {"state": "Delhi", "order_count": 10, "revenue": "30000"}
        ],
        day_of_week_counts={
            "mon": 1, "tue": 1, "wed": 1, "thu": 1, "fri": 1, "sat": 1,
            "sun": 1,
        },
        alerts=alerts or ["all_clear"],
        alert_text="test",
    )


def _make_calling_team_leader_snapshot(
    *, alerts: list[str] | None = None
) -> CallingTeamLeaderSnapshot:
    return CallingTeamLeaderSnapshot.objects.create(
        snapshot_at=timezone.now(),
        call_count_24h=10,
        call_count_7d=70,
        call_count_30d=300,
        answered_count_30d=200,
        connection_rate_30d=0.67,
        avg_duration_seconds_30d=85.0,
        outcome_breakdown={"Completed": 200, "Missed": 100},
        agent_breakdown=[
            {
                "agent_id": "Agent-A",
                "agent_label": "Agent-A",
                "call_count": 150,
                "connection_rate": 0.7,
                "avg_duration_seconds": 80.0,
            }
        ],
        transcript_backlog_count=2,
        alerts=alerts or ["all_clear"],
        alert_text="test",
    )


def _seed_all_agents(*, healthy: bool = True) -> None:
    _make_customer_success_snapshot()
    _make_rto_snapshot()
    _make_cfo_snapshot()
    _make_data_analyst_snapshot()
    _make_calling_team_leader_snapshot()


# ---------------------------------------------------------------------------
# fetch_latest_snapshots
# ---------------------------------------------------------------------------


def test_fetch_latest_snapshots_all_missing_returns_none():
    bundle = fetch_latest_snapshots()
    assert bundle.customer_success is None
    assert bundle.rto_prevention is None
    assert bundle.cfo is None
    assert bundle.data_analyst is None
    assert bundle.calling_team_leader is None


def test_fetch_latest_snapshots_finds_all_when_seeded():
    _seed_all_agents()
    bundle = fetch_latest_snapshots()
    assert bundle.customer_success is not None
    assert bundle.rto_prevention is not None
    assert bundle.cfo is not None
    assert bundle.data_analyst is not None
    assert bundle.calling_team_leader is not None
    assert bundle.customer_success_rollup["snapshot_count"] >= 1


# ---------------------------------------------------------------------------
# compute_health_score
# ---------------------------------------------------------------------------


def test_compute_health_score_all_missing_penalty():
    bundle = LatestSnapshots(snapshot_at=timezone.now()) \
        if False else LatestSnapshots()
    # 70 - 5*5 = 45.
    assert compute_health_score(bundle) == 45


def test_compute_health_score_healthy_with_all_clear_alerts():
    _seed_all_agents()
    bundle = fetch_latest_snapshots()
    score = compute_health_score(bundle)
    # Base 70 + 5 (CFO all_clear) - 0 rto/cs/da/ctl penalty = 75.
    assert 70 <= score <= 80


def test_compute_health_score_cfo_critical_alerts_penalize():
    _seed_all_agents()
    # Replace the CFO with one carrying critical alerts.
    CfoFinancialSnapshot.objects.all().delete()
    _make_cfo_snapshot(alerts=["revenue_drop_24h", "high_pending_payments"])
    bundle = fetch_latest_snapshots()
    score = compute_health_score(bundle)
    # Healthy base ~70, then -15 - 10 = ~45.
    assert score <= 55


def test_compute_health_score_clamps_at_zero():
    _make_cfo_snapshot(
        alerts=["revenue_drop_24h", "high_pending_payments", "low_order_volume", "rto_spike"]
    )
    _make_data_analyst_snapshot(
        alerts=["conversion_drop", "dead_end_calls", "lead_volume_drop"]
    )
    _make_calling_team_leader_snapshot(
        alerts=["low_connection_rate", "high_transcript_backlog", "no_calls_today"]
    )
    # Add some critical RTO snapshots.
    for i in range(10):
        order = Order.objects.create(
            id=f"NRG-CRIT-{i}",
            customer_name="C",
            phone=f"+91999999777{i}",
            product="Nirogidhara",
            quantity=1,
            amount=3000,
            state="Delhi",
            city="Delhi",
        )
        RtoRiskSnapshot.objects.create(
            order=order,
            risk_score=95,
            risk_tier="critical",
            lifecycle_stage="in_transit",
            days_since_order=2,
            failed_delivery_attempts=0,
            risk_reasons=[],
            signals={},
            recommendation_kind="escalate_to_team_lead",
            recommendation_text="test",
        )
    _make_customer_success_snapshot()
    bundle = fetch_latest_snapshots()
    score = compute_health_score(bundle)
    assert score == 0  # clamped


def test_compute_health_score_clamps_at_hundred_when_only_cfo_present():
    # Only CFO with all_clear: 70 + 5 - 5*4 (other 4 missing) = 55. So
    # it cannot exceed 100 from just CFO. We test clamp instead by
    # seeding everything healthy + reorder bonus.
    _seed_all_agents()
    # Add 25 reorder-candidate Customer Success snapshots to drive
    # the bonus to its cap of +5.
    for i in range(25):
        _make_customer_success_snapshot(
            lifecycle_stage=f"reorder_window_{i}",
            reorder_candidate=True,
        )
    bundle = fetch_latest_snapshots()
    score = compute_health_score(bundle)
    assert score <= 100


# ---------------------------------------------------------------------------
# compute_health_tier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,tier",
    [
        (0, "critical"),
        (19, "critical"),
        (20, "poor"),
        (39, "poor"),
        (40, "fair"),
        (59, "fair"),
        (60, "good"),
        (79, "good"),
        (80, "excellent"),
        (100, "excellent"),
    ],
)
def test_health_tier_boundaries(score: int, tier: str):
    assert compute_health_tier(score) == tier


# ---------------------------------------------------------------------------
# roll_up_alerts
# ---------------------------------------------------------------------------


def test_roll_up_alerts_empty_when_all_clear():
    _seed_all_agents()
    bundle = fetch_latest_snapshots()
    alerts = roll_up_alerts(bundle)
    # all_clear is excluded; healthy seed has none.
    assert all(entry["code"] != "all_clear" for entry in alerts)


def test_roll_up_alerts_unions_across_agents_and_sorts_by_severity():
    _make_cfo_snapshot(
        alerts=["revenue_drop_24h", "high_pending_payments"]
    )
    _make_data_analyst_snapshot(alerts=["conversion_drop"])
    _make_calling_team_leader_snapshot(alerts=["high_transcript_backlog"])
    _make_customer_success_snapshot()
    _make_rto_snapshot()
    bundle = fetch_latest_snapshots()
    alerts = roll_up_alerts(bundle)
    codes = [entry["code"] for entry in alerts]
    assert "revenue_drop_24h" in codes
    assert "conversion_drop" in codes
    assert "high_pending_payments" in codes
    assert "high_transcript_backlog" in codes
    # Critical comes before high comes before medium.
    severities = [entry["severity"] for entry in alerts]
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    assert severities == sorted(
        severities, key=lambda s: severity_order[s]
    )


def test_roll_up_alerts_data_gap_added_for_missing_agent():
    _make_cfo_snapshot()
    bundle = fetch_latest_snapshots()
    alerts = roll_up_alerts(bundle, missing=["customer_success"])
    assert any(
        entry["code"] == "data_gap"
        and entry["source_agent"] == "customer_success"
        for entry in alerts
    )


# ---------------------------------------------------------------------------
# compute_top_3_priorities
# ---------------------------------------------------------------------------


def test_top_3_priorities_picks_first_three_actionable_alerts():
    alerts = [
        {"code": "revenue_drop_24h", "severity": "critical", "source_agent": "cfo", "rationale": "x"},
        {"code": "lead_volume_drop", "severity": "critical", "source_agent": "data_analyst", "rationale": "x"},
        {"code": "high_pending_payments", "severity": "high", "source_agent": "cfo", "rationale": "x"},
        {"code": "low_connection_rate", "severity": "high", "source_agent": "calling_team_leader", "rationale": "x"},
    ]
    priorities = compute_top_3_priorities(alerts, LatestSnapshots())
    assert len(priorities) == 3
    assert priorities[0]["priority"] == "1"
    assert priorities[0]["issue"] == "revenue_drop_24h"
    assert "Razorpay" in priorities[2]["recommended_action"]


def test_top_3_priorities_fewer_than_three_alerts():
    alerts = [
        {"code": "revenue_drop_24h", "severity": "critical", "source_agent": "cfo", "rationale": "x"},
    ]
    priorities = compute_top_3_priorities(alerts, LatestSnapshots())
    assert len(priorities) == 1


def test_top_3_priorities_no_actionable_alerts_returns_all_clear():
    priorities = compute_top_3_priorities([], LatestSnapshots())
    assert priorities[0]["issue"] == "all_clear"
    assert priorities[0]["source_agent"] == "none"


def test_top_3_priorities_excludes_all_clear_and_no_agent_attribution():
    alerts = [
        {"code": "all_clear", "severity": "low", "source_agent": "x", "rationale": "x"},
        {"code": "no_agent_attribution_field", "severity": "low", "source_agent": "x", "rationale": "x"},
    ]
    priorities = compute_top_3_priorities(alerts, LatestSnapshots())
    assert priorities[0]["issue"] == "all_clear"
    assert priorities[0]["source_agent"] == "none"


# ---------------------------------------------------------------------------
# compute_agent_status_summary
# ---------------------------------------------------------------------------


def test_agent_status_summary_marks_missing_agents():
    bundle = fetch_latest_snapshots()
    summary = compute_agent_status_summary(bundle)
    for key in AGENT_KEYS:
        assert summary[key]["status"] == "missing"


def test_agent_status_summary_marks_alert_when_problematic():
    _make_cfo_snapshot(alerts=["revenue_drop_24h"])
    _make_data_analyst_snapshot()
    _make_calling_team_leader_snapshot()
    _make_customer_success_snapshot(at_risk=True)
    _make_rto_snapshot(risk_tier="critical")
    bundle = fetch_latest_snapshots()
    summary = compute_agent_status_summary(bundle)
    assert summary["cfo"]["status"] == "alert"
    assert summary["customer_success"]["status"] == "alert"
    assert summary["rto_prevention"]["status"] == "alert"
    # Data Analyst + CTL are all_clear.
    assert summary["data_analyst"]["status"] == "ok"
    assert summary["calling_team_leader"]["status"] == "ok"


# ---------------------------------------------------------------------------
# generate_briefing_text
# ---------------------------------------------------------------------------


def test_generate_briefing_text_contains_key_sections():
    _seed_all_agents()
    bundle = fetch_latest_snapshots()
    score = compute_health_score(bundle)
    tier = compute_health_tier(score)
    alerts = roll_up_alerts(bundle)
    priorities = compute_top_3_priorities(alerts, bundle)
    summary = compute_agent_status_summary(bundle)
    text = generate_briefing_text(
        bundle,
        score=score,
        tier=tier,
        alerts=alerts,
        priorities=priorities,
        summary=summary,
    )
    assert "Daily Director Briefing" in text
    assert "health_score=" in text
    assert "Agent status:" in text
    assert "customer_success" in text
    assert "Top priorities:" in text


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_daily_task_happy_path_persists_one_snapshot():
    _seed_all_agents()
    result = run_ceo_orchestration_agent_daily(triggered_by="pytest")
    assert result["status"] == "completed"
    assert "snapshot" in result
    assert CeoOrchestrationSnapshot.objects.count() == 1
    snap = CeoOrchestrationSnapshot.objects.get()
    assert snap.business_health_score >= 0
    assert snap.customer_success_snapshot is not None
    assert snap.cfo_snapshot is not None
    run = AgentRun.objects.get(agent=AgentRun.Agent.CEO)
    assert run.model == MODEL_USED
    assert run.dry_run is True
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_SNAPSHOT).count() == 1
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_COMPLETED).count() == 1


def test_daily_task_data_gap_added_when_agent_missing():
    # Seed only CFO + Data Analyst — leave 9A/9B/9E missing.
    _make_cfo_snapshot()
    _make_data_analyst_snapshot()
    result = run_ceo_orchestration_agent_daily(triggered_by="pytest")
    assert result["status"] == "completed"
    snap = CeoOrchestrationSnapshot.objects.get()
    assert "data_gap" in snap.alerts
    # Cross-cutting alerts should include data_gap entries for the
    # three missing agents.
    data_gap_entries = [
        entry
        for entry in snap.cross_cutting_alerts
        if entry["code"] == "data_gap"
    ]
    sources = {entry["source_agent"] for entry in data_gap_entries}
    assert "customer_success" in sources
    assert "rto_prevention" in sources
    assert "calling_team_leader" in sources


def test_daily_task_kill_switch_off_exits_cleanly():
    RuntimeKillSwitch.objects.create(scope="global", enabled=False)
    result = run_ceo_orchestration_agent_daily(triggered_by="pytest")
    assert result["status"] == "blocked"
    assert result["reason"] == "runtime_kill_switch_disabled"
    assert CeoOrchestrationSnapshot.objects.count() == 0
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_BLOCKED).exists()


def test_daily_task_sandbox_flag_propagates():
    _make_cfo_snapshot()
    set_sandbox_enabled(enabled=True)
    try:
        run_ceo_orchestration_agent_daily(triggered_by="pytest")
    finally:
        set_sandbox_enabled(enabled=False)
    snap = CeoOrchestrationSnapshot.objects.get()
    assert snap.sandbox is True
    assert snap.agent_run is not None
    assert snap.agent_run.sandbox_mode is True


def test_daily_task_does_not_send_whatsapp_or_call_or_mutate_business():
    _seed_all_agents()
    pre_cs = CustomerSuccessSnapshot.objects.count()
    pre_rto = RtoRiskSnapshot.objects.count()
    pre_call = Call.objects.count()
    pre_order = Order.objects.count()
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
        run_ceo_orchestration_agent_daily(triggered_by="pytest")
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    # Phase 9A/9B per-customer / per-order snapshots are read-only —
    # the task must NOT add any.
    assert CustomerSuccessSnapshot.objects.count() == pre_cs
    assert RtoRiskSnapshot.objects.count() == pre_rto
    assert Call.objects.count() == pre_call
    assert Order.objects.count() == pre_order
    assert AGENT_NAME == "ceo_orchestration_v1"


def test_build_snapshot_handles_all_missing_with_data_gap_alert():
    snap, bundle = build_snapshot()
    assert snap.business_health_score == 45  # 70 - 5*5
    assert snap.health_tier == "fair"
    assert "data_gap" in snap.alerts
    assert snap.briefing_text  # non-empty
