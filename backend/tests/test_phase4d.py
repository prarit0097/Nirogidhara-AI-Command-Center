"""Phase 4D — Approved Action Execution Layer tests.

Covers:
- ApprovalExecutionLog model behaviour + idempotency constraint.
- execute_approval_request: status pre-check, CAIO refusal, role gate,
  director_override → director-only, registry lookup, success / failed /
  skipped paths, audit firing.
- Handlers: payment.link.advance_499 (always ₹499), payment.link.custom_amount
  (positive amount required), ai.prompt_version.activate (uses the existing
  service helper, idempotent on already-active version).
- POST /api/ai/approvals/{id}/execute/ endpoint:
  - anonymous → 401
  - viewer → 403
  - operations → 403
  - admin → 200 on standard approved action
  - director → 200 on director_override action
  - admin → 403 on director_override action
  - 404 on missing request
  - 409 when request is not approved
  - already-executed approvals return prior result without re-running.
- Phase 4D unmapped actions return 400 + skipped audit:
  - discount.11_to_20
  - ai.sandbox.disable
  - payment.refund
  - whatsapp.broadcast_or_campaign
"""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.ai_governance import approval_engine, approval_execution
from apps.ai_governance.models import (
    ApprovalDecisionLog,
    ApprovalExecutionLog,
    ApprovalRequest,
    PromptVersion,
)
from apps.audit.models import AuditEvent
from apps.compliance.models import Claim
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.payments.policies import FIXED_ADVANCE_AMOUNT_INR


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def director_user(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="director_p4d",
        password="director12345",
        email="director_p4d@nirogidhara.test",
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _make_order(order_id: str = "NRG-99500") -> Order:
    return Order.objects.create(
        id=order_id,
        customer_name="P4D Test",
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


def _approve(req: ApprovalRequest, user) -> ApprovalRequest:
    return approval_engine.approve_request(request_id=req.id, user=user)


def _make_approved_advance_499(order_id: str, admin_user) -> ApprovalRequest:
    # advance_499 is auto-approved per matrix.
    result = approval_engine.enforce_or_queue(
        action="payment.link.advance_499",
        payload={"orderId": order_id},
        actor_role="operations",
        target={"app": "payments", "model": "Order", "id": order_id},
        by_user=admin_user,
    )
    return ApprovalRequest.objects.get(pk=result.approval_request_id)


def _make_approved_custom_amount(
    order_id: str,
    admin_user,
    amount: int = 1500,
) -> ApprovalRequest:
    # custom_amount needs admin approval — create + approve.
    req = approval_engine.create_approval_request(
        action="payment.link.custom_amount",
        payload={"orderId": order_id, "amount": amount, "type": "Advance"},
        actor_role="operations",
        target={"app": "payments", "model": "Order", "id": order_id},
        by_user=admin_user,
    )
    return _approve(req, admin_user)


def _make_promptversion(agent: str = "ceo", version: str = "v1.0") -> PromptVersion:
    return PromptVersion.objects.create(
        id=f"PV-{agent}-{version}",
        agent=agent,
        version=version,
        title="Test prompt",
        system_policy="Test policy",
        role_prompt="Test role",
        is_active=False,
        status=PromptVersion.Status.DRAFT,
    )


def _make_approved_prompt_activate(
    prompt_version: PromptVersion, admin_user
) -> ApprovalRequest:
    req = approval_engine.create_approval_request(
        action="ai.prompt_version.activate",
        payload={"promptVersionId": prompt_version.id},
        actor_role="admin",
        target={
            "app": "ai_governance",
            "model": "PromptVersion",
            "id": prompt_version.id,
        },
        by_user=admin_user,
    )
    return _approve(req, admin_user)


# ---------------------------------------------------------------------------
# 1. Model + idempotency.
# ---------------------------------------------------------------------------


def test_approval_execution_log_creates_successfully(admin_user) -> None:
    order_id = "NRG-99001"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.EXECUTED
    log = ApprovalExecutionLog.objects.get(approval_request=req)
    assert log.status == "executed"
    assert log.executed_by == admin_user


def test_only_one_executed_log_per_request(admin_user) -> None:
    order_id = "NRG-99002"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    approval_execution.execute_approval_request(approval_request=req, user=admin_user)
    # Re-running should NOT create a second executed log.
    approval_execution.execute_approval_request(approval_request=req, user=admin_user)
    assert (
        ApprovalExecutionLog.objects.filter(
            approval_request=req,
            status=ApprovalExecutionLog.Status.EXECUTED,
        ).count()
        == 1
    )


def test_already_executed_returns_prior_result_without_rerun(admin_user) -> None:
    order_id = "NRG-99003"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    first = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    payments_before = Payment.objects.count()
    second = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert second.already_executed is True
    assert second.status == "executed"
    assert second.result == first.result
    assert Payment.objects.count() == payments_before  # no new payment row


# ---------------------------------------------------------------------------
# 2. Pre-check refusals.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        ApprovalRequest.Status.PENDING,
        ApprovalRequest.Status.REJECTED,
        ApprovalRequest.Status.BLOCKED,
        ApprovalRequest.Status.ESCALATED,
        ApprovalRequest.Status.EXPIRED,
    ],
)
def test_non_approved_status_cannot_execute(admin_user, status) -> None:
    req = approval_engine.create_approval_request(
        action="payment.link.advance_499",
        payload={"orderId": "NRG-NOSTATUS"},
        actor_role="operations",
        by_user=admin_user,
    )
    req.status = status
    req.save(update_fields=["status"])
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert outcome.http_status == 409


def test_caio_requested_approval_cannot_execute(admin_user) -> None:
    # Force a CAIO requested_by_agent on an otherwise valid approved request.
    order_id = "NRG-99010"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    req.requested_by_agent = "caio"
    req.save(update_fields=["requested_by_agent"])
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert outcome.http_status == 403


def test_caio_actor_in_metadata_cannot_execute(admin_user) -> None:
    order_id = "NRG-99011"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    req.metadata = {**(req.metadata or {}), "actor_agent": "caio"}
    req.save(update_fields=["metadata"])
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert outcome.http_status == 403


# ---------------------------------------------------------------------------
# 3. Handler: payment.link.advance_499
# ---------------------------------------------------------------------------


def test_advance_499_executes_through_payment_service(admin_user) -> None:
    order_id = "NRG-99100"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == "executed"
    assert outcome.result["amount"] == FIXED_ADVANCE_AMOUNT_INR
    assert Payment.objects.filter(order_id=order_id, amount=499).exists()


def test_advance_499_ignores_arbitrary_amount_in_payload(admin_user) -> None:
    order_id = "NRG-99101"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    # Tamper with the stored payload.
    req.proposed_payload = {**(req.proposed_payload or {}), "amount": 999_999}
    req.save(update_fields=["proposed_payload"])
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.result["amount"] == FIXED_ADVANCE_AMOUNT_INR


def test_advance_499_missing_order_id_fails(admin_user) -> None:
    req = approval_engine.create_approval_request(
        action="payment.link.advance_499",
        payload={},  # no orderId
        actor_role="operations",
        by_user=admin_user,
    )
    req.status = ApprovalRequest.Status.AUTO_APPROVED
    req.save(update_fields=["status"])
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert "orderId" in (outcome.error_message or "")


# ---------------------------------------------------------------------------
# 4. Handler: payment.link.custom_amount
# ---------------------------------------------------------------------------


def test_custom_amount_executes_only_after_approval(admin_user) -> None:
    order_id = "NRG-99200"
    _make_order(order_id)
    req = _make_approved_custom_amount(order_id, admin_user, amount=1500)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == "executed"
    assert outcome.result["amount"] == 1500
    assert Payment.objects.filter(order_id=order_id, amount=1500).exists()


def test_custom_amount_pending_cannot_execute(admin_user) -> None:
    order_id = "NRG-99201"
    _make_order(order_id)
    req = approval_engine.create_approval_request(
        action="payment.link.custom_amount",
        payload={"orderId": order_id, "amount": 1500},
        actor_role="operations",
        by_user=admin_user,
    )
    # Leave it pending.
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert outcome.http_status == 409


def test_custom_amount_zero_or_negative_fails(admin_user) -> None:
    order_id = "NRG-99202"
    _make_order(order_id)
    req = _make_approved_custom_amount(order_id, admin_user, amount=0)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert "positive amount" in (outcome.error_message or "")


def test_custom_amount_missing_amount_fails(admin_user) -> None:
    order_id = "NRG-99203"
    _make_order(order_id)
    req = approval_engine.create_approval_request(
        action="payment.link.custom_amount",
        payload={"orderId": order_id},  # no amount
        actor_role="operations",
        by_user=admin_user,
    )
    _approve(req, admin_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED


# ---------------------------------------------------------------------------
# 5. Handler: ai.prompt_version.activate
# ---------------------------------------------------------------------------


def test_prompt_version_activate_executes(admin_user) -> None:
    pv = _make_promptversion("ceo", "v4d-1")
    req = _make_approved_prompt_activate(pv, admin_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == "executed"
    pv.refresh_from_db()
    assert pv.is_active is True


def test_prompt_version_activate_idempotent_when_already_active(admin_user) -> None:
    pv = _make_promptversion("ads", "v4d-2")
    pv.is_active = True
    pv.status = PromptVersion.Status.ACTIVE
    pv.save(update_fields=["is_active", "status"])
    req = _make_approved_prompt_activate(pv, admin_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == "executed"
    assert outcome.result.get("alreadyActive") is True


def test_prompt_version_activate_does_not_bypass_claim_vault(admin_user) -> None:
    """Activation only flips the active flag — it does not generate any
    medical text. The Claim Vault grounding still happens at AgentRun
    dispatch time. Sanity-check that activation doesn't drop Claim rows.
    """
    Claim.objects.create(product="Weight Management", approved=["safe copy"])
    pv = _make_promptversion("compliance", "v4d-3")
    req = _make_approved_prompt_activate(pv, admin_user)
    approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert Claim.objects.filter(product="Weight Management").exists()


# ---------------------------------------------------------------------------
# 6. Unmapped actions → skipped + audit.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        # approval_required + human_escalation matrix modes — admin passes
        # the role check → engine reaches the registry lookup → SKIPPED.
        "discount.11_to_20",
        "payment.refund",
        "whatsapp.broadcast_or_campaign",
        "complaint.medical_emergency",
    ],
)
def test_unmapped_action_skipped_for_admin(admin_user, action) -> None:
    req = approval_engine.create_approval_request(
        action=action,
        payload={},
        actor_role="admin",
        by_user=admin_user,
        initial_status=ApprovalRequest.Status.APPROVED,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.SKIPPED
    assert outcome.http_status == 400
    assert AuditEvent.objects.filter(kind="ai.approval.execution_skipped").exists()


@pytest.mark.parametrize(
    "action",
    [
        # director_override matrix modes — only director can pass the role
        # check; once past it, the registry lookup fails → SKIPPED.
        "ai.sandbox.disable",
        "ad.budget_change",
    ],
)
def test_unmapped_director_override_action_skipped(director_user, action) -> None:
    req = approval_engine.create_approval_request(
        action=action,
        payload={},
        actor_role="director",
        by_user=director_user,
        initial_status=ApprovalRequest.Status.APPROVED,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=director_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.SKIPPED
    assert outcome.http_status == 400
    assert AuditEvent.objects.filter(kind="ai.approval.execution_skipped").exists()


# ---------------------------------------------------------------------------
# 7. Audit events.
# ---------------------------------------------------------------------------


def test_successful_execution_writes_audit(admin_user) -> None:
    order_id = "NRG-99300"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    AuditEvent.objects.filter(kind__startswith="ai.approval.").delete()
    approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert AuditEvent.objects.filter(kind="ai.approval.executed").exists()


def test_failed_execution_writes_audit(admin_user) -> None:
    req = approval_engine.create_approval_request(
        action="payment.link.advance_499",
        payload={},  # missing orderId → handler raises ExecutionRefused.
        actor_role="operations",
        by_user=admin_user,
        initial_status=ApprovalRequest.Status.AUTO_APPROVED,
    )
    AuditEvent.objects.filter(kind__startswith="ai.approval.").delete()
    approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert AuditEvent.objects.filter(kind="ai.approval.execution_failed").exists()


def test_skipped_execution_writes_audit(admin_user) -> None:
    req = approval_engine.create_approval_request(
        action="payment.refund",
        payload={},
        actor_role="admin",
        by_user=admin_user,
        initial_status=ApprovalRequest.Status.APPROVED,
    )
    AuditEvent.objects.filter(kind__startswith="ai.approval.").delete()
    approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert AuditEvent.objects.filter(kind="ai.approval.execution_skipped").exists()


# ---------------------------------------------------------------------------
# 8. Endpoint role gating.
# ---------------------------------------------------------------------------


def test_execute_endpoint_anonymous_blocked(admin_user) -> None:
    order_id = "NRG-99400"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    res = APIClient().post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 401


def test_execute_endpoint_viewer_blocked(viewer_user, auth_client, admin_user) -> None:
    order_id = "NRG-99401"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    res = auth_client(viewer_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 403


def test_execute_endpoint_operations_blocked(
    operations_user, auth_client, admin_user
) -> None:
    order_id = "NRG-99402"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    res = auth_client(operations_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 403


def test_execute_endpoint_admin_can_execute_normal(
    admin_user, auth_client
) -> None:
    order_id = "NRG-99403"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    res = auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["executionStatus"] == "executed"
    assert body["result"]["amount"] == FIXED_ADVANCE_AMOUNT_INR


def test_execute_endpoint_director_can_execute_normal(
    director_user, auth_client
) -> None:
    order_id = "NRG-99404"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, director_user)
    res = auth_client(director_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 200


def test_execute_endpoint_404_on_missing_request(admin_user, auth_client) -> None:
    res = auth_client(admin_user).post(
        "/api/ai/approvals/APR-NOPE/execute/", {}, format="json"
    )
    assert res.status_code == 404


def test_execute_endpoint_returns_409_on_pending_request(
    admin_user, auth_client
) -> None:
    order_id = "NRG-99405"
    _make_order(order_id)
    req = approval_engine.create_approval_request(
        action="payment.link.custom_amount",
        payload={"orderId": order_id, "amount": 1500},
        actor_role="operations",
        by_user=admin_user,
    )
    res = auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 409


def test_execute_endpoint_already_executed_returns_alreadyExecuted(
    admin_user, auth_client
) -> None:
    order_id = "NRG-99406"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    first = auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert first.status_code == 200
    second = auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert second.status_code == 200
    body = second.json()
    assert body["alreadyExecuted"] is True
    assert body["executionStatus"] == "executed"


def test_execute_endpoint_director_override_blocks_admin(
    admin_user, director_user, auth_client
) -> None:
    # Build a director_override-mode approval and approve it as director.
    req = approval_engine.create_approval_request(
        action="discount.above_20",
        payload={"discount": 25},
        actor_role="admin",
        by_user=admin_user,
    )
    approval_engine.approve_request(request_id=req.id, user=director_user)
    # Admin should be refused at execute.
    res_admin = auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res_admin.status_code == 403


# ---------------------------------------------------------------------------
# 9. ApprovalRequest serializer surfaces execution status.
# ---------------------------------------------------------------------------


def test_approvals_list_surfaces_latest_execution_status(
    admin_user, auth_client
) -> None:
    order_id = "NRG-99500"
    _make_order(order_id)
    req = _make_approved_advance_499(order_id, admin_user)
    auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    res = auth_client(admin_user).get(f"/api/ai/approvals/{req.id}/")
    assert res.status_code == 200
    body = res.json()
    assert body["latestExecutionStatus"] == "executed"
    assert isinstance(body["executionLogs"], list)
    assert len(body["executionLogs"]) == 1
