"""Phase 6H - Controlled Runtime Routing Live Audit Gate tests."""
from __future__ import annotations

import io
import json
from unittest import mock

from django.core.management import call_command
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.saas.live_gate import (
    approve_live_execution_request,
    create_live_execution_request,
    evaluate_live_execution_gate,
    get_or_create_default_runtime_kill_switch,
    is_runtime_kill_switch_active,
    reject_live_execution_request,
    set_runtime_kill_switch,
    summarize_live_gate_readiness,
)
from apps.saas.live_gate_policy import (
    get_live_gate_policy,
    list_live_gate_policies,
)
from apps.saas.models import Organization, RuntimeLiveExecutionRequest


def _ensure_default_org() -> Organization:
    out = io.StringIO()
    call_command(
        "ensure_default_organization",
        "--json",
        "--skip-memberships",
        stdout=out,
    )
    return Organization.objects.get(code="nirogidhara")


def test_default_global_kill_switch_is_enabled(db):
    switch = get_or_create_default_runtime_kill_switch()
    assert switch.enabled is True
    assert switch.scope == "global"
    assert is_runtime_kill_switch_active() is True


def test_policy_registry_has_required_phase6h_operations(db):
    required = {
        "whatsapp.send_text",
        "whatsapp.send_template",
        "razorpay.create_order",
        "razorpay.create_payment_link",
        "payu.create_payment",
        "delhivery.create_shipment",
        "vapi.place_call",
        "ai.customer_hinglish_chat",
        "ai.caio_compliance",
        "ai.ceo_planning",
        "ai.reports_summary",
        "ai.critical_fallback",
        "ai.smoke_test",
    }
    assert {p.operation_type for p in list_live_gate_policies()} == required
    for policy in list_live_gate_policies():
        assert policy.live_allowed_by_default is False
        assert policy.allowed_in_phase_6h is False
        assert policy.approval_required is True
        assert policy.idempotency_required is True
        assert policy.audit_required is True


def test_dry_run_preview_returns_dry_run_allowed(db):
    org = _ensure_default_org()
    decision = evaluate_live_execution_gate(
        "whatsapp.send_text", organization=org, live_requested=False
    )
    assert decision["gateDecision"] == "dry_run_allowed"
    assert decision["dryRun"] is True
    assert decision["liveExecutionAllowed"] is False
    assert decision["externalCallWillBeMade"] is False


def test_live_requested_is_blocked_by_default_and_never_external(db):
    org = _ensure_default_org()
    decision = evaluate_live_execution_gate(
        "razorpay.create_order", organization=org, live_requested=True
    )
    assert decision["gateDecision"] == "blocked_by_default"
    assert decision["liveExecutionAllowed"] is False
    assert decision["externalCallWillBeMade"] is False
    assert "phase_6h_live_execution_disabled" in decision["blockers"]


def test_whatsapp_send_blocked_without_consent_claimvault_approval(db):
    org = _ensure_default_org()
    decision = evaluate_live_execution_gate(
        "whatsapp.send_text", organization=org, live_requested=True
    )
    assert "approval_required" in decision["blockers"]
    assert "consent_verified_required" in decision["blockers"]
    assert "claim_vault_validation_required" in decision["blockers"]
    assert "caio_review_required" in decision["blockers"]
    assert decision["externalCallWillBeMade"] is False


def test_razorpay_live_request_blocked_without_approval(db):
    org = _ensure_default_org()
    decision = evaluate_live_execution_gate(
        "razorpay.create_order", organization=org, live_requested=True
    )
    assert "approval_required" in decision["blockers"]
    assert "payment_approval_required" in decision["blockers"]
    assert decision["externalCallWillBeMade"] is False


def test_deferred_and_partial_provider_config_blockers_surface(db):
    org = _ensure_default_org()
    delhivery = evaluate_live_execution_gate(
        "delhivery.create_shipment", organization=org, live_requested=True
    )
    vapi = evaluate_live_execution_gate(
        "vapi.place_call", organization=org, live_requested=True
    )
    assert "provider_deferred:delhivery" in delhivery["blockers"]
    assert any("missing_provider_env" in b for b in vapi["blockers"])
    assert delhivery["externalCallWillBeMade"] is False
    assert vapi["externalCallWillBeMade"] is False


def test_ai_customer_chat_blocked_without_caio_claimvault_human_approval(db):
    org = _ensure_default_org()
    decision = evaluate_live_execution_gate(
        "ai.customer_hinglish_chat", organization=org, live_requested=True
    )
    assert "claim_vault_validation_required" in decision["blockers"]
    assert "caio_review_required" in decision["blockers"]
    assert "human_approval_required" in decision["blockers"]
    assert decision["externalCallWillBeMade"] is False


def test_request_approval_and_approval_never_call_providers(db):
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
        row = create_live_execution_request(
            "razorpay.create_payment_link",
            organization=org,
            payload={"amount": 499, "phone": "+919999991234"},
        )
        approved = approve_live_execution_request(row.id, approver=None)
    whatsapp_send.assert_not_called()
    razorpay_link.assert_not_called()
    delhivery_awb.assert_not_called()
    vapi_call.assert_not_called()
    assert row.approval_status == "pending"
    assert approved.approval_status == "approved"
    assert approved.live_execution_allowed is False
    assert approved.external_call_will_be_made is False


def test_rejection_works(db):
    org = _ensure_default_org()
    row = create_live_execution_request(
        "razorpay.create_order", organization=org, payload={}
    )
    rejected = reject_live_execution_request(row.id, rejector=None)
    assert rejected.approval_status == "rejected"
    assert rejected.external_call_will_be_made is False
    assert "request_rejected" in rejected.blockers


def test_disabling_kill_switch_does_not_enable_external_call(db):
    org = _ensure_default_org()
    set_runtime_kill_switch(
        enabled=False,
        reason="test disable for phase 6h",
    )
    decision = evaluate_live_execution_gate(
        "razorpay.create_order",
        organization=org,
        live_requested=True,
        approval_status="approved",
        payload={
            "idempotencyKey": "phase6h-test",
            "paymentApprovalRecorded": True,
            "webhookConfigured": True,
        },
    )
    assert decision["killSwitchActive"] is False
    assert decision["liveExecutionAllowed"] is False
    assert decision["externalCallWillBeMade"] is False


def test_audit_events_are_sanitized_and_payload_hash_exists(db):
    org = _ensure_default_org()
    decision = evaluate_live_execution_gate(
        "whatsapp.send_text",
        organization=org,
        live_requested=False,
        payload={
            "phone": "+919876543210",
            "access_token": "sk-raw-token",
            "message": "safe summary",
        },
        audit_preview=True,
    )
    event = AuditEvent.objects.filter(
        kind="runtime.live_gate.previewed"
    ).latest("occurred_at")
    blob = json.dumps(event.payload)
    assert decision["payloadHash"]
    assert "sk-raw-token" not in blob
    assert "+919876543210" not in blob
    assert "+91******3210" in blob


def test_management_commands_return_safe_json(db):
    _ensure_default_org()
    out = io.StringIO()
    call_command("inspect_runtime_live_audit_gate", "--json", stdout=out)
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert report["runtimeSource"] == "env_config"
    assert report["defaultLiveExecutionAllowed"] is False

    out = io.StringIO()
    call_command(
        "preview_live_gate_decision",
        "--operation",
        "whatsapp.send_text",
        "--json",
        stdout=out,
    )
    preview = json.loads(out.getvalue().strip().splitlines()[-1])
    assert preview["gateDecision"] == "dry_run_allowed"
    assert preview["externalCallWillBeMade"] is False


def test_live_gate_api_get_auth_and_post_permission(db, admin_user, viewer_user, auth_client):
    _ensure_default_org()
    assert auth_client(None).get(reverse("saas-runtime-live-gate")).status_code in (
        401,
        403,
    )
    assert auth_client(viewer_user).get(reverse("saas-runtime-live-gate")).status_code == 200
    assert auth_client(viewer_user).post(
        reverse("saas-runtime-live-gate-preview"),
        {"operationType": "whatsapp.send_text"},
        format="json",
    ).status_code in (401, 403)

    client = auth_client(admin_user)
    res = client.post(
        reverse("saas-runtime-live-gate-preview"),
        {"operationType": "whatsapp.send_text", "liveRequested": True},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["liveExecutionAllowed"] is False
    assert body["externalCallWillBeMade"] is False


def test_live_gate_api_outputs_no_raw_secrets_or_full_phones(db, admin_user, auth_client):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.post(
        reverse("saas-runtime-live-gate-preview"),
        {
            "operationType": "whatsapp.send_text",
            "payload": {
                "phone": "+919999998888",
                "api_key": "sk-secret-never-leak",
            },
        },
        format="json",
    )
    assert res.status_code == 200
    blob = json.dumps(res.json())
    assert "sk-secret-never-leak" not in blob
    assert "+919999998888" not in blob
    assert "+91******8888" in blob


def test_summary_reports_phase6i_next_action(db):
    org = _ensure_default_org()
    summary = summarize_live_gate_readiness(org)
    assert summary["runtimeSource"] == "env_config"
    assert summary["perOrgRuntimeEnabled"] is False
    assert summary["defaultDryRun"] is True
    assert summary["defaultLiveExecutionAllowed"] is False
    assert summary["externalCallWillBeMade"] is False
    assert summary["nextAction"] in {
        "ready_for_phase_6i_single_internal_live_gate_simulation",
        "keep_live_execution_blocked",
    }
