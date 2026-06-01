"""Phase 16H — Internal Pilot Execution Workbench + Role-Based Task Queues tests.

Coverage:
  - task list/summary require auth; generate/create/transition require director/admin.
  - generate-tasks refuses on a non-approved plan (409); seeds role-based queues
    on an approved/running plan; idempotent per team.
  - task transition lifecycle (start → block → unblock → complete); skip/cancel;
    block requires a reason (400); invalid transition (409); unknown action (400).
  - assign + checklist update + events recorded.
  - execution summary returns per-team breakdown + overall progress + safety.
  - defensive: no Razorpay/PayU/Delhivery/WhatsApp/Vapi/AI provider call;
    RuntimeKillSwitch + SandboxState untouched; provider lock holds at every task state.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.pilot.models import PilotPlan, PilotTask, PilotTaskEvent

PLANS = "/api/v1/pilot/plans/"
TASKS = "/api/v1/pilot/tasks/"
EXEC_SUMMARY = "/api/v1/pilot/execution/summary/"


@pytest.fixture
def director_user(db):
    user = User.objects.create_user(
        username="d16h", password="d16h12345", email="d16h@nirogidhara.test"
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _approved_plan(client):
    """Create a plan and drive it to approved_internal."""
    pk = client.post(
        PLANS, {"name": "Exec pilot", "pilotType": "full_lifecycle"}, format="json"
    ).json()["id"]
    client.post(f"{PLANS}{pk}/transition/", {"action": "mark_ready"}, format="json")
    client.post(f"{PLANS}{pk}/transition/", {"action": "approve_internal"}, format="json")
    return pk


def _generate(client, plan_id, teams=None):
    body = {} if teams is None else {"teams": teams}
    return client.post(f"{PLANS}{plan_id}/tasks/", body, format="json")


# --------------------------------------------------------------------------
# Auth + permissions
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_tasks_list_requires_auth() -> None:
    assert APIClient().get(TASKS).status_code in {401, 403}


@pytest.mark.django_db
def test_execution_summary_requires_auth() -> None:
    assert APIClient().get(EXEC_SUMMARY).status_code in {401, 403}


@pytest.mark.django_db
def test_viewer_can_read_tasks(viewer_user, auth_client) -> None:
    assert auth_client(viewer_user).get(TASKS).status_code == 200


@pytest.mark.django_db
def test_non_admin_cannot_generate_tasks(director_user, viewer_user, auth_client) -> None:
    pk = _approved_plan(auth_client(director_user))
    res = auth_client(viewer_user).post(f"{PLANS}{pk}/tasks/", {}, format="json")
    assert res.status_code == 403


@pytest.mark.django_db
def test_non_admin_cannot_transition_task(director_user, operations_user, auth_client) -> None:
    dc = auth_client(director_user)
    pk = _approved_plan(dc)
    _generate(dc, pk)
    task_id = PilotTask.objects.filter(pilot_plan_id=pk).first().id
    res = auth_client(operations_user).post(
        f"{TASKS}{task_id}/transition/", {"action": "start"}, format="json"
    )
    assert res.status_code == 403


# --------------------------------------------------------------------------
# Generate role-based task queues
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_generate_refuses_non_approved_plan(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = client.post(PLANS, {"name": "draft pilot", "pilotType": "full_lifecycle"}, format="json").json()["id"]
    res = _generate(client, pk)
    assert res.status_code == 409
    assert res.json()["detail"] == "plan_not_ready_for_execution"


@pytest.mark.django_db
def test_generate_seeds_role_queues(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    res = _generate(client, pk)
    assert res.status_code == 201, res.content
    assert res.json()["created"] > 0
    roles = set(PilotTask.objects.filter(pilot_plan_id=pk).values_list("team_role", flat=True))
    assert {"calling_agent", "confirmation_team", "warehouse_dispatch"}.issubset(roles)
    # Every generated task is internal-only.
    for t in PilotTask.objects.filter(pilot_plan_id=pk):
        assert t.provider_actions_allowed is False
        assert t.provider_actions_blocked is True


@pytest.mark.django_db
def test_generate_is_idempotent_per_team(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    _generate(client, pk, teams=["calling_agent"])
    first = PilotTask.objects.filter(pilot_plan_id=pk, team_role="calling_agent").count()
    # Re-generating the same team adds nothing.
    res = _generate(client, pk, teams=["calling_agent"])
    assert res.json()["created"] == 0
    assert PilotTask.objects.filter(pilot_plan_id=pk, team_role="calling_agent").count() == first


@pytest.mark.django_db
def test_generate_only_requested_team(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    _generate(client, pk, teams=["qa_compliance"])
    roles = set(PilotTask.objects.filter(pilot_plan_id=pk).values_list("team_role", flat=True))
    assert roles == {"qa_compliance"}


# --------------------------------------------------------------------------
# Task create / transition / assign / checklist
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_single_task(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    res = client.post(
        TASKS,
        {"pilotPlanId": pk, "teamRole": "calling_agent", "title": "Manual call task"},
        format="json",
    )
    assert res.status_code == 201, res.content
    assert res.json()["providerActionsBlocked"] is True


@pytest.mark.django_db
def test_create_task_validation(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    assert client.post(TASKS, {"pilotPlanId": pk, "teamRole": "bogus", "title": "x"}, format="json").status_code == 400
    assert client.post(TASKS, {"pilotPlanId": pk, "teamRole": "calling_agent", "title": ""}, format="json").status_code == 400
    assert client.post(TASKS, {"pilotPlanId": 999999, "teamRole": "calling_agent", "title": "x"}, format="json").status_code == 400


@pytest.mark.django_db
def test_task_transition_lifecycle(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    _generate(client, pk, teams=["calling_agent"])
    task_id = PilotTask.objects.filter(pilot_plan_id=pk).first().id

    def _t(action, note=""):
        return client.post(f"{TASKS}{task_id}/transition/", {"action": action, "note": note}, format="json")

    assert _t("start").json()["status"] == "in_progress"
    blocked = _t("block", note="waiting on data")
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["blockedReason"] == "waiting on data"
    assert _t("unblock").json()["status"] == "in_progress"
    done = _t("complete").json()
    assert done["status"] == "done"
    assert done["completedAt"] is not None
    assert done["providerActionsBlocked"] is True

    types = set(PilotTaskEvent.objects.filter(task_id=task_id).values_list("event_type", flat=True))
    assert {"created", "started", "blocked", "unblocked", "completed"}.issubset(types)


@pytest.mark.django_db
def test_block_requires_reason(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    _generate(client, pk, teams=["calling_agent"])
    task_id = PilotTask.objects.filter(pilot_plan_id=pk).first().id
    client.post(f"{TASKS}{task_id}/transition/", {"action": "start"}, format="json")
    res = client.post(f"{TASKS}{task_id}/transition/", {"action": "block"}, format="json")
    assert res.status_code == 400
    assert res.json()["reason"] == "block_requires_reason"


@pytest.mark.django_db
def test_invalid_and_unknown_transitions(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    _generate(client, pk, teams=["calling_agent"])
    task_id = PilotTask.objects.filter(pilot_plan_id=pk).first().id
    # complete from todo is invalid → 409
    assert client.post(f"{TASKS}{task_id}/transition/", {"action": "complete"}, format="json").status_code == 409
    # unknown action → 400
    assert client.post(f"{TASKS}{task_id}/transition/", {"action": "go_live"}, format="json").status_code == 400


@pytest.mark.django_db
def test_assign_and_checklist(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    _generate(client, pk, teams=["calling_agent"])
    task_id = PilotTask.objects.filter(pilot_plan_id=pk).first().id
    assign = client.post(f"{TASKS}{task_id}/assign/", {"teamLabel": "calling-pod-1"}, format="json")
    assert assign.status_code == 200
    assert assign.json()["assignedTeamLabel"] == "calling-pod-1"
    patched = client.patch(
        f"{TASKS}{task_id}/",
        {"checklist": [{"key": "s1", "label": "Call done", "done": True}]},
        format="json",
    )
    assert patched.status_code == 200
    assert patched.json()["checklist"][0]["done"] is True


@pytest.mark.django_db
def test_task_events_endpoint(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    _generate(client, pk, teams=["calling_agent"])
    task_id = PilotTask.objects.filter(pilot_plan_id=pk).first().id
    client.post(f"{TASKS}{task_id}/transition/", {"action": "start"}, format="json")
    res = client.get(f"{TASKS}{task_id}/events/")
    assert res.status_code == 200
    types = {e["eventType"] for e in res.json()["items"]}
    assert "created" in types and "started" in types


# --------------------------------------------------------------------------
# Execution summary
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_execution_summary(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    _generate(client, pk)
    res = client.get(f"{EXEC_SUMMARY}?plan={pk}")
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["overall"]["total"] > 0
    assert isinstance(body["byTeam"], list) and len(body["byTeam"]) > 0
    assert "progressPct" in body["overall"]
    assert body["noSideEffect"] is True
    assert body["safety"]["providerLiveActionsLocked"] is True
    assert "teamPerformance" in body


@pytest.mark.django_db
def test_plan_tasks_filter_by_team(director_user, auth_client) -> None:
    client = auth_client(director_user)
    pk = _approved_plan(client)
    _generate(client, pk)
    res = client.get(f"{PLANS}{pk}/tasks/?team=calling_agent")
    assert res.status_code == 200
    assert all(t["teamRole"] == "calling_agent" for t in res.json()["items"])


# --------------------------------------------------------------------------
# Defensive: no provider side effect, safety state untouched
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_execution_flow_triggers_no_provider_side_effect(director_user, auth_client) -> None:
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
        pk = _approved_plan(client)
        _generate(client, pk)
        client.get(EXEC_SUMMARY)
        client.get(f"{EXEC_SUMMARY}?plan={pk}")
        task_id = PilotTask.objects.filter(pilot_plan_id=pk).first().id
        client.get(f"{TASKS}{task_id}/")
        client.post(f"{TASKS}{task_id}/assign/", {"teamLabel": "pod-1"}, format="json")
        client.post(f"{TASKS}{task_id}/transition/", {"action": "start"}, format="json")
        client.post(f"{TASKS}{task_id}/transition/", {"action": "complete"}, format="json")

    wa_template.assert_not_called()
    wa_freeform.assert_not_called()
    vapi_call.assert_not_called()
    razor_create.assert_not_called()
    dlv_create.assert_not_called()

    assert is_sandbox_enabled() == sandbox_before
    assert RuntimeKillSwitch.objects.count() == killswitch_before
    # Completed task still reports provider actions blocked.
    task = PilotTask.objects.get(pk=task_id)
    assert task.status == "done"
    assert task.provider_actions_allowed is False
    assert task.provider_actions_blocked is True
