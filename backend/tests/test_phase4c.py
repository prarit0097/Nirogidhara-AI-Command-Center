"""Phase 4C — Approval Matrix Middleware enforcement tests.

Covers:
- ``evaluate_action`` for every matrix mode (auto, auto_with_consent,
  approval_required, director_override, human_escalation, unknown).
- Persistence (``create_approval_request``) snapshots the policy.
- ``approve_request`` / ``reject_request`` flip status, write
  ``ApprovalDecisionLog`` rows, and emit audit events.
- Director-only override on ``director_override`` requests.
- Viewer / operations / anonymous can never approve.
- AgentRun → ApprovalRequest bridge: success-only, CAIO blocked,
  failed/skipped runs blocked, missing action/payload blocked.
- Endpoints: list / detail / approve / reject / evaluate /
  agent-run request-approval — full role gating.
- Real enforcement smoke: payment-link custom-amount + sandbox-disable
  flow through the engine and surface ApprovalRequest rows.
- Existing 244 backend tests stay green (run separately).
"""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.ai_governance import approval_engine
from apps.ai_governance.models import (
    AgentRun,
    ApprovalDecisionLog,
    ApprovalRequest,
    SandboxState,
)
from apps.audit.models import AuditEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def director_user(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="director_p4c",
        password="director12345",
        email="director_p4c@nirogidhara.test",
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


# ---------------------------------------------------------------------------
# 1. Pure evaluate_action coverage.
# ---------------------------------------------------------------------------


def test_evaluate_auto_action_is_allowed() -> None:
    result = approval_engine.evaluate_action(
        action="lead.create", actor_role="operations"
    )
    assert result.allowed is True
    assert result.mode == "auto"
    assert result.status == ApprovalRequest.Status.AUTO_APPROVED


def test_evaluate_approval_required_blocks_until_approval() -> None:
    result = approval_engine.evaluate_action(
        action="discount.11_to_20", actor_role="operations"
    )
    assert result.allowed is False
    assert result.requires_human is True
    assert result.mode == "approval_required"
    assert result.status == ApprovalRequest.Status.PENDING


def test_evaluate_director_override_blocks_non_director() -> None:
    result = approval_engine.evaluate_action(
        action="discount.above_20",
        actor_role="admin",
        payload={"director_override": True, "override_reason": "vip"},
    )
    assert result.allowed is False
    assert result.status == ApprovalRequest.Status.BLOCKED


def test_evaluate_director_override_allows_director_with_reason() -> None:
    result = approval_engine.evaluate_action(
        action="discount.above_20",
        actor_role="director",
        payload={"director_override": True, "override_reason": "year-end push"},
    )
    assert result.allowed is True
    assert result.status == ApprovalRequest.Status.AUTO_APPROVED


def test_evaluate_auto_with_consent_blocks_without_consent() -> None:
    result = approval_engine.evaluate_action(
        action="whatsapp.payment_reminder",
        actor_role="operations",
        payload={"customer_consent": False},
        target={"consent": {"whatsapp": False}},
    )
    assert result.allowed is False
    assert "consent_missing" in result.notes


def test_evaluate_auto_with_consent_allows_with_consent() -> None:
    result = approval_engine.evaluate_action(
        action="whatsapp.payment_reminder",
        actor_role="operations",
        payload={"customer_consent": True},
    )
    assert result.allowed is True


def test_evaluate_human_escalation_creates_escalated_status() -> None:
    result = approval_engine.evaluate_action(
        action="complaint.medical_emergency", actor_role="operations"
    )
    assert result.allowed is False
    assert result.status == ApprovalRequest.Status.ESCALATED


def test_evaluate_unknown_action_is_blocked() -> None:
    result = approval_engine.evaluate_action(
        action="nope.never.happened", actor_role="director"
    )
    assert result.allowed is False
    assert "unknown_action" in result.notes


def test_evaluate_caio_actor_is_always_blocked() -> None:
    result = approval_engine.evaluate_action(
        action="lead.create", actor_role="operations", actor_agent="caio"
    )
    assert result.allowed is False
    assert "caio_no_execute" in result.notes


# ---------------------------------------------------------------------------
# 2. Persistence + state transitions.
# ---------------------------------------------------------------------------


def test_create_approval_request_snapshots_policy(admin_user) -> None:
    req = approval_engine.create_approval_request(
        action="discount.11_to_20",
        payload={"discount": 18},
        actor_role="operations",
        by_user=admin_user,
    )
    assert req.policy_snapshot["action"] == "discount.11_to_20"
    assert req.policy_snapshot["mode"] == "approval_required"
    assert ApprovalDecisionLog.objects.filter(approval_request=req).exists()
    assert AuditEvent.objects.filter(kind="ai.approval.requested").exists()


def test_approve_request_changes_status_and_writes_audit(admin_user) -> None:
    req = approval_engine.create_approval_request(
        action="discount.11_to_20",
        payload={"discount": 18},
        actor_role="operations",
        by_user=admin_user,
    )
    approved = approval_engine.approve_request(
        request_id=req.id, user=admin_user, note="approved on call"
    )
    assert approved.status == ApprovalRequest.Status.APPROVED
    assert approved.decision_note == "approved on call"
    assert AuditEvent.objects.filter(kind="ai.approval.approved").exists()
    assert ApprovalDecisionLog.objects.filter(
        approval_request=req, new_status="approved"
    ).exists()


def test_reject_request_changes_status_and_writes_audit(admin_user) -> None:
    req = approval_engine.create_approval_request(
        action="discount.11_to_20",
        payload={"discount": 18},
        actor_role="operations",
        by_user=admin_user,
    )
    rejected = approval_engine.reject_request(
        request_id=req.id, user=admin_user, note="not now"
    )
    assert rejected.status == ApprovalRequest.Status.REJECTED
    assert AuditEvent.objects.filter(kind="ai.approval.rejected").exists()


def test_director_override_request_requires_director_approval(
    admin_user, director_user
) -> None:
    req = approval_engine.create_approval_request(
        action="discount.above_20",
        payload={"discount": 25},
        actor_role="admin",
        by_user=admin_user,
    )
    # Admin cannot approve a director_override action.
    with pytest.raises(PermissionError):
        approval_engine.approve_request(request_id=req.id, user=admin_user)
    # Director can.
    approved = approval_engine.approve_request(
        request_id=req.id, user=director_user, note="festival promo"
    )
    assert approved.status == ApprovalRequest.Status.APPROVED


def test_cannot_approve_already_decided_request(admin_user) -> None:
    req = approval_engine.create_approval_request(
        action="discount.11_to_20",
        payload={"discount": 18},
        actor_role="operations",
        by_user=admin_user,
    )
    approval_engine.approve_request(request_id=req.id, user=admin_user)
    with pytest.raises(ValueError):
        approval_engine.approve_request(request_id=req.id, user=admin_user)


# ---------------------------------------------------------------------------
# 3. AgentRun → ApprovalRequest bridge.
# ---------------------------------------------------------------------------


def _make_agent_run(
    *,
    agent: str = AgentRun.Agent.SALES_GROWTH,
    status: str = AgentRun.Status.SUCCESS,
    output: dict | None = None,
) -> AgentRun:
    return AgentRun.objects.create(
        id=f"AR-{agent}-{status}",
        agent=agent,
        prompt_version="v1.0",
        input_payload={},
        output_payload=output or {},
        status=status,
        provider="disabled",
        model="",
        latency_ms=0,
        dry_run=True,
        triggered_by="phase4c-test",
    )


def test_request_approval_for_successful_agent_run(admin_user) -> None:
    run = _make_agent_run(
        output={
            "action": "ad.budget_change",
            "proposedPayload": {"campaignId": "abc", "deltaPct": 10},
            "reason": "ROAS up",
        }
    )
    req = approval_engine.request_approval_for_agent_run(
        agent_run=run, by_user=admin_user
    )
    assert req.action == "ad.budget_change"
    assert req.status == ApprovalRequest.Status.PENDING
    assert req.metadata.get("agent_run_id") == run.id
    assert AuditEvent.objects.filter(kind="ai.agent_run.approval_requested").exists()


def test_caio_agent_run_cannot_request_approval(admin_user) -> None:
    run = _make_agent_run(
        agent=AgentRun.Agent.CAIO,
        output={
            "action": "ad.budget_change",
            "proposedPayload": {"campaignId": "abc"},
        },
    )
    with pytest.raises(PermissionError):
        approval_engine.request_approval_for_agent_run(
            agent_run=run, by_user=admin_user
        )


def test_failed_agent_run_cannot_request_approval(admin_user) -> None:
    run = _make_agent_run(
        status=AgentRun.Status.FAILED,
        output={
            "action": "ad.budget_change",
            "proposedPayload": {"campaignId": "abc"},
        },
    )
    with pytest.raises(ValueError):
        approval_engine.request_approval_for_agent_run(
            agent_run=run, by_user=admin_user
        )


def test_skipped_agent_run_cannot_request_approval(admin_user) -> None:
    run = _make_agent_run(
        status=AgentRun.Status.SKIPPED,
        output={
            "action": "ad.budget_change",
            "proposedPayload": {"campaignId": "abc"},
        },
    )
    with pytest.raises(ValueError):
        approval_engine.request_approval_for_agent_run(
            agent_run=run, by_user=admin_user
        )


def test_agent_run_without_action_or_payload_cannot_be_promoted(admin_user) -> None:
    run = _make_agent_run(output={"summary": "nothing actionable"})
    with pytest.raises(ValueError):
        approval_engine.request_approval_for_agent_run(
            agent_run=run, by_user=admin_user
        )


def test_agent_run_with_unknown_action_cannot_be_promoted(admin_user) -> None:
    run = _make_agent_run(
        output={
            "action": "not.in.matrix",
            "proposedPayload": {"thing": "x"},
        }
    )
    with pytest.raises(ValueError):
        approval_engine.request_approval_for_agent_run(
            agent_run=run, by_user=admin_user
        )


# ---------------------------------------------------------------------------
# 4. Endpoint role gating.
# ---------------------------------------------------------------------------


def test_approvals_list_role_gating(
    admin_user, viewer_user, operations_user, auth_client
) -> None:
    # Anonymous → 401
    assert APIClient().get("/api/ai/approvals/").status_code == 401
    # Viewer → 403
    assert auth_client(viewer_user).get("/api/ai/approvals/").status_code == 403
    # Operations → 403
    assert auth_client(operations_user).get("/api/ai/approvals/").status_code == 403
    # Admin → 200
    res = auth_client(admin_user).get("/api/ai/approvals/")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_approve_endpoint_role_gating(
    admin_user, viewer_user, operations_user, auth_client
) -> None:
    req = approval_engine.create_approval_request(
        action="discount.11_to_20",
        payload={"discount": 18},
        actor_role="operations",
        by_user=admin_user,
    )
    # Anonymous → 401
    assert (
        APIClient().post(
            f"/api/ai/approvals/{req.id}/approve/", {}, format="json"
        ).status_code
        == 401
    )
    # Viewer → 403
    assert (
        auth_client(viewer_user).post(
            f"/api/ai/approvals/{req.id}/approve/", {}, format="json"
        ).status_code
        == 403
    )
    # Operations → 403
    assert (
        auth_client(operations_user).post(
            f"/api/ai/approvals/{req.id}/approve/", {}, format="json"
        ).status_code
        == 403
    )
    # Admin → 200 (this is approval_required, admin satisfies it)
    res = auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/approve/",
        {"note": "ok"},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["status"] == "approved"


def test_director_override_endpoint_blocks_admin(
    admin_user, director_user, auth_client
) -> None:
    req = approval_engine.create_approval_request(
        action="discount.above_20",
        payload={"discount": 25},
        actor_role="admin",
        by_user=admin_user,
    )
    # Admin → 403 (director_override needs director)
    res_admin = auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/approve/", {}, format="json"
    )
    assert res_admin.status_code == 403
    # Director → 200
    res_dir = auth_client(director_user).post(
        f"/api/ai/approvals/{req.id}/approve/",
        {"note": "festival"},
        format="json",
    )
    assert res_dir.status_code == 200
    assert res_dir.json()["status"] == "approved"


def test_evaluate_endpoint_returns_camelcase(admin_user, auth_client) -> None:
    res = auth_client(admin_user).post(
        "/api/ai/approvals/evaluate/",
        {"action": "lead.create", "actorRole": "operations"},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["allowed"] is True
    assert body["mode"] == "auto"
    assert body["status"] == "auto_approved"


def test_evaluate_endpoint_with_persist_creates_request(
    admin_user, auth_client
) -> None:
    before = ApprovalRequest.objects.count()
    res = auth_client(admin_user).post(
        "/api/ai/approvals/evaluate/",
        {
            "action": "discount.11_to_20",
            "actorRole": "operations",
            "payload": {"discount": 18},
            "persist": True,
        },
        format="json",
    )
    assert res.status_code == 200
    assert ApprovalRequest.objects.count() == before + 1
    assert res.json()["approvalRequestId"]


def test_agent_run_request_approval_endpoint(admin_user, auth_client) -> None:
    run = _make_agent_run(
        output={
            "action": "ad.budget_change",
            "proposedPayload": {"campaignId": "abc"},
        }
    )
    res = auth_client(admin_user).post(
        f"/api/ai/agent-runs/{run.id}/request-approval/",
        {"reason": "boost ROAS"},
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "pending"
    assert body["action"] == "ad.budget_change"


def test_agent_run_request_approval_endpoint_blocks_caio(
    admin_user, auth_client
) -> None:
    run = _make_agent_run(
        agent=AgentRun.Agent.CAIO,
        output={
            "action": "ad.budget_change",
            "proposedPayload": {"campaignId": "abc"},
        },
    )
    res = auth_client(admin_user).post(
        f"/api/ai/agent-runs/{run.id}/request-approval/",
        {},
        format="json",
    )
    assert res.status_code == 403


def test_agent_run_request_approval_endpoint_role_gating(
    viewer_user, operations_user, auth_client
) -> None:
    run = _make_agent_run(
        output={
            "action": "ad.budget_change",
            "proposedPayload": {"campaignId": "abc"},
        }
    )
    assert (
        APIClient().post(
            f"/api/ai/agent-runs/{run.id}/request-approval/", {}, format="json"
        ).status_code
        == 401
    )
    assert (
        auth_client(viewer_user).post(
            f"/api/ai/agent-runs/{run.id}/request-approval/", {}, format="json"
        ).status_code
        == 403
    )
    assert (
        auth_client(operations_user).post(
            f"/api/ai/agent-runs/{run.id}/request-approval/", {}, format="json"
        ).status_code
        == 403
    )


# ---------------------------------------------------------------------------
# 5. Live enforcement integrations.
# ---------------------------------------------------------------------------


def _make_order(order_id: str = "NRG-99001"):
    from apps.orders.models import Order

    return Order.objects.create(
        id=order_id,
        customer_name="P4C Test",
        phone="+91 9000099999",
        product="Weight Management",
        quantity=1,
        amount=2640,
        state="MH",
        city="Pune",
        rto_risk=Order.RtoRisk.LOW,
        rto_score=10,
        agent="Calling AI",
        stage=Order.Stage.ORDER_PUNCHED,
    )


def test_payment_link_advance_499_logs_auto_approval(
    operations_user, auth_client
) -> None:
    _make_order("NRG-99010")
    res = auth_client(operations_user).post(
        "/api/payments/links/",
        {
            "orderId": "NRG-99010",
            "gateway": "Razorpay",
            "type": "Advance",
        },
        format="json",
    )
    assert res.status_code == 201
    # Auto approval logged.
    assert ApprovalRequest.objects.filter(
        action="payment.link.advance_499",
        status=ApprovalRequest.Status.AUTO_APPROVED,
    ).exists()


def test_payment_link_custom_amount_blocks_operations(
    operations_user, auth_client
) -> None:
    _make_order("NRG-99020")
    res = auth_client(operations_user).post(
        "/api/payments/links/",
        {
            "orderId": "NRG-99020",
            "amount": 1500,
            "gateway": "Razorpay",
            "type": "Advance",
        },
        format="json",
    )
    assert res.status_code == 403
    # Pending approval logged.
    assert ApprovalRequest.objects.filter(
        action="payment.link.custom_amount",
        status=ApprovalRequest.Status.PENDING,
    ).exists()


def test_sandbox_disable_requires_director_override(
    admin_user, director_user, auth_client
) -> None:
    # Pre-condition: enable sandbox.
    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": True}
    )
    # Admin without director_override → blocked.
    res_admin = auth_client(admin_user).patch(
        "/api/ai/sandbox/status/",
        {"isEnabled": False},
        format="json",
    )
    assert res_admin.status_code == 403
    assert SandboxState.objects.get(pk=1).is_enabled is True
    # Director with override + reason → allowed.
    res_dir = auth_client(director_user).patch(
        "/api/ai/sandbox/status/",
        {
            "isEnabled": False,
            "note": "rolling out new prompt",
            "director_override": True,
        },
        format="json",
    )
    assert res_dir.status_code == 200
    assert SandboxState.objects.get(pk=1).is_enabled is False
