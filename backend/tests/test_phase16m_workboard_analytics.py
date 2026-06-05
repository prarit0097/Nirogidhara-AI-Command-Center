"""Phase 16M — Workboard Analytics + SLA Throughput Dashboard tests.

Coverage (directive 1–15):
  1. Analytics endpoint requires authentication.
  2. Authorized user (incl. read-only) can read analytics.
  3. Endpoint is GET-only/read-only; POST/PATCH/DELETE return 405.
  4. Summary counts are correct across multiple work statuses.
  5. Department analytics counts are correct.
  6. Member workload counts are correct.
  7. SLA overdue/due-soon/no-due-date classification is correct.
  8. Blocker reason aggregation is safe and truncated.
  9. Completion time is computed safely where completed_at exists.
  10. Trend returns safe data or a safe empty state.
  11. No provider calls are made (WhatsApp / Vapi / Razorpay / Delhivery patched).
  12. No business row counts mutate (Lead/Customer/Order/Payment).
  13. RuntimeKillSwitch and SandboxState are not mutated.
  14. Phase 16L permission/membership behaviour remains unchanged.
  15. Phase 16K workboard summary still works (regression smoke).

Everything here is read-only/internal-only. No live provider/customer-facing
action is ever taken.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai_copilot.models import AiApprovedAction, AiCopilotSuggestion

ANALYTICS = "/api/v1/ai-copilot/workboard/analytics/"


@pytest.fixture
def director_user(db):
    u = User.objects.create_user(username="d16m", password="d16m12345", email="d16m@n.test")
    u.role = User.Role.DIRECTOR
    u.save(update_fields=["role"])
    return u
FROM_SUGGESTION = "/api/v1/ai-copilot/actions/from-suggestion/"
MEMBERS = "/api/v1/ai-copilot/workboard/department-members/"


def _suggestion(reviewed_by=None):
    return AiCopilotSuggestion.objects.create(
        suggestion_type="director_briefing", source_type="manual", source_id="",
        title="S", summary="s", recommendation="r", ai_mode="mock",
        status="approved", reviewed_by=reviewed_by,
    )


def _new_action(client, reviewed_by, action_type="create_qa_review_task"):
    s = _suggestion(reviewed_by=reviewed_by)
    res = client.post(
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


def _set_due(action_id, *, hours):
    """Set due_at relative to now (negative = past) directly (test setup only)."""
    from django.utils import timezone

    AiApprovedAction.objects.filter(pk=action_id).update(
        due_at=timezone.now() + timezone.timedelta(hours=hours)
    )


# --------------------------------------------------------------------------
# 1-3 auth + read-only
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_analytics_requires_auth() -> None:
    assert APIClient().get(ANALYTICS).status_code in {401, 403}


@pytest.mark.django_db
def test_authorized_user_can_read_analytics(director_user, auth_client) -> None:
    res = auth_client(director_user).get(ANALYTICS)
    assert res.status_code == 200, res.content
    body = res.json()
    for key in ("summary", "departments", "members", "sla", "blockers", "trend"):
        assert key in body
    assert body["readonly"] is True
    assert body["internalOnly"] is True
    assert body["providerActionAttempted"] is False
    assert body["providerActionTaken"] is False
    assert body["externalActionAllowed"] is False
    assert body["externalActionTaken"] is False
    assert body["phase"] == "16M"


@pytest.mark.django_db
def test_viewer_can_read_analytics(viewer_user, auth_client) -> None:
    # Read = any authenticated user (AuthenticatedReadAdminWrite).
    assert auth_client(viewer_user).get(ANALYTICS).status_code == 200


@pytest.mark.django_db
def test_analytics_is_get_only(director_user, auth_client) -> None:
    dc = auth_client(director_user)
    assert dc.post(ANALYTICS, {}, format="json").status_code == 405
    assert dc.patch(ANALYTICS, {}, format="json").status_code == 405
    assert dc.delete(ANALYTICS).status_code == 405


# --------------------------------------------------------------------------
# 4 summary counts
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_summary_counts_across_statuses(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    a_unassigned = _new_action(dc, director_user)  # stays unassigned
    a_assigned = _new_action(dc, director_user)
    _act(dc, a_assigned, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    a_inprogress = _new_action(dc, director_user)
    _act(dc, a_inprogress, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    _act(dc, a_inprogress, "start")
    a_blocked = _new_action(dc, director_user)
    _act(dc, a_blocked, "assign", {"department": "finance_accounts", "assigneeUserId": operations_user.id})
    _act(dc, a_blocked, "start")
    _act(dc, a_blocked, "block", {"reason": "waiting on customer"})
    a_done = _new_action(dc, director_user)
    _act(dc, a_done, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    _act(dc, a_done, "complete-internal")

    s = auth_client(director_user).get(ANALYTICS).json()["summary"]
    assert s["total"] == 5
    assert s["unassigned"] == 1
    assert s["assigned"] == 1
    assert s["inProgress"] == 1
    assert s["blocked"] == 1
    assert s["completedInternal"] == 1
    assert s["openActions"] == 4  # all except the completed one
    assert isinstance(s["directorAttention"], int)


# --------------------------------------------------------------------------
# 5 department analytics
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_department_analytics_counts(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    for _ in range(2):
        aid = _new_action(dc, director_user)
        _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    fin = _new_action(dc, director_user)
    _act(dc, fin, "assign", {"department": "finance_accounts", "assigneeUserId": operations_user.id})

    depts = {d["department"]: d for d in auth_client(director_user).get(ANALYTICS).json()["departments"]}
    assert depts["calling"]["total"] == 2
    assert depts["calling"]["assigned"] == 2
    assert depts["finance_accounts"]["total"] == 1
    assert "label" in depts["calling"]
    assert depts["calling"]["completionRate"] == 0.0


# --------------------------------------------------------------------------
# 6 member workload
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_member_workload_counts(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    a1 = _new_action(dc, director_user)
    _act(dc, a1, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    a2 = _new_action(dc, director_user)
    _act(dc, a2, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    _act(dc, a2, "start")

    members = {m["userId"]: m for m in auth_client(director_user).get(ANALYTICS).json()["members"]}
    me = members[operations_user.id]
    assert me["username"] == operations_user.username
    assert me["assignedOpen"] == 1
    assert me["inProgress"] == 1
    assert "calling" in me["departments"]


# --------------------------------------------------------------------------
# 7 SLA classification
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_sla_classification(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    overdue = _new_action(dc, director_user)
    _act(dc, overdue, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    _set_due(overdue, hours=-2)
    soon = _new_action(dc, director_user)
    _act(dc, soon, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    _set_due(soon, hours=1)
    _no_due = _new_action(dc, director_user)  # no due date

    sla = auth_client(director_user).get(ANALYTICS).json()["sla"]
    assert sla["overdue"] == 1
    assert sla["dueSoon"] == 1
    assert sla["noDueDate"] == 1  # only the 3rd action has no due date
    assert sla["highestRiskDepartment"] == "calling"
    assert sla["overdueByDepartment"].get("calling") == 1


# --------------------------------------------------------------------------
# 8 blocker aggregation + truncation
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_blocker_aggregation_truncated(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    long_reason = "X" * 250
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    _act(dc, aid, "start")
    _act(dc, aid, "block", {"reason": long_reason})

    blockers = auth_client(director_user).get(ANALYTICS).json()["blockers"]
    assert blockers["blockedCount"] == 1
    assert len(blockers["topBlockerReasons"]) == 1
    assert len(blockers["topBlockerReasons"][0]["reason"]) <= 80  # truncated
    assert blockers["blockedByDepartment"].get("calling") == 1
    assert blockers["oldestBlockedAgeHours"] is not None


# --------------------------------------------------------------------------
# 9 completion time
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_completion_time_computed(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    _act(dc, aid, "complete-internal")
    body = auth_client(director_user).get(ANALYTICS).json()
    assert body["summary"]["avgCompletionHours"] is not None
    assert body["summary"]["avgCompletionHours"] >= 0.0


# --------------------------------------------------------------------------
# 10 trend safe data / empty state
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_trend_empty_state_safe(director_user, auth_client) -> None:
    body = auth_client(director_user).get(ANALYTICS).json()
    trend = body["trend"]
    assert trend["windowDays"] == 14
    assert isinstance(trend["days"], list)
    assert len(trend["days"]) == 14
    assert trend["hasData"] is False
    assert trend["reason"] == "insufficient_event_data"


@pytest.mark.django_db
def test_trend_has_data_after_activity(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    _act(dc, aid, "start")
    trend = auth_client(director_user).get(ANALYTICS + "?windowDays=7").json()["trend"]
    assert trend["windowDays"] == 7
    assert len(trend["days"]) == 7
    assert trend["hasData"] is True
    assert sum(d["created"] for d in trend["days"]) >= 1
    assert sum(d["assigned"] for d in trend["days"]) >= 1
    assert sum(d["started"] for d in trend["days"]) >= 1


# --------------------------------------------------------------------------
# 11-13 defensive: no provider call, no business mutation, safety state intact
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_analytics_no_provider_or_business_side_effect(
    director_user, operations_user, auth_client
) -> None:
    from apps.ai_governance.sandbox import is_sandbox_enabled
    from apps.crm.models import Customer, Lead
    from apps.orders.models import Order
    from apps.payments.models import Payment
    from apps.saas.models import RuntimeKillSwitch

    dc = auth_client(director_user)
    # seed a small workboard
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling", "assigneeUserId": operations_user.id})
    _act(dc, aid, "start")

    sandbox_before = is_sandbox_enabled()
    ks_before = RuntimeKillSwitch.objects.count()
    counts_before = (
        Lead.objects.count(), Customer.objects.count(),
        Order.objects.count(), Payment.objects.count(),
    )
    action_rows_before = AiApprovedAction.objects.count()

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
        c = auth_client(director_user)
        assert c.get(ANALYTICS).status_code == 200
        assert c.get(ANALYTICS + "?windowDays=7").status_code == 200
        assert auth_client(operations_user).get(ANALYTICS).status_code == 200

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
    # reading analytics never creates/mutates a workboard row
    assert AiApprovedAction.objects.count() == action_rows_before
    for a in AiApprovedAction.objects.all():
        assert a.provider_action_taken is False
        assert a.provider_action_attempted is False
        assert a.external_action_taken is False
        assert a.external_action_allowed is False


# --------------------------------------------------------------------------
# 14 Phase 16L permission behaviour unchanged
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase16l_claim_permission_unchanged(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    aid = _new_action(dc, director_user)
    _act(dc, aid, "assign", {"department": "calling"})  # dept set, no assignee, no membership
    res = _act(auth_client(operations_user), aid, "claim")
    assert res.status_code == 403
    assert res.json()["reason"] == "no_active_membership"


# --------------------------------------------------------------------------
# 15 Phase 16K workboard summary still works (regression smoke)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase16k_workboard_summary_still_works(director_user, auth_client) -> None:
    res = auth_client(director_user).get("/api/v1/ai-copilot/workboard/summary/")
    assert res.status_code == 200
    assert res.json()["phase"] == "16K"
