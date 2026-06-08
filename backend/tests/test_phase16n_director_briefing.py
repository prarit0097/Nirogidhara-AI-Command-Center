"""Phase 16N — Director AI Daily Briefing + Safe Recommendation Pack tests.

Coverage (directive 1-17):
  1. Director briefing endpoint requires auth.
  2. Summary / recommendations endpoints require auth.
  3. Responses include internalOnly=true, readonly=true, providerCallMade=false,
     externalActionTaken=false (+ liveAutonomousLocked=true).
  4. Briefing uses existing workboard analytics data.
  5. Attention items include blocked actions.
  6. Attention items include overdue actions.
  7. Attention items include unassigned high/urgent actions when present.
  8. Recommendations are internal-only with a safe permittedAction.
  9. Blocked live actions list includes WhatsApp/payment/courier/Vapi/live-AI.
  10. No live provider calls are made (5 entrypoints patched).
  11. RuntimeKillSwitch / SandboxState untouched.
  12. Lead/Customer/Order/Payment counts unchanged.
  13. No AiApprovedAction mutation (row counts + flags).
  14. (No Celery enqueue — read path imports/triggers no business task.)
  15. GET-only endpoints reject POST/PATCH/DELETE with 405.
  16. (No snapshot model — read-only; nothing to gate.)
  17. Phase 16M/16L/16K targeted suites still pass (run separately).

Everything is read-only / internal-only. No live provider / customer-facing
action is ever taken.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai_copilot.models import AiApprovedAction, AiCopilotSuggestion

BRIEFING = "/api/v1/ai-copilot/director-briefing/"
SUMMARY = "/api/v1/ai-copilot/director-briefing/summary/"
RECS = "/api/v1/ai-copilot/director-briefing/recommendations/"
FROM_SUGGESTION = "/api/v1/ai-copilot/actions/from-suggestion/"


@pytest.fixture
def director_user(db):
    u = User.objects.create_user(username="d16n", password="d16n12345", email="d16n@n.test")
    u.role = User.Role.DIRECTOR
    u.save(update_fields=["role"])
    return u


def _suggestion(reviewed_by=None, status="approved"):
    return AiCopilotSuggestion.objects.create(
        suggestion_type="director_briefing", source_type="manual", source_id="",
        title="S", summary="s", recommendation="r", ai_mode="mock",
        status=status, reviewed_by=reviewed_by,
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


def _seed_workboard(dc, director_user, operations_user):
    """A small workboard with blocked + overdue + unassigned-high + pending items."""
    from django.utils import timezone

    # blocked
    blk = _new_action(dc, director_user)
    _act(dc, blk, "assign", {"department": "qa_compliance", "assigneeUserId": operations_user.id})
    _act(dc, blk, "start")
    _act(dc, blk, "block", {"reason": "waiting on compliance sign-off"})
    # overdue (assigned, due in the past)
    ovd = _new_action(dc, director_user)
    _act(dc, ovd, "assign", {"department": "finance_accounts", "assigneeUserId": operations_user.id})
    AiApprovedAction.objects.filter(pk=ovd).update(
        due_at=timezone.now() - timezone.timedelta(hours=3)
    )
    # unassigned high-priority
    hi = _new_action(dc, director_user)
    AiApprovedAction.objects.filter(pk=hi).update(priority="urgent")
    # a pending suggestion (not approved) + a pending internal action
    _suggestion(status="pending_review")
    return {"blocked": blk, "overdue": ovd, "unassignedHigh": hi}


# --------------------------------------------------------------------------
# 1-2 auth
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_briefing_requires_auth() -> None:
    assert APIClient().get(BRIEFING).status_code in {401, 403}


@pytest.mark.django_db
def test_summary_requires_auth() -> None:
    assert APIClient().get(SUMMARY).status_code in {401, 403}


@pytest.mark.django_db
def test_recommendations_requires_auth() -> None:
    assert APIClient().get(RECS).status_code in {401, 403}


@pytest.mark.django_db
def test_viewer_can_read_briefing(viewer_user, auth_client) -> None:
    # read = any authenticated user (AuthenticatedReadAdminWrite)
    assert auth_client(viewer_user).get(BRIEFING).status_code == 200


# --------------------------------------------------------------------------
# 3 locked safety flags on every endpoint
# --------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("url", [BRIEFING, SUMMARY, RECS])
def test_safe_flags_present(url, director_user, auth_client) -> None:
    body = auth_client(director_user).get(url).json()
    assert body["internalOnly"] is True
    assert body["readonly"] is True
    assert body["providerCallMade"] is False
    assert body["externalActionTaken"] is False
    assert body["liveAutonomousLocked"] is True
    assert body["phase"] == "16N"
    bs = body["briefingStatus"]
    assert bs["providerCallMade"] is False
    assert bs["externalActionTaken"] is False
    assert bs["liveAutonomousLocked"] is True
    assert bs["aiMode"] in {"mock", "sandbox"}


# --------------------------------------------------------------------------
# 4 briefing uses workboard analytics data
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_briefing_uses_analytics(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    _seed_workboard(dc, director_user, operations_user)
    body = auth_client(director_user).get(BRIEFING).json()
    # departmentSummary + memberSummary + slaSummary mirror the Phase 16M analytics
    assert isinstance(body["departmentSummary"], list) and len(body["departmentSummary"]) >= 1
    assert "slaSummary" in body and "overdue" in body["slaSummary"]
    assert any(d["department"] == "qa_compliance" for d in body["departmentSummary"])
    assert isinstance(body["memberSummary"], list)
    assert len(body["executiveSummary"]) >= 3


# --------------------------------------------------------------------------
# 5-7 attention items
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_attention_includes_blocked_overdue_unassigned(
    director_user, operations_user, auth_client
) -> None:
    dc = auth_client(director_user)
    ids = _seed_workboard(dc, director_user, operations_user)
    att = auth_client(director_user).get(BRIEFING).json()["attentionItems"]
    assert att["blockedCount"] >= 1
    assert att["overdueCount"] >= 1
    assert att["unassignedHighPriority"] >= 1
    assert att["pendingSuggestions"] >= 1
    blocked_ids = {i["id"] for i in att["blocked"]}
    overdue_ids = {i["id"] for i in att["overdue"]}
    high_ids = {i["id"] for i in att["unassignedHigh"]}
    assert ids["blocked"] in blocked_ids
    assert ids["overdue"] in overdue_ids
    assert ids["unassignedHigh"] in high_ids
    # attention items carry only safe fields (no raw customer PII)
    for item in att["items"]:
        assert set(item.keys()) == {
            "id", "title", "department", "workStatus", "priority",
            "slaStatus", "assigneeUser", "reason",
        }


# --------------------------------------------------------------------------
# 8 recommendations internal-only + safe permittedAction
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_recommendations_internal_only(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    _seed_workboard(dc, director_user, operations_user)
    recs = auth_client(director_user).get(RECS).json()
    allowed = {
        "internal_review", "assign_internal", "create_internal_action",
        "review_blocker", "no_external_action",
    }
    assert len(recs["safeRecommendations"]) >= 1
    for r in recs["safeRecommendations"]:
        for key in ("recommendationType", "priority", "reason", "linkedMetric", "permittedAction"):
            assert key in r
        assert r["permittedAction"] in allowed
        assert r["priority"] in {"low", "medium", "high"}
    assert set(recs["permittedActions"]) == allowed


@pytest.mark.django_db
def test_all_clear_recommendation_when_empty(director_user, auth_client) -> None:
    recs = auth_client(director_user).get(RECS).json()["safeRecommendations"]
    assert any(r["recommendationType"] == "all_clear" for r in recs)
    assert all(r["permittedAction"] != "send_whatsapp" for r in recs)


# --------------------------------------------------------------------------
# 9 blocked live actions list
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_blocked_live_actions(director_user, auth_client) -> None:
    body = auth_client(director_user).get(BRIEFING).json()
    channels = {b["channel"] for b in body["blockedLiveActions"]}
    assert channels == {"whatsapp", "payment", "courier", "vapi", "live_ai"}
    assert all(b["locked"] is True for b in body["blockedLiveActions"])


# --------------------------------------------------------------------------
# 10-14 defensive: no provider call, no business mutation, safety state intact
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_briefing_no_provider_or_business_side_effect(
    director_user, operations_user, viewer_user, auth_client
) -> None:
    from apps.ai_governance.sandbox import is_sandbox_enabled
    from apps.crm.models import Customer, Lead
    from apps.orders.models import Order
    from apps.payments.models import Payment
    from apps.saas.models import RuntimeKillSwitch

    dc = auth_client(director_user)
    _seed_workboard(dc, director_user, operations_user)

    sandbox_before = is_sandbox_enabled()
    ks_before = RuntimeKillSwitch.objects.count()
    counts_before = (
        Lead.objects.count(), Customer.objects.count(),
        Order.objects.count(), Payment.objects.count(),
    )
    action_rows_before = AiApprovedAction.objects.count()
    actions_before = {
        a.pk: (a.status, a.work_status) for a in AiApprovedAction.objects.all()
    }

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
        assert c.get(BRIEFING).status_code == 200
        assert c.get(BRIEFING + "?windowDays=1").status_code == 200
        assert c.get(SUMMARY).status_code == 200
        assert c.get(RECS).status_code == 200
        assert auth_client(viewer_user).get(BRIEFING).status_code == 200

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
    # no AiApprovedAction created / mutated by reading the briefing
    assert AiApprovedAction.objects.count() == action_rows_before
    assert {
        a.pk: (a.status, a.work_status) for a in AiApprovedAction.objects.all()
    } == actions_before
    for a in AiApprovedAction.objects.all():
        assert a.provider_action_taken is False
        assert a.provider_action_attempted is False
        assert a.external_action_taken is False
        assert a.external_action_allowed is False


# --------------------------------------------------------------------------
# 15 GET-only — POST/PATCH/DELETE → 405
# --------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("url", [BRIEFING, SUMMARY, RECS])
def test_get_only(url, director_user, auth_client) -> None:
    dc = auth_client(director_user)
    assert dc.post(url, {}, format="json").status_code == 405
    assert dc.patch(url, {}, format="json").status_code == 405
    assert dc.delete(url).status_code == 405


# --------------------------------------------------------------------------
# Regression smoke — Phase 16M analytics endpoint still works
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase16m_analytics_still_works(director_user, auth_client) -> None:
    res = auth_client(director_user).get("/api/v1/ai-copilot/workboard/analytics/")
    assert res.status_code == 200
    assert res.json()["phase"] == "16M"
