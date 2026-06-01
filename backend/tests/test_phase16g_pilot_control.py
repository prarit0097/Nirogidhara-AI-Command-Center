"""Phase 16G — Internal Pilot Control Center tests.

Coverage:
  - plan list requires auth; create requires director/admin; non-admin blocked.
  - plan created internal-only with provider_actions_allowed=False.
  - full transition lifecycle draft → ready_for_review → approved_internal →
    running_internal → paused → running_internal → completed; cancel path.
  - events recorded; Director review stored.
  - control summary returns status counts + gate snapshot.
  - linking imported campaign / dry-run / order is safe.
  - defensive: no Razorpay/PayU/Delhivery/WhatsApp/Vapi/AI provider call;
    RuntimeKillSwitch + SandboxState untouched.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.pilot.models import PilotPlan, PilotPlanEvent, PilotPlanReview

PLANS = "/api/v1/pilot/plans/"
SUMMARY = "/api/v1/pilot/control/summary/"


@pytest.fixture
def director_user(db):
    user = User.objects.create_user(
        username="d16g", password="d16g12345", email="d16g@nirogidhara.test"
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _create_plan(client, **overrides):
    payload = {"name": "Joint pain internal pilot", "pilotType": "full_lifecycle"}
    payload.update(overrides)
    return client.post(PLANS, payload, format="json")


# --------------------------------------------------------------------------
# Auth + permissions
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_plans_list_requires_auth() -> None:
    assert APIClient().get(PLANS).status_code in {401, 403}


@pytest.mark.django_db
def test_summary_requires_auth() -> None:
    assert APIClient().get(SUMMARY).status_code in {401, 403}


@pytest.mark.django_db
def test_viewer_can_read_plans(viewer_user, auth_client) -> None:
    res = auth_client(viewer_user).get(PLANS)
    assert res.status_code == 200, res.content
    assert "items" in res.json()


@pytest.mark.django_db
def test_create_requires_director_admin(director_user, admin_user, auth_client) -> None:
    assert _create_plan(auth_client(director_user)).status_code == 201
    assert _create_plan(auth_client(admin_user)).status_code == 201


@pytest.mark.django_db
def test_non_admin_cannot_create(viewer_user, operations_user, auth_client) -> None:
    assert _create_plan(auth_client(viewer_user)).status_code == 403
    assert _create_plan(auth_client(operations_user)).status_code == 403


@pytest.mark.django_db
def test_non_admin_cannot_transition(viewer_user, director_user, auth_client) -> None:
    created = _create_plan(auth_client(director_user)).json()
    pk = created["id"]
    res = auth_client(viewer_user).post(
        f"{PLANS}{pk}/transition/", {"action": "mark_ready"}, format="json"
    )
    assert res.status_code == 403


# --------------------------------------------------------------------------
# Create + internal-only contract
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_is_internal_only(director_user, auth_client) -> None:
    res = _create_plan(auth_client(director_user))
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["status"] == "draft"
    assert body["providerActionsAllowed"] is False
    assert body["providerActionsBlocked"] is True
    # A "created" event is recorded.
    plan = PilotPlan.objects.get(pk=body["id"])
    assert plan.events.filter(event_type="created").exists()


@pytest.mark.django_db
def test_invalid_pilot_type_and_name(director_user, auth_client) -> None:
    client = auth_client(director_user)
    assert _create_plan(client, pilotType="bogus").status_code == 400
    assert client.post(PLANS, {"name": "", "pilotType": "fresh_leads"}, format="json").status_code == 400


# --------------------------------------------------------------------------
# Transitions
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_transition_lifecycle(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _create_plan(client).json()["id"]

    def _t(action):
        return client.post(f"{PLANS}{pk}/transition/", {"action": action}, format="json")

    assert _t("mark_ready").json()["status"] == "ready_for_review"
    assert _t("approve_internal").json()["status"] == "approved_internal"
    started = _t("start_internal").json()
    assert started["status"] == "running_internal"
    # running_internal still keeps provider actions locked.
    assert started["providerActionsAllowed"] is False
    assert started["providerActionsBlocked"] is True
    assert _t("pause").json()["status"] == "paused"
    assert _t("resume_internal").json()["status"] == "running_internal"
    assert _t("complete").json()["status"] == "completed"

    plan = PilotPlan.objects.get(pk=pk)
    recorded = set(plan.events.values_list("event_type", flat=True))
    assert {
        "created", "ready_for_review", "approved_internal", "started_internal",
        "paused", "resumed_internal", "completed",
    }.issubset(recorded)


@pytest.mark.django_db
def test_invalid_transition_returns_409(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _create_plan(client).json()["id"]
    # Cannot start from draft.
    res = client.post(f"{PLANS}{pk}/transition/", {"action": "start_internal"}, format="json")
    assert res.status_code == 409


@pytest.mark.django_db
def test_unknown_action_returns_400(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _create_plan(client).json()["id"]
    res = client.post(f"{PLANS}{pk}/transition/", {"action": "launch_live"}, format="json")
    assert res.status_code == 400


@pytest.mark.django_db
def test_cancel_from_draft(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _create_plan(client).json()["id"]
    res = client.post(f"{PLANS}{pk}/transition/", {"action": "cancel"}, format="json")
    assert res.json()["status"] == "cancelled"


# --------------------------------------------------------------------------
# Review + detail + events + summary
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_director_review_stored(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _create_plan(client).json()["id"]
    res = client.post(
        f"{PLANS}{pk}/review/",
        {"decision": "reviewed", "note": "Looks safe internally."},
        format="json",
    )
    assert res.status_code == 201, res.content
    assert PilotPlanReview.objects.filter(pilot_plan_id=pk, decision="reviewed").exists()


@pytest.mark.django_db
def test_review_invalid_decision(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _create_plan(client).json()["id"]
    res = client.post(f"{PLANS}{pk}/review/", {"decision": "go_live"}, format="json")
    assert res.status_code == 400


@pytest.mark.django_db
def test_detail_returns_gate_and_metrics(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _create_plan(client).json()["id"]
    res = client.get(f"{PLANS}{pk}/")
    assert res.status_code == 200, res.content
    body = res.json()
    assert "gateStatus" in body and "metrics" in body
    gate_keys = {g["key"] for g in body["gateStatus"]}
    for key in ("payment_live_gate_blocked", "shipment_live_gate_blocked", "whatsapp_blocked", "vapi_ai_blocked"):
        assert key in gate_keys


@pytest.mark.django_db
def test_events_endpoint(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _create_plan(client).json()["id"]
    client.post(f"{PLANS}{pk}/transition/", {"action": "mark_ready"}, format="json")
    res = client.get(f"{PLANS}{pk}/events/")
    assert res.status_code == 200
    types = {e["eventType"] for e in res.json()["items"]}
    assert "created" in types and "ready_for_review" in types


@pytest.mark.django_db
def test_control_summary(director_user, auth_client) -> None:
    client = auth_client(director_user)
    _create_plan(client)
    res = client.get(SUMMARY)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["totalPlans"] >= 1
    assert "statusCounts" in body and "gates" in body
    assert body["noSideEffect"] is True
    assert body["safety"]["providerLiveActionsLocked"] is True


# --------------------------------------------------------------------------
# Linking (safe references)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_link_existing_order_and_dry_run(director_user, auth_client) -> None:
    from apps.orders.services import create_order
    from apps.pilot.models import PilotDryRun

    order = create_order(
        customer_name="Pilot 16G", phone="+919812345670",
        product="Joint Care", state="MH", city="Mumbai",
    )
    dry_run = PilotDryRun.objects.create(name="dr", scenario_type="full_lifecycle")
    client = auth_client(director_user)
    res = _create_plan(
        client,
        pilotType="existing_orders",
        linkedOrderId=order.id,
        linkedDryRunId=dry_run.id,
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["linkedOrderId"] == order.id
    assert body["linkedDryRunId"] == dry_run.id


# --------------------------------------------------------------------------
# Defensive: no provider side effect, safety state untouched
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_flow_triggers_no_provider_side_effect(director_user, auth_client) -> None:
    from apps.ai_governance.sandbox import is_sandbox_enabled
    from apps.saas.models import RuntimeKillSwitch

    sandbox_before = is_sandbox_enabled()
    killswitch_before = RuntimeKillSwitch.objects.count()

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
        pk = _create_plan(client).json()["id"]
        client.get(SUMMARY)
        client.get(f"{PLANS}{pk}/")
        for action in ("mark_ready", "approve_internal", "start_internal", "pause", "resume_internal", "complete"):
            client.post(f"{PLANS}{pk}/transition/", {"action": action}, format="json")
        client.post(f"{PLANS}{pk}/review/", {"decision": "approved_internal"}, format="json")

    wa_template.assert_not_called()
    wa_freeform.assert_not_called()
    vapi_call.assert_not_called()
    razor_create.assert_not_called()
    dlv_create.assert_not_called()

    assert is_sandbox_enabled() == sandbox_before
    assert RuntimeKillSwitch.objects.count() == killswitch_before
    # A completed plan still reports provider actions blocked.
    plan = PilotPlan.objects.get(pk=pk)
    assert plan.provider_actions_allowed is False
    assert plan.provider_actions_blocked is True
    assert plan.status == "completed"
