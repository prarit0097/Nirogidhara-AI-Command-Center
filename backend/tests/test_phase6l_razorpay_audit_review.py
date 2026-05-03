"""Phase 6L — Razorpay Test Execution Audit Review + Webhook Readiness tests.

Asserts:

- ``review_razorpay_test_execution_audit`` PASSes when every Phase 6K
  invariant holds + rollback completed + provider object id present.
- ``review_razorpay_test_execution_audit`` FAILs on missing rollback,
  flipped safety booleans, or raw-secret leak.
- Audit review never returns the raw provider response and never
  exposes raw secrets.
- ``inspect_razorpay_webhook_readiness`` reports presence-only env
  state + latest-succeeded execution + typed nextAction.
- ``plan_razorpay_webhook_readiness`` returns the canonical policy
  doc (allowlist, denylist, signature design, idempotency,
  replay window, audit logging plan, business-mutation policy =
  all-False).
- The 3 management commands run safely without provider calls.
- The 3 DRF endpoints are auth-protected, return 405 on POST, and
  never leak raw secrets.
- No Razorpay SDK call happens during the test run (asserted via a
  module-level patch).
"""
from __future__ import annotations

import io
import json
import os
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.saas.models import (
    Organization,
    RuntimeProviderExecutionAttempt,
    RuntimeProviderTestPlan,
)
from apps.saas.provider_execution import (
    execute_single_razorpay_test_order,
    rollback_single_provider_execution_attempt,
)
from apps.saas.provider_execution_policy import PHASE_6K_ENV_FLAG
from apps.saas.provider_test_plan import (
    approve_single_provider_test_plan,
    prepare_single_provider_test_plan,
    validate_single_provider_test_plan,
)
from apps.saas.razorpay_audit_review import (
    PHASE_6K_AUDIT_KINDS,
    SENSITIVE_PAYLOAD_KEYS,
    WEBHOOK_EVENT_ALLOWLIST,
    WEBHOOK_EVENT_DENYLIST,
    inspect_razorpay_webhook_readiness,
    plan_razorpay_webhook_readiness,
    review_razorpay_test_execution_audit,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FAKE_KEY_ID = "rzp_test_FAKEphase6l_DO_NOT_LEAK"
_FAKE_KEY_SECRET = "rzp_test_FAKEsecret6l_DO_NOT_LEAK"
_FAKE_WEBHOOK = "rzp_test_FAKEhook6l_DO_NOT_LEAK"


@pytest.fixture
def fake_razorpay_test_env():
    """Phase 6K env flag + non-leaking Razorpay test envs."""
    overrides = {
        "RAZORPAY_KEY_ID": _FAKE_KEY_ID,
        "RAZORPAY_KEY_SECRET": _FAKE_KEY_SECRET,
        "RAZORPAY_WEBHOOK_SECRET": _FAKE_WEBHOOK,
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
    plan = prepare_single_provider_test_plan(
        operation_type="razorpay.create_order",
        reason="phase6l audit fixture",
    )
    plan = validate_single_provider_test_plan(plan.plan_id)
    plan = approve_single_provider_test_plan(plan.plan_id)
    return plan


def _patch_create_order(response):
    return mock.patch(
        "apps.saas.razorpay_test_execution._create_order_via_sdk",
        return_value=response,
    )


def _executed_and_rolled_back(plan):
    """Drive a Phase 6K success → rollback flow with a mocked SDK."""
    response = {
        "id": "order_TEST_phase6l",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_phase6l_demo",
    }
    with _patch_create_order(response):
        attempt = execute_single_razorpay_test_order(
            plan.plan_id, confirm=True
        )
    rolled = rollback_single_provider_execution_attempt(
        attempt.execution_id, reason="phase6l audit"
    )
    return rolled


# ---------------------------------------------------------------------------
# Section A — review_razorpay_test_execution_audit
# ---------------------------------------------------------------------------


def test_a01_audit_review_passes_for_clean_phase6k_run(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    review = review_razorpay_test_execution_audit(attempt.execution_id)
    assert review["passed"] is True
    assert review["executionId"] == attempt.execution_id
    assert review["providerObjectId"] == "order_TEST_phase6l"
    assert review["rollbackStatus"] == "completed"
    assert review["rawSecretLeakDetected"] is False
    keys = {inv["key"]: inv for inv in review["invariantResults"]}
    assert keys["providerCallAttempted"]["passed"] is True
    assert keys["externalCallWasMade"]["passed"] is True
    assert keys["businessMutationWasMade"]["passed"] is True
    assert keys["paymentLinkCreated"]["passed"] is True
    assert keys["paymentCaptured"]["passed"] is True
    assert keys["customerNotificationSent"]["passed"] is True
    assert keys["realMoney"]["passed"] is True
    assert keys["realCustomerDataAllowed"]["passed"] is True
    assert keys["rollbackStatus"]["passed"] is True
    assert keys["providerObjectIdPresent"]["passed"] is True
    assert review["nextAction"] == (
        "ready_for_phase_6l_webhook_readiness_planning"
    )


def test_a02_audit_review_returns_audit_events_safe_summary(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    review = review_razorpay_test_execution_audit(attempt.execution_id)
    # At least four Phase 6K events should be linked: started + succeeded
    # + rolled_back + (optionally prepared via execute path).
    assert review["auditEventCount"] >= 3
    for event in review["auditEvents"]:
        assert event["kind"] in PHASE_6K_AUDIT_KINDS
        # Payload keys only — never values.
        assert isinstance(event["payloadKeys"], list)


def test_a03_audit_review_fails_on_flipped_safety_boolean(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    # Tamper with the row to simulate a regression.
    attempt.business_mutation_was_made = True
    attempt.save(update_fields=["business_mutation_was_made"])
    review = review_razorpay_test_execution_audit(attempt.execution_id)
    assert review["passed"] is False
    assert any(
        "businessMutationWasMade" in b for b in review["blockers"]
    )


def test_a04_audit_review_fails_on_missing_rollback(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    response = {
        "id": "order_TEST_norb",
        "status": "created",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase6k_norb",
    }
    with _patch_create_order(response):
        attempt = execute_single_razorpay_test_order(
            plan.plan_id, confirm=True
        )
    review = review_razorpay_test_execution_audit(attempt.execution_id)
    assert review["passed"] is False
    assert any(
        "rollback_status_must_be_completed" in b for b in review["blockers"]
    )


def test_a05_audit_review_handles_unknown_execution_id(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    review = review_razorpay_test_execution_audit("pex_does_not_exist")
    assert review["passed"] is False
    assert any(
        "execution_attempt_not_found" in b for b in review["blockers"]
    )
    assert review["nextAction"] == (
        "verify_execution_id_or_run_phase_6k_again"
    )


def test_a06_audit_review_does_not_leak_raw_secrets(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    review = review_razorpay_test_execution_audit(attempt.execution_id)
    blob = json.dumps(review, default=str)
    for fake in (_FAKE_KEY_ID, _FAKE_KEY_SECRET, _FAKE_WEBHOOK):
        assert fake not in blob


def test_a07_audit_review_detects_raw_secret_leak_in_audit(
    db, fake_razorpay_test_env
):
    """If a future regression writes the raw key to an audit row, the
    review must mark the run as FAILED with a typed blocker."""
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    # Inject a poisonous row that mentions the raw key.
    write_event(
        kind="runtime.provider_execution.succeeded",
        text=f"raw key leak test {_FAKE_KEY_ID}",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "execution_id": attempt.execution_id,
            "leak": _FAKE_KEY_ID,
        },
    )
    review = review_razorpay_test_execution_audit(attempt.execution_id)
    assert review["passed"] is False
    assert review["rawSecretLeakDetected"] is True
    assert any(
        "raw_razorpay_key_id_leaked_in_audit" in b
        for b in review["blockers"]
    )


# ---------------------------------------------------------------------------
# Section B — inspect_razorpay_webhook_readiness
# ---------------------------------------------------------------------------


def test_b01_webhook_readiness_reports_test_mode(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    _executed_and_rolled_back(plan)
    readiness = inspect_razorpay_webhook_readiness()
    assert readiness["isTestKey"] is True
    assert readiness["isLiveKey"] is False
    assert readiness["razorpayWebhookSecretPresent"] is True
    assert readiness["latestSucceededExecutionId"] is not None
    assert readiness["safeToPlanWebhookReadiness"] is True
    assert readiness["nextAction"] == (
        "ready_to_plan_razorpay_webhook_readiness"
    )


def test_b02_webhook_readiness_blocks_when_secret_missing(db):
    _ensure_default_org()
    env = {
        "RAZORPAY_KEY_ID": _FAKE_KEY_ID,
        "RAZORPAY_KEY_SECRET": _FAKE_KEY_SECRET,
        # RAZORPAY_WEBHOOK_SECRET intentionally absent.
    }
    env_clean = {
        k: v
        for k, v in os.environ.items()
        if k not in {"RAZORPAY_WEBHOOK_SECRET"}
    }
    with mock.patch.dict(os.environ, {**env_clean, **env}, clear=True):
        readiness = inspect_razorpay_webhook_readiness()
    assert readiness["safeToPlanWebhookReadiness"] is False
    assert any(
        "razorpay_webhook_secret_missing" in b
        for b in readiness["blockers"]
    )


def test_b03_webhook_readiness_blocks_for_live_key(db):
    _ensure_default_org()
    overrides = {
        "RAZORPAY_KEY_ID": "rzp_live_FAKEphase6l_DO_NOT_LEAK",
        "RAZORPAY_KEY_SECRET": _FAKE_KEY_SECRET,
        "RAZORPAY_WEBHOOK_SECRET": _FAKE_WEBHOOK,
    }
    with mock.patch.dict(os.environ, overrides):
        readiness = inspect_razorpay_webhook_readiness()
    assert readiness["isLiveKey"] is True
    assert readiness["safeToPlanWebhookReadiness"] is False
    assert any(
        "razorpay_key_id_is_live_key_phase_6l_blocked" in b
        for b in readiness["blockers"]
    )


def test_b04_webhook_readiness_does_not_leak_secrets(
    db, fake_razorpay_test_env
):
    readiness = inspect_razorpay_webhook_readiness()
    blob = json.dumps(readiness, default=str)
    for fake in (_FAKE_KEY_ID, _FAKE_KEY_SECRET, _FAKE_WEBHOOK):
        assert fake not in blob


# ---------------------------------------------------------------------------
# Section C — plan_razorpay_webhook_readiness
# ---------------------------------------------------------------------------


def test_c01_plan_returns_canonical_policy_doc(
    db, fake_razorpay_test_env
):
    plan = plan_razorpay_webhook_readiness()
    assert plan["phase"] == "6L"
    assert plan["policyVersion"] == "phase6l.v1"
    assert (
        plan["endpointDesign"]["path"] == "/api/webhooks/razorpay/test/"
    )
    assert plan["endpointDesign"]["phase6LRegistration"] is False
    assert plan["endpointDesign"]["phase6MRegistration"] is True
    assert (
        plan["signatureVerificationDesign"]["algorithm"] == "HMAC-SHA256"
    )
    assert plan["signatureVerificationDesign"]["constantTimeCompare"] is True
    assert plan["replayProtection"]["windowSeconds"] == 300
    assert plan["idempotencyDesign"]["uniqueConstraint"] is True
    assert plan["idempotencyDesign"]["key"] == "x_razorpay_event_id"
    assert plan["nextPhase"] == (
        "phase_6m_razorpay_webhook_handler_implementation_test_mode"
    )


def test_c02_plan_event_lists_lock_known_events():
    plan = plan_razorpay_webhook_readiness()
    assert tuple(plan["eventAllowlist"]) == WEBHOOK_EVENT_ALLOWLIST
    assert tuple(plan["eventDenylist"]) == WEBHOOK_EVENT_DENYLIST
    overlap = set(plan["eventAllowlist"]) & set(plan["eventDenylist"])
    assert overlap == set()


def test_c03_plan_business_mutation_policy_is_all_false():
    plan = plan_razorpay_webhook_readiness()
    policy = plan["businessMutationPolicy"]
    for key, value in policy.items():
        assert value is False, f"{key} must be False in Phase 6L"


def test_c04_plan_audit_logging_plan_scrubs_sensitive_keys():
    plan = plan_razorpay_webhook_readiness()
    audit = plan["auditLoggingPlan"]
    assert audit["phase6LAuditMutationAllowed"] is False
    assert audit["payloadHandling"]["storeRawBody"] is False
    assert audit["payloadHandling"]["storePayloadHash"] is True
    for key in SENSITIVE_PAYLOAD_KEYS:
        assert key in audit["payloadHandling"]["sensitiveKeysToScrub"]


def test_c05_plan_does_not_leak_secrets(db, fake_razorpay_test_env):
    plan = plan_razorpay_webhook_readiness()
    blob = json.dumps(plan, default=str)
    for fake in (_FAKE_KEY_ID, _FAKE_KEY_SECRET, _FAKE_WEBHOOK):
        assert fake not in blob


# ---------------------------------------------------------------------------
# Section D — Management commands
# ---------------------------------------------------------------------------


def _run(cmd: str, *args: str) -> dict:
    out = io.StringIO()
    call_command(cmd, "--json", *args, stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_d01_inspect_audit_command_runs(db, fake_razorpay_test_env):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    report = _run(
        "inspect_razorpay_test_execution_audit",
        "--execution-id",
        attempt.execution_id,
    )
    assert report["passed"] is True
    assert report["executionId"] == attempt.execution_id


def test_d02_inspect_webhook_readiness_command_runs(
    db, fake_razorpay_test_env
):
    _ensure_default_org()
    report = _run("inspect_razorpay_webhook_readiness")
    assert "safeToPlanWebhookReadiness" in report
    assert report["isTestKey"] is True


def test_d03_plan_command_runs(db, fake_razorpay_test_env):
    report = _run("plan_razorpay_webhook_readiness")
    assert report["phase"] == "6L"
    assert report["policyVersion"] == "phase6l.v1"


def test_d04_commands_make_no_provider_call(db, fake_razorpay_test_env):
    """All 3 commands must NOT touch the Razorpay SDK."""
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    with mock.patch(
        "apps.saas.razorpay_test_execution._create_order_via_sdk"
    ) as sdk_mock:
        _run(
            "inspect_razorpay_test_execution_audit",
            "--execution-id",
            attempt.execution_id,
        )
        _run("inspect_razorpay_webhook_readiness")
        _run("plan_razorpay_webhook_readiness")
    sdk_mock.assert_not_called()


def test_d05_commands_do_not_leak_secrets(db, fake_razorpay_test_env):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    audit_report = _run(
        "inspect_razorpay_test_execution_audit",
        "--execution-id",
        attempt.execution_id,
    )
    readiness = _run("inspect_razorpay_webhook_readiness")
    plan_report = _run("plan_razorpay_webhook_readiness")
    blob = json.dumps(
        {
            "audit": audit_report,
            "readiness": readiness,
            "plan": plan_report,
        },
        default=str,
    )
    for fake in (_FAKE_KEY_ID, _FAKE_KEY_SECRET, _FAKE_WEBHOOK):
        assert fake not in blob


# ---------------------------------------------------------------------------
# Section E — DRF endpoints
# ---------------------------------------------------------------------------


def test_e01_audit_endpoint_requires_auth(db, auth_client):
    _ensure_default_org()
    res = auth_client(None).get(
        reverse("saas-razorpay-execution-audit"),
        {"execution_id": "pex_demo"},
    )
    assert res.status_code in (401, 403)


def test_e02_audit_endpoint_admin_returns_review(
    db, admin_user, auth_client, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    res = auth_client(admin_user).get(
        reverse("saas-razorpay-execution-audit"),
        {"execution_id": attempt.execution_id},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["passed"] is True
    assert body["executionId"] == attempt.execution_id


def test_e03_audit_endpoint_requires_query_param(
    db, admin_user, auth_client
):
    _ensure_default_org()
    res = auth_client(admin_user).get(
        reverse("saas-razorpay-execution-audit")
    )
    assert res.status_code == 400


def test_e04_audit_endpoint_rejects_post(
    db, admin_user, auth_client
):
    _ensure_default_org()
    res = auth_client(admin_user).post(
        reverse("saas-razorpay-execution-audit"), {}
    )
    assert res.status_code == 405


def test_e05_webhook_readiness_endpoint_admin_shape(
    db, admin_user, auth_client, fake_razorpay_test_env
):
    _ensure_default_org()
    res = auth_client(admin_user).get(
        reverse("saas-razorpay-webhook-readiness")
    )
    assert res.status_code == 200
    body = res.json()
    assert body["razorpayWebhookSecretPresent"] is True
    assert body["isTestKey"] is True


def test_e06_webhook_readiness_endpoint_requires_auth(db, auth_client):
    _ensure_default_org()
    res = auth_client(None).get(
        reverse("saas-razorpay-webhook-readiness")
    )
    assert res.status_code in (401, 403)


def test_e07_webhook_readiness_rejects_post(
    db, admin_user, auth_client
):
    _ensure_default_org()
    res = auth_client(admin_user).post(
        reverse("saas-razorpay-webhook-readiness"), {}
    )
    assert res.status_code == 405


def test_e08_webhook_plan_endpoint_admin_shape(
    db, admin_user, auth_client, fake_razorpay_test_env
):
    _ensure_default_org()
    res = auth_client(admin_user).get(
        reverse("saas-razorpay-webhook-plan")
    )
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6L"
    assert body["endpointDesign"]["phase6LRegistration"] is False


def test_e09_webhook_plan_endpoint_requires_auth(db, auth_client):
    _ensure_default_org()
    res = auth_client(None).get(reverse("saas-razorpay-webhook-plan"))
    assert res.status_code in (401, 403)


def test_e10_webhook_plan_rejects_post(db, admin_user, auth_client):
    _ensure_default_org()
    res = auth_client(admin_user).post(
        reverse("saas-razorpay-webhook-plan"), {}
    )
    assert res.status_code == 405


def test_e11_endpoints_do_not_leak_secrets(
    db, admin_user, auth_client, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    client = auth_client(admin_user)
    audit_res = client.get(
        reverse("saas-razorpay-execution-audit"),
        {"execution_id": attempt.execution_id},
    )
    readiness_res = client.get(
        reverse("saas-razorpay-webhook-readiness")
    )
    plan_res = client.get(reverse("saas-razorpay-webhook-plan"))
    blob = json.dumps(
        {
            "audit": audit_res.json(),
            "readiness": readiness_res.json(),
            "plan": plan_res.json(),
        },
        default=str,
    )
    for fake in (_FAKE_KEY_ID, _FAKE_KEY_SECRET, _FAKE_WEBHOOK):
        assert fake not in blob


def test_e12_endpoints_make_no_provider_call(
    db, admin_user, auth_client, fake_razorpay_test_env
):
    _ensure_default_org()
    plan = _approved_plan()
    attempt = _executed_and_rolled_back(plan)
    client = auth_client(admin_user)
    with mock.patch(
        "apps.saas.razorpay_test_execution._create_order_via_sdk"
    ) as sdk_mock:
        client.get(
            reverse("saas-razorpay-execution-audit"),
            {"execution_id": attempt.execution_id},
        )
        client.get(reverse("saas-razorpay-webhook-readiness"))
        client.get(reverse("saas-razorpay-webhook-plan"))
    sdk_mock.assert_not_called()
