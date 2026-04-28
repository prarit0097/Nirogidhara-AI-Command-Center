"""Phase 4E — Expanded Approved Action Execution Registry tests.

Covers the three new allow-listed handlers (`discount.up_to_10`,
`discount.11_to_20`, `ai.sandbox.disable`) plus regression on the
hard-stop set that must STAY unmapped:

- `discount.above_20` (director_override matrix row, intentionally
  unmapped — execute → 400 + skipped)
- `ad.budget_change`, `payment.refund`, `whatsapp.*`,
  `ai.production.live_mode_switch` (still unmapped)
- CAIO requested_by_agent + metadata.actor_agent guard (Phase 4D rule
  carries through Phase 4E)

Phase 4D's existing 39 tests stay green (the test file's parametrized
"unmapped" set was trimmed to remove the two actions Phase 4E now
maps — see ``tests/test_phase4d.py``).
"""
from __future__ import annotations

import pytest

from apps.ai_governance import approval_engine, approval_execution
from apps.ai_governance.models import (
    AgentRun,
    ApprovalExecutionLog,
    ApprovalRequest,
    SandboxState,
)
from apps.audit.models import AuditEvent
from apps.orders.models import Order


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def director_user(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="director_p4e",
        password="director12345",
        email="director_p4e@nirogidhara.test",
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _make_order(order_id: str = "NRG-95001", discount_pct: int = 0) -> Order:
    return Order.objects.create(
        id=order_id,
        customer_name="P4E Test",
        phone="+91 9000099999",
        product="Weight Management",
        quantity=1,
        amount=2640,
        discount_pct=discount_pct,
        state="MH",
        city="Pune",
        rto_risk=Order.RtoRisk.LOW,
        rto_score=10,
        agent="Calling AI",
        stage=Order.Stage.ORDER_PUNCHED,
    )


def _approve(req: ApprovalRequest, user) -> ApprovalRequest:
    return approval_engine.approve_request(request_id=req.id, user=user)


def _make_discount_approval(
    *,
    action: str,
    order_id: str,
    discount_pct: int,
    actor_role: str,
    by_user,
    auto: bool = False,
) -> ApprovalRequest:
    initial_status = (
        ApprovalRequest.Status.AUTO_APPROVED if auto
        else ApprovalRequest.Status.PENDING
    )
    req = approval_engine.create_approval_request(
        action=action,
        payload={
            "orderId": order_id,
            "discountPct": discount_pct,
            "reason": "test",
        },
        actor_role=actor_role,
        target={"app": "orders", "model": "Order", "id": order_id},
        by_user=by_user,
        initial_status=initial_status,
    )
    if not auto:
        return _approve(req, by_user)
    return req


def _make_sandbox_disable_approval(
    by_user, *, payload: dict | None = None
) -> ApprovalRequest:
    req = approval_engine.create_approval_request(
        action="ai.sandbox.disable",
        payload=payload
        or {"note": "rolling out new prompt", "overrideReason": "weekly review"},
        actor_role="director",
        by_user=by_user,
    )
    return _approve(req, by_user)


# ---------------------------------------------------------------------------
# 1. discount.up_to_10 — happy paths + bands.
# ---------------------------------------------------------------------------


def test_discount_up_to_10_auto_approved_executes(admin_user) -> None:
    order = _make_order("NRG-95010", discount_pct=0)
    req = _make_discount_approval(
        action="discount.up_to_10",
        order_id=order.id,
        discount_pct=8,
        actor_role="operations",
        by_user=admin_user,
        auto=True,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == "executed"
    assert outcome.result["newDiscountPct"] == 8
    assert outcome.result["oldDiscountPct"] == 0
    assert outcome.result["approvalRequestId"] == req.id

    order.refresh_from_db()
    assert order.discount_pct == 8


def test_discount_up_to_10_approved_executes(admin_user) -> None:
    order = _make_order("NRG-95011", discount_pct=2)
    req = _make_discount_approval(
        action="discount.up_to_10",
        order_id=order.id,
        discount_pct=10,
        actor_role="operations",
        by_user=admin_user,
        auto=False,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == "executed"
    assert outcome.result["newDiscountPct"] == 10
    order.refresh_from_db()
    assert order.discount_pct == 10


def test_discount_up_to_10_blocks_above_band(admin_user) -> None:
    order = _make_order("NRG-95012", discount_pct=5)
    req = _make_discount_approval(
        action="discount.up_to_10",
        order_id=order.id,
        discount_pct=15,
        actor_role="operations",
        by_user=admin_user,
        auto=True,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    order.refresh_from_db()
    assert order.discount_pct == 5  # unchanged


def test_discount_up_to_10_blocks_negative(admin_user) -> None:
    order = _make_order("NRG-95013", discount_pct=4)
    req = _make_discount_approval(
        action="discount.up_to_10",
        order_id=order.id,
        discount_pct=-1,
        actor_role="operations",
        by_user=admin_user,
        auto=True,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    order.refresh_from_db()
    assert order.discount_pct == 4


# ---------------------------------------------------------------------------
# 2. discount.11_to_20 — happy paths + band edges.
# ---------------------------------------------------------------------------


def test_discount_11_to_20_approved_executes(admin_user) -> None:
    order = _make_order("NRG-95020", discount_pct=5)
    req = _make_discount_approval(
        action="discount.11_to_20",
        order_id=order.id,
        discount_pct=15,
        actor_role="operations",
        by_user=admin_user,
        auto=False,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == "executed"
    assert outcome.result["newDiscountPct"] == 15
    order.refresh_from_db()
    assert order.discount_pct == 15


def test_discount_11_to_20_auto_approved_executes(admin_user) -> None:
    """Locked Phase 4E rule: auto_approved is enough — but only because
    the backend approval_engine put it there. Frontend cannot fake this
    status because POST /api/ai/approvals/evaluate/ requires admin/director.
    """
    order = _make_order("NRG-95021", discount_pct=0)
    req = _make_discount_approval(
        action="discount.11_to_20",
        order_id=order.id,
        discount_pct=18,
        actor_role="operations",
        by_user=admin_user,
        auto=True,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == "executed"


def test_discount_11_to_20_blocks_above_20(admin_user) -> None:
    order = _make_order("NRG-95022", discount_pct=5)
    req = _make_discount_approval(
        action="discount.11_to_20",
        order_id=order.id,
        discount_pct=25,
        actor_role="operations",
        by_user=admin_user,
        auto=False,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED


def test_discount_11_to_20_blocks_at_or_below_10(admin_user) -> None:
    order = _make_order("NRG-95023", discount_pct=5)
    req = _make_discount_approval(
        action="discount.11_to_20",
        order_id=order.id,
        discount_pct=10,
        actor_role="operations",
        by_user=admin_user,
        auto=False,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED


def test_discount_11_to_20_blocks_missing_pct(admin_user) -> None:
    order = _make_order("NRG-95024", discount_pct=5)
    req = approval_engine.create_approval_request(
        action="discount.11_to_20",
        payload={"orderId": order.id},  # no discountPct
        actor_role="operations",
        by_user=admin_user,
    )
    req = _approve(req, admin_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert "discountPct" in (outcome.error_message or "")


def test_discount_11_to_20_blocks_negative(admin_user) -> None:
    order = _make_order("NRG-95025", discount_pct=5)
    req = _make_discount_approval(
        action="discount.11_to_20",
        order_id=order.id,
        discount_pct=-3,
        actor_role="operations",
        by_user=admin_user,
        auto=False,
    )
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED


# ---------------------------------------------------------------------------
# 3. discount.above_20 must remain unmapped.
# ---------------------------------------------------------------------------


def test_discount_above_20_remains_unmapped(director_user) -> None:
    order = _make_order("NRG-95030", discount_pct=5)
    req = approval_engine.create_approval_request(
        action="discount.above_20",
        payload={"orderId": order.id, "discountPct": 25},
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
    order.refresh_from_db()
    assert order.discount_pct == 5  # unchanged


# ---------------------------------------------------------------------------
# 4. Idempotency + side-effect scope on discount.
# ---------------------------------------------------------------------------


def test_already_executed_discount_returns_prior_result(admin_user) -> None:
    order = _make_order("NRG-95040", discount_pct=0)
    req = _make_discount_approval(
        action="discount.up_to_10",
        order_id=order.id,
        discount_pct=7,
        actor_role="operations",
        by_user=admin_user,
        auto=True,
    )
    first = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    # Second call: prior result returned, no second discount.applied write.
    audit_before = AuditEvent.objects.filter(kind="discount.applied").count()
    second = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert second.already_executed is True
    assert second.result == first.result
    assert AuditEvent.objects.filter(kind="discount.applied").count() == audit_before


def test_discount_execution_only_touches_discount_pct(admin_user) -> None:
    order = _make_order("NRG-95041", discount_pct=2)
    original_amount = order.amount
    original_stage = order.stage
    original_advance = order.advance_amount
    req = _make_discount_approval(
        action="discount.11_to_20",
        order_id=order.id,
        discount_pct=15,
        actor_role="operations",
        by_user=admin_user,
        auto=True,
    )
    approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    order.refresh_from_db()
    assert order.discount_pct == 15
    # Other fields untouched.
    assert order.amount == original_amount
    assert order.stage == original_stage
    assert order.advance_amount == original_advance


def test_discount_writes_discount_applied_audit(admin_user) -> None:
    order = _make_order("NRG-95042", discount_pct=0)
    req = _make_discount_approval(
        action="discount.up_to_10",
        order_id=order.id,
        discount_pct=10,
        actor_role="operations",
        by_user=admin_user,
        auto=True,
    )
    AuditEvent.objects.filter(
        kind__in=("discount.applied", "ai.approval.executed")
    ).delete()
    approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert AuditEvent.objects.filter(kind="discount.applied").exists()
    assert AuditEvent.objects.filter(kind="ai.approval.executed").exists()


# ---------------------------------------------------------------------------
# 5. ai.sandbox.disable — Director-only, idempotent, audit.
# ---------------------------------------------------------------------------


def test_sandbox_disable_executes_for_director(director_user) -> None:
    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": True}
    )
    req = _make_sandbox_disable_approval(director_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=director_user
    )
    assert outcome.status == "executed"
    assert outcome.result["isEnabled"] is False
    assert outcome.result["alreadyDisabled"] is False
    assert SandboxState.objects.get(pk=1).is_enabled is False


def test_sandbox_disable_blocks_admin(admin_user, director_user) -> None:
    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": True}
    )
    req = _make_sandbox_disable_approval(director_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert outcome.http_status == 403
    # Sandbox stays enabled.
    assert SandboxState.objects.get(pk=1).is_enabled is True


def test_sandbox_disable_blocks_operations(operations_user, director_user) -> None:
    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": True}
    )
    req = _make_sandbox_disable_approval(director_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=operations_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert outcome.http_status == 403


def test_sandbox_disable_blocks_anonymous_via_endpoint(
    director_user, auth_client
) -> None:
    from rest_framework.test import APIClient

    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": True}
    )
    req = _make_sandbox_disable_approval(director_user)
    res = APIClient().post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 401


def test_sandbox_disable_requires_note_or_override_reason(director_user) -> None:
    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": True}
    )
    req = approval_engine.create_approval_request(
        action="ai.sandbox.disable",
        payload={},  # no note, no overrideReason
        actor_role="director",
        by_user=director_user,
    )
    req = _approve(req, director_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=director_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert "note" in (outcome.error_message or "").lower()


def test_sandbox_disable_idempotent_when_already_off(director_user) -> None:
    # Pre-condition: sandbox already off.
    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": False}
    )
    req = _make_sandbox_disable_approval(director_user)
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=director_user
    )
    assert outcome.status == "executed"
    assert outcome.result["alreadyDisabled"] is True
    assert outcome.result["isEnabled"] is False


def test_sandbox_disable_writes_audit(director_user) -> None:
    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": True}
    )
    req = _make_sandbox_disable_approval(director_user)
    AuditEvent.objects.filter(
        kind__in=("ai.sandbox.disabled", "ai.approval.executed")
    ).delete()
    approval_execution.execute_approval_request(
        approval_request=req, user=director_user
    )
    assert AuditEvent.objects.filter(kind="ai.sandbox.disabled").exists()
    assert AuditEvent.objects.filter(kind="ai.approval.executed").exists()


# ---------------------------------------------------------------------------
# 6. Hard-stop regression — CAIO + still-unmapped actions.
# ---------------------------------------------------------------------------


def test_caio_requested_discount_cannot_execute(admin_user) -> None:
    order = _make_order("NRG-95060", discount_pct=0)
    req = _make_discount_approval(
        action="discount.up_to_10",
        order_id=order.id,
        discount_pct=8,
        actor_role="operations",
        by_user=admin_user,
        auto=True,
    )
    req.requested_by_agent = "caio"
    req.save(update_fields=["requested_by_agent"])
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=admin_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert outcome.http_status == 403
    order.refresh_from_db()
    assert order.discount_pct == 0  # unchanged


def test_caio_actor_metadata_blocks_sandbox_disable(director_user) -> None:
    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": True}
    )
    req = _make_sandbox_disable_approval(director_user)
    req.metadata = {**(req.metadata or {}), "actor_agent": "caio"}
    req.save(update_fields=["metadata"])
    outcome = approval_execution.execute_approval_request(
        approval_request=req, user=director_user
    )
    assert outcome.status == ApprovalExecutionLog.Status.FAILED
    assert outcome.http_status == 403
    assert SandboxState.objects.get(pk=1).is_enabled is True


@pytest.mark.parametrize(
    "action",
    [
        "ad.budget_change",
        "payment.refund",
        "whatsapp.broadcast_or_campaign",
        "ai.production.live_mode_switch",
    ],
)
def test_remaining_unmapped_actions_skipped(director_user, action) -> None:
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


# ---------------------------------------------------------------------------
# 7. Endpoint-level smoke: discount executes through the HTTP path.
# ---------------------------------------------------------------------------


def test_discount_up_to_10_via_endpoint(admin_user, auth_client) -> None:
    order = _make_order("NRG-95070", discount_pct=0)
    req = _make_discount_approval(
        action="discount.up_to_10",
        order_id=order.id,
        discount_pct=9,
        actor_role="operations",
        by_user=admin_user,
        auto=True,
    )
    res = auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["executionStatus"] == "executed"
    assert body["result"]["newDiscountPct"] == 9


def test_discount_11_to_20_via_endpoint(admin_user, auth_client) -> None:
    order = _make_order("NRG-95071", discount_pct=0)
    req = _make_discount_approval(
        action="discount.11_to_20",
        order_id=order.id,
        discount_pct=15,
        actor_role="operations",
        by_user=admin_user,
        auto=False,
    )
    res = auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["executionStatus"] == "executed"


def test_sandbox_disable_via_endpoint_director(director_user, auth_client) -> None:
    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": True}
    )
    req = _make_sandbox_disable_approval(director_user)
    res = auth_client(director_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["executionStatus"] == "executed"
    assert body["result"]["isEnabled"] is False


def test_sandbox_disable_via_endpoint_admin_blocked(
    admin_user, director_user, auth_client
) -> None:
    SandboxState.objects.update_or_create(
        pk=1, defaults={"is_enabled": True}
    )
    req = _make_sandbox_disable_approval(director_user)
    res = auth_client(admin_user).post(
        f"/api/ai/approvals/{req.id}/execute/", {}, format="json"
    )
    assert res.status_code == 403
    assert SandboxState.objects.get(pk=1).is_enabled is True
