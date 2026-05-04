"""Phase 6N — Razorpay Webhook Business-Mutation Sandbox Plan tests.

Asserts:

- Plan service returns every required section.
- Readiness service returns ``safeToStartPhase6O`` correctly.
- All 9 Razorpay events in the mapping plan, each with
  ``mutationAllowedInPhase6N=False``.
- Env defaults stay locked off.
- Plan / readiness paths NEVER mutate Order / Payment / Shipment /
  DiscountOfferLog / Customer / RazorpayWebhookEvent.
- Plan / readiness paths NEVER call Razorpay client / WhatsApp /
  customer notification.
- API endpoints are admin-auth gated.
- POST/PATCH/DELETE return 405 on every Phase 6N endpoint.
- Output never exposes a planted raw secret or planted PII string.
- Phase 6M safety counters are honoured: any non-zero
  business-mutation / customer-notification / raw-secret /
  full-PII counter blocks ``safeToStartPhase6O``.
- Both management commands are read-only and emit JSON.
"""
from __future__ import annotations

import io
import json
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment, RazorpayWebhookEvent
from apps.saas.razorpay_business_mutation_plan import (
    PHASE_6N_FORBIDDEN_ACTIONS,
    PHASE_6N_REQUIRED_ENV_DEFAULTS,
    build_phase6n_manual_review_checklist,
    build_phase6n_rollback_plan,
    build_razorpay_event_status_mapping_plan,
    build_synthetic_order_eligibility_policy,
    get_razorpay_business_mutation_sandbox_plan,
    inspect_razorpay_business_mutation_sandbox_readiness,
    validate_phase6n_no_mutation_invariants,
)
from apps.shipments.models import Shipment


# ---------------------------------------------------------------------------
# Counter helpers
# ---------------------------------------------------------------------------


def _row_counts() -> dict[str, int]:
    return {
        "order": Order.objects.count(),
        "payment": Payment.objects.count(),
        "shipment": Shipment.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "customer": Customer.objects.count(),
        "razorpay_webhook_event": RazorpayWebhookEvent.objects.count(),
    }


# ---------------------------------------------------------------------------
# Service-layer assertions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_plan_returns_all_required_sections():
    plan = get_razorpay_business_mutation_sandbox_plan()
    expected_keys = {
        "phase",
        "policyVersion",
        "status",
        "latestCompletedPhase",
        "nextPhase",
        "businessMutationEnabled",
        "customerNotificationEnabled",
        "rawPayloadStorageEnabled",
        "safeToStartPhase6O",
        "blockers",
        "warnings",
        "nextAction",
        "summary",
        "eventMappings",
        "syntheticEligibilityPolicy",
        "manualReviewChecklist",
        "rollbackPlan",
        "safetyInvariants",
        "forbiddenActions",
        "requiredEnvDefaults",
        "auditPlan",
    }
    assert expected_keys.issubset(set(plan.keys()))
    assert plan["phase"] == "6N"
    assert plan["status"] == "planning_only"
    assert plan["latestCompletedPhase"] == "6M"
    assert plan["nextPhase"] == "6O"


@pytest.mark.django_db
def test_plan_safety_flags_all_locked_off():
    plan = get_razorpay_business_mutation_sandbox_plan()
    assert plan["businessMutationEnabled"] is False
    assert plan["customerNotificationEnabled"] is False
    assert plan["rawPayloadStorageEnabled"] is False


@pytest.mark.django_db
def test_event_mappings_cover_all_nine_required_events():
    mappings = build_razorpay_event_status_mapping_plan()
    expected_events = {
        "payment_link.paid",
        "payment.captured",
        "payment.failed",
        "payment.authorized",
        "order.paid",
        "payment_link.cancelled",
        "payment_link.expired",
        "refund.created",
        "refund.processed",
    }
    found = {row["razorpayEventName"] for row in mappings}
    assert found == expected_events
    assert len(mappings) == 9


@pytest.mark.django_db
def test_every_event_mapping_has_mutation_allowed_false():
    mappings = build_razorpay_event_status_mapping_plan()
    for row in mappings:
        assert row["mutationAllowedInPhase6N"] is False, row[
            "razorpayEventName"
        ]
        assert row["customerNotificationAllowed"] is False
        assert row["shipmentEffectAllowed"] is False
        assert row["discountEffectAllowed"] is False
        assert row["idempotencyRequired"] is True
        assert row["rollbackRequired"] is True
        assert (
            row["mutationAllowedInFuturePhase6O"]
            == "only_if_synthetic_and_approved"
        )


@pytest.mark.django_db
def test_synthetic_eligibility_policy_locks_every_required_field():
    policy = build_synthetic_order_eligibility_policy()
    required_true_keys = {
        "providerEnvironmentMustBeTest",
        "razorpayKeyModeMustBeTest",
        "eventMustComeFromPhase6MVerifiedHandler",
        "sourceEventIdRequired",
        "signatureValidRequired",
        "replayWindowValidRequired",
        "idempotencyFirstSeenRequired",
        "eventMustBeAllowlisted",
        "eventMustNotBeDenylisted",
        "orderPaymentPaymentLinkReferenceMustBeSynthetic",
        "noRealCustomerData",
        "noFullPhoneEmailAddressInPayload",
        "noCustomerNotification",
        "noShipmentCreation",
        "noDiscountMutation",
        "manualReviewBeforeMutation",
        "rollbackPathDefined",
        "auditRequiredBeforeAndAfterFutureMutation",
    }
    for key in required_true_keys:
        assert policy[key] is True, key


@pytest.mark.django_db
def test_manual_review_checklist_includes_minimum_items():
    checklist = build_phase6n_manual_review_checklist()
    keys = {entry["key"] for entry in checklist}
    expected = {
        "verifyPhase6MHandlerSafetyCountersZero",
        "verifyEnvFlagsLockedOff",
        "verifyTestKeyMode",
        "verifySyntheticReferenceOnly",
        "verifyNoFullPiiInPayload",
        "verifyDirectorSignOff",
        "verifyRollbackDryRun",
        "verifyDocsSyncedThroughPhase6N",
    }
    assert expected.issubset(keys)


@pytest.mark.django_db
def test_rollback_plan_phase_6n_cannot_execute_rollback():
    rollback = build_phase6n_rollback_plan()
    assert rollback["phase6NCanExecuteRollback"] is False
    assert rollback["rollbackOwnedByOperatorOnly"] is True
    assert rollback["rollbackNeverInvokesProviderApi"] is True
    assert len(rollback["rollbackSteps"]) >= 5
    assert len(rollback["rollbackTriggers"]) >= 3


@pytest.mark.django_db
def test_validate_no_mutation_invariants_passes_on_default_plan():
    plan = get_razorpay_business_mutation_sandbox_plan()
    result = validate_phase6n_no_mutation_invariants(plan)
    assert result["passed"] is True
    assert result["failures"] == []


@pytest.mark.django_db
def test_validate_no_mutation_invariants_catches_tampered_event():
    plan = get_razorpay_business_mutation_sandbox_plan()
    plan["eventMappings"][0]["mutationAllowedInPhase6N"] = True
    result = validate_phase6n_no_mutation_invariants(plan)
    assert result["passed"] is False
    assert any("mutation_allowed_in_phase_6n" in f for f in result["failures"])


@pytest.mark.django_db
def test_validate_no_mutation_invariants_catches_flag_flip():
    plan = get_razorpay_business_mutation_sandbox_plan()
    plan["businessMutationEnabled"] = True
    result = validate_phase6n_no_mutation_invariants(plan)
    assert result["passed"] is False
    assert any(
        f == "business_mutation_enabled_flag_must_be_false"
        for f in result["failures"]
    )


@pytest.mark.django_db
def test_required_env_defaults_are_locked_off():
    for key, expected in PHASE_6N_REQUIRED_ENV_DEFAULTS.items():
        assert expected is False, key


@pytest.mark.django_db
def test_forbidden_actions_include_critical_paths():
    expected_forbidden = {
        "call_razorpay_api",
        "create_razorpay_payment_link",
        "capture_razorpay_payment",
        "refund_razorpay_payment",
        "mutate_order_status",
        "mutate_payment_status",
        "create_or_update_shipment",
        "create_or_update_discount_offer",
        "send_whatsapp_template",
        "send_freeform_whatsapp",
        "place_vapi_call",
        "enable_business_mutation_env_flag",
        "enable_customer_notification_env_flag",
        "enable_raw_payload_storage_env_flag",
    }
    assert expected_forbidden.issubset(set(PHASE_6N_FORBIDDEN_ACTIONS))


@pytest.mark.django_db
def test_audit_plan_lists_only_safe_payload_keys():
    plan = get_razorpay_business_mutation_sandbox_plan()
    for entry in plan["auditPlan"]:
        # Never lists secret-bearing keys in payloadKeys.
        for key in entry["payloadKeys"]:
            assert "secret" not in key.lower()
            assert "token" not in key.lower()
            assert "phone" not in key.lower()
            assert "email" not in key.lower()
        # Always lists explicit "neverIncludes" guarding the obvious leaks.
        for forbidden in (
            "razorpayKeySecret",
            "razorpayWebhookSecret",
            "rawWebhookPayload",
            "customerEmail",
            "customerPhone",
            "cardNumber",
            "vpa",
            "upi",
            "bankAccount",
        ):
            assert forbidden in entry["neverIncludes"], (entry, forbidden)


# ---------------------------------------------------------------------------
# Readiness signal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_default_state_safe_to_start_phase_6o():
    readiness = inspect_razorpay_business_mutation_sandbox_readiness()
    assert readiness["phase"] == "6N"
    assert readiness["status"] == "planning_only"
    assert readiness["latestCompletedPhase"] == "6M"
    assert readiness["nextPhase"] == "6O"
    assert readiness["businessMutationEnabled"] is False
    assert readiness["customerNotificationEnabled"] is False
    assert readiness["rawPayloadStorageEnabled"] is False
    assert readiness["safeToStartPhase6O"] is True
    assert readiness["blockers"] == []
    assert readiness["nextAction"] == (
        "ready_for_phase_6o_sandbox_payment_status_mapping_and_manual_review"
    )


@pytest.mark.django_db
def test_readiness_blocks_when_business_mutation_count_nonzero():
    """A persisted RazorpayWebhookEvent with business_mutation_was_made=True
    must drag ``safeToStartPhase6O`` down regardless of env defaults."""
    RazorpayWebhookEvent.objects.create(
        provider="razorpay",
        source_event_id="evt_phase6n_test_001",
        event_name="payment.captured",
        event_id="evt_phase6n_test_001",
        payload_hash="x" * 64,
        signature_present=True,
        signature_valid=True,
        replay_window_valid=True,
        idempotency_status=RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN,
        processing_status=RazorpayWebhookEvent.ProcessingStatus.STORED,
        processing_mode=(
            RazorpayWebhookEvent.ProcessingMode.TEST_MODE_RECORD_ONLY
        ),
        # Forced safety-counter drift — proves the readiness signal blocks.
        business_mutation_was_made=True,
    )
    readiness = inspect_razorpay_business_mutation_sandbox_readiness()
    assert readiness["safeToStartPhase6O"] is False
    assert (
        "phase_6m_business_mutation_count_observed_must_be_zero"
        in readiness["blockers"]
    )


@pytest.mark.django_db
def test_readiness_blocks_when_customer_notification_count_nonzero():
    RazorpayWebhookEvent.objects.create(
        provider="razorpay",
        source_event_id="evt_phase6n_test_002",
        event_name="payment.captured",
        event_id="evt_phase6n_test_002",
        payload_hash="x" * 64,
        signature_present=True,
        signature_valid=True,
        replay_window_valid=True,
        idempotency_status=RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN,
        processing_status=RazorpayWebhookEvent.ProcessingStatus.STORED,
        processing_mode=(
            RazorpayWebhookEvent.ProcessingMode.TEST_MODE_RECORD_ONLY
        ),
        customer_notification_sent=True,
    )
    readiness = inspect_razorpay_business_mutation_sandbox_readiness()
    assert readiness["safeToStartPhase6O"] is False
    assert (
        "phase_6m_customer_notification_count_observed_must_be_zero"
        in readiness["blockers"]
    )


@pytest.mark.django_db
def test_readiness_blocks_when_raw_secret_or_pii_exposure():
    RazorpayWebhookEvent.objects.create(
        provider="razorpay",
        source_event_id="evt_phase6n_test_003",
        event_name="payment.captured",
        event_id="evt_phase6n_test_003",
        payload_hash="x" * 64,
        signature_present=True,
        signature_valid=True,
        replay_window_valid=True,
        idempotency_status=RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN,
        processing_status=RazorpayWebhookEvent.ProcessingStatus.STORED,
        processing_mode=(
            RazorpayWebhookEvent.ProcessingMode.TEST_MODE_RECORD_ONLY
        ),
        raw_secret_exposed=True,
        full_pii_exposed=True,
    )
    readiness = inspect_razorpay_business_mutation_sandbox_readiness()
    assert readiness["safeToStartPhase6O"] is False
    assert any(
        "raw_secret_exposure" in b for b in readiness["blockers"]
    )
    assert any("pii_exposure" in b for b in readiness["blockers"])


@pytest.mark.django_db
@override_settings(RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED=True)
def test_readiness_blocks_when_business_mutation_flag_flipped():
    readiness = inspect_razorpay_business_mutation_sandbox_readiness()
    assert readiness["safeToStartPhase6O"] is False
    assert (
        "phase_6m_business_mutation_flag_must_remain_disabled"
        in readiness["blockers"]
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED=True)
def test_readiness_blocks_when_customer_notify_flag_flipped():
    readiness = inspect_razorpay_business_mutation_sandbox_readiness()
    assert readiness["safeToStartPhase6O"] is False
    assert (
        "phase_6m_customer_notification_flag_must_remain_disabled"
        in readiness["blockers"]
    )


# ---------------------------------------------------------------------------
# Mutation safety — composing the plan must NEVER write business rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_plan_composition_does_not_mutate_business_tables(seeded):
    before = _row_counts()
    plan = get_razorpay_business_mutation_sandbox_plan()
    readiness = inspect_razorpay_business_mutation_sandbox_readiness()
    after = _row_counts()
    assert plan is not None
    assert readiness is not None
    assert before == after


@pytest.mark.django_db
def test_plan_composition_does_not_call_razorpay():
    """If anyone wires the planning service to a Razorpay HTTP client,
    this test catches the regression — every HTTP-client entry point we
    know about is patched and asserted not-called."""
    with mock.patch(
        "apps.payments.integrations.razorpay_client.create_payment_link"
    ) as create_link, mock.patch(
        "apps.payments.integrations.razorpay_client.capture_payment",
        create=True,
    ) as capture, mock.patch(
        "apps.payments.integrations.razorpay_client.create_refund",
        create=True,
    ) as refund:
        get_razorpay_business_mutation_sandbox_plan()
        inspect_razorpay_business_mutation_sandbox_readiness()
        create_link.assert_not_called()
        capture.assert_not_called()
        refund.assert_not_called()


@pytest.mark.django_db
def test_plan_composition_does_not_send_whatsapp_or_call():
    with mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as wa_send, mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as wa_queue, mock.patch(
        "apps.calls.integrations.vapi_client.trigger_call",
        create=True,
    ) as vapi:
        get_razorpay_business_mutation_sandbox_plan()
        inspect_razorpay_business_mutation_sandbox_readiness()
        wa_send.assert_not_called()
        wa_queue.assert_not_called()
        vapi.assert_not_called()


# ---------------------------------------------------------------------------
# Output sanity — output never carries planted secret / PII
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RAZORPAY_KEY_ID="rzp_test_PHASE6N_FAKE_KEYID_PLANTED_DO_NOT_LEAK",
    RAZORPAY_KEY_SECRET="PHASE6N_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
    RAZORPAY_WEBHOOK_SECRET="PHASE6N_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
)
def test_plan_output_does_not_expose_planted_secret():
    plan = get_razorpay_business_mutation_sandbox_plan()
    blob = json.dumps(plan, default=str)
    for planted in (
        "rzp_test_PHASE6N_FAKE_KEYID_PLANTED_DO_NOT_LEAK",
        "PHASE6N_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6N_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted


@pytest.mark.django_db
def test_readiness_output_does_not_expose_planted_pii():
    Customer.objects.create(
        name="Phase6N Planted Customer",
        phone="+919999777888",
        product_interest="weight-management",
    )
    readiness = inspect_razorpay_business_mutation_sandbox_readiness()
    blob = json.dumps(readiness, default=str)
    assert "+919999777888" not in blob
    assert "Phase6N Planted Customer" not in blob


# ---------------------------------------------------------------------------
# Endpoint guards — admin auth required + 405 on writes
# ---------------------------------------------------------------------------


_ENDPOINT_NAMES = (
    "saas-razorpay-business-mutation-sandbox-plan",
    "saas-razorpay-business-mutation-sandbox-readiness",
)


@pytest.mark.django_db
def test_plan_endpoint_requires_auth(client):
    res = client.get(
        reverse("saas-razorpay-business-mutation-sandbox-plan")
    )
    assert res.status_code in {401, 403}


@pytest.mark.django_db
def test_readiness_endpoint_requires_auth(client):
    res = client.get(
        reverse("saas-razorpay-business-mutation-sandbox-readiness")
    )
    assert res.status_code in {401, 403}


@pytest.mark.django_db
def test_plan_endpoint_blocks_viewer(viewer_user, auth_client):
    res = auth_client(viewer_user).get(
        reverse("saas-razorpay-business-mutation-sandbox-plan")
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_plan_endpoint_allows_admin(admin_user, auth_client):
    res = auth_client(admin_user).get(
        reverse("saas-razorpay-business-mutation-sandbox-plan")
    )
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6N"
    assert body["status"] == "planning_only"
    assert body["businessMutationEnabled"] is False
    assert len(body["eventMappings"]) == 9


@pytest.mark.django_db
def test_readiness_endpoint_allows_admin(admin_user, auth_client):
    res = auth_client(admin_user).get(
        reverse("saas-razorpay-business-mutation-sandbox-readiness")
    )
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6N"
    assert body["safeToStartPhase6O"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("name", _ENDPOINT_NAMES)
def test_phase_6n_endpoints_reject_non_get_methods(
    name, admin_user, auth_client
):
    url = reverse(name)
    client = auth_client(admin_user)
    for method in ("post", "patch", "put", "delete"):
        res = getattr(client, method)(url, {})
        assert res.status_code == 405, f"{method} {name} -> {res.status_code}"


# ---------------------------------------------------------------------------
# Management commands — read-only, JSON-emitting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_inspect_plan_command_emits_json():
    buf = io.StringIO()
    call_command(
        "inspect_razorpay_business_mutation_sandbox_plan",
        "--json",
        stdout=buf,
    )
    payload = json.loads(buf.getvalue())
    assert payload["phase"] == "6N"
    assert payload["status"] == "planning_only"
    assert payload["businessMutationEnabled"] is False
    assert len(payload["eventMappings"]) == 9


@pytest.mark.django_db
def test_inspect_readiness_command_emits_json():
    buf = io.StringIO()
    call_command(
        "inspect_razorpay_business_mutation_sandbox_readiness",
        "--json",
        stdout=buf,
    )
    payload = json.loads(buf.getvalue())
    assert payload["phase"] == "6N"
    assert payload["safeToStartPhase6O"] is True


@pytest.mark.django_db
def test_inspect_plan_command_does_not_mutate(seeded):
    before = _row_counts()
    audit_before = AuditEvent.objects.count()
    buf = io.StringIO()
    call_command(
        "inspect_razorpay_business_mutation_sandbox_plan",
        "--json",
        stdout=buf,
    )
    after = _row_counts()
    audit_after = AuditEvent.objects.count()
    assert before == after
    # Plan inspection is read-only; it must not emit audit events
    # (Phase 6N does not require AuditEvent emission for read-only
    # commands per Phase 6L convention).
    assert audit_before == audit_after


@pytest.mark.django_db
def test_inspect_readiness_command_does_not_mutate(seeded):
    before = _row_counts()
    audit_before = AuditEvent.objects.count()
    buf = io.StringIO()
    call_command(
        "inspect_razorpay_business_mutation_sandbox_readiness",
        "--json",
        stdout=buf,
    )
    after = _row_counts()
    audit_after = AuditEvent.objects.count()
    assert before == after
    assert audit_before == audit_after
