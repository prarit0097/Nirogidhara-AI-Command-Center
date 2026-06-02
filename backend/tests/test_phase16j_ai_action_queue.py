"""Phase 16J — AI-Approved Internal Action Queue + Work Execution Bridge tests.

Coverage:
  - action queue list/summary require auth; create/apply/reject/cancel require director/admin.
  - create action only from an APPROVED suggestion (pending/rejected refused, 409).
  - apply marks status applied_internal + keeps provider/external flags false.
  - safe action creates an internal result payload (or a pilot task for a pilot plan).
  - reject / cancel work; invalid transitions → 409.
  - summary endpoint returns status counts.
  - defensive: no Razorpay/PayU/Delhivery/WhatsApp/Vapi/live-AI provider call;
    RuntimeKillSwitch + SandboxState untouched; no order/payment/customer mutation.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai_copilot.models import AiApprovedAction, AiCopilotSuggestion

ACTIONS = "/api/v1/ai-copilot/actions/"
FROM_SUGGESTION = "/api/v1/ai-copilot/actions/from-suggestion/"
SUMMARY = "/api/v1/ai-copilot/actions/summary/"


@pytest.fixture
def director_user(db):
    user = User.objects.create_user(
        username="d16j", password="d16j12345", email="d16j@nirogidhara.test"
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _suggestion(status="approved", reviewed_by=None):
    return AiCopilotSuggestion.objects.create(
        suggestion_type="director_briefing",
        source_type="manual",
        source_id="",
        title="Test suggestion",
        summary="internal summary",
        recommendation="internal recommendation",
        ai_mode="mock",
        status=status,
        reviewed_by=reviewed_by,
    )


def _create_action(client, suggestion, action_type="create_qa_review_task", **extra):
    body = {"suggestionId": suggestion.id, "actionType": action_type}
    body.update(extra)
    return client.post(FROM_SUGGESTION, body, format="json")


# --------------------------------------------------------------------------
# Auth + permissions
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_action_queue_requires_auth() -> None:
    assert APIClient().get(ACTIONS).status_code in {401, 403}


@pytest.mark.django_db
def test_summary_requires_auth() -> None:
    assert APIClient().get(SUMMARY).status_code in {401, 403}


@pytest.mark.django_db
def test_viewer_can_read_queue(viewer_user, auth_client) -> None:
    assert auth_client(viewer_user).get(ACTIONS).status_code == 200


@pytest.mark.django_db
def test_non_admin_cannot_create_action(director_user, viewer_user, auth_client) -> None:
    s = _suggestion(reviewed_by=director_user)
    res = _create_action(auth_client(viewer_user), s)
    assert res.status_code == 403


@pytest.mark.django_db
def test_non_admin_cannot_apply_action(director_user, operations_user, auth_client) -> None:
    s = _suggestion(reviewed_by=director_user)
    aid = _create_action(auth_client(director_user), s).json()["id"]
    res = auth_client(operations_user).post(f"{ACTIONS}{aid}/apply/", {}, format="json")
    assert res.status_code == 403


# --------------------------------------------------------------------------
# Create from suggestion — approval gate
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_requires_approved_suggestion(director_user, auth_client) -> None:
    client = auth_client(director_user)
    for bad in ("draft", "pending_review", "rejected"):
        s = _suggestion(status=bad)
        res = _create_action(client, s)
        assert res.status_code == 409, bad
        assert res.json()["reason"].startswith("suggestion_not_approved")


@pytest.mark.django_db
def test_create_from_approved_suggestion(director_user, auth_client) -> None:
    client = auth_client(director_user)
    s = _suggestion(reviewed_by=director_user)
    res = _create_action(client, s, title="QA review", assignedTeam="qa", priority="high")
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["status"] == "pending_internal_action"
    assert body["actionType"] == "create_qa_review_task"
    assert body["priority"] == "high"
    assert body["externalActionAllowed"] is False
    assert body["providerActionTaken"] is False


@pytest.mark.django_db
def test_create_invalid_action_type(director_user, auth_client) -> None:
    s = _suggestion(reviewed_by=director_user)
    res = auth_client(director_user).post(
        FROM_SUGGESTION, {"suggestionId": s.id, "actionType": "send_whatsapp_now"}, format="json"
    )
    assert res.status_code == 400


# --------------------------------------------------------------------------
# Apply / reject / cancel
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_apply_internal_action(director_user, auth_client) -> None:
    client = auth_client(director_user)
    s = _suggestion(reviewed_by=director_user)
    aid = _create_action(client, s).json()["id"]
    res = client.post(f"{ACTIONS}{aid}/apply/", {"note": "go"}, format="json")
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["status"] == "applied_internal"
    assert body["appliedAt"] is not None
    assert body["providerActionTaken"] is False
    assert body["externalActionTaken"] is False
    assert body["resultPayload"]["providerActionsBlocked"] is True


@pytest.mark.django_db
def test_apply_twice_is_invalid(director_user, auth_client) -> None:
    client = auth_client(director_user)
    s = _suggestion(reviewed_by=director_user)
    aid = _create_action(client, s).json()["id"]
    client.post(f"{ACTIONS}{aid}/apply/", {}, format="json")
    res = client.post(f"{ACTIONS}{aid}/apply/", {}, format="json")
    assert res.status_code == 409


@pytest.mark.django_db
def test_reject_and_cancel(director_user, auth_client) -> None:
    client = auth_client(director_user)
    s1 = _suggestion(reviewed_by=director_user)
    a1 = _create_action(client, s1).json()["id"]
    assert client.post(f"{ACTIONS}{a1}/reject/", {}, format="json").json()["status"] == "rejected"

    s2 = _suggestion(reviewed_by=director_user)
    a2 = _create_action(client, s2).json()["id"]
    assert client.post(f"{ACTIONS}{a2}/cancel/", {}, format="json").json()["status"] == "cancelled"


@pytest.mark.django_db
def test_cannot_apply_rejected_action(director_user, auth_client) -> None:
    client = auth_client(director_user)
    s = _suggestion(reviewed_by=director_user)
    aid = _create_action(client, s).json()["id"]
    client.post(f"{ACTIONS}{aid}/reject/", {}, format="json")
    res = client.post(f"{ACTIONS}{aid}/apply/", {}, format="json")
    assert res.status_code == 409


@pytest.mark.django_db
def test_summary(director_user, auth_client) -> None:
    client = auth_client(director_user)
    s = _suggestion(reviewed_by=director_user)
    aid = _create_action(client, s).json()["id"]
    client.post(f"{ACTIONS}{aid}/apply/", {}, format="json")
    body = client.get(SUMMARY).json()
    assert body["total"] >= 1
    assert body["statusCounts"]["applied_internal"] >= 1
    assert body["providerActionsLocked"] is True
    assert body["noProviderActionTaken"] is True
    assert body["phase"] == "16J"


@pytest.mark.django_db
def test_detail_and_events(director_user, auth_client) -> None:
    client = auth_client(director_user)
    s = _suggestion(reviewed_by=director_user)
    aid = _create_action(client, s).json()["id"]
    client.post(f"{ACTIONS}{aid}/apply/", {}, format="json")
    body = client.get(f"{ACTIONS}{aid}/").json()
    types = {e["eventType"] for e in body["events"]}
    assert "created" in types and "applied_internal" in types


@pytest.mark.django_db
def test_pilot_task_materialised_for_pilot_plan(director_user, auth_client) -> None:
    """A pilot_plan-sourced action materialises a real internal PilotTask."""
    from apps.pilot.models import PilotPlan, PilotTask

    client = auth_client(director_user)
    plan = PilotPlan.objects.create(
        name="J pilot", pilot_type="full_lifecycle",
        status=PilotPlan.Status.APPROVED_INTERNAL,
    )
    s = AiCopilotSuggestion.objects.create(
        suggestion_type="pilot_recommendation", source_type="pilot_plan",
        source_id=str(plan.pk), title="Pilot rec", ai_mode="mock",
        status="approved", reviewed_by=director_user,
    )
    aid = _create_action(client, s, action_type="create_pilot_task").json()["id"]
    before = PilotTask.objects.count()
    body = client.post(f"{ACTIONS}{aid}/apply/", {}, format="json").json()
    assert body["status"] == "applied_internal"
    assert body["resultPayload"]["kind"] == "pilot_task"
    assert PilotTask.objects.count() == before + 1
    task = PilotTask.objects.get(pk=body["resultPayload"]["pilotTaskId"])
    assert task.provider_actions_blocked is True


# --------------------------------------------------------------------------
# Defensive: no provider call, no business mutation, safety state untouched
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_flow_triggers_no_provider_side_effect(director_user, auth_client) -> None:
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
        for atype in ("create_calling_followup_task", "create_qa_review_task",
                      "create_customer_note", "create_order_note",
                      "create_callback_item", "create_rto_review_task",
                      "create_payment_followup_task", "create_dispatch_review_task",
                      "create_director_review_item"):
            s = _suggestion(reviewed_by=director_user)
            aid = _create_action(client, s, action_type=atype).json()["id"]
            client.post(f"{ACTIONS}{aid}/apply/", {}, format="json")

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
        assert a.external_action_taken is False
        assert a.external_action_allowed is False
