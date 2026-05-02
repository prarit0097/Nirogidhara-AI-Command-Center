"""Phase 6I - Single Internal Live Gate Simulation tests."""
from __future__ import annotations

import io
import json
from unittest import mock

from django.core.management import call_command
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.saas.live_gate_simulation import (
    ALLOWED_SIMULATION_OPERATIONS,
    DEFAULT_SIMULATION_OPERATION,
    approve_single_internal_live_gate_simulation,
    inspect_single_internal_live_gate_simulation,
    prepare_single_internal_live_gate_simulation,
    reject_single_internal_live_gate_simulation,
    request_single_internal_live_gate_approval,
    rollback_single_internal_live_gate_simulation,
    run_single_internal_live_gate_simulation,
    serialize_live_gate_simulation,
)
from apps.saas.models import (
    Organization,
    RuntimeLiveExecutionRequest,
    RuntimeLiveGateSimulation,
)


def _ensure_default_org() -> Organization:
    out = io.StringIO()
    call_command(
        "ensure_default_organization",
        "--json",
        "--skip-memberships",
        stdout=out,
    )
    return Organization.objects.get(code="nirogidhara")


def test_runtime_live_gate_simulation_model_creation(db):
    org = _ensure_default_org()
    row = prepare_single_internal_live_gate_simulation(organization=org)

    assert row.operation_type == DEFAULT_SIMULATION_OPERATION
    assert row.provider_type == "razorpay"
    assert row.status == RuntimeLiveGateSimulation.Status.PREPARED
    assert row.dry_run is True
    assert row.live_execution_allowed is False
    assert row.external_call_will_be_made is False
    assert row.external_call_was_made is False
    assert row.provider_call_attempted is False
    assert row.kill_switch_active is True


def test_allowed_operations_and_default_operation(db):
    assert ALLOWED_SIMULATION_OPERATIONS == (
        "razorpay.create_order",
        "whatsapp.send_text",
        "ai.smoke_test",
    )
    assert DEFAULT_SIMULATION_OPERATION == "razorpay.create_order"


def test_prepare_rejects_unsupported_operation(db):
    _ensure_default_org()
    try:
        prepare_single_internal_live_gate_simulation(
            operation_type="delhivery.create_shipment"
        )
    except ValueError as exc:
        assert "Unsupported Phase 6I simulation operation" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Unsupported operation was accepted")


def test_simulation_approval_run_and_rollback_no_provider_calls(db):
    org = _ensure_default_org()
    with mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as whatsapp_send, mock.patch(
        "apps.payments.integrations.razorpay_client.create_payment_link"
    ) as razorpay_link, mock.patch(
        "apps.shipments.integrations.delhivery_client.create_awb"
    ) as delhivery_awb, mock.patch(
        "apps.calls.integrations.vapi_client.trigger_call"
    ) as vapi_call:
        row = prepare_single_internal_live_gate_simulation(organization=org)
        requested = request_single_internal_live_gate_approval(row.id)
        approved = approve_single_internal_live_gate_simulation(requested.id)
        ran = run_single_internal_live_gate_simulation(approved.id)
        rolled_back = rollback_single_internal_live_gate_simulation(ran.id)

    whatsapp_send.assert_not_called()
    razorpay_link.assert_not_called()
    delhivery_awb.assert_not_called()
    vapi_call.assert_not_called()
    assert requested.live_execution_request_id is not None
    assert approved.approval_status == RuntimeLiveExecutionRequest.ApprovalStatus.APPROVED
    assert ran.status == RuntimeLiveGateSimulation.Status.SIMULATED
    assert ran.simulation_result["passed"] is True
    assert ran.external_call_was_made is False
    assert ran.provider_call_attempted is False
    assert rolled_back.status == RuntimeLiveGateSimulation.Status.ROLLED_BACK
    assert rolled_back.external_call_was_made is False


def test_run_without_approval_is_blocked_and_safe(db):
    org = _ensure_default_org()
    row = prepare_single_internal_live_gate_simulation(organization=org)
    ran = run_single_internal_live_gate_simulation(row.id)

    assert ran.status == RuntimeLiveGateSimulation.Status.BLOCKED
    assert "approval_required_before_simulation_run" in ran.blockers
    assert ran.external_call_was_made is False
    assert ran.provider_call_attempted is False
    assert ran.simulation_result["passed"] is False


def test_rejection_works_without_external_calls(db):
    org = _ensure_default_org()
    row = prepare_single_internal_live_gate_simulation(organization=org)
    requested = request_single_internal_live_gate_approval(row.id)
    rejected = reject_single_internal_live_gate_simulation(requested.id)

    assert rejected.status == RuntimeLiveGateSimulation.Status.REJECTED
    assert rejected.approval_status == RuntimeLiveExecutionRequest.ApprovalStatus.REJECTED
    assert rejected.external_call_will_be_made is False
    assert rejected.provider_call_attempted is False


def test_serialized_simulation_has_no_raw_secret_or_full_phone(db):
    org = _ensure_default_org()
    row = prepare_single_internal_live_gate_simulation(
        operation_type="whatsapp.send_text",
        organization=org,
        payload={
            "phone": "+919876543210",
            "access_token": "sk-raw-secret",
            "message": "internal only",
        },
    )
    payload = json.dumps(serialize_live_gate_simulation(row))

    assert row.payload_hash
    assert "sk-raw-secret" not in payload
    assert "+919876543210" not in payload
    assert "+91******3210" in payload


def test_audit_events_are_created_without_raw_payload(db):
    org = _ensure_default_org()
    row = prepare_single_internal_live_gate_simulation(
        organization=org,
        payload={"api_key": "sk-never-expose"},
    )
    event = AuditEvent.objects.filter(
        kind="runtime.live_gate.simulation_prepared"
    ).latest("occurred_at")
    blob = json.dumps(event.payload)

    assert event.payload["simulation_id"] == row.id
    assert "sk-never-expose" not in blob
    assert row.payload_hash in blob


def test_inspect_and_management_commands_return_safe_json(db):
    _ensure_default_org()
    out = io.StringIO()
    call_command(
        "prepare_single_internal_live_gate_simulation",
        "--operation",
        "razorpay.create_order",
        "--json",
        stdout=out,
    )
    prepared = json.loads(out.getvalue().strip().splitlines()[-1])
    assert prepared["operationType"] == "razorpay.create_order"
    assert prepared["providerCallAttempted"] is False

    out = io.StringIO()
    call_command(
        "inspect_single_internal_live_gate_simulation",
        "--json",
        stdout=out,
    )
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert report["defaultOperation"] == "razorpay.create_order"
    assert report["providerCallAttempted"] is False
    assert report["externalCallWasMade"] is False


def test_inspect_summary_reports_latest_simulation(db):
    org = _ensure_default_org()
    row = prepare_single_internal_live_gate_simulation(organization=org)
    report = inspect_single_internal_live_gate_simulation(organization=org)

    assert report["simulationCount"] >= 1
    assert report["latestSimulation"]["id"] == row.id
    assert report["killSwitchActive"] is True
    assert report["liveExecutionAllowed"] is False


def test_simulation_api_get_auth_and_post_permission(db, admin_user, viewer_user, auth_client):
    _ensure_default_org()
    list_url = reverse("saas-runtime-live-gate-simulations")
    prepare_url = reverse("saas-runtime-live-gate-simulation-prepare")

    assert auth_client(None).get(list_url).status_code in (401, 403)
    assert auth_client(viewer_user).get(list_url).status_code == 200
    assert auth_client(viewer_user).post(
        prepare_url,
        {"operationType": "razorpay.create_order"},
        format="json",
    ).status_code in (401, 403)

    res = auth_client(admin_user).post(
        prepare_url,
        {"operationType": "razorpay.create_order"},
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["dryRun"] is True
    assert body["liveExecutionAllowed"] is False
    assert body["externalCallWillBeMade"] is False
    assert body["externalCallWasMade"] is False
    assert body["providerCallAttempted"] is False


def test_simulation_api_lifecycle_endpoints_safe(db, admin_user, auth_client):
    _ensure_default_org()
    client = auth_client(admin_user)
    created = client.post(
        reverse("saas-runtime-live-gate-simulation-prepare"),
        {"operationType": "razorpay.create_order"},
        format="json",
    ).json()
    simulation_id = created["id"]

    request_res = client.post(
        reverse(
            "saas-runtime-live-gate-simulation-request-approval",
            args=[simulation_id],
        ),
        {"reason": "test"},
        format="json",
    )
    approve_res = client.post(
        reverse("saas-runtime-live-gate-simulation-approve", args=[simulation_id]),
        {"reason": "test"},
        format="json",
    )
    run_res = client.post(
        reverse("saas-runtime-live-gate-simulation-run", args=[simulation_id]),
        {"reason": "test"},
        format="json",
    )
    rollback_res = client.post(
        reverse(
            "saas-runtime-live-gate-simulation-rollback",
            args=[simulation_id],
        ),
        {"reason": "test"},
        format="json",
    )

    assert request_res.status_code == 200
    assert approve_res.status_code == 200
    assert run_res.status_code == 200
    assert rollback_res.status_code == 200
    for response in [request_res, approve_res, run_res, rollback_res]:
        body = response.json()
        assert body["liveExecutionAllowed"] is False
        assert body["externalCallWillBeMade"] is False
        assert body["externalCallWasMade"] is False
        assert body["providerCallAttempted"] is False


def test_simulation_api_outputs_no_raw_secrets_or_full_phones(db, admin_user, auth_client):
    _ensure_default_org()
    res = auth_client(admin_user).post(
        reverse("saas-runtime-live-gate-simulation-prepare"),
        {
            "operationType": "whatsapp.send_text",
            "payload": {
                "phone": "+919999998888",
                "api_key": "sk-secret-never-leak",
            },
        },
        format="json",
    )

    assert res.status_code == 201
    blob = json.dumps(res.json())
    assert "sk-secret-never-leak" not in blob
    assert "+919999998888" not in blob
    assert "+91******8888" in blob
