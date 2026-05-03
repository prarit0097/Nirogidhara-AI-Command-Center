"""Phase 6K — Single Internal Razorpay Test-Mode Execution Gate tests.

Asserts:

- Execution policy only allows ``razorpay.create_order`` in Phase 6K.
- Execution blocks if plan is not approved.
- Execution blocks if env flag is missing / false.
- Execution blocks if ``--confirm-test-execution`` flag is missing.
- Execution blocks if ``RAZORPAY_KEY_ID`` starts with ``rzp_live``.
- Execution blocks if plan amount != 100 paise.
- Execution blocks if plan declares ``real_customer_data_allowed=True``.
- Execution blocks if a previous successful execution exists.
- Prepare creates an execution attempt without an external call.
- Mocked successful Razorpay create_order saves a SAFE summary,
  flips ``provider_call_attempted`` and ``external_call_was_made`` to
  ``True``, but keeps ``business_mutation_was_made``,
  ``payment_link_created``, ``payment_captured``, and
  ``customer_notification_sent`` at ``False``.
- Raw secrets NEVER appear in any payload / API output.
- Rollback marks ``rollback_status=completed`` without a Razorpay
  cancel call.
- DRF endpoints require auth; POST endpoints require admin.
- Existing Phase 6J / 6I / 6H / 6G tests stay green.
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
from apps.saas.models import (
    Organization,
    RuntimeProviderExecutionAttempt,
    RuntimeProviderTestPlan,
)
from apps.saas.provider_execution import (
    archive_single_provider_execution_attempt,
    assert_execution_invariants,
    execute_single_razorpay_test_order,
    inspect_single_provider_execution_attempt,
    prepare_single_provider_execution_attempt,
    rollback_single_provider_execution_attempt,
)
from apps.saas.provider_execution_policy import (
    PHASE_6K_ALLOWED_OPERATION,
    PHASE_6K_ENV_FLAG,
    get_provider_execution_policy,
    is_phase_6k_allowed_operation,
    list_provider_execution_policies,
)
from apps.saas.provider_test_plan import (
    approve_single_provider_test_plan,
    prepare_single_provider_test_plan,
    validate_single_provider_test_plan,
)
from apps.saas.razorpay_test_execution import (
    RazorpayTestExecutionError,
    inspect_razorpay_test_env,
    mask_razorpay_key_id,
    summarize_razorpay_order_response,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FAKE_KEY_ID = "rzp_test_FAKEphase6k_DO_NOT_LEAK"
_FAKE_KEY_SECRET = "rzp_test_FAKEsecret_DO_NOT_LEAK"
_FAKE_WEBHOOK = "rzp_test_FAKEhook_DO_NOT_LEAK"


@pytest.fixture
def fake_razorpay_test_env():
    """Provide non-leaking Razorpay test envs + Phase 6K env flag."""
    overrides = {
        "RAZORPAY_KEY_ID": _FAKE_KEY_ID,
        "RAZORPAY_KEY_SECRET": _FAKE_KEY_SECRET,
        "RAZORPAY_WEBHOOK_SECRET": _FAKE_WEBHOOK,
        PHASE_6K_ENV_FLAG: "true",
    }
    with mock.patch.dict(os.environ, overrides):
        yield overrides


@pytest.fixture
def fake_razorpay_env_no_flag():
    overrides = {
        "RAZORPAY_KEY_ID": _FAKE_KEY_ID,
        "RAZORPAY_KEY_SECRET": _FAKE_KEY_SECRET,
    }
    with mock.patch.dict(os.environ, overrides):
        yield overrides


@pytest.fixture
def fake_razorpay_live_env():
    overrides = {
        "RAZORPAY_KEY_ID": "rzp_live_FAKEphase6k_DO_NOT_LEAK",
        "RAZORPAY_KEY_SECRET": _FAKE_KEY_SECRET,
        PHASE_6K_ENV_FLAG: "true",
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


def _approved_plan() -> RuntimeProviderTestPlan:
    """Phase 6J plan in ``approved_for_future_execution`` state."""
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
        reason="phase6k test fixture",
    )
    plan = validate_single_provider_test_plan(plan.plan_id)
    plan = approve_single_provider_test_plan(plan.plan_id)
    return plan


# ---------------------------------------------------------------------------
# Section A — Policy
# ---------------------------------------------------------------------------


def test_a01_policy_only_allows_razorpay_create_order():
    policy = get_provider_execution_policy("razorpay.create_order")
    assert policy is not None
    assert policy.allowed_in_phase_6k is True
    assert policy.provider_environment == "test"
    assert policy.amount_paise == 100
    assert policy.currency == "INR"
    assert policy.real_money is False
    assert policy.real_customer_data_allowed is False
    assert policy.api_execution_allowed is False
    assert policy.env_flag_required is True
    assert policy.explicit_cli_confirmation_required is True
    assert policy.frontend_execution_allowed is False
    assert policy.max_executions_per_approved_plan == 1
    assert policy.business_mutation_allowed is False
    assert policy.payment_link_creation_allowed is False
    assert policy.capture_allowed is False
    assert policy.customer_notification_allowed is False


def test_a02_phase_6k_allowed_operation_rejects_others():
    assert is_phase_6k_allowed_operation(PHASE_6K_ALLOWED_OPERATION) is True
    for other in (
        "razorpay.create_payment_link",
        "whatsapp.send_text",
        "vapi.place_call",
        "ai.smoke_test",
    ):
        assert is_phase_6k_allowed_operation(other) is False
        assert get_provider_execution_policy(other) is None


def test_a03_policy_registry_size():
    assert len(list_provider_execution_policies()) == 1


# ---------------------------------------------------------------------------
# Section B — Razorpay adapter helpers
# ---------------------------------------------------------------------------


def test_b01_mask_razorpay_key_id_does_not_leak():
    masked = mask_razorpay_key_id("rzp_test_ABCDEF1234567890")
    assert masked.startswith("rzp_test_")
    assert "ABCDEF" not in masked
    assert "1234" not in masked or "7890" in masked


def test_b02_inspect_razorpay_test_env_reports_test_mode(
    db, fake_razorpay_test_env
):
    env = inspect_razorpay_test_env()
    assert env["envFlagEnabled"] is True
    assert env["razorpayKeyIdPresent"] is True
    assert env["razorpayKeyMode"] == "test"
    assert env["isTestKey"] is True
    assert env["isLiveKey"] is False
    blob = json.dumps(env)
    assert _FAKE_KEY_ID not in blob
    assert _FAKE_KEY_SECRET not in blob


def test_b03_inspect_razorpay_test_env_flags_live_key(
    db, fake_razorpay_live_env
):
    env = inspect_razorpay_test_env()
    assert env["isLiveKey"] is True
    assert env["isTestKey"] is False


def test_b04_summarize_response_keeps_safe_keys_only():
    raw = {
        "id": "order_TEST_xyz",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_pex_demo",
        "amount_due": 100,
        "amount_paid": 0,
        "notes": {"purpose": "phase6k_internal_test_mode_only"},
    }
    summary = summarize_razorpay_order_response(raw)
    assert set(summary.keys()) == {"id", "status", "amount", "currency", "receipt"}
    assert summary["id"] == "order_TEST_xyz"
    assert summary["amount"] == 100


# ---------------------------------------------------------------------------
# Section C — Prepare + invariants
# ---------------------------------------------------------------------------


def test_c01_prepare_creates_attempt_without_external_call(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = prepare_single_provider_execution_attempt(plan.plan_id)
    assert attempt.status == RuntimeProviderExecutionAttempt.Status.PREPARED
    assert attempt.provider_call_allowed is False
    assert attempt.external_call_will_be_made is False
    assert attempt.external_call_was_made is False
    assert attempt.provider_call_attempted is False
    assert attempt.business_mutation_was_made is False
    assert attempt.payment_link_created is False
    assert attempt.payment_captured is False
    assert attempt.customer_notification_sent is False
    assert attempt.amount_paise == 100
    assert attempt.currency == "INR"
    assert assert_execution_invariants(attempt) is True


def test_c02_prepare_blocks_when_env_flag_missing(
    db, fake_razorpay_env_no_flag
):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = prepare_single_provider_execution_attempt(plan.plan_id)
    assert attempt.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    assert any(PHASE_6K_ENV_FLAG in b for b in attempt.blockers)
    assert assert_execution_invariants(attempt) is True


# ---------------------------------------------------------------------------
# Section D — Execute (mocked)
# ---------------------------------------------------------------------------


def _patch_create_order(response):
    return mock.patch(
        "apps.saas.razorpay_test_execution._create_order_via_sdk",
        return_value=response,
    )


def test_d01_execute_blocks_without_confirm_flag(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = execute_single_razorpay_test_order(plan.plan_id, confirm=False)
    assert attempt.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    assert any(
        "explicit_cli_confirmation_required" in b for b in attempt.blockers
    )
    assert attempt.provider_call_attempted is False
    assert attempt.external_call_was_made is False


def test_d02_execute_blocks_without_env_flag(db, fake_razorpay_env_no_flag):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = execute_single_razorpay_test_order(plan.plan_id, confirm=True)
    assert attempt.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    assert any(PHASE_6K_ENV_FLAG in b for b in attempt.blockers)
    assert attempt.provider_call_attempted is False


def test_d03_execute_blocks_for_live_key(db, fake_razorpay_live_env):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = execute_single_razorpay_test_order(plan.plan_id, confirm=True)
    assert attempt.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    assert any(
        "razorpay_key_id_is_live_key_refusing" in b for b in attempt.blockers
    )
    assert attempt.provider_call_attempted is False
    assert attempt.external_call_was_made is False


def test_d04_execute_blocks_when_plan_not_approved(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
    )
    plan = validate_single_provider_test_plan(plan.plan_id)
    # Skip approve — plan stays in 'validated' state.
    attempt = execute_single_razorpay_test_order(plan.plan_id, confirm=True)
    assert attempt.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    assert any(
        "approved_for_future_execution" in b for b in attempt.blockers
    )


def test_d05_execute_blocks_when_amount_not_100(db, fake_razorpay_test_env):
    _ensure_default_org()
    plan = _approved_plan()
    plan.amount_paise = 1000
    plan.save(update_fields=["amount_paise"])
    attempt = execute_single_razorpay_test_order(plan.plan_id, confirm=True)
    assert attempt.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    assert any("amount_paise_must_be_100" in b for b in attempt.blockers)


def test_d06_execute_blocks_when_real_customer_data_allowed_true(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    plan.real_customer_data_allowed = True
    plan.save(update_fields=["real_customer_data_allowed"])
    attempt = execute_single_razorpay_test_order(plan.plan_id, confirm=True)
    assert attempt.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    assert any(
        "real_customer_data_must_be_false" in b for b in attempt.blockers
    )


def test_d07_execute_blocks_duplicate_after_success(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    response = {
        "id": "order_TEST_first",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_demo",
    }
    with _patch_create_order(response):
        first = execute_single_razorpay_test_order(plan.plan_id, confirm=True)
    assert first.status == RuntimeProviderExecutionAttempt.Status.SUCCEEDED
    second = execute_single_razorpay_test_order(plan.plan_id, confirm=True)
    assert second.status == RuntimeProviderExecutionAttempt.Status.BLOCKED
    assert any(
        "plan_already_has_successful_execution" in b
        for b in second.blockers
    )


def test_d08_execute_succeeds_with_mocked_sdk(db, fake_razorpay_test_env):
    _ensure_default_org()
    plan = _approved_plan()
    response = {
        "id": "order_TEST_ok",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_ok",
    }
    with _patch_create_order(response):
        attempt = execute_single_razorpay_test_order(
            plan.plan_id, confirm=True
        )
    assert attempt.status == RuntimeProviderExecutionAttempt.Status.SUCCEEDED
    assert attempt.provider_call_attempted is True
    assert attempt.external_call_was_made is True
    assert attempt.business_mutation_was_made is False
    assert attempt.payment_link_created is False
    assert attempt.payment_captured is False
    assert attempt.customer_notification_sent is False
    assert attempt.provider_object_id == "order_TEST_ok"
    assert attempt.safe_response_summary == {
        "id": "order_TEST_ok",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_ok",
    }
    assert assert_execution_invariants(attempt) is True


def test_d09_execute_failure_records_failed_status(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    with mock.patch(
        "apps.saas.razorpay_test_execution._create_order_via_sdk",
        side_effect=RazorpayTestExecutionError("Razorpay SDK error: BadRequestError"),
    ):
        attempt = execute_single_razorpay_test_order(
            plan.plan_id, confirm=True
        )
    assert attempt.status == RuntimeProviderExecutionAttempt.Status.FAILED
    assert attempt.provider_call_attempted is True
    assert attempt.business_mutation_was_made is False
    assert attempt.payment_link_created is False
    assert attempt.payment_captured is False


def test_d10_execute_does_not_leak_raw_secrets(db, fake_razorpay_test_env):
    _ensure_default_org()
    plan = _approved_plan()
    response = {
        "id": "order_TEST_safe",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_safe",
    }
    with _patch_create_order(response):
        attempt = execute_single_razorpay_test_order(
            plan.plan_id, confirm=True
        )
    blob = json.dumps(
        {
            "safeRequest": attempt.safe_request_summary,
            "safeResponse": attempt.safe_response_summary,
            "envReadiness": attempt.env_readiness,
            "metadata": attempt.metadata,
            "blockers": attempt.blockers,
            "warnings": attempt.warnings,
        }
    )
    for fake in (_FAKE_KEY_ID, _FAKE_KEY_SECRET, _FAKE_WEBHOOK):
        assert fake not in blob
    audits = AuditEvent.objects.filter(
        kind__startswith="runtime.provider_execution."
    )
    audit_blob = json.dumps(list(audits.values_list("payload", flat=True)))
    for fake in (_FAKE_KEY_ID, _FAKE_KEY_SECRET, _FAKE_WEBHOOK):
        assert fake not in audit_blob


# ---------------------------------------------------------------------------
# Section E — Rollback / archive / inspect
# ---------------------------------------------------------------------------


def test_e01_rollback_marks_completed(db, fake_razorpay_test_env):
    _ensure_default_org()
    plan = _approved_plan()
    response = {
        "id": "order_TEST_rb",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_rb",
    }
    with _patch_create_order(response):
        attempt = execute_single_razorpay_test_order(
            plan.plan_id, confirm=True
        )
    rolled = rollback_single_provider_execution_attempt(
        attempt.execution_id, reason="cleanup"
    )
    assert rolled.status == RuntimeProviderExecutionAttempt.Status.ROLLED_BACK
    assert (
        rolled.rollback_status
        == RuntimeProviderExecutionAttempt.RollbackStatus.COMPLETED
    )
    assert rolled.business_mutation_was_made is False
    assert rolled.payment_captured is False
    assert rolled.customer_notification_sent is False


def test_e02_archive_marks_archived(db, fake_razorpay_test_env):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = prepare_single_provider_execution_attempt(plan.plan_id)
    archived = archive_single_provider_execution_attempt(
        attempt.execution_id, reason="cleanup"
    )
    assert archived.status == RuntimeProviderExecutionAttempt.Status.ARCHIVED


def test_e03_inspect_safe_to_run_only_with_clean_state(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    report = inspect_single_provider_execution_attempt()
    assert report["safeToRunPhase6KExecution"] is True
    assert report["latestApprovedPlan"]["planId"] == plan.plan_id

    response = {
        "id": "order_TEST_done",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_done",
    }
    with _patch_create_order(response):
        execute_single_razorpay_test_order(plan.plan_id, confirm=True)

    after = inspect_single_provider_execution_attempt()
    # Successful execution should immediately push the next action to
    # rollback/archive — the gate stops being "safe to run again".
    assert after["successfulExecutionCount"] == 1
    assert after["safeToRunPhase6KExecution"] is False
    assert (
        after["nextAction"]
        == "rollback_or_archive_phase_6k_execution_attempt"
    )
    assert after["businessMutationCount"] == 0


def test_e04_inspect_no_raw_secrets_in_output(db, fake_razorpay_test_env):
    _ensure_default_org()
    _approved_plan()
    report = inspect_single_provider_execution_attempt()
    blob = json.dumps(report, default=str)
    for fake in (_FAKE_KEY_ID, _FAKE_KEY_SECRET, _FAKE_WEBHOOK):
        assert fake not in blob


# ---------------------------------------------------------------------------
# Section F — Management commands
# ---------------------------------------------------------------------------


def _run(cmd: str, *args: str) -> dict:
    out = io.StringIO()
    call_command(cmd, "--json", *args, stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_f01_inspect_command_runs(db, fake_razorpay_test_env):
    _ensure_default_org()
    report = _run("inspect_single_provider_execution_gate")
    assert "safeToRunPhase6KExecution" in report


def test_f02_prepare_command_creates_attempt(db, fake_razorpay_test_env):
    _ensure_default_org()
    plan = _approved_plan()
    report = _run(
        "prepare_single_provider_execution_attempt",
        "--plan-id",
        plan.plan_id,
    )
    assert report["status"] == "prepared"
    assert report["providerCallAllowed"] is False


def test_f03_execute_command_blocks_without_confirm(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    out = io.StringIO()
    call_command(
        "execute_single_razorpay_test_order",
        "--plan-id",
        plan.plan_id,
        "--json",
        stdout=out,
    )
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert report["status"] == "blocked"
    assert report["passed"] is False


def test_f04_execute_command_with_mocked_sdk(db, fake_razorpay_test_env):
    _ensure_default_org()
    plan = _approved_plan()
    response = {
        "id": "order_TEST_cmd",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_cmd",
    }
    out = io.StringIO()
    with _patch_create_order(response):
        call_command(
            "execute_single_razorpay_test_order",
            "--plan-id",
            plan.plan_id,
            "--confirm-test-execution",
            "--json",
            stdout=out,
        )
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert report["status"] == "succeeded"
    assert report["providerCallAttempted"] is True
    assert report["externalCallWasMade"] is True
    assert report["businessMutationWasMade"] is False
    assert report["paymentCaptured"] is False
    assert report["paymentLinkCreated"] is False
    assert report["customerNotificationSent"] is False
    assert report["providerObjectId"] == "order_TEST_cmd"


def test_f05_rollback_and_archive_commands(db, fake_razorpay_test_env):
    _ensure_default_org()
    plan = _approved_plan()
    response = {
        "id": "order_TEST_rba",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_rba",
    }
    with _patch_create_order(response):
        attempt = execute_single_razorpay_test_order(
            plan.plan_id, confirm=True
        )
    report = _run(
        "rollback_single_provider_execution_attempt",
        "--execution-id",
        attempt.execution_id,
        "--reason",
        "test rollback",
    )
    assert report["status"] == "rolled_back"
    arc = _run(
        "archive_single_provider_execution_attempt",
        "--execution-id",
        attempt.execution_id,
        "--reason",
        "cleanup",
    )
    assert arc["status"] == "archived"


# ---------------------------------------------------------------------------
# Section G — DRF endpoints
# ---------------------------------------------------------------------------


def test_g01_list_endpoint_requires_auth(db, auth_client):
    _ensure_default_org()
    res = auth_client(None).get(
        reverse("saas-provider-execution-attempts")
    )
    assert res.status_code in (401, 403)


def test_g02_list_endpoint_admin_returns_shape(
    db, admin_user, auth_client, fake_razorpay_test_env
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-provider-execution-attempts"))
    assert res.status_code == 200
    body = res.json()
    assert body["runtimeSource"] == "env_config"
    assert body["perOrgRuntimeEnabled"] is False
    assert body["businessMutationCount"] == 0


def test_g03_prepare_endpoint_blocks_viewer(
    db, viewer_user, auth_client
):
    _ensure_default_org()
    res = auth_client(viewer_user).post(
        reverse("saas-provider-execution-attempts-prepare"),
        {"planId": "no-such-plan"},
    )
    assert res.status_code in (401, 403)


def test_g04_prepare_endpoint_admin_creates_attempt(
    db, admin_user, auth_client, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    res = auth_client(admin_user).post(
        reverse("saas-provider-execution-attempts-prepare"),
        {"planId": plan.plan_id},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "prepared"
    assert body["providerCallAllowed"] is False
    assert body["externalCallWillBeMade"] is False


def test_g05_list_endpoint_rejects_post(
    db, admin_user, auth_client
):
    _ensure_default_org()
    res = auth_client(admin_user).post(
        reverse("saas-provider-execution-attempts"), {}
    )
    assert res.status_code == 405


def test_g06_endpoint_outputs_no_raw_secrets(
    db, admin_user, auth_client, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    auth_client(admin_user).post(
        reverse("saas-provider-execution-attempts-prepare"),
        {"planId": plan.plan_id},
    )
    res = auth_client(admin_user).get(
        reverse("saas-provider-execution-attempts")
    )
    blob = json.dumps(res.json(), default=str)
    for fake in (_FAKE_KEY_ID, _FAKE_KEY_SECRET, _FAKE_WEBHOOK):
        assert fake not in blob
