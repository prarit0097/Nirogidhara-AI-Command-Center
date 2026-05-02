"""Phase 6J — Single Internal Provider Test Plan tests.

Asserts:

- Policy registry supports razorpay.create_order with locked Phase 6J
  invariants.
- Phase 6J implementation target is razorpay.create_order ONLY; other
  registered ops are accepted as policy entries but are not 6J targets.
- ``prepare_single_provider_test_plan`` creates a row with
  ``dryRun=True``, ``providerCallAllowed=False``,
  ``externalCallWillBeMade=False``, ``providerCallAttempted=False``,
  ``realMoney=False``, ``realCustomerDataAllowed=False``.
- Synthetic payload uses amount_paise <= max test amount and
  carries no real customer PII.
- ``validate_single_provider_test_plan`` checks env presence without
  exposing raw secrets, generates a payload hash, and never flips
  side-effect flags.
- ``approve_single_provider_test_plan`` does not enable any provider
  call.
- ``archive_single_provider_test_plan`` works.
- ``inspect_single_provider_test_plan`` reports
  ``safeToStartPhase6K=True`` only when an approved plan exists with
  zero side effects observed.
- ``providerCallAttemptedCount`` and ``externalCallMadeCount`` remain
  zero throughout.
- API GET endpoints require auth; POST endpoints require admin.
- API outputs contain no raw secrets.
"""
from __future__ import annotations

import io
import json
import os
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.saas.models import Organization, RuntimeProviderTestPlan
from apps.saas.provider_test_plan import (
    approve_single_provider_test_plan,
    archive_single_provider_test_plan,
    assert_provider_test_plan_has_no_side_effects,
    inspect_single_provider_test_plan,
    prepare_single_provider_test_plan,
    reject_single_provider_test_plan,
    validate_single_provider_test_plan,
)
from apps.saas.provider_test_plan_policy import (
    PHASE_6J_IMPLEMENTATION_TARGETS,
    POLICY_VERSION,
    get_provider_test_plan_policy,
    is_phase_6j_implementation_target,
    list_provider_test_plan_policies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_razorpay_env():
    """Provide non-leaking Razorpay test envs for the test session."""
    overrides = {
        "RAZORPAY_KEY_ID": "rzp_test_FAKEphase6j_DO_NOT_LEAK",
        "RAZORPAY_KEY_SECRET": "rzp_test_FAKEsecret_DO_NOT_LEAK",
        "RAZORPAY_WEBHOOK_SECRET": "rzp_test_FAKEhook_DO_NOT_LEAK",
    }
    with mock.patch.dict(os.environ, overrides):
        yield overrides


def _ensure_default_org() -> Organization:
    out = io.StringIO()
    call_command(
        "ensure_default_organization",
        "--json",
        "--skip-memberships",
        stdout=out,
    )
    return Organization.objects.get(code="nirogidhara")


# ---------------------------------------------------------------------------
# Section A — Policy
# ---------------------------------------------------------------------------


def test_a01_policy_registry_supports_razorpay_create_order():
    policy = get_provider_test_plan_policy("razorpay.create_order")
    assert policy is not None
    assert policy.provider_type == "razorpay"
    assert policy.provider_environment == "test"
    assert policy.real_money is False
    assert policy.real_customer_data_allowed is False
    assert policy.provider_call_allowed is False
    assert policy.external_provider_call_allowed_in_phase_6j is False
    assert policy.approval_required is True
    assert policy.live_gate_required is True
    assert policy.kill_switch_must_remain_enabled is True
    assert policy.idempotency_required is True
    assert policy.webhook_required_for_future_execution is True
    assert policy.synthetic_payload_required is True
    assert policy.safe_amount_only is True
    assert policy.max_test_amount_paise == 100
    assert policy.currency == "INR"
    assert policy.rollback_required is True
    assert policy.audit_required is True
    assert policy.implementation_target_in_phase_6j is True
    assert "phase_6k" in policy.next_phase_for_execution


def test_a02_phase_6j_only_implements_razorpay_create_order():
    assert PHASE_6J_IMPLEMENTATION_TARGETS == ("razorpay.create_order",)
    assert is_phase_6j_implementation_target("razorpay.create_order") is True
    for op in (
        "razorpay.create_payment_link",
        "whatsapp.send_text",
        "ai.smoke_test",
        "vapi.place_call",
        "delhivery.create_shipment",
        "payu.create_payment",
    ):
        assert is_phase_6j_implementation_target(op) is False


def test_a03_policy_to_dict_keeps_phase_6j_locks():
    policy = get_provider_test_plan_policy("razorpay.create_order")
    payload = policy.to_dict()
    assert payload["realMoney"] is False
    assert payload["realCustomerDataAllowed"] is False
    assert payload["providerCallAllowed"] is False
    assert payload["externalProviderCallAllowedInPhase6J"] is False
    assert payload["maxTestAmountPaise"] == 100
    assert payload["policyVersion"] == POLICY_VERSION


def test_a04_policy_registry_lists_seven_operations():
    operation_types = {p.operation_type for p in list_provider_test_plan_policies()}
    for required in (
        "razorpay.create_order",
        "razorpay.create_payment_link",
        "whatsapp.send_text",
        "ai.smoke_test",
        "vapi.place_call",
        "delhivery.create_shipment",
        "payu.create_payment",
    ):
        assert required in operation_types


# ---------------------------------------------------------------------------
# Section B — Plan preparation
# ---------------------------------------------------------------------------


def test_b01_prepare_creates_plan_with_locked_invariants(db, fake_razorpay_env):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
        reason="phase 6j test",
    )
    assert plan.plan_id.startswith("ptp_")
    assert plan.provider_type == "razorpay"
    assert plan.operation_type == "razorpay.create_order"
    assert plan.status == RuntimeProviderTestPlan.Status.PREPARED
    assert plan.dry_run is True
    assert plan.provider_call_allowed is False
    assert plan.external_call_will_be_made is False
    assert plan.external_call_was_made is False
    assert plan.provider_call_attempted is False
    assert plan.real_money is False
    assert plan.real_customer_data_allowed is False
    assert plan.runtime_source == "env_config"
    assert plan.per_org_runtime_enabled is False
    assert assert_provider_test_plan_has_no_side_effects(plan) is True


def test_b02_prepare_uses_amount_at_most_100_paise(db, fake_razorpay_env):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    assert plan.amount_paise == 100
    assert plan.currency == "INR"


def test_b03_prepare_does_not_use_real_customer_data(db, fake_razorpay_env):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    payload = plan.safe_payload_summary
    blob = json.dumps(payload)
    # No phone numbers, no email shapes, no real customer markers.
    assert "+91" not in blob
    assert "@" not in blob
    assert payload["notes"]["real_customer_data"] is False
    assert payload["notes"]["external_call"] is False


def test_b04_prepare_creates_payload_hash_and_idempotency_key(
    db, fake_razorpay_env
):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    assert plan.payload_hash != ""
    assert plan.idempotency_key.startswith("phase6j_internal_test_plan_")


def test_b05_prepare_blocks_when_razorpay_env_missing(db):
    _ensure_default_org()
    env_clean = {
        k: v
        for k, v in os.environ.items()
        if k not in {"RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"}
    }
    with mock.patch.dict(os.environ, env_clean, clear=True):
        plan = prepare_single_provider_test_plan(
            operation_type="razorpay.create_order",
        )
    assert plan.status == RuntimeProviderTestPlan.Status.BLOCKED
    assert any("RAZORPAY_KEY_ID" in b for b in plan.blockers)
    assert plan.dry_run is True
    assert plan.provider_call_allowed is False


def test_b06_prepare_unknown_operation_returns_blocked(db):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="bogus.operation",
    )
    assert plan.status == RuntimeProviderTestPlan.Status.BLOCKED
    assert any("No provider test plan policy" in b for b in plan.blockers)


def test_b07_prepare_emits_audit_row_without_raw_secrets(
    db, fake_razorpay_env
):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    audits = AuditEvent.objects.filter(
        kind="runtime.provider_test_plan.prepared"
    )
    assert audits.exists()
    blob = json.dumps(list(audits.values_list("payload", flat=True)))
    for fake in fake_razorpay_env.values():
        assert fake not in blob
    # Also ensure raw env values do not leak through any field.
    blob_full = json.dumps(
        {
            "metadata": plan.metadata,
            "envReadiness": plan.env_readiness,
            "secretRefReadiness": plan.secret_ref_readiness,
            "safePayloadSummary": plan.safe_payload_summary,
        }
    )
    for fake in fake_razorpay_env.values():
        assert fake not in blob_full


# ---------------------------------------------------------------------------
# Section C — Validate / approve / archive
# ---------------------------------------------------------------------------


def test_c01_validate_promotes_to_validated_when_clean(db, fake_razorpay_env):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    plan = validate_single_provider_test_plan(plan.plan_id)
    assert plan.status == RuntimeProviderTestPlan.Status.VALIDATED
    assert assert_provider_test_plan_has_no_side_effects(plan) is True


def test_c02_validate_blocks_when_env_missing(db):
    """validate consumes the env snapshot captured at prepare time —
    if prepare ran without Razorpay envs, the plan is already blocked
    and validate keeps it blocked rather than promoting to validated."""
    _ensure_default_org()
    env_clean = {
        k: v
        for k, v in os.environ.items()
        if k not in {"RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"}
    }
    with mock.patch.dict(os.environ, env_clean, clear=True):
        plan = prepare_single_provider_test_plan(
            operation_type="razorpay.create_order",
        )
        plan = validate_single_provider_test_plan(plan.plan_id)
    assert plan.status == RuntimeProviderTestPlan.Status.BLOCKED
    assert plan.dry_run is True
    assert plan.provider_call_allowed is False


def test_c03_approve_does_not_enable_provider_call(db, fake_razorpay_env):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    plan = validate_single_provider_test_plan(plan.plan_id)
    plan = approve_single_provider_test_plan(plan.plan_id)
    assert plan.status == (
        RuntimeProviderTestPlan.Status.APPROVED_FOR_FUTURE_EXECUTION
    )
    assert plan.provider_call_allowed is False
    assert plan.external_call_will_be_made is False
    assert plan.provider_call_attempted is False
    assert assert_provider_test_plan_has_no_side_effects(plan) is True


def test_c04_approve_refuses_unvalidated_plan(db, fake_razorpay_env):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    plan = approve_single_provider_test_plan(plan.plan_id)
    # Status must be BLOCKED (was prepared, not validated) — never
    # silently approved.
    assert plan.status == RuntimeProviderTestPlan.Status.BLOCKED


def test_c05_reject_records_status(db, fake_razorpay_env):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    plan = reject_single_provider_test_plan(plan.plan_id, reason="testing")
    assert plan.status == RuntimeProviderTestPlan.Status.REJECTED
    assert assert_provider_test_plan_has_no_side_effects(plan) is True


def test_c06_archive_records_status(db, fake_razorpay_env):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    plan = archive_single_provider_test_plan(plan.plan_id, reason="cleanup")
    assert plan.status == RuntimeProviderTestPlan.Status.ARCHIVED
    assert assert_provider_test_plan_has_no_side_effects(plan) is True


# ---------------------------------------------------------------------------
# Section D — Inspect / safeToStartPhase6K
# ---------------------------------------------------------------------------


def test_d01_inspect_safe_to_start_phase_6k_only_after_approval(
    db, fake_razorpay_env
):
    _ensure_default_org()
    report = inspect_single_provider_test_plan()
    # No plan yet → not safe.
    assert report["safeToStartPhase6K"] is False
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    plan = validate_single_provider_test_plan(plan.plan_id)
    plan = approve_single_provider_test_plan(plan.plan_id)
    report = inspect_single_provider_test_plan()
    assert report["approvedCount"] >= 1
    assert report["providerCallAttemptedCount"] == 0
    assert report["externalCallMadeCount"] == 0
    assert report["safeToStartPhase6K"] is True
    assert report["nextAction"] == (
        "ready_for_phase_6k_single_internal_razorpay_test_mode_execution_gate"
    )


def test_d02_inspect_keeps_provider_call_attempted_count_zero(
    db, fake_razorpay_env
):
    _ensure_default_org()
    for _ in range(3):
        prepare_single_provider_test_plan(
            operation_type="razorpay.create_order",
        )
    report = inspect_single_provider_test_plan()
    assert report["providerCallAttemptedCount"] == 0
    assert report["externalCallMadeCount"] == 0


def test_d03_inspect_no_raw_secrets_in_output(db, fake_razorpay_env):
    _ensure_default_org()
    prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    report = inspect_single_provider_test_plan()
    blob = json.dumps(report, default=str)
    for fake in fake_razorpay_env.values():
        assert fake not in blob


# ---------------------------------------------------------------------------
# Section E — Management commands
# ---------------------------------------------------------------------------


def _run(cmd: str, *args: str) -> dict:
    out = io.StringIO()
    call_command(cmd, "--json", *args, stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_e01_prepare_command_creates_plan(db, fake_razorpay_env):
    _ensure_default_org()
    report = _run(
        "prepare_single_provider_test_plan",
        "--provider",
        "razorpay",
        "--operation",
        "razorpay.create_order",
    )
    assert report["passed"] is True
    assert report["status"] == "prepared"
    assert report["dryRun"] is True
    assert report["providerCallAllowed"] is False
    assert report["externalCallWillBeMade"] is False


def test_e02_validate_and_approve_commands(db, fake_razorpay_env):
    _ensure_default_org()
    prepared = _run(
        "prepare_single_provider_test_plan",
        "--operation",
        "razorpay.create_order",
    )
    plan_id = prepared["planId"]
    validated = _run(
        "validate_single_provider_test_plan",
        "--plan-id",
        plan_id,
    )
    assert validated["passed"] is True
    assert validated["status"] == "validated"
    approved = _run(
        "approve_single_provider_test_plan",
        "--plan-id",
        plan_id,
        "--reason",
        "ready",
    )
    assert approved["passed"] is True
    assert approved["status"] == "approved_for_future_execution"


def test_e03_inspect_command_returns_safe_to_start_after_approval(
    db, fake_razorpay_env
):
    _ensure_default_org()
    prepared = _run(
        "prepare_single_provider_test_plan",
        "--operation",
        "razorpay.create_order",
    )
    plan_id = prepared["planId"]
    _run("validate_single_provider_test_plan", "--plan-id", plan_id)
    _run(
        "approve_single_provider_test_plan",
        "--plan-id",
        plan_id,
        "--reason",
        "ready",
    )
    report = _run("inspect_single_provider_test_plan")
    assert report["safeToStartPhase6K"] is True
    assert report["providerCallAttemptedCount"] == 0
    assert report["externalCallMadeCount"] == 0


def test_e04_archive_command_works(db, fake_razorpay_env):
    _ensure_default_org()
    prepared = _run(
        "prepare_single_provider_test_plan",
        "--operation",
        "razorpay.create_order",
    )
    plan_id = prepared["planId"]
    archived = _run(
        "archive_single_provider_test_plan",
        "--plan-id",
        plan_id,
        "--reason",
        "demo",
    )
    assert archived["passed"] is True
    assert archived["status"] == "archived"


# ---------------------------------------------------------------------------
# Section F — DRF endpoints
# ---------------------------------------------------------------------------


def test_f01_list_endpoint_requires_auth(db, auth_client):
    _ensure_default_org()
    res = auth_client(None).get(reverse("saas-provider-test-plans"))
    assert res.status_code in (401, 403)


def test_f02_list_endpoint_admin_returns_shape(
    db, admin_user, auth_client, fake_razorpay_env
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-provider-test-plans"))
    assert res.status_code == 200
    body = res.json()
    assert body["dryRun"] is True
    assert body["providerCallAllowed"] is False
    assert body["externalCallWillBeMade"] is False
    assert body["runtimeSource"] == "env_config"


def test_f03_prepare_endpoint_blocks_viewer(
    db, viewer_user, auth_client
):
    _ensure_default_org()
    client = auth_client(viewer_user)
    res = client.post(
        reverse("saas-provider-test-plans-prepare"),
        {"operationType": "razorpay.create_order"},
    )
    assert res.status_code in (401, 403)


def test_f04_prepare_endpoint_admin_creates_plan(
    db, admin_user, auth_client, fake_razorpay_env
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.post(
        reverse("saas-provider-test-plans-prepare"),
        {"operationType": "razorpay.create_order", "reason": "ui demo"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "prepared"
    assert body["dryRun"] is True
    assert body["providerCallAllowed"] is False


def test_f05_list_endpoint_rejects_post(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.post(reverse("saas-provider-test-plans"), {})
    assert res.status_code == 405


def test_f06_endpoint_outputs_no_raw_secrets(
    db, admin_user, auth_client, fake_razorpay_env
):
    _ensure_default_org()
    client = auth_client(admin_user)
    client.post(
        reverse("saas-provider-test-plans-prepare"),
        {"operationType": "razorpay.create_order"},
    )
    res = client.get(reverse("saas-provider-test-plans"))
    blob = json.dumps(res.json(), default=str)
    for fake in fake_razorpay_env.values():
        assert fake not in blob


def test_f07_endpoint_blocks_unauthenticated_post(db, auth_client):
    _ensure_default_org()
    res = auth_client(None).post(
        reverse("saas-provider-test-plans-prepare"),
        {"operationType": "razorpay.create_order"},
    )
    assert res.status_code in (401, 403)
