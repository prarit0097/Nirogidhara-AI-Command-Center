"""Phase 16F — Controlled Internal Pilot Readiness + End-to-End Dry Run tests.

Coverage:
  - readiness endpoint requires auth + returns safety + provider gate statuses.
  - dry-run create requires director/admin; non-admin blocked; viewer read OK.
  - dry-run stores gate results + marks live provider actions blocked.
  - dry-run can reference an existing order / imported campaign.
  - review/signoff endpoint stores an internal decision; live gate stays unapproved.
  - defensive: no Razorpay/PayU/Delhivery/WhatsApp/Vapi/AI provider call,
    RuntimeKillSwitch + SandboxState untouched.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.pilot.models import PilotDecision, PilotDryRun

READINESS = "/api/v1/pilot/readiness/"
DRY_RUNS = "/api/v1/pilot/dry-runs/"


@pytest.fixture
def director_user(db):
    user = User.objects.create_user(
        username="d16f", password="d16f12345", email="d16f@nirogidhara.test"
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _order():
    from apps.orders.services import create_order

    return create_order(
        customer_name="Pilot Customer",
        phone="+919812345678",
        product="Joint Care",
        state="MH",
        city="Mumbai",
    )


# --------------------------------------------------------------------------
# Readiness
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_requires_auth() -> None:
    assert APIClient().get(READINESS).status_code in {401, 403}


@pytest.mark.django_db
def test_readiness_returns_safety_and_gates(viewer_user, auth_client) -> None:
    res = auth_client(viewer_user).get(READINESS)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["noSideEffect"] is True
    assert body["generatedByProvider"] is False
    assert "aiPaused" in body["safety"]
    assert body["safety"]["providerLiveActionsLocked"] is True
    gate_keys = {g["key"] for g in body["gates"]}
    # The lifecycle gates are present.
    for key in (
        "lead_customer_data", "order_creation", "confirmation_flow",
        "payment_readiness", "shipment_readiness", "whatsapp_automation",
        "vapi_ai_calling", "claim_vault_seed", "safety_state",
    ):
        assert key in gate_keys
    # Payment + shipment live gates are blocked by default.
    payment_gate = next(g for g in body["gates"] if g["key"] == "payment_readiness")
    shipment_gate = next(g for g in body["gates"] if g["key"] == "shipment_readiness")
    assert payment_gate["status"] == "blocked"
    assert shipment_gate["status"] == "blocked"
    assert len(body["blockedLiveActions"]) >= 4


# --------------------------------------------------------------------------
# Dry-run create + permissions
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_dry_run_create_requires_auth() -> None:
    res = APIClient().post(DRY_RUNS, {"name": "x"}, format="json")
    assert res.status_code in {401, 403}


@pytest.mark.django_db
def test_dry_run_create_non_admin_blocked(
    viewer_user, operations_user, auth_client
) -> None:
    for user in (viewer_user, operations_user):
        res = auth_client(user).post(
            DRY_RUNS, {"name": "x", "scenarioType": "full_lifecycle"}, format="json"
        )
        assert res.status_code == 403, (user.role, res.content)
    assert PilotDryRun.objects.count() == 0


@pytest.mark.django_db
def test_dry_run_list_viewer_allowed(viewer_user, auth_client) -> None:
    assert auth_client(viewer_user).get(DRY_RUNS).status_code == 200


@pytest.mark.django_db
def test_dry_run_create_stores_gate_results(director_user, auth_client) -> None:
    res = auth_client(director_user).post(
        DRY_RUNS,
        {"name": "Pilot dry-run 1", "scenarioType": "full_lifecycle"},
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["status"] in {"passed", "warning", "blocked"}
    assert isinstance(body["gateResults"], list) and len(body["gateResults"]) > 0
    assert body["providerActionsAttempted"] is False
    assert body["providerActionsBlocked"] is True
    assert len(body["blockedReasons"]) >= 4

    dr = PilotDryRun.objects.get(pk=body["id"])
    assert dr.provider_actions_blocked is True
    assert dr.provider_actions_attempted is False


@pytest.mark.django_db
def test_dry_run_invalid_scenario_rejected(director_user, auth_client) -> None:
    res = auth_client(director_user).post(
        DRY_RUNS, {"name": "x", "scenarioType": "bogus"}, format="json"
    )
    assert res.status_code == 400
    assert res.json()["field"] == "scenarioType"


@pytest.mark.django_db
def test_dry_run_blank_name_rejected(director_user, auth_client) -> None:
    res = auth_client(director_user).post(DRY_RUNS, {"name": "  "}, format="json")
    assert res.status_code == 400
    assert res.json()["field"] == "name"


@pytest.mark.django_db
def test_dry_run_can_reference_existing_order(director_user, auth_client) -> None:
    order = _order()
    res = auth_client(director_user).post(
        DRY_RUNS,
        {
            "name": "With order",
            "scenarioType": "existing_order",
            "selectedOrderId": order.id,
        },
        format="json",
    )
    assert res.status_code == 201, res.content
    dr = PilotDryRun.objects.get(pk=res.json()["id"])
    assert dr.selected_order_id == order.id


@pytest.mark.django_db
def test_dry_run_payment_logistics_scenario_focuses_provider_gates(
    director_user, auth_client
) -> None:
    res = auth_client(director_user).post(
        DRY_RUNS,
        {"name": "PL only", "scenarioType": "payment_logistics"},
        format="json",
    )
    assert res.status_code == 201, res.content
    gate_keys = {g["key"] for g in res.json()["gateResults"]}
    assert "payment_readiness" in gate_keys
    assert "shipment_readiness" in gate_keys


# --------------------------------------------------------------------------
# Detail + review
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_dry_run_detail(director_user, auth_client) -> None:
    create = auth_client(director_user).post(
        DRY_RUNS, {"name": "detail", "scenarioType": "full_lifecycle"}, format="json"
    )
    pk = create.json()["id"]
    res = auth_client(director_user).get(f"{DRY_RUNS}{pk}/")
    assert res.status_code == 200, res.content
    assert res.json()["id"] == pk
    assert "gateResults" in res.json()


@pytest.mark.django_db
def test_review_stores_decision_and_keeps_live_gate_unapproved(
    director_user, auth_client
) -> None:
    create = auth_client(director_user).post(
        DRY_RUNS, {"name": "review", "scenarioType": "full_lifecycle"}, format="json"
    )
    pk = create.json()["id"]
    res = auth_client(director_user).post(
        f"{DRY_RUNS}{pk}/review/",
        {
            "decision": "approved_for_next_phase",
            "note": "Looks ready for a controlled pilot.",
            "signoffChecklist": {
                "pilot_team_selected": True,
                # Attempt to approve the live gate — must be forced False.
                "live_provider_gate_not_approved": False,
            },
        },
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["decision"] == "approved_for_next_phase"
    # The live-provider gate is force-locked to True (= NOT approved).
    assert body["signoffChecklist"]["live_provider_gate_not_approved"] is True
    assert PilotDecision.objects.filter(dry_run_id=pk).count() == 1


@pytest.mark.django_db
def test_review_requires_admin(director_user, viewer_user, auth_client) -> None:
    create = auth_client(director_user).post(
        DRY_RUNS, {"name": "r", "scenarioType": "full_lifecycle"}, format="json"
    )
    pk = create.json()["id"]
    res = auth_client(viewer_user).post(
        f"{DRY_RUNS}{pk}/review/", {"decision": "reviewed"}, format="json"
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_review_invalid_decision_rejected(director_user, auth_client) -> None:
    create = auth_client(director_user).post(
        DRY_RUNS, {"name": "r", "scenarioType": "full_lifecycle"}, format="json"
    )
    pk = create.json()["id"]
    res = auth_client(director_user).post(
        f"{DRY_RUNS}{pk}/review/", {"decision": "bogus"}, format="json"
    )
    assert res.status_code == 400
    assert res.json()["field"] == "decision"


# --------------------------------------------------------------------------
# Defensive — no provider/business side effect, safety state untouched
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_pilot_full_flow_triggers_no_provider_side_effect(
    director_user, auth_client
) -> None:
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
        client.get(READINESS)
        create = client.post(
            DRY_RUNS, {"name": "safe", "scenarioType": "full_lifecycle"}, format="json"
        )
        pk = create.json()["id"]
        client.get(f"{DRY_RUNS}{pk}/")
        client.post(f"{DRY_RUNS}{pk}/review/", {"decision": "reviewed"}, format="json")

    wa_template.assert_not_called()
    wa_freeform.assert_not_called()
    vapi_call.assert_not_called()
    razor_create.assert_not_called()
    dlv_create.assert_not_called()

    assert is_sandbox_enabled() == sandbox_before
    assert RuntimeKillSwitch.objects.count() == killswitch_before


@pytest.mark.django_db
def test_phase16e_readiness_still_works(director_user, auth_client) -> None:
    # Phase 16E sanity — pilot must not break the integration readiness.
    res = auth_client(director_user).get(
        "/api/v1/integrations/payment-logistics/readiness/"
    )
    assert res.status_code == 200, res.content
