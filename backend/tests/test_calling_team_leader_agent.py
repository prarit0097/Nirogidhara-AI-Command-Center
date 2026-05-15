from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.agents.calling_team_leader.models import (
    CallingTeamLeaderSnapshot,
)
from apps.agents.calling_team_leader.service import (
    AGENT_NAME,
    MODEL_USED,
    CallingSignals,
    _parse_duration_seconds,
    build_snapshot,
    compute_agent_breakdown_30d,
    compute_avg_duration_30d,
    compute_call_counts,
    compute_connection_stats_30d,
    compute_outcome_breakdown_30d,
    compute_signals,
    compute_transcript_backlog,
    detect_anomalies,
)
from apps.agents.calling_team_leader.tasks import (
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_COMPLETED,
    AUDIT_KIND_SNAPSHOT,
    run_calling_team_leader_agent_daily,
)
from apps.ai_governance.models import AgentRun
from apps.ai_governance.sandbox import set_sandbox_enabled
from apps.audit.models import AuditEvent
from apps.calls.models import Call, CallTranscriptLine
from apps.crm.models import Customer
from apps.orders.models import Order
from apps.saas.models import RuntimeKillSwitch


pytestmark = pytest.mark.django_db


def _make_call(
    *,
    call_id: str,
    lead_id: str = "LD-CTL",
    agent: str = "AI-Agent-A",
    status: str = Call.Status.COMPLETED.value,
    duration: str = "1:30",
    created_offset_hours: float = 1.0,
) -> Call:
    call = Call.objects.create(
        id=call_id,
        lead_id=lead_id,
        customer="Test",
        phone="+919999993000",
        agent=agent,
        language="Hindi",
        duration=duration,
        status=status,
    )
    if created_offset_hours:
        Call.objects.filter(pk=call.pk).update(
            created_at=timezone.now()
            - timedelta(hours=created_offset_hours)
        )
        call.refresh_from_db()
    return call


# ---------------------------------------------------------------------------
# _parse_duration_seconds
# ---------------------------------------------------------------------------


def test_parse_duration_handles_known_formats():
    assert _parse_duration_seconds("0:00") == 0
    assert _parse_duration_seconds("1:30") == 90
    assert _parse_duration_seconds("12:05") == 725
    assert _parse_duration_seconds("1:02:03") == 3723
    assert _parse_duration_seconds("45") == 45


def test_parse_duration_returns_zero_on_garbage():
    assert _parse_duration_seconds("") == 0
    assert _parse_duration_seconds("abc") == 0
    assert _parse_duration_seconds("1:bad:3") == 0


# ---------------------------------------------------------------------------
# compute_call_counts
# ---------------------------------------------------------------------------


def test_call_counts_window_filtering():
    _make_call(call_id="CL-A", created_offset_hours=2)
    _make_call(call_id="CL-B", created_offset_hours=72)
    _make_call(call_id="CL-OLD", created_offset_hours=24 * 40)
    counts = compute_call_counts()
    assert counts["call_count_24h"] == 1
    assert counts["call_count_7d"] == 2
    assert counts["call_count_30d"] == 2


# ---------------------------------------------------------------------------
# compute_connection_stats_30d
# ---------------------------------------------------------------------------


def test_connection_stats_happy_path():
    _make_call(call_id="CL-C1", status=Call.Status.COMPLETED.value)
    _make_call(call_id="CL-C2", status=Call.Status.COMPLETED.value)
    _make_call(call_id="CL-M1", status=Call.Status.MISSED.value)
    _make_call(call_id="CL-F1", status=Call.Status.FAILED.value)
    stats = compute_connection_stats_30d()
    assert stats["answered_count_30d"] == 2
    assert stats["connection_rate_30d"] == 0.5


def test_connection_stats_zero_calls():
    stats = compute_connection_stats_30d()
    assert stats["answered_count_30d"] == 0
    assert stats["connection_rate_30d"] == 0.0


# ---------------------------------------------------------------------------
# compute_avg_duration_30d
# ---------------------------------------------------------------------------


def test_avg_duration_happy_path():
    _make_call(call_id="CL-D1", duration="1:00")  # 60s
    _make_call(call_id="CL-D2", duration="2:00")  # 120s
    _make_call(
        call_id="CL-D-MISSED",
        status=Call.Status.MISSED.value,
        duration="5:00",  # ignored
    )
    avg = compute_avg_duration_30d()
    assert avg == 90.0  # (60+120)/2


def test_avg_duration_returns_zero_when_no_answered_calls():
    _make_call(
        call_id="CL-D-NA",
        status=Call.Status.MISSED.value,
        duration="3:00",
    )
    assert compute_avg_duration_30d() == 0.0


# ---------------------------------------------------------------------------
# compute_outcome_breakdown_30d (groups by Call.status)
# ---------------------------------------------------------------------------


def test_outcome_breakdown_groups_by_status():
    _make_call(call_id="CL-O1", status=Call.Status.COMPLETED.value)
    _make_call(call_id="CL-O2", status=Call.Status.COMPLETED.value)
    _make_call(call_id="CL-O3", status=Call.Status.MISSED.value)
    _make_call(call_id="CL-O4", status=Call.Status.FAILED.value)
    breakdown = compute_outcome_breakdown_30d()
    assert breakdown == {
        "Completed": 2,
        "Missed": 1,
        "Failed": 1,
    }


def test_outcome_breakdown_empty_db_returns_empty():
    assert compute_outcome_breakdown_30d() == {}


# ---------------------------------------------------------------------------
# compute_agent_breakdown_30d
# ---------------------------------------------------------------------------


def test_agent_breakdown_with_field_groups_and_orders_by_count():
    for i in range(3):
        _make_call(
            call_id=f"CL-AG-A{i}",
            agent="Agent-A",
            status=Call.Status.COMPLETED.value,
            duration="1:00",
        )
    _make_call(
        call_id="CL-AG-B1",
        agent="Agent-B",
        status=Call.Status.COMPLETED.value,
        duration="2:00",
    )
    _make_call(
        call_id="CL-AG-B2",
        agent="Agent-B",
        status=Call.Status.MISSED.value,
        duration="0:00",
    )
    rows = compute_agent_breakdown_30d(top_n=10)
    assert rows[0]["agent_id"] == "Agent-A"
    assert rows[0]["call_count"] == 3
    assert rows[0]["connection_rate"] == 1.0
    assert rows[0]["avg_duration_seconds"] == 60.0
    assert rows[1]["agent_id"] == "Agent-B"
    assert rows[1]["call_count"] == 2
    assert rows[1]["connection_rate"] == 0.5


def test_agent_breakdown_without_field_returns_empty_list():
    _make_call(call_id="CL-AG-NO", agent="Agent-X")
    # Caller forces the no-field branch by overriding the flag.
    rows = compute_agent_breakdown_30d(has_agent_field=False)
    assert rows == []


# ---------------------------------------------------------------------------
# compute_transcript_backlog
# ---------------------------------------------------------------------------


def test_transcript_backlog_excludes_calls_with_transcripts_and_fresh_calls():
    backlog = _make_call(
        call_id="CL-BACKLOG-1",
        created_offset_hours=48,
    )
    # Newer call (within last 24h) shouldn't count as backlog.
    _make_call(call_id="CL-FRESH", created_offset_hours=2)
    # Old call with transcript line shouldn't count.
    transcribed = _make_call(
        call_id="CL-TRANS",
        created_offset_hours=48,
    )
    CallTranscriptLine.objects.create(
        call=transcribed, order=0, who="agent", text="hello"
    )
    assert compute_transcript_backlog() == 1
    assert backlog.id == "CL-BACKLOG-1"


# ---------------------------------------------------------------------------
# detect_anomalies
# ---------------------------------------------------------------------------


def test_detect_anomalies_low_connection_rate_only_for_high_volume():
    small = CallingSignals(
        snapshot_at=timezone.now(),
        call_count_30d=5,
        connection_rate_30d=0.0,
    )
    assert "low_connection_rate" not in detect_anomalies(small)
    big = CallingSignals(
        snapshot_at=timezone.now(),
        call_count_30d=50,
        connection_rate_30d=0.20,
    )
    assert "low_connection_rate" in detect_anomalies(big)


def test_detect_anomalies_high_transcript_backlog():
    s = CallingSignals(
        snapshot_at=timezone.now(), transcript_backlog_count=25
    )
    assert "high_transcript_backlog" in detect_anomalies(s)


def test_detect_anomalies_no_calls_today():
    s = CallingSignals(
        snapshot_at=timezone.now(),
        call_count_24h=0,
        call_count_7d=10,
    )
    assert "no_calls_today" in detect_anomalies(s)


def test_detect_anomalies_agent_concentration_risk():
    s = CallingSignals(
        snapshot_at=timezone.now(),
        call_count_30d=100,
        agent_breakdown=[
            {"agent_id": "A", "agent_label": "A", "call_count": 80},
            {"agent_id": "B", "agent_label": "B", "call_count": 20},
        ],
    )
    assert "agent_concentration_risk" in detect_anomalies(s)


def test_detect_anomalies_no_agent_attribution_field():
    s = CallingSignals(
        snapshot_at=timezone.now(),
        call_count_30d=50,
        connection_rate_30d=0.8,
        has_agent_field=False,
        agent_breakdown=[],
    )
    alerts = detect_anomalies(s)
    assert "no_agent_attribution_field" in alerts
    # Informational only — all_clear still present because no real problem.
    assert "all_clear" in alerts


def test_detect_anomalies_all_clear_when_healthy():
    s = CallingSignals(
        snapshot_at=timezone.now(),
        call_count_24h=10,
        call_count_7d=70,
        call_count_30d=300,
        connection_rate_30d=0.65,
        agent_breakdown=[
            {"agent_id": "A", "agent_label": "A", "call_count": 60},
            {"agent_id": "B", "agent_label": "B", "call_count": 100},
            {"agent_id": "C", "agent_label": "C", "call_count": 140},
        ],
    )
    assert detect_anomalies(s) == ["all_clear"]


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_daily_task_happy_path_persists_one_snapshot():
    _make_call(call_id="CL-T1", status=Call.Status.COMPLETED.value)
    result = run_calling_team_leader_agent_daily(triggered_by="pytest")
    assert result["status"] == "completed"
    assert result["snapshot"]["call_count_30d"] == 1
    assert CallingTeamLeaderSnapshot.objects.count() == 1
    run = AgentRun.objects.get(agent=AgentRun.Agent.CALLING_TEAM_LEADER)
    assert run.model == MODEL_USED
    assert run.dry_run is True
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_SNAPSHOT).count() == 1
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_COMPLETED).count() == 1


def test_daily_task_kill_switch_off_exits_cleanly():
    RuntimeKillSwitch.objects.create(scope="global", enabled=False)
    result = run_calling_team_leader_agent_daily(triggered_by="pytest")
    assert result["status"] == "blocked"
    assert result["reason"] == "runtime_kill_switch_disabled"
    assert CallingTeamLeaderSnapshot.objects.count() == 0
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_BLOCKED).exists()


def test_daily_task_sandbox_flag_propagates():
    set_sandbox_enabled(enabled=True)
    try:
        run_calling_team_leader_agent_daily(triggered_by="pytest")
    finally:
        set_sandbox_enabled(enabled=False)
    snap = CallingTeamLeaderSnapshot.objects.get()
    assert snap.sandbox is True
    assert snap.agent_run is not None
    assert snap.agent_run.sandbox_mode is True


def test_daily_task_does_not_send_whatsapp_or_call_or_mutate_business():
    _make_call(call_id="CL-S", status=Call.Status.COMPLETED.value)
    Customer.objects.create(
        id="CTL-C-1",
        name="C",
        phone="+919999993111",
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
    )
    Order.objects.create(
        id="NRG-CTL-1",
        customer_name="C",
        phone="+919999993111",
        product="Nirogidhara",
        quantity=1,
        amount=3000,
        state="Delhi",
        city="Delhi",
    )
    pre_call = Call.objects.count()
    pre_customer = Customer.objects.count()
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
        run_calling_team_leader_agent_daily(triggered_by="pytest")
    wa_queue.assert_not_called()
    wa_freeform.assert_not_called()
    call_trigger.assert_not_called()
    ship_create.assert_not_called()
    assert Call.objects.count() == pre_call
    assert Customer.objects.count() == pre_customer
    assert Order.objects.count() == pre_order
    assert AGENT_NAME == "calling_team_leader_v1"


def test_compute_signals_empty_db_is_all_clear():
    signals = compute_signals()
    assert signals.call_count_30d == 0
    assert "all_clear" in signals.alerts


def test_build_snapshot_propagates_fields():
    s = CallingSignals(
        snapshot_at=timezone.now(),
        call_count_30d=5,
        agent_breakdown=[
            {
                "agent_id": "A",
                "agent_label": "A",
                "call_count": 3,
                "connection_rate": 1.0,
                "avg_duration_seconds": 60.0,
            }
        ],
        outcome_breakdown={"Completed": 3, "Missed": 2},
    )
    s.alerts = detect_anomalies(s)
    snap = build_snapshot(s, sandbox=True)
    assert snap.call_count_30d == 5
    assert snap.agent_breakdown[0]["agent_id"] == "A"
    assert snap.outcome_breakdown == {"Completed": 3, "Missed": 2}
    assert snap.sandbox is True
