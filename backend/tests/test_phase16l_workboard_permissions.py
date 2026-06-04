"""Phase 16L — Scoped Team Member Work Permissions + My Work Queue tests.

Coverage (directive 1–27):
  - My Work list/summary require auth; only return the caller's own work.
  - Membership create/activate/deactivate are Director/Admin-only.
  - Operations user without membership cannot claim; with active membership in the
    department can claim; cannot claim another department / inactive / can_claim=false.
  - Assigned user can start/block/unblock/complete/note their own action; a
    non-assignee cannot; can_complete=false membership blocks completion.
  - Assign/reassign stay Director/Admin-only.
  - Terminal queue actions + closed work items stay protected.
  - Permission booleans serialize; provider/external flags stay false; kill-switch
    + sandbox untouched; no WhatsApp/Razorpay/PayU/Delhivery/Vapi/live-AI call.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai_copilot.models import (
    AiApprovedAction,
    AiCopilotSuggestion,
    AiWorkboardDepartmentMember,
)

FROM_SUGGESTION = "/api/v1/ai-copilot/actions/from-suggestion/"
MY = "/api/v1/ai-copilot/workboard/my/"
MY_SUMMARY = "/api/v1/ai-copilot/workboard/my/summary/"
MY_PERMS = "/api/v1/ai-copilot/workboard/my-permissions/"
MEMBERS = "/api/v1/ai-copilot/workboard/department-members/"


@pytest.fixture
def director_user(db):
    u = User.objects.create_user(username="d16l", password="d16l12345", email="d16l@n.test")
    u.role = User.Role.DIRECTOR
    u.save(update_fields=["role"])
    return u


@pytest.fixture
def ops2_user(db):
    u = User.objects.create_user(username="ops2", password="ops212345", email="ops2@n.test")
    u.role = User.Role.OPERATIONS
    u.save(update_fields=["role"])
    return u


def _suggestion(reviewed_by=None):
    return AiCopilotSuggestion.objects.create(
        suggestion_type="director_briefing", source_type="manual", source_id="",
        title="S", summary="s", recommendation="r", ai_mode="mock",
        status="approved", reviewed_by=reviewed_by,
    )


def _new_action(director_client, reviewed_by, action_type="create_qa_review_task"):
    s = _suggestion(reviewed_by=reviewed_by)
    res = director_client.post(
        FROM_SUGGESTION, {"suggestionId": s.id, "actionType": action_type}, format="json"
    )
    assert res.status_code == 201, res.content
    return res.json()["id"]


def _act(client, action_id, verb, body=None):
    return client.post(
        f"/api/v1/ai-copilot/actions/{action_id}/{verb}/", body or {}, format="json"
    )


def _make_member(client, user, department, **flags):
    body = {"userId": user.id, "department": department}
    body.update(flags)
    return client.post(MEMBERS, body, format="json")


# --------------------------------------------------------------------------
# 1-3 My Work auth + scoping
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_my_work_requires_auth() -> None:
    assert APIClient().get(MY).status_code in {401, 403}


@pytest.mark.django_db
def test_my_work_summary_requires_auth() -> None:
    assert APIClient().get(MY_SUMMARY).status_code in {401, 403}


@pytest.mark.django_db
def test_my_work_only_returns_own_assigned(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    # another action assigned to the director, not the ops user
    other = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})

    body = auth_client(operations_user).get(MY).json()
    ids = {i["id"] for i in body["items"]}
    assert aid in ids
    assert other not in ids


# --------------------------------------------------------------------------
# 4-5 Membership management is Director/Admin-only
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_membership_create_requires_admin(director_user, operations_user, auth_client) -> None:
    res = _make_member(auth_client(director_user), operations_user, "calling")
    assert res.status_code in {200, 201}, res.content


@pytest.mark.django_db
def test_viewer_cannot_create_membership(viewer_user, operations_user, auth_client) -> None:
    assert _make_member(auth_client(viewer_user), operations_user, "calling").status_code == 403


@pytest.mark.django_db
def test_membership_list_admin_only(viewer_user, auth_client) -> None:
    assert auth_client(viewer_user).get(MEMBERS).status_code == 403


# --------------------------------------------------------------------------
# 6-8 Claim scoping
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_ops_without_membership_cannot_claim(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling"})  # dept set, no assignee
    res = _act(auth_client(operations_user), aid, "claim")
    assert res.status_code == 403
    assert res.json()["reason"] == "no_active_membership"


@pytest.mark.django_db
def test_ops_with_membership_can_claim(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    _make_member(dc, operations_user, "calling")
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling"})
    res = _act(auth_client(operations_user), aid, "claim")
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["assigneeUser"] == operations_user.username
    assert body["workStatus"] == "assigned"
    assert body["externalActionTaken"] is False
    assert body["providerActionTaken"] is False


@pytest.mark.django_db
def test_ops_cannot_claim_other_department(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    _make_member(dc, operations_user, "calling")
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "finance_accounts"})
    res = _act(auth_client(operations_user), aid, "claim")
    assert res.status_code == 403
    assert res.json()["reason"] == "no_active_membership"


# --------------------------------------------------------------------------
# 9-14 Assigned-user lifecycle
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_assigned_user_can_start_own(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    res = _act(auth_client(operations_user), aid, "start")
    assert res.status_code == 200, res.content
    assert res.json()["workStatus"] == "in_progress"


@pytest.mark.django_db
def test_non_assignee_cannot_start(director_user, operations_user, ops2_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    res = _act(auth_client(ops2_user), aid, "start")
    assert res.status_code == 403
    assert res.json()["reason"] == "not_assignee"


@pytest.mark.django_db
def test_assigned_user_block_unblock(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    oc = auth_client(operations_user)
    _act(oc, aid, "start")
    assert _act(oc, aid, "block", {}).status_code == 409  # reason required
    blocked = _act(oc, aid, "block", {"reason": "waiting"})
    assert blocked.status_code == 200
    assert blocked.json()["workStatus"] == "blocked"
    un = _act(oc, aid, "unblock")
    assert un.status_code == 200 and un.json()["workStatus"] == "in_progress"


@pytest.mark.django_db
def test_assigned_user_complete_and_note(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    oc = auth_client(operations_user)
    assert _act(oc, aid, "notes", {"note": "progress"}).status_code == 200
    _act(oc, aid, "start")
    done = _act(oc, aid, "complete-internal", {"note": "done"})
    assert done.status_code == 200
    assert done.json()["workStatus"] == "completed_internal"
    assert done.json()["providerActionTaken"] is False


# --------------------------------------------------------------------------
# 15-16 Assign/reassign stay admin-only
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_ops_cannot_assign_or_reassign(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    oc = auth_client(operations_user)
    assert _act(oc, aid, "assign", {"department": "calling"}).status_code == 403
    assert _act(oc, aid, "reassign", {"department": "calling"}).status_code == 403


@pytest.mark.django_db
def test_director_can_assign_and_reassign(director_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    assert _act(dc, aid, "assign", {"department": "calling"}).status_code == 200
    assert _act(dc, aid, "reassign", {"department": "delivery_rto"}).status_code == 200


# --------------------------------------------------------------------------
# 17-19 Membership flag guards
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_inactive_membership_cannot_claim(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    res = _make_member(dc, operations_user, "calling")
    mid = res.json()["id"]
    dc.post(f"{MEMBERS}{mid}/deactivate/", {}, format="json")
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling"})
    assert _act(auth_client(operations_user), aid, "claim").status_code == 403


@pytest.mark.django_db
def test_can_claim_false_cannot_claim(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    _make_member(dc, operations_user, "calling", canClaim=False)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling"})
    res = _act(auth_client(operations_user), aid, "claim")
    assert res.status_code == 403
    assert res.json()["reason"] == "membership_cannot_claim"


@pytest.mark.django_db
def test_can_complete_false_cannot_complete(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    _make_member(dc, operations_user, "calling", canComplete=False)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    oc = auth_client(operations_user)
    _act(oc, aid, "start")
    res = _act(oc, aid, "complete-internal")
    assert res.status_code == 403
    assert res.json()["reason"] == "membership_cannot_complete"


# --------------------------------------------------------------------------
# 20-21 Terminal / closed protection
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_terminal_queue_action_cannot_be_claimed(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    _make_member(dc, operations_user, "calling")
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling"})
    _act(dc, aid, "reject")  # Phase 16J queue reject → terminal
    res = _act(auth_client(operations_user), aid, "claim")
    assert res.status_code == 403
    assert res.json()["reason"] == "action_terminal_or_closed"


@pytest.mark.django_db
def test_closed_work_item_cannot_reopen(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    oc = auth_client(operations_user)
    _act(oc, aid, "complete-internal")
    # cannot start a completed work item
    assert _act(oc, aid, "start").status_code in {403, 409}


# --------------------------------------------------------------------------
# 22 Permission booleans serialize
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_permission_booleans_serialize(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    _make_member(dc, operations_user, "calling")
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling"})
    body = auth_client(operations_user).get("/api/v1/ai-copilot/workboard/").json()
    assert "myPermissions" in body
    assert body["myPermissions"]["isAdmin"] is False
    item = next(i for i in body["items"] if i["id"] == aid)
    perms = item["permissions"]
    for key in ("canClaim", "canStart", "canBlock", "canUnblock",
                "canCompleteInternal", "canAddNote", "canAssign", "canReassign"):
        assert key in perms and isinstance(perms[key], bool)
    assert perms["canClaim"] is True
    assert perms["canAssign"] is False  # ops user is not admin


@pytest.mark.django_db
def test_my_permissions_endpoint(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    _make_member(dc, operations_user, "qa_compliance")
    body = auth_client(operations_user).get(MY_PERMS).json()
    assert body["isAdmin"] is False
    assert body["canAssign"] is False
    assert any(d["department"] == "qa_compliance" for d in body["departments"])
    admin_body = auth_client(director_user).get(MY_PERMS).json()
    assert admin_body["isAdmin"] is True and admin_body["canAssign"] is True


# --------------------------------------------------------------------------
# 23-27 Defensive: no provider call, flags false, safety state untouched
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_scoped_flow_no_provider_side_effect(director_user, operations_user, auth_client) -> None:
    from apps.ai_governance.sandbox import is_sandbox_enabled
    from apps.crm.models import Customer, Lead
    from apps.orders.models import Order
    from apps.payments.models import Payment
    from apps.saas.models import RuntimeKillSwitch

    sandbox_before = is_sandbox_enabled()
    ks_before = RuntimeKillSwitch.objects.count()
    counts_before = (
        Lead.objects.count(), Customer.objects.count(),
        Order.objects.count(), Payment.objects.count(),
    )

    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as wa_t, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as wa_f, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as vapi, mock.patch(
        "apps.payments.integrations.razorpay_client.create_payment_link"
    ) as rz, mock.patch(
        "apps.shipments.integrations.delhivery_client.create_awb"
    ) as dl:
        dc = auth_client(director_user)
        _make_member(dc, operations_user, "calling")
        aid = _new_action(dc, director_user)
        _act(dc, aid, "assign", {"department": "calling"})
        oc = auth_client(operations_user)
        _act(oc, aid, "claim")
        _act(oc, aid, "start")
        _act(oc, aid, "block", {"reason": "x"})
        _act(oc, aid, "unblock")
        _act(oc, aid, "notes", {"note": "n"})
        _act(oc, aid, "complete-internal")
        oc.get(MY)
        oc.get(MY_SUMMARY)
        oc.get(MY_PERMS)

    wa_t.assert_not_called()
    wa_f.assert_not_called()
    vapi.assert_not_called()
    rz.assert_not_called()
    dl.assert_not_called()
    assert is_sandbox_enabled() == sandbox_before
    assert RuntimeKillSwitch.objects.count() == ks_before
    assert (
        Lead.objects.count(), Customer.objects.count(),
        Order.objects.count(), Payment.objects.count(),
    ) == counts_before
    for a in AiApprovedAction.objects.all():
        assert a.provider_action_taken is False
        assert a.provider_action_attempted is False
        assert a.external_action_taken is False
        assert a.external_action_allowed is False


@pytest.mark.django_db
def test_unique_active_membership_reused(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    r1 = _make_member(dc, operations_user, "calling")
    r2 = _make_member(dc, operations_user, "calling", canComplete=False)
    assert r1.json()["id"] == r2.json()["id"]  # reactivated/updated, not duplicated
    assert AiWorkboardDepartmentMember.objects.filter(
        user=operations_user, department="calling", is_active=True
    ).count() == 1
    assert r2.json()["canComplete"] is False
