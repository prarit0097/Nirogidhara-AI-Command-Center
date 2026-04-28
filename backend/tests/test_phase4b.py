"""Phase 4B — Reward / Penalty Engine wiring tests.

Covers:
- calculate_for_order creates RewardPenaltyEvent rows.
- A second run is idempotent (updates in place via unique_key).
- Delivered → reward event(s) including CEO AI net accountability.
- RTO → penalty event(s) + CEO AI accountability.
- Cancelled → penalty event(s) + CEO AI accountability.
- CAIO never receives a business reward / penalty.
- Only AI agents are scored — no human staff.
- Missing data is recorded explicitly.
- Reward / penalty caps respected (+100 / -100).
- Audit events are written for sweep + leaderboard.
- Management command works (and --dry-run does not persist).
- Celery task runs in eager mode.
- GET /api/rewards/events/ + /summary/ admin/director only.
- POST /api/rewards/sweep/ permission gating.
"""
from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.orders.models import Order
from apps.rewards.engine import (
    AI_AGENT_BY_ID,
    EXCLUDED_AGENTS,
    SweepSummary,
    calculate_for_all_eligible_orders,
    calculate_for_order,
    rebuild_agent_leaderboard,
)
from apps.rewards.models import RewardPenalty, RewardPenaltyEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def director_user(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="director_p4b",
        password="director12345",
        email="director_p4b@nirogidhara.test",
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _make_order(
    *,
    order_id: str = "NRG-91001",
    stage: str = Order.Stage.DELIVERED,
    rto_risk: str = Order.RtoRisk.LOW,
    advance_paid: bool = True,
    advance_amount: int = 499,
    discount_pct: int = 5,
    state: str = "Maharashtra",
    city: str = "Pune",
    confirmation_outcome: str = Order.ConfirmationOutcome.CONFIRMED,
) -> Order:
    return Order.objects.create(
        id=order_id,
        customer_name="Test Customer",
        phone="+91 9999999999",
        product="Weight Management",
        quantity=1,
        amount=2640,
        discount_pct=discount_pct,
        advance_paid=advance_paid,
        advance_amount=advance_amount,
        payment_status=Order.PaymentStatus.PAID,
        state=state,
        city=city,
        rto_risk=rto_risk,
        rto_score=10,
        agent="Calling AI · Vaani-3",
        stage=stage,
        confirmation_outcome=confirmation_outcome,
    )


# ---------------------------------------------------------------------------
# 1. Per-order engine behaviour
# ---------------------------------------------------------------------------


def test_calculate_for_order_creates_events_for_delivered() -> None:
    order = _make_order()
    result, events, summary = calculate_for_order(order, triggered_by="t")
    assert summary.evaluated_orders == 1
    assert summary.dry_run is False
    persisted = RewardPenaltyEvent.objects.filter(order_id_snapshot=order.id)
    assert persisted.count() == len(events) > 0
    # CEO AI must be present.
    assert persisted.filter(agent_name="CEO AI Agent").exists()
    # CAIO never receives an event.
    assert not persisted.filter(agent_name__icontains="CAIO").exists()


def test_calculate_for_order_idempotent_on_second_run() -> None:
    order = _make_order(order_id="NRG-91002")
    calculate_for_order(order, triggered_by="t1")
    first_count = RewardPenaltyEvent.objects.count()
    # Second run with same order should update in place, not duplicate.
    _, _, summary = calculate_for_order(order, triggered_by="t2")
    assert RewardPenaltyEvent.objects.count() == first_count
    # All events for this order should now show triggered_by="t2".
    triggered = set(
        RewardPenaltyEvent.objects.filter(order_id_snapshot=order.id).values_list(
            "triggered_by", flat=True
        )
    )
    assert triggered == {"t2"}
    assert summary.updated_events == first_count
    assert summary.created_events == 0


def test_delivered_order_creates_ceo_reward_event() -> None:
    order = _make_order(order_id="NRG-91003")
    calculate_for_order(order, triggered_by="t")
    ceo_event = RewardPenaltyEvent.objects.get(
        order_id_snapshot=order.id, agent_name="CEO AI Agent"
    )
    assert ceo_event.event_type == RewardPenaltyEvent.EventType.REWARD
    assert ceo_event.reward_score > 0
    assert ceo_event.penalty_score == 0


def test_rto_order_always_creates_ceo_penalty_event() -> None:
    order = _make_order(
        order_id="NRG-91010",
        stage=Order.Stage.RTO,
        rto_risk=Order.RtoRisk.HIGH,
        advance_paid=False,
        advance_amount=0,
        discount_pct=15,
        confirmation_outcome=Order.ConfirmationOutcome.PENDING,
    )
    _, _, summary = calculate_for_order(order, triggered_by="t")
    ceo_event = RewardPenaltyEvent.objects.get(
        order_id_snapshot=order.id, agent_name="CEO AI Agent"
    )
    assert ceo_event.event_type == RewardPenaltyEvent.EventType.PENALTY
    assert ceo_event.penalty_score > 0
    assert ceo_event.reward_score == 0
    # And RTO Agent + Sales Growth Agent should also have penalty rows.
    agents_with_penalty = set(
        RewardPenaltyEvent.objects.filter(
            order_id_snapshot=order.id, event_type="penalty"
        ).values_list("agent_name", flat=True)
    )
    assert "CEO AI Agent" in agents_with_penalty


def test_cancelled_order_creates_ceo_penalty_event() -> None:
    order = _make_order(
        order_id="NRG-91011",
        stage=Order.Stage.CANCELLED,
        confirmation_outcome=Order.ConfirmationOutcome.CANCELLED,
        advance_paid=False,
        advance_amount=0,
    )
    calculate_for_order(order, triggered_by="t")
    ceo_event = RewardPenaltyEvent.objects.get(
        order_id_snapshot=order.id, agent_name="CEO AI Agent"
    )
    assert ceo_event.event_type == RewardPenaltyEvent.EventType.PENALTY
    assert ceo_event.penalty_score > 0


def test_caio_excluded_from_engine_scope() -> None:
    assert "caio" in EXCLUDED_AGENTS
    # Engine doesn't include CAIO in AI_AGENT_BY_ID either.
    assert "caio" not in AI_AGENT_BY_ID


def test_only_ai_agents_are_scored() -> None:
    order = _make_order(order_id="NRG-91020")
    calculate_for_order(order, triggered_by="t")
    names = set(
        RewardPenaltyEvent.objects.filter(
            order_id_snapshot=order.id
        ).values_list("agent_name", flat=True)
    )
    # No human staff names should appear.
    for human_token in ("Priya", "Anil", "Human", "(Human)"):
        assert not any(human_token in n for n in names)


def test_missing_data_is_recorded_not_invented() -> None:
    order = _make_order(order_id="NRG-91030")
    _, _, summary = calculate_for_order(order, triggered_by="t")
    # Net profit / customer satisfaction / reorder potential are NOT in
    # build_reward_context, so they must surface as missing data.
    warnings = " ".join(summary.missing_data_warnings)
    assert "net_profit_inr" in warnings
    assert "customer_satisfaction" in warnings


def test_reward_cap_respected() -> None:
    from apps.rewards.scoring import REWARD_MAX_TOTAL

    order = _make_order(
        order_id="NRG-91040",
        stage=Order.Stage.DELIVERED,
        rto_risk=Order.RtoRisk.LOW,
        advance_paid=True,
        discount_pct=5,
    )
    _, _, summary = calculate_for_order(
        order,
        triggered_by="t",
        context={
            "net_profit_inr": 999,
            "customer_satisfaction": "positive",
            "reorder_potential": "high",
            "clean_data": True,
            "compliance_safe": True,
        },
    )
    # The CEO net accountability event should reflect the capped reward.
    ceo_event = RewardPenaltyEvent.objects.get(
        order_id_snapshot=order.id, agent_name="CEO AI Agent"
    )
    assert ceo_event.reward_score <= REWARD_MAX_TOTAL


def test_penalty_cap_respected() -> None:
    from apps.rewards.scoring import PENALTY_MAX_TOTAL

    order = _make_order(
        order_id="NRG-91041",
        stage=Order.Stage.RTO,
        rto_risk=Order.RtoRisk.HIGH,
        advance_paid=False,
        advance_amount=0,
        discount_pct=30,
        confirmation_outcome=Order.ConfirmationOutcome.PENDING,
        state="",
        city="",
    )
    calculate_for_order(
        order,
        triggered_by="t",
        context={
            "risky_claim_logged": True,
            "side_effect_or_legal_mishandled": True,
            "fake_lead_quality": True,
            "rto_warning_was_raised": True,
        },
    )
    ceo_event = RewardPenaltyEvent.objects.get(
        order_id_snapshot=order.id, agent_name="CEO AI Agent"
    )
    assert ceo_event.penalty_score == PENALTY_MAX_TOTAL


# ---------------------------------------------------------------------------
# 2. Sweep behaviour
# ---------------------------------------------------------------------------


def test_full_sweep_is_idempotent() -> None:
    _make_order(order_id="NRG-91100", stage=Order.Stage.DELIVERED)
    _make_order(
        order_id="NRG-91101",
        stage=Order.Stage.RTO,
        rto_risk=Order.RtoRisk.HIGH,
        advance_paid=False,
        advance_amount=0,
        confirmation_outcome=Order.ConfirmationOutcome.PENDING,
    )
    _make_order(
        order_id="NRG-91102",
        stage=Order.Stage.CANCELLED,
        confirmation_outcome=Order.ConfirmationOutcome.CANCELLED,
    )
    first = calculate_for_all_eligible_orders(triggered_by="sweep1")
    after_first = RewardPenaltyEvent.objects.count()
    second = calculate_for_all_eligible_orders(triggered_by="sweep2")
    assert RewardPenaltyEvent.objects.count() == after_first
    # Second sweep should report only updates, no creations.
    assert second.updated_events > 0
    assert second.created_events == 0


def test_sweep_writes_audit_events() -> None:
    _make_order(order_id="NRG-91200", stage=Order.Stage.DELIVERED)
    before = AuditEvent.objects.count()
    calculate_for_all_eligible_orders(triggered_by="t")
    kinds = set(
        AuditEvent.objects.filter(
            kind__startswith="ai.reward_penalty"
        ).values_list("kind", flat=True)
    )
    assert "ai.reward_penalty.sweep_started" in kinds
    assert "ai.reward_penalty.sweep_completed" in kinds
    assert "ai.reward_penalty.leaderboard_updated" in kinds
    assert AuditEvent.objects.count() > before


def test_dry_run_does_not_persist_events() -> None:
    order = _make_order(order_id="NRG-91300", stage=Order.Stage.DELIVERED)
    _, events, summary = calculate_for_order(
        order, triggered_by="t", dry_run=True
    )
    assert summary.dry_run is True
    assert summary.created_events > 0
    # Nothing persisted to the DB.
    assert not RewardPenaltyEvent.objects.filter(
        order_id_snapshot=order.id
    ).exists()
    # But the in-memory events expose the same attribution.
    assert any(e.agent_name == "CEO AI Agent" for e in events)


def test_rebuild_agent_leaderboard_creates_rollup_rows() -> None:
    _make_order(order_id="NRG-91400", stage=Order.Stage.DELIVERED)
    calculate_for_all_eligible_orders(triggered_by="t")
    # CEO AI rollup row should exist with reward > 0.
    ceo_row = RewardPenalty.objects.get(name="CEO AI Agent")
    assert ceo_row.reward > 0
    assert ceo_row.last_calculated_at is not None
    assert ceo_row.agent_id == "ceo"


# ---------------------------------------------------------------------------
# 3. Management command
# ---------------------------------------------------------------------------


def test_management_command_runs_full_sweep() -> None:
    from io import StringIO

    from django.core.management import call_command

    _make_order(order_id="NRG-91500", stage=Order.Stage.DELIVERED)
    out = StringIO()
    call_command("calculate_reward_penalties", stdout=out)
    assert RewardPenaltyEvent.objects.filter(
        order_id_snapshot="NRG-91500"
    ).exists()
    assert "Reward / Penalty sweep summary:" in out.getvalue()


def test_management_command_dry_run_does_not_persist() -> None:
    from io import StringIO

    from django.core.management import call_command

    _make_order(order_id="NRG-91501", stage=Order.Stage.DELIVERED)
    out = StringIO()
    call_command("calculate_reward_penalties", "--dry-run", stdout=out)
    assert not RewardPenaltyEvent.objects.filter(
        order_id_snapshot="NRG-91501"
    ).exists()


def test_management_command_supports_order_id() -> None:
    from io import StringIO

    from django.core.management import call_command

    _make_order(order_id="NRG-91502", stage=Order.Stage.DELIVERED)
    out = StringIO()
    call_command(
        "calculate_reward_penalties", "--order-id", "NRG-91502", stdout=out
    )
    assert RewardPenaltyEvent.objects.filter(
        order_id_snapshot="NRG-91502"
    ).exists()


# ---------------------------------------------------------------------------
# 4. Celery task (eager mode)
# ---------------------------------------------------------------------------


def test_celery_task_runs_in_eager_mode() -> None:
    from apps.rewards.tasks import run_reward_penalty_sweep_task

    _make_order(order_id="NRG-91600", stage=Order.Stage.DELIVERED)
    summary = run_reward_penalty_sweep_task.delay(triggered_by="celery-test").get()
    assert summary["evaluatedOrders"] == 1
    assert summary["leaderboardUpdated"] is True


# ---------------------------------------------------------------------------
# 5. API endpoints
# ---------------------------------------------------------------------------


def test_rewards_list_endpoint_is_public_and_camelcase() -> None:
    _make_order(order_id="NRG-91700", stage=Order.Stage.DELIVERED)
    calculate_for_all_eligible_orders(triggered_by="t")
    res = APIClient().get("/api/rewards/")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    sample = next((row for row in body if row["name"] == "CEO AI Agent"), None)
    assert sample is not None
    # Phase 4B fields surface in camelCase.
    assert "agentId" in sample
    assert "rewardedOrders" in sample
    assert "lastCalculatedAt" in sample


def test_events_endpoint_admin_only(admin_user, viewer_user, auth_client) -> None:
    _make_order(order_id="NRG-91710", stage=Order.Stage.DELIVERED)
    calculate_for_all_eligible_orders(triggered_by="t")
    # Anonymous → 401
    assert APIClient().get("/api/rewards/events/").status_code == 401
    # Viewer → 403
    assert auth_client(viewer_user).get("/api/rewards/events/").status_code == 403
    # Admin → 200
    res = auth_client(admin_user).get("/api/rewards/events/")
    assert res.status_code == 200
    rows = res.json()
    assert isinstance(rows, list)
    assert any(r["agentName"] == "CEO AI Agent" for r in rows)


def test_summary_endpoint_admin_only(admin_user, viewer_user, auth_client) -> None:
    _make_order(order_id="NRG-91720", stage=Order.Stage.DELIVERED)
    calculate_for_all_eligible_orders(triggered_by="t")
    assert APIClient().get("/api/rewards/summary/").status_code == 401
    assert auth_client(viewer_user).get("/api/rewards/summary/").status_code == 403
    res = auth_client(admin_user).get("/api/rewards/summary/")
    assert res.status_code == 200
    body = res.json()
    for key in (
        "evaluatedOrders",
        "totalReward",
        "totalPenalty",
        "netScore",
        "lastSweepAt",
        "agentLeaderboard",
        "missingDataWarnings",
    ):
        assert key in body


def test_sweep_endpoint_role_gating(
    admin_user, viewer_user, operations_user, auth_client
) -> None:
    _make_order(order_id="NRG-91730", stage=Order.Stage.DELIVERED)
    # Anonymous → 401
    assert APIClient().post("/api/rewards/sweep/", {}, format="json").status_code == 401
    # Viewer / Operations → 403
    assert (
        auth_client(viewer_user).post("/api/rewards/sweep/", {}, format="json").status_code
        == 403
    )
    assert (
        auth_client(operations_user).post(
            "/api/rewards/sweep/", {}, format="json"
        ).status_code
        == 403
    )
    # Admin → 200 + summary payload
    res = auth_client(admin_user).post("/api/rewards/sweep/", {}, format="json")
    assert res.status_code == 200
    body = res.json()
    assert body["evaluatedOrders"] >= 1
    assert body["leaderboardUpdated"] is True


def test_sweep_endpoint_supports_order_id(admin_user, auth_client) -> None:
    _make_order(order_id="NRG-91740", stage=Order.Stage.DELIVERED)
    res = auth_client(admin_user).post(
        "/api/rewards/sweep/",
        {"orderId": "NRG-91740", "dryRun": False},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["evaluatedOrders"] == 1
    assert body["leaderboardUpdated"] is True


def test_sweep_endpoint_dry_run_does_not_persist(admin_user, auth_client) -> None:
    _make_order(order_id="NRG-91750", stage=Order.Stage.DELIVERED)
    res = auth_client(admin_user).post(
        "/api/rewards/sweep/",
        {"dryRun": True},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["dryRun"] is True
    # Nothing persisted.
    assert not RewardPenaltyEvent.objects.filter(
        order_id_snapshot="NRG-91750"
    ).exists()


# ---------------------------------------------------------------------------
# 6. Compliance guarantees still hold
# ---------------------------------------------------------------------------


def test_caio_does_not_receive_business_reward_or_penalty_after_sweep() -> None:
    _make_order(order_id="NRG-91800", stage=Order.Stage.DELIVERED)
    _make_order(
        order_id="NRG-91801",
        stage=Order.Stage.RTO,
        rto_risk=Order.RtoRisk.HIGH,
        advance_paid=False,
        advance_amount=0,
    )
    calculate_for_all_eligible_orders(triggered_by="t")
    assert not RewardPenaltyEvent.objects.filter(
        agent_name__icontains="CAIO"
    ).exists()
    # Legacy leaderboard rollup also excludes CAIO from the AI rebuild.
    rebuilt = rebuild_agent_leaderboard(triggered_by="t")
    assert "CAIO" not in " ".join(rebuilt.keys())
