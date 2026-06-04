"""Phase 16K — Department Action Workboard + Ownership / SLA Execution Layer tests.

Coverage:
  - workboard list / summary / director-attention require auth.
  - Director/Admin can assign; non-admin cannot assign/start (mutations are
    Director/Admin-only in Phase 16K).
  - Director can claim / start / block (stores reason) / unblock / complete /
    reassign / add note.
  - SLA status calculation (no_due_date / on_track / due_soon / overdue).
  - Director attention queue includes blocked / overdue / unassigned high-priority.
  - provider/external flags stay false after EVERY workboard transition.
  - RuntimeKillSwitch + SandboxState untouched; no WhatsApp/Razorpay/PayU/
    Delhivery/Vapi/live-AI provider call; no order/payment/customer mutation.
"""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai_copilot.models import AiApprovedAction, AiCopilotSuggestion

WORKBOARD = "/api/v1/ai-copilot/workboard/"
WB_SUMMARY = "/api/v1/ai-copilot/workboard/summary/"
WB_ATTENTION = "/api/v1/ai-copilot/workboard/director-attention/"
FROM_SUGGESTION = "/api/v1/ai-copilot/actions/from-suggestion/"


@pytest.fixture
def director_user(db):
    user = User.objects.create_user(
        username="d16k", password="d16k12345", email="d16k@nirogidhara.test"
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _suggestion(reviewed_by=None):
    return AiCopilotSuggestion.objects.create(
        suggestion_type="director_briefing", source_type="manual", source_id="",
        title="Test suggestion", summary="internal", recommendation="internal",
        ai_mode="mock", status="approved", reviewed_by=reviewed_by,
    )


def _make_action(client, reviewed_by, action_type="create_qa_review_task", priority="normal"):
    s = _suggestion(reviewed_by=reviewed_by)
    res = client.post(
        FROM_SUGGESTION,
        {"suggestionId": s.id, "actionType": action_type, "priority": priority},
        format="json",
    )
    assert res.status_code == 201, res.content
    return res.json()["id"]


def _post(client, action_id, verb, body=None):
    return client.post(f"/api/v1/ai-copilot/actions/{action_id}/{verb}/", body or {}, format="json")


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_workboard_requires_auth() -> None:
    assert APIClient().get(WORKBOARD).status_code in {401, 403}


@pytest.mark.django_db
def test_summary_requires_auth() -> None:
    assert APIClient().get(WB_SUMMARY).status_code in {401, 403}


@pytest.mark.django_db
def test_director_attention_requires_auth() -> None:
    assert APIClient().get(WB_ATTENTION).status_code in {401, 403}


@pytest.mark.django_db
def test_viewer_can_read_workboard(viewer_user, auth_client) -> None:
    res = auth_client(viewer_user).get(WORKBOARD)
    assert res.status_code == 200
    assert "items" in res.json()
    assert "departments" in res.json()


# --------------------------------------------------------------------------
# Permissions on mutations (Director/Admin only in Phase 16K)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_director_can_assign(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    res = _post(client, aid, "assign", {"department": "qa_compliance"})
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["workStatus"] == "assigned"
    assert body["department"] == "qa_compliance"
    assert body["externalActionAllowed"] is False
    assert body["providerActionTaken"] is False


@pytest.mark.django_db
def test_non_admin_cannot_assign(director_user, viewer_user, auth_client) -> None:
    aid = _make_action(auth_client(director_user), director_user)
    res = _post(auth_client(viewer_user), aid, "assign", {"department": "calling"})
    assert res.status_code == 403


@pytest.mark.django_db
def test_non_admin_cannot_start(director_user, operations_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    _post(client, aid, "assign", {"department": "calling"})
    res = _post(auth_client(operations_user), aid, "start")
    assert res.status_code == 403


@pytest.mark.django_db
def test_assign_requires_department(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    res = _post(client, aid, "assign", {})
    assert res.status_code == 409
    assert res.json()["reason"] == "department_required"


# --------------------------------------------------------------------------
# Lifecycle: assign → start → block → unblock → complete
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_assigned_user_or_director_can_start(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    _post(client, aid, "assign", {"department": "calling", "assigneeUserId": director_user.id})
    res = _post(client, aid, "start")
    assert res.status_code == 200, res.content
    assert res.json()["workStatus"] == "in_progress"


@pytest.mark.django_db
def test_block_stores_reason_and_requires_it(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    _post(client, aid, "assign", {"department": "finance_accounts"})
    _post(client, aid, "start")
    # reason required
    assert _post(client, aid, "block", {}).status_code == 409
    res = _post(client, aid, "block", {"reason": "waiting on customer callback"})
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["workStatus"] == "blocked"
    assert body["blockerReason"] == "waiting on customer callback"


@pytest.mark.django_db
def test_unblock(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    _post(client, aid, "assign", {"department": "calling"})
    _post(client, aid, "start")
    _post(client, aid, "block", {"reason": "blocked"})
    res = _post(client, aid, "unblock")
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["workStatus"] == "in_progress"
    assert body["blockerReason"] == ""


@pytest.mark.django_db
def test_complete_internal(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    _post(client, aid, "assign", {"department": "qa_compliance"})
    _post(client, aid, "start")
    res = _post(client, aid, "complete-internal", {"note": "done internally"})
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["workStatus"] == "completed_internal"
    assert body["completedAt"] is not None
    assert body["providerActionTaken"] is False
    assert body["externalActionTaken"] is False


@pytest.mark.django_db
def test_reassign(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    _post(client, aid, "assign", {"department": "calling"})
    res = _post(client, aid, "reassign", {"department": "delivery_rto"})
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["department"] == "delivery_rto"
    assert body["workStatus"] == "assigned"


@pytest.mark.django_db
def test_claim(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    res = _post(client, aid, "claim")
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["workStatus"] == "assigned"
    assert body["assigneeUser"] == director_user.username


@pytest.mark.django_db
def test_add_note_and_director_review(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    res = _post(client, aid, "notes", {"note": "internal note"})
    assert res.status_code == 200, res.content
    body = res.json()
    types = {e["eventType"] for e in body["workEvents"]}
    assert "note_added" in types
    res2 = _post(client, aid, "notes", {"directorReview": True, "note": "please review"})
    assert {"director_review_requested"} <= {e["eventType"] for e in res2.json()["workEvents"]}


@pytest.mark.django_db
def test_cannot_complete_unassigned(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    res = _post(client, aid, "complete-internal")
    assert res.status_code == 409


@pytest.mark.django_db
def test_cannot_reopen_completed(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    _post(client, aid, "assign", {"department": "calling"})
    _post(client, aid, "complete-internal")
    # start on a completed item is refused
    assert _post(client, aid, "start").status_code == 409


@pytest.mark.django_db
def test_cannot_work_queue_terminal_action(director_user, auth_client) -> None:
    """An action rejected at the Phase 16J queue level cannot be worked."""
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    _post(client, aid, "reject")  # Phase 16J queue reject
    res = _post(client, aid, "assign", {"department": "calling"})
    assert res.status_code == 409
    assert res.json()["reason"].startswith("action_queue_terminal")


# --------------------------------------------------------------------------
# SLA + director attention
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_sla_status_calculation(director_user, auth_client) -> None:
    from apps.ai_copilot.services import compute_sla_status

    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    a = AiApprovedAction.objects.get(pk=aid)
    assert compute_sla_status(a) == "no_due_date"

    a.due_at = timezone.now() + timedelta(hours=2)
    assert compute_sla_status(a) == "due_soon"
    a.due_at = timezone.now() + timedelta(days=3)
    assert compute_sla_status(a) == "on_track"
    a.due_at = timezone.now() - timedelta(hours=1)
    assert compute_sla_status(a) == "overdue"


@pytest.mark.django_db
def test_director_attention_queue(director_user, auth_client) -> None:
    client = auth_client(director_user)

    # blocked
    blocked = _make_action(client, director_user)
    _post(client, blocked, "assign", {"department": "calling"})
    _post(client, blocked, "start")
    _post(client, blocked, "block", {"reason": "stuck"})

    # overdue
    overdue = _make_action(client, director_user)
    _post(client, overdue, "assign", {"department": "finance_accounts"})
    AiApprovedAction.objects.filter(pk=overdue).update(
        due_at=timezone.now() - timedelta(hours=5)
    )

    # unassigned high priority
    urgent = _make_action(client, director_user, priority="urgent")

    body = client.get(WB_ATTENTION).json()
    reasons = {(i["id"], i["attentionReason"]) for i in body["items"]}
    assert (blocked, "blocked") in reasons
    assert (overdue, "overdue") in reasons
    assert (urgent, "unassigned_high_priority") in reasons


@pytest.mark.django_db
def test_summary_counts(director_user, auth_client) -> None:
    client = auth_client(director_user)
    a1 = _make_action(client, director_user)
    _post(client, a1, "assign", {"department": "calling"})
    a2 = _make_action(client, director_user)
    _post(client, a2, "assign", {"department": "qa_compliance"})
    _post(client, a2, "start")
    _post(client, a2, "complete-internal")

    body = client.get(WB_SUMMARY).json()
    assert body["phase"] == "16K"
    assert body["total"] >= 2
    assert body["assigned"] >= 1
    assert body["completedInternal"] >= 1
    assert body["providerActionsLocked"] is True
    assert body["noProviderActionTaken"] is True


@pytest.mark.django_db
def test_workboard_filters(director_user, auth_client) -> None:
    client = auth_client(director_user)
    aid = _make_action(client, director_user)
    _post(client, aid, "assign", {"department": "delivery_rto"})
    res = client.get(WORKBOARD, {"department": "delivery_rto"})
    assert res.status_code == 200
    items = res.json()["items"]
    assert items and all(i["department"] == "delivery_rto" for i in items)


# --------------------------------------------------------------------------
# Defensive: no provider call, no business mutation, safety state untouched
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_workboard_flow_no_provider_side_effect(director_user, auth_client) -> None:
    from apps.ai_governance.sandbox import is_sandbox_enabled
    from apps.crm.models import Customer, Lead
    from apps.orders.models import Order
    from apps.payments.models import Payment
    from apps.saas.models import RuntimeKillSwitch

    sandbox_before = is_sandbox_enabled()
    killswitch_before = RuntimeKillSwitch.objects.count()
    counts_before = (
        Lead.objects.count(), Customer.objects.count(),
        Order.objects.count(), Payment.objects.count(),
    )

    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as wa_template, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as wa_freeform, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as vapi_call, mock.patch(
        "apps.payments.integrations.razorpay_client.create_payment_link"
    ) as razor_create, mock.patch(
        "apps.shipments.integrations.delhivery_client.create_awb"
    ) as dlv_create:
        client = auth_client(director_user)
        # exercise the full department workboard lifecycle across every transition
        aid = _make_action(client, director_user)
        _post(client, aid, "assign", {"department": "calling", "assigneeUserId": director_user.id})
        _post(client, aid, "start")
        _post(client, aid, "block", {"reason": "waiting"})
        _post(client, aid, "unblock")
        _post(client, aid, "reassign", {"department": "qa_compliance"})
        _post(client, aid, "notes", {"note": "progress"})
        _post(client, aid, "complete-internal", {"note": "done"})
        # claim path on a separate action
        aid2 = _make_action(client, director_user)
        _post(client, aid2, "claim")
        client.get(WORKBOARD)
        client.get(WB_SUMMARY)
        client.get(WB_ATTENTION)

    wa_template.assert_not_called()
    wa_freeform.assert_not_called()
    vapi_call.assert_not_called()
    razor_create.assert_not_called()
    dlv_create.assert_not_called()

    assert is_sandbox_enabled() == sandbox_before
    assert RuntimeKillSwitch.objects.count() == killswitch_before
    counts_after = (
        Lead.objects.count(), Customer.objects.count(),
        Order.objects.count(), Payment.objects.count(),
    )
    assert counts_after == counts_before
    for a in AiApprovedAction.objects.all():
        assert a.provider_action_taken is False
        assert a.provider_action_attempted is False
        assert a.external_action_taken is False
        assert a.external_action_allowed is False
