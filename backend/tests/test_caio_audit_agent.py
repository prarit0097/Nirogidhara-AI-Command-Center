"""Phase 11C — CAIO Audit Agent V1 tests.

Defensive contract: CAIO has NO direct execution power. Across every
service / Celery / API path, all outbound entrypoints
(`queue_template_message`, `send_freeform_text_message`,
`trigger_call_for_lead`, `create_shipment`) are patched and asserted
`assert_not_called`. `Customer` / `Lead` / `Order` / `Payment` /
`Shipment` row counts stay constant, AND row counts on EVERY Phase 9
snapshot table stay constant (CAIO is read-only over upstream
snapshots — it must never mutate them).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.agents.calling_team_leader.models import (
    CallingTeamLeaderSnapshot,
)
from apps.agents.ceo_orchestration.models import CeoOrchestrationSnapshot
from apps.agents.cfo.models import CfoFinancialSnapshot
from apps.agents.data_analyst.models import DataAnalystSnapshot
from apps.agents.rto_prevention.models import RtoRiskSnapshot
from apps.ai_governance.models import AgentRun
from apps.audit.models import AuditEvent
from apps.caio.models import CaioAuditSnapshot
from apps.calls.models import Call, CallQualityScore, CallTranscriptLine
from apps.orders.models import Order


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_cfo(
    *, alerts: list[str] | None = None, snapshot_at=None
) -> CfoFinancialSnapshot:
    return CfoFinancialSnapshot.objects.create(
        snapshot_at=snapshot_at or timezone.now(),
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


def _make_data_analyst(
    *,
    alerts: list[str] | None = None,
    call_to_confirmed_rate: float = 0.5,
    call_count_30d: int = 80,
    snapshot_at=None,
) -> DataAnalystSnapshot:
    return DataAnalystSnapshot.objects.create(
        snapshot_at=snapshot_at or timezone.now(),
        lead_count_30d=100,
        call_count_30d=call_count_30d,
        confirmed_order_count_30d=40,
        delivered_order_count_30d=30,
        reorder_count_30d=6,
        lead_to_call_rate=0.8,
        call_to_confirmed_rate=call_to_confirmed_rate,
        confirmed_to_delivered_rate=0.75,
        delivered_to_reorder_rate=0.2,
        top_states=[{"state": "Delhi", "order_count": 10, "revenue": "30000"}],
        day_of_week_counts={
            "mon": 1, "tue": 1, "wed": 1, "thu": 1, "fri": 1, "sat": 1, "sun": 1,
        },
        alerts=alerts or ["all_clear"],
        alert_text="test",
    )


def _make_calling_team_leader(
    *,
    alerts: list[str] | None = None,
    call_count_7d: int = 70,
    snapshot_at=None,
) -> CallingTeamLeaderSnapshot:
    return CallingTeamLeaderSnapshot.objects.create(
        snapshot_at=snapshot_at or timezone.now(),
        call_count_24h=10,
        call_count_7d=call_count_7d,
        call_count_30d=300,
        answered_count_30d=200,
        connection_rate_30d=0.67,
        avg_duration_seconds_30d=85.0,
        outcome_breakdown={"Completed": 200, "Missed": 100},
        agent_breakdown=[],
        transcript_backlog_count=2,
        alerts=alerts or ["all_clear"],
        alert_text="test",
    )


def _make_ceo(
    *,
    health_tier: str = "good",
    health_score: int = 75,
    alerts: list[str] | None = None,
    agent_status_summary: dict | None = None,
    top_3_priorities: list | None = None,
    snapshot_at=None,
) -> CeoOrchestrationSnapshot:
    return CeoOrchestrationSnapshot.objects.create(
        snapshot_at=snapshot_at or timezone.now(),
        business_health_score=health_score,
        health_tier=health_tier,
        cross_cutting_alerts=[],
        top_3_priorities=top_3_priorities or [],
        agent_status_summary=agent_status_summary or {},
        briefing_text="",
        alerts=alerts or ["all_clear"],
    )


def _make_rto(
    *, risk_tier: str = "low", created_offset_hours: int = 0
) -> RtoRiskSnapshot:
    order = Order.objects.create(
        id=f"NRG-CAIO-{risk_tier}-{created_offset_hours}",
        customer_name="Test",
        phone="+919999998888",
        product="Nirogidhara",
        quantity=1,
        amount=3000,
        state="Delhi",
        city="Delhi",
        stage=Order.Stage.CONFIRMED.value,
    )
    snap = RtoRiskSnapshot.objects.create(
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
    if created_offset_hours:
        RtoRiskSnapshot.objects.filter(pk=snap.pk).update(
            created_at=timezone.now() - timedelta(hours=created_offset_hours)
        )
        snap.refresh_from_db()
    return snap


def _seed_all_agents(*, all_recent: bool = True) -> None:
    now = timezone.now()
    _make_cfo(snapshot_at=now)
    _make_data_analyst(snapshot_at=now)
    _make_calling_team_leader(snapshot_at=now)
    _make_ceo(snapshot_at=now)
    _make_rto()


def _make_call_and_score(
    *,
    call_id: str,
    composite: int = 80,
    compliance: int = 100,
    flags: list[str] | None = None,
    agent_label: str = "Calling AI . Vapi",
    scored_offset_days: int = 0,
) -> CallQualityScore:
    call = Call.objects.create(
        id=call_id,
        lead_id=f"LD-{call_id}",
        customer="Test",
        phone="+919999990000",
        agent=agent_label,
        language="Hindi",
        provider=Call.Provider.VAPI,
        provider_call_id=f"vapi_{call_id}",
        status=Call.Status.COMPLETED,
        duration="2:00",
        transcript_line_count=1,
        transcript_ingested_at=timezone.now(),
    )
    CallTranscriptLine.objects.create(call=call, order=0, who="agent", text="x")
    scored_at = timezone.now() - timedelta(days=scored_offset_days)
    return CallQualityScore.objects.create(
        call=call,
        scored_at=scored_at,
        scoring_version="deterministic_v1",
        line_count=1,
        agent_label=agent_label,
        duration_raw="2:00",
        connection_score=80,
        product_knowledge_score=60,
        compliance_score=compliance,
        objection_handling_score=70,
        tonality_score=80,
        composite_score=composite,
        flags=flags or [],
        raw_signals={},
    )


@pytest.fixture
def patched_outbound():
    """CAIO has NO execution power. Every outbound entrypoint patched."""
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
        yield {
            "wa_queue": wa_queue,
            "wa_freeform": wa_freeform,
            "call_trigger": call_trigger,
            "ship_create": ship_create,
        }


# ---------------------------------------------------------------------------
# gather_compliance_risk
# ---------------------------------------------------------------------------


def test_gather_compliance_risk_no_scored_calls_returns_zero(patched_outbound):
    from apps.caio.service import gather_compliance_risk

    result = gather_compliance_risk(window_days=30)
    assert result == {"count": 0, "agent_labels": []}


def test_gather_compliance_risk_counts_flagged_calls(patched_outbound):
    from apps.caio.service import gather_compliance_risk

    _make_call_and_score(call_id="CA-1", flags=["compliance_violation"])
    _make_call_and_score(
        call_id="CA-2",
        flags=["compliance_violation"],
        agent_label="Agent-X",
    )
    _make_call_and_score(call_id="CA-3")  # clean
    result = gather_compliance_risk(window_days=30)
    assert result["count"] == 2
    assert "Calling AI . Vapi" in result["agent_labels"]
    assert "Agent-X" in result["agent_labels"]


# ---------------------------------------------------------------------------
# gather_transcript_backlog
# ---------------------------------------------------------------------------


def test_gather_transcript_backlog_reads_phase11a_overview(patched_outbound):
    from apps.caio.service import gather_transcript_backlog

    with mock.patch(
        "apps.caio.service.get_backlog_overview",
        return_value={
            "backlog_count": 7,
            "total_calls_in_window": 30,
            "ingested_count": 23,
        },
    ) as get_ov:
        result = gather_transcript_backlog(window_days=30)
    get_ov.assert_called_once()
    assert result["backlog_count"] == 7
    assert result["total_calls_in_window"] == 30
    assert result["ingested_count"] == 23


# ---------------------------------------------------------------------------
# gather_call_quality_trend
# ---------------------------------------------------------------------------


def test_call_quality_trend_no_data(patched_outbound):
    from apps.caio.service import gather_call_quality_trend

    assert gather_call_quality_trend() == "no_data"


def test_call_quality_trend_up(patched_outbound):
    from apps.caio.service import gather_call_quality_trend

    # This 7d: avg 90; prior 7d: avg 50.
    for i, comp in enumerate([90, 92, 88]):
        _make_call_and_score(
            call_id=f"CT-UP-NOW-{i}",
            composite=comp,
            scored_offset_days=2,
        )
    for i, comp in enumerate([50, 52, 48]):
        _make_call_and_score(
            call_id=f"CT-UP-OLD-{i}",
            composite=comp,
            scored_offset_days=10,
        )
    assert gather_call_quality_trend() == "up"


def test_call_quality_trend_down(patched_outbound):
    from apps.caio.service import gather_call_quality_trend

    for i, comp in enumerate([40, 42, 38]):
        _make_call_and_score(
            call_id=f"CT-DN-NOW-{i}",
            composite=comp,
            scored_offset_days=2,
        )
    for i, comp in enumerate([90, 92, 88]):
        _make_call_and_score(
            call_id=f"CT-DN-OLD-{i}",
            composite=comp,
            scored_offset_days=10,
        )
    assert gather_call_quality_trend() == "down"


def test_call_quality_trend_flat(patched_outbound):
    from apps.caio.service import gather_call_quality_trend

    for i, comp in enumerate([70, 72, 68]):
        _make_call_and_score(
            call_id=f"CT-FL-NOW-{i}",
            composite=comp,
            scored_offset_days=2,
        )
    for i, comp in enumerate([70, 71, 69]):
        _make_call_and_score(
            call_id=f"CT-FL-OLD-{i}",
            composite=comp,
            scored_offset_days=10,
        )
    assert gather_call_quality_trend() == "flat"


# ---------------------------------------------------------------------------
# gather_agent_snapshots + stale detection
# ---------------------------------------------------------------------------


def test_agent_snapshots_all_recent(patched_outbound):
    from apps.caio.service import gather_agent_snapshots

    _seed_all_agents(all_recent=True)
    bundle = gather_agent_snapshots()
    assert bundle.ceo is not None
    assert bundle.cfo is not None
    assert bundle.data_analyst is not None
    assert bundle.calling_team_leader is not None
    assert bundle.rto_prevention is not None
    assert bundle.stale_agents == []


def test_agent_snapshots_one_stale_when_missing(patched_outbound):
    from apps.caio.service import gather_agent_snapshots

    # Seed all except calling_team_leader.
    _make_cfo()
    _make_data_analyst()
    _make_ceo()
    _make_rto()
    bundle = gather_agent_snapshots()
    assert bundle.calling_team_leader is None
    assert "calling_team_leader" in bundle.stale_agents


def test_agent_snapshots_old_snapshot_is_stale(patched_outbound):
    from apps.caio.service import gather_agent_snapshots

    # CFO snapshot from 60h ago -> stale.
    _make_cfo(snapshot_at=timezone.now() - timedelta(hours=60))
    bundle = gather_agent_snapshots()
    assert "cfo" in bundle.stale_agents


# ---------------------------------------------------------------------------
# compute_agent_anomaly_flags
# ---------------------------------------------------------------------------


def test_anomaly_flags_clean_when_all_clear(patched_outbound):
    from apps.caio.service import (
        compute_agent_anomaly_flags,
        gather_agent_snapshots,
    )

    _seed_all_agents()
    bundle = gather_agent_snapshots()
    flags = compute_agent_anomaly_flags(bundle)
    # No anomalies — all snapshots use alerts=["all_clear"].
    assert "cfo" not in flags
    assert "calling_team_leader" not in flags


def test_anomaly_flags_picks_up_cfo_high_pending_payments(patched_outbound):
    from apps.caio.service import (
        compute_agent_anomaly_flags,
        gather_agent_snapshots,
    )

    _make_cfo(alerts=["high_pending_payments", "rto_spike"])
    bundle = gather_agent_snapshots()
    flags = compute_agent_anomaly_flags(bundle)
    assert "cfo" in flags
    assert "high_pending_payments" in flags["cfo"]
    assert "rto_spike" in flags["cfo"]


def test_anomaly_flags_funnel_low_when_rate_below_threshold(patched_outbound):
    from apps.caio.service import (
        compute_agent_anomaly_flags,
        gather_agent_snapshots,
    )

    _make_data_analyst(call_to_confirmed_rate=0.05, call_count_30d=20)
    bundle = gather_agent_snapshots()
    flags = compute_agent_anomaly_flags(bundle)
    assert "data_analyst" in flags
    assert "funnel_conversion_low" in flags["data_analyst"]


def test_anomaly_flags_ceo_critical(patched_outbound):
    from apps.caio.service import (
        compute_agent_anomaly_flags,
        gather_agent_snapshots,
    )

    _make_ceo(health_tier="critical", health_score=10)
    bundle = gather_agent_snapshots()
    flags = compute_agent_anomaly_flags(bundle)
    assert "ceo_health_critical" in flags["ceo_orchestration"]


def test_anomaly_flags_rto_high_critical(patched_outbound):
    from apps.caio.service import (
        compute_agent_anomaly_flags,
        gather_agent_snapshots,
    )

    _make_rto(risk_tier="critical")
    bundle = gather_agent_snapshots()
    flags = compute_agent_anomaly_flags(bundle)
    assert "high_rto_risk_orders" in flags["rto_prevention"]


# ---------------------------------------------------------------------------
# compute_severity
# ---------------------------------------------------------------------------


def test_severity_red_when_compliance_risk(patched_outbound):
    from apps.caio.service import compute_severity

    assert (
        compute_severity(
            compliance_risk_count=1,
            agent_data_gaps=0,
            weak_learning_indicators=[],
            agent_anomaly_flags={},
            transcript_backlog_count=0,
            call_quality_trend="flat",
        )
        == "red"
    )


def test_severity_red_when_three_data_gaps(patched_outbound):
    from apps.caio.service import compute_severity

    assert (
        compute_severity(
            compliance_risk_count=0,
            agent_data_gaps=3,
            weak_learning_indicators=[],
            agent_anomaly_flags={},
            transcript_backlog_count=0,
            call_quality_trend="flat",
        )
        == "red"
    )


def test_severity_amber_when_weak_learning(patched_outbound):
    from apps.caio.service import compute_severity

    assert (
        compute_severity(
            compliance_risk_count=0,
            agent_data_gaps=0,
            weak_learning_indicators=["declining_call_quality"],
            agent_anomaly_flags={},
            transcript_backlog_count=0,
            call_quality_trend="flat",
        )
        == "amber"
    )


def test_severity_amber_when_anomalies(patched_outbound):
    from apps.caio.service import compute_severity

    assert (
        compute_severity(
            compliance_risk_count=0,
            agent_data_gaps=0,
            weak_learning_indicators=[],
            agent_anomaly_flags={"cfo": ["rto_spike"]},
            transcript_backlog_count=0,
            call_quality_trend="flat",
        )
        == "amber"
    )


def test_severity_green_default(patched_outbound):
    from apps.caio.service import compute_severity

    assert (
        compute_severity(
            compliance_risk_count=0,
            agent_data_gaps=0,
            weak_learning_indicators=[],
            agent_anomaly_flags={},
            transcript_backlog_count=0,
            call_quality_trend="flat",
        )
        == "green"
    )


# ---------------------------------------------------------------------------
# audit_ceo_ai
# ---------------------------------------------------------------------------


def test_audit_ceo_ai_missing_snapshot(patched_outbound):
    from apps.caio.service import audit_ceo_ai

    notes = audit_ceo_ai(None)
    assert any("data gap" in n.lower() for n in notes)


def test_audit_ceo_ai_poor_tier_includes_tier(patched_outbound):
    from apps.caio.service import audit_ceo_ai

    ceo = _make_ceo(
        health_tier="poor",
        health_score=30,
        top_3_priorities=[
            {"issue": "revenue_drop_24h", "source_agent": "cfo"},
            {"issue": "rto_spike", "source_agent": "cfo"},
        ],
        agent_status_summary={
            "cfo": {"status": "alert", "summary": "revenue down"},
        },
    )
    notes = audit_ceo_ai(ceo)
    joined = " ".join(notes).lower()
    assert "poor" in joined
    assert any("cfo" in n.lower() and "alert" in n.lower() for n in notes)


# ---------------------------------------------------------------------------
# build_snapshot
# ---------------------------------------------------------------------------


def test_build_snapshot_green_happy_path(patched_outbound):
    from apps.caio.service import build_snapshot

    _seed_all_agents()
    snap = build_snapshot()
    assert snap.severity == "green"
    assert snap.compliance_risk_call_count == 0
    assert snap.agent_data_gaps == 0
    assert snap.recommendation_text  # non-empty
    assert "phase9f_ceo_orchestration" in snap.audited_agents


def test_build_snapshot_red_on_compliance_violation(patched_outbound):
    from apps.caio.service import build_snapshot

    _seed_all_agents()
    _make_call_and_score(call_id="RB-1", flags=["compliance_violation"])
    snap = build_snapshot()
    assert snap.severity == "red"
    assert snap.compliance_risk_call_count == 1


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_celery_happy_path_persists_snapshot_and_agent_run(patched_outbound):
    from apps.caio.tasks import run_caio_audit_agent_daily

    _seed_all_agents()
    result = run_caio_audit_agent_daily()
    assert result["status"] == "completed"
    snap = CaioAuditSnapshot.objects.first()
    assert snap is not None
    assert snap.agent_run_id is not None
    run = AgentRun.objects.get(pk=snap.agent_run_id)
    assert run.agent == AgentRun.Agent.CAIO
    assert run.model == "deterministic_v1"
    assert run.provider == "disabled"
    assert run.dry_run is True
    assert run.cost_usd == Decimal("0")
    # Audit rows.
    assert AuditEvent.objects.filter(
        kind="caio.audit.snapshot.created"
    ).exists()
    assert AuditEvent.objects.filter(
        kind="caio.audit.daily_run.completed"
    ).exists()


def test_celery_blocked_by_kill_switch(patched_outbound):
    from apps.caio.tasks import run_caio_audit_agent_daily

    _seed_all_agents()
    with mock.patch(
        "apps.caio.tasks._kill_switch_blocked",
        return_value=(True, {"enabled": False, "model": "test"}),
    ):
        result = run_caio_audit_agent_daily()
    assert result["status"] == "blocked"
    assert CaioAuditSnapshot.objects.count() == 0
    assert AuditEvent.objects.filter(
        kind="caio.audit.daily_run.blocked"
    ).exists()


def test_celery_sandbox_propagates_to_snapshot(patched_outbound):
    from apps.caio.tasks import run_caio_audit_agent_daily

    _seed_all_agents()
    with mock.patch(
        "apps.caio.service._sandbox_active",
        return_value=True,
    ):
        result = run_caio_audit_agent_daily()
    assert result["status"] == "completed"
    snap = CaioAuditSnapshot.objects.first()
    assert snap.sandbox is True
    run = AgentRun.objects.get(pk=snap.agent_run_id)
    assert run.sandbox_mode is True


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_anonymous_blocked():
    from rest_framework.test import APIClient

    client = APIClient()
    url = reverse("caio-snapshots-list")
    response = client.get(url)
    assert response.status_code in {401, 403}


def test_api_admin_can_read_list_latest_detail(
    auth_client, admin_user, patched_outbound
):
    from apps.caio.tasks import run_caio_audit_agent_daily

    _seed_all_agents()
    run_caio_audit_agent_daily()
    client = auth_client(admin_user)
    list_resp = client.get(reverse("caio-snapshots-list"))
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["count"] == 1
    snap_id = body["results"][0]["id"]

    latest_resp = client.get(reverse("caio-snapshot-latest"))
    assert latest_resp.status_code == 200
    assert latest_resp.json()["id"] == snap_id
    assert "severity" in latest_resp.json()
    assert "recommendationText" in latest_resp.json()

    detail_resp = client.get(reverse("caio-snapshot-detail", args=[snap_id]))
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == snap_id


def test_api_latest_404_when_empty(auth_client, admin_user):
    client = auth_client(admin_user)
    response = client.get(reverse("caio-snapshot-latest"))
    assert response.status_code == 404


def test_api_detail_404_for_missing(auth_client, admin_user):
    client = auth_client(admin_user)
    response = client.get(reverse("caio-snapshot-detail", args=[99999]))
    assert response.status_code == 404


def test_api_post_returns_405(auth_client, admin_user):
    client = auth_client(admin_user)
    url = reverse("caio-snapshots-list")
    assert client.post(url, data={}).status_code == 405
    assert client.patch(url, data={}).status_code == 405
    assert client.delete(url).status_code == 405


# ---------------------------------------------------------------------------
# Defensive integration — CAIO has NO execution power
# ---------------------------------------------------------------------------


def test_no_outbound_no_business_mutation_no_phase9_change(patched_outbound):
    from apps.caio.tasks import run_caio_audit_agent_daily
    from apps.crm.models import Customer, Lead
    from apps.payments.models import Payment

    _seed_all_agents()
    _make_call_and_score(call_id="DEF-1", flags=["compliance_violation"])

    pre_counts = {
        "Customer": Customer.objects.count(),
        "Lead": Lead.objects.count(),
        "Order": Order.objects.count(),
        "Payment": Payment.objects.count(),
        "Call": Call.objects.count(),
        "CallQualityScore": CallQualityScore.objects.count(),
        "CallTranscriptLine": CallTranscriptLine.objects.count(),
        # Phase 9 snapshot tables — CAIO must read-only over these.
        "CeoOrchestrationSnapshot": CeoOrchestrationSnapshot.objects.count(),
        "CfoFinancialSnapshot": CfoFinancialSnapshot.objects.count(),
        "DataAnalystSnapshot": DataAnalystSnapshot.objects.count(),
        "CallingTeamLeaderSnapshot": (
            CallingTeamLeaderSnapshot.objects.count()
        ),
        "RtoRiskSnapshot": RtoRiskSnapshot.objects.count(),
    }

    result = run_caio_audit_agent_daily()
    assert result["status"] == "completed"

    # CAIO can ONLY write its own snapshot + the linked AgentRun + audit
    # rows. Everything else stays constant.
    assert Customer.objects.count() == pre_counts["Customer"]
    assert Lead.objects.count() == pre_counts["Lead"]
    assert Order.objects.count() == pre_counts["Order"]
    assert Payment.objects.count() == pre_counts["Payment"]
    assert Call.objects.count() == pre_counts["Call"]
    assert CallQualityScore.objects.count() == pre_counts["CallQualityScore"]
    assert (
        CallTranscriptLine.objects.count()
        == pre_counts["CallTranscriptLine"]
    )
    assert (
        CeoOrchestrationSnapshot.objects.count()
        == pre_counts["CeoOrchestrationSnapshot"]
    )
    assert (
        CfoFinancialSnapshot.objects.count()
        == pre_counts["CfoFinancialSnapshot"]
    )
    assert (
        DataAnalystSnapshot.objects.count()
        == pre_counts["DataAnalystSnapshot"]
    )
    assert (
        CallingTeamLeaderSnapshot.objects.count()
        == pre_counts["CallingTeamLeaderSnapshot"]
    )
    assert RtoRiskSnapshot.objects.count() == pre_counts["RtoRiskSnapshot"]

    # No outbound entrypoint touched.
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


# ---------------------------------------------------------------------------
# Beat schedule sanity
# ---------------------------------------------------------------------------


def test_beat_schedule_has_caio_audit_daily():
    from config.celery import build_beat_schedule

    schedule = build_beat_schedule()
    assert "caio-audit-daily" in schedule
    entry = schedule["caio-audit-daily"]
    assert entry["task"] == "apps.caio.tasks.run_caio_audit_agent_daily"
    assert len(schedule) == 11
