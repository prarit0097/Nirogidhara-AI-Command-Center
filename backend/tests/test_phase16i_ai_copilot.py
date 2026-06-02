"""Phase 16I — AI Copilot Enablement + Human Approval Workflow tests.

Coverage:
  - status + suggestions list require auth; generate + review require director/admin.
  - generated suggestion uses deterministic mock/sandbox AI mode by default;
    provider_call_made / external_action_allowed / external_action_taken all False.
  - lead/order/pilot suggestions store sanitized output (no full phone).
  - review approve/reject/comment/apply_internal works internally; non-admin blocked.
  - validation: unknown suggestion type / source type / review action → 400.
  - defensive: no Razorpay/PayU/Delhivery/WhatsApp/Vapi/AI provider call;
    RuntimeKillSwitch + SandboxState untouched; no order/payment/customer mutation.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai_copilot.models import AiCopilotSuggestion

STATUS = "/api/v1/ai-copilot/status/"
SUGGESTIONS = "/api/v1/ai-copilot/suggestions/"
GENERATE = "/api/v1/ai-copilot/suggestions/generate/"


@pytest.fixture
def director_user(db):
    user = User.objects.create_user(
        username="d16i", password="d16i12345", email="d16i@nirogidhara.test"
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _lead():
    from apps.crm.services import create_lead

    return create_lead(
        name="Copilot Lead", phone="+919812345678", state="MH", city="Mumbai",
        product_interest="Joint Care",
    )


def _generate(client, suggestion_type, source_type="manual", source_id="", text=""):
    body = {"suggestionType": suggestion_type, "sourceType": source_type}
    if source_id:
        body["sourceId"] = source_id
    if text:
        body["text"] = text
    return client.post(GENERATE, body, format="json")


# --------------------------------------------------------------------------
# Auth + permissions
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_status_requires_auth() -> None:
    assert APIClient().get(STATUS).status_code in {401, 403}


@pytest.mark.django_db
def test_suggestions_list_requires_auth() -> None:
    assert APIClient().get(SUGGESTIONS).status_code in {401, 403}


@pytest.mark.django_db
def test_viewer_can_read_status_and_list(viewer_user, auth_client) -> None:
    client = auth_client(viewer_user)
    assert client.get(STATUS).status_code == 200
    assert client.get(SUGGESTIONS).status_code == 200


@pytest.mark.django_db
def test_non_admin_cannot_generate(viewer_user, auth_client) -> None:
    res = _generate(auth_client(viewer_user), "director_briefing")
    assert res.status_code == 403


@pytest.mark.django_db
def test_non_admin_cannot_review(director_user, operations_user, auth_client) -> None:
    sid = _generate(auth_client(director_user), "director_briefing").json()["id"]
    res = auth_client(operations_user).post(
        f"{SUGGESTIONS}{sid}/review/", {"action": "approve"}, format="json"
    )
    assert res.status_code == 403


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_status_shape(director_user, auth_client) -> None:
    body = auth_client(director_user).get(STATUS).json()
    assert body["liveAutonomousExecutionLocked"] is True
    assert body["providerLiveActionsLocked"] is True
    assert body["humanApprovalRequired"] is True
    assert body["noProviderCallMade"] is True
    assert body["aiMode"] in {"mock", "sandbox"}
    assert body["liveProviderStatus"] in {"live_gated", "unavailable"}
    assert body["phase"] == "16I"


# --------------------------------------------------------------------------
# Generation — safe/mock + locked contract
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_generate_uses_mock_mode_and_locked_contract(director_user, auth_client) -> None:
    res = _generate(auth_client(director_user), "director_briefing")
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["aiMode"] in {"mock", "sandbox"}
    assert body["providerCallMade"] is False
    assert body["externalActionAllowed"] is False
    assert body["externalActionTaken"] is False
    assert body["status"] == "pending_review"


@pytest.mark.django_db
def test_generate_lead_summary_sanitized(director_user, auth_client) -> None:
    lead = _lead()
    res = _generate(auth_client(director_user), "lead_summary", "lead", lead.id)
    assert res.status_code == 201, res.content
    body = res.json()
    # Full phone must never appear; masked last-4 only.
    assert "9812345678" not in body["summary"]
    assert "*****5678" in body["summary"] or body["detail"]["phoneMasked"].endswith("5678")
    assert body["externalActionAllowed"] is False


@pytest.mark.django_db
def test_generate_call_priority_scores(director_user, auth_client) -> None:
    lead = _lead()
    body = _generate(auth_client(director_user), "call_priority", "lead", lead.id).json()
    assert "score" in body["detail"]
    assert 0 <= body["detail"]["score"] <= 100


@pytest.mark.django_db
def test_generate_compliance_risk_detects_terms(director_user, auth_client) -> None:
    body = _generate(
        auth_client(director_user), "compliance_risk", "manual", "",
        text="This product is a guaranteed cure with 100% no side effect.",
    ).json()
    assert "unapproved_claim_risk" in body["riskFlags"]
    assert body["detail"]["verdict"] == "review_required"


@pytest.mark.django_db
def test_generate_compliance_risk_clean(director_user, auth_client) -> None:
    body = _generate(
        auth_client(director_user), "compliance_risk", "manual", "",
        text="We will call to understand your problem and guide you.",
    ).json()
    assert body["detail"]["verdict"] == "clean"


@pytest.mark.django_db
def test_generate_whatsapp_draft_is_draft_only(director_user, auth_client) -> None:
    body = _generate(auth_client(director_user), "whatsapp_draft", "manual", "").json()
    assert "draft_only_not_sent" in body["riskFlags"]
    assert body["externalActionTaken"] is False


@pytest.mark.django_db
def test_generate_invalid_type(director_user, auth_client) -> None:
    res = _generate(auth_client(director_user), "send_whatsapp_now")
    assert res.status_code == 400


@pytest.mark.django_db
def test_generate_invalid_source_type(director_user, auth_client) -> None:
    res = auth_client(director_user).post(
        GENERATE, {"suggestionType": "lead_summary", "sourceType": "bogus"}, format="json"
    )
    assert res.status_code == 400


# --------------------------------------------------------------------------
# Review
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_review_approve_and_reject(director_user, auth_client) -> None:
    client = auth_client(director_user)
    sid1 = _generate(client, "director_briefing").json()["id"]
    approve = client.post(f"{SUGGESTIONS}{sid1}/review/", {"action": "approve", "note": "ok"}, format="json")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"
    assert approve.json()["reviewerNote"] == "ok"

    sid2 = _generate(client, "director_briefing").json()["id"]
    reject = client.post(f"{SUGGESTIONS}{sid2}/review/", {"action": "reject"}, format="json")
    assert reject.json()["status"] == "rejected"


@pytest.mark.django_db
def test_review_apply_internal_keeps_contract(director_user, auth_client) -> None:
    client = auth_client(director_user)
    sid = _generate(client, "director_briefing").json()["id"]
    body = client.post(f"{SUGGESTIONS}{sid}/review/", {"action": "apply_internal"}, format="json").json()
    assert body["status"] == "applied_internal"
    assert body["externalActionAllowed"] is False
    assert body["externalActionTaken"] is False
    assert body["providerCallMade"] is False


@pytest.mark.django_db
def test_review_invalid_action(director_user, auth_client) -> None:
    sid = _generate(auth_client(director_user), "director_briefing").json()["id"]
    res = auth_client(director_user).post(
        f"{SUGGESTIONS}{sid}/review/", {"action": "send_live"}, format="json"
    )
    assert res.status_code == 400


@pytest.mark.django_db
def test_detail_and_events(director_user, auth_client) -> None:
    client = auth_client(director_user)
    sid = _generate(client, "director_briefing").json()["id"]
    client.post(f"{SUGGESTIONS}{sid}/review/", {"action": "approve"}, format="json")
    body = client.get(f"{SUGGESTIONS}{sid}/").json()
    actions = {e["action"] for e in body["events"]}
    assert "generated" in actions and "approved" in actions


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

    lead = _lead()
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
        client.get(STATUS)
        for s_type in ("lead_summary", "call_priority", "call_script",
                       "compliance_risk", "pilot_recommendation",
                       "director_briefing", "whatsapp_draft",
                       "payment_followup_draft", "rto_rescue_draft"):
            sid = _generate(client, s_type, "lead", lead.id).json()["id"]
            client.post(f"{SUGGESTIONS}{sid}/review/", {"action": "approve"}, format="json")
            client.post(f"{SUGGESTIONS}{sid}/review/", {"action": "apply_internal"}, format="json")

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
    # Every stored suggestion keeps the locked contract.
    for s in AiCopilotSuggestion.objects.all():
        assert s.provider_call_made is False
        assert s.external_action_allowed is False
        assert s.external_action_taken is False
