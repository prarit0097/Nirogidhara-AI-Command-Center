"""Phase 6Q — Payment → Order Workflow Safety Gate tests.

Asserts the 28 spec requirements:

1.  Readiness command returns Phase 6Q shape.
2.  Readiness endpoint returns Phase 6Q shape.
3.  Contract includes all 9 events.
4.  Every contract row says ``workflowMutationAllowedInPhase6Q=False``.
5.  Prepare gate fails when ``RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=False``.
6.  Prepare gate succeeds with env override + eligible Phase 6P attempt.
7.  Prepare gate fails if Phase 6P attempt not executed.
8.  Prepare gate fails if Phase 6P attempt has ``real_order_mutation_was_made=True``.
9.  Prepare gate fails if Phase 6P attempt has ``real_payment_mutation_was_made=True``.
10. Prepare gate fails if Phase 6P attempt has ``customer_notification_sent=True``.
11. Prepare gate fails if Phase 6P attempt has ``provider_call_attempted=True``.
12. Approve changes gate status only.
13. Reject changes gate status only.
14. Archive changes gate status only.
15. No Order mutation.
16. No Payment mutation.
17. No Shipment mutation.
18. No DiscountOfferLog mutation.
19. No Customer / Lead mutation.
20. No Razorpay API call.
21. No WhatsApp / customer notification.
22. No raw secret in command/API output.
23. No planted PII in command/API output.
24. API endpoints are read-only / auth-protected.
25. POST/PATCH/DELETE return 405 where not allowed.
26. Audit events are safe + contain no secrets.
27. ``safeToStartPhase6R=False`` until at least one gate is approved.
28. Phase 6R not implemented.
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
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import (
    Payment,
    RazorpayPaymentOrderWorkflowGate,
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)
from apps.payments.razorpay_payment_order_workflow_gate import (
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_REJECTED,
    PHASE_6Q_FORBIDDEN_ACTIONS,
    PHASE_6Q_MAX_SAFE_AMOUNT_PAISE,
    approve_phase6q_payment_order_workflow_gate,
    archive_phase6q_payment_order_workflow_gate,
    build_phase6q_payment_order_workflow_contract,
    inspect_phase6q_payment_order_workflow_gate_readiness,
    prepare_phase6q_payment_order_workflow_gate,
    preview_phase6q_payment_order_workflow_gate,
    reject_phase6q_payment_order_workflow_gate,
)
from apps.payments.razorpay_sandbox_paid_status_mutation import (
    execute_phase6p_paid_status_mutation_attempt,
    rollback_phase6p_paid_status_mutation_attempt,
)
from apps.payments.razorpay_sandbox_status_mapping import (
    approve_phase6o_sandbox_status_review,
    prepare_phase6o_sandbox_status_review,
)
from apps.shipments.models import Shipment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_counts() -> dict[str, int]:
    return {
        "order": Order.objects.count(),
        "payment": Payment.objects.count(),
        "shipment": Shipment.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "customer": Customer.objects.count(),
        "lead": Lead.objects.count(),
        "razorpay_event": RazorpayWebhookEvent.objects.count(),
        "phase6o_review": RazorpaySandboxStatusReview.objects.count(),
        "phase6p_attempt": RazorpaySandboxPaidStatusMutationAttempt.objects.count(),
        "phase6p_ledger": RazorpaySandboxPaidStatusLedger.objects.count(),
        "phase6q_gate": RazorpayPaymentOrderWorkflowGate.objects.count(),
    }


def _make_safe_event(
    *,
    event_name: str = "payment.captured",
    source_event_id: str = "evt_phase6q_001",
    amount_paise: int = 100,
) -> RazorpayWebhookEvent:
    return RazorpayWebhookEvent.objects.create(
        provider="razorpay",
        source_event_id=source_event_id,
        event_id=source_event_id,
        event_name=event_name,
        environment=RazorpayWebhookEvent.Environment.TEST,
        signature_present=True,
        signature_valid=True,
        replay_window_valid=True,
        idempotency_status=RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN,
        processing_status=RazorpayWebhookEvent.ProcessingStatus.STORED,
        processing_mode=(
            RazorpayWebhookEvent.ProcessingMode.TEST_MODE_RECORD_ONLY
        ),
        provider_order_id="order_phase6q_synthetic",
        provider_payment_id="pay_phase6q_synthetic",
        amount_paise=amount_paise,
        currency="INR",
        payload_hash="x" * 64,
        scrubbed_keys=[],
        business_mutation_was_made=False,
        customer_notification_sent=False,
        raw_secret_exposed=False,
        full_pii_exposed=False,
    )


def _make_full_phase6p_lifecycle(
    *,
    source_event_id: str = "evt_phase6q_full",
    rollback: bool = True,
) -> RazorpaySandboxPaidStatusMutationAttempt:
    """Walk a webhook event through Phase 6O approve + Phase 6P
    execute + (optional) rollback. Returns the executed attempt.
    """
    with override_settings(
        RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True,
        RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True,
    ):
        event = _make_safe_event(source_event_id=source_event_id)
        prepared = prepare_phase6o_sandbox_status_review(event.pk)
        approve_phase6o_sandbox_status_review(
            prepared["review"]["id"], reviewed_by=None, reason="ok"
        )
        review_id = prepared["review"]["id"]
        executed = execute_phase6p_paid_status_mutation_attempt(
            review_id, confirmed=True, director_signoff_text="Director ok"
        )
        attempt_id = executed["attempt"]["id"]
        if rollback:
            rollback_phase6p_paid_status_mutation_attempt(
                attempt_id, confirmed=True, reason="rehearsal"
            )
    return RazorpaySandboxPaidStatusMutationAttempt.objects.get(pk=attempt_id)


# ---------------------------------------------------------------------------
# Contract (#3, #4)
# ---------------------------------------------------------------------------


def test_contract_covers_all_nine_events() -> None:
    rows = build_phase6q_payment_order_workflow_contract()
    assert len(rows) == 9
    assert {r["razorpayEventName"] for r in rows} == {
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


def test_every_contract_row_locks_workflow_mutation_off() -> None:
    for row in build_phase6q_payment_order_workflow_contract():
        assert row["workflowMutationAllowedInPhase6Q"] is False, row[
            "razorpayEventName"
        ]
        assert row["customerNotificationAllowed"] is False
        assert row["providerCallAllowed"] is False
        assert row["shipmentEffectAllowed"] is False
        assert row["discountEffectAllowed"] is False
        assert row["idempotencyRequired"] is True
        assert row["rollbackRequired"] is True


# ---------------------------------------------------------------------------
# Readiness (#1, #2, #27)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_selector_returns_phase6q_shape() -> None:
    report = inspect_phase6q_payment_order_workflow_gate_readiness()
    assert report["phase"] == "6Q"
    assert report["status"] == "audit_gate_only"
    assert report["latestCompletedPhase"] == "6P"
    assert report["nextPhase"] == "6R"
    assert report["razorpayPaymentOrderWorkflowGateEnabled"] is False
    assert report["frontendCanExecute"] is False
    assert report["apiEndpointCanExecute"] is False
    assert report["apiEndpointCanApprove"] is False
    assert report["executionPath"] == "cli_only"
    assert len(report["workflowContract"]) == 9
    assert report["safeToStartPhase6R"] is False


@pytest.mark.django_db
def test_readiness_command_emits_json() -> None:
    buf = io.StringIO()
    call_command(
        "inspect_razorpay_payment_order_workflow_gate_readiness",
        "--json",
        "--no-audit",
        stdout=buf,
    )
    body = json.loads(buf.getvalue())
    assert body["phase"] == "6Q"
    assert body["status"] == "audit_gate_only"


# ---------------------------------------------------------------------------
# Prepare gating (#5, #6, #7, #8, #9, #10, #11)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_blocked_when_env_flag_off() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_no_flag"
    )
    out = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    assert out["created"] is False
    assert any(
        "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED" in b
        for b in out["blockers"]
    )
    assert RazorpayPaymentOrderWorkflowGate.objects.count() == 0


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_prepare_succeeds_with_eligible_phase6p_attempt() -> None:
    attempt = _make_full_phase6p_lifecycle(source_event_id="evt_phase6q_ok")
    out = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    assert out["created"] is True
    assert out["gate"]["workflowMutationAllowedInPhase6Q"] is False
    assert out["gate"]["realOrderMutationWasMade"] is False
    assert out["gate"]["realPaymentMutationWasMade"] is False
    assert RazorpayPaymentOrderWorkflowGate.objects.count() == 1


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_prepare_blocked_when_phase6p_attempt_not_executed() -> None:
    """Phase 6O approved but Phase 6P not yet executed → no
    `executed_at` on attempt → reject."""
    with override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True):
        event = _make_safe_event(source_event_id="evt_phase6q_no_exec")
        prepared = prepare_phase6o_sandbox_status_review(event.pk)
        approve_phase6o_sandbox_status_review(
            prepared["review"]["id"], reviewed_by=None, reason="ok"
        )
    review = RazorpaySandboxStatusReview.objects.get(
        pk=prepared["review"]["id"]
    )
    # Manually create a PREPARED but not executed Phase 6P attempt.
    attempt = RazorpaySandboxPaidStatusMutationAttempt.objects.create(
        review=review,
        razorpay_webhook_event=event,
        source_event_id=event.source_event_id,
        event_name=event.event_name,
        status=RazorpaySandboxPaidStatusMutationAttempt.Status.PREPARED,
        requested_action=(
            RazorpaySandboxPaidStatusMutationAttempt.RequestedAction.APPLY_SANDBOX_STATUS
        ),
        proposed_payment_status="captured",
        proposed_order_effect="payment_verified_candidate",
        idempotency_key="phase6q-test-not-executed",
    )
    out = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    assert out["created"] is False
    assert any(
        "phase6p_attempt_status_prepared_not_eligible" in b
        or "phase6p_attempt_must_have_been_executed" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_prepare_blocked_if_phase6p_real_order_mutation_was_made() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_real_order"
    )
    attempt.real_order_mutation_was_made = True
    attempt.save(update_fields=["real_order_mutation_was_made"])
    out = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    assert out["created"] is False
    assert "phase6p_attempt_real_order_mutation_was_made" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_prepare_blocked_if_phase6p_real_payment_mutation_was_made() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_real_payment"
    )
    attempt.real_payment_mutation_was_made = True
    attempt.save(update_fields=["real_payment_mutation_was_made"])
    out = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    assert out["created"] is False
    assert "phase6p_attempt_real_payment_mutation_was_made" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_prepare_blocked_if_phase6p_customer_notification_sent() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_notify"
    )
    attempt.customer_notification_sent = True
    attempt.save(update_fields=["customer_notification_sent"])
    out = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    assert out["created"] is False
    assert "phase6p_attempt_customer_notification_sent" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_prepare_blocked_if_phase6p_provider_call_attempted() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_provider"
    )
    attempt.provider_call_attempted = True
    attempt.save(update_fields=["provider_call_attempted"])
    out = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    assert out["created"] is False
    assert "phase6p_attempt_provider_call_attempted" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_prepare_is_idempotent() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_idem"
    )
    first = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    second = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert first["gate"]["id"] == second["gate"]["id"]


# ---------------------------------------------------------------------------
# Approve / reject / archive (#12, #13, #14)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_approve_sets_status_to_approved_for_future_phase6r_only() -> None:
    attempt = _make_full_phase6p_lifecycle(source_event_id="evt_phase6q_app")
    prepared = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    out = approve_phase6q_payment_order_workflow_gate(
        prepared["gate"]["id"],
        reviewed_by=None,
        reason="Reviewer signoff for sandbox proof",
    )
    assert out["ok"] is True
    assert (
        out["gate"]["status"]
        == RazorpayPaymentOrderWorkflowGate.Status.APPROVED_FOR_FUTURE_PHASE6R
    )
    assert "phase_6r" in out["nextAction"].lower()


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_approve_requires_reason() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_no_reason"
    )
    prepared = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    out = approve_phase6q_payment_order_workflow_gate(
        prepared["gate"]["id"], reviewed_by=None, reason=""
    )
    assert out["ok"] is False
    assert "manual_review_reason_must_be_non_empty" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_reject_sets_status_to_rejected() -> None:
    attempt = _make_full_phase6p_lifecycle(source_event_id="evt_phase6q_rej")
    prepared = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    out = reject_phase6q_payment_order_workflow_gate(
        prepared["gate"]["id"], reviewed_by=None, reason="not yet"
    )
    assert out["ok"] is True
    assert (
        out["gate"]["status"]
        == RazorpayPaymentOrderWorkflowGate.Status.REJECTED
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_archive_sets_status_to_archived() -> None:
    attempt = _make_full_phase6p_lifecycle(source_event_id="evt_phase6q_arc")
    prepared = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    out = archive_phase6q_payment_order_workflow_gate(
        prepared["gate"]["id"], archived_by=None, reason="close"
    )
    assert out["ok"] is True
    assert (
        out["gate"]["status"]
        == RazorpayPaymentOrderWorkflowGate.Status.ARCHIVED
    )


# ---------------------------------------------------------------------------
# Mutation safety (#15-#19, #20, #21)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_full_lifecycle_does_not_mutate_real_business_tables(seeded) -> None:
    attempt = _make_full_phase6p_lifecycle(source_event_id="evt_phase6q_safe")
    before = _row_counts()

    prepared = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    after_prepare = _row_counts()

    approve_phase6q_payment_order_workflow_gate(
        prepared["gate"]["id"], reason="sign-off ok"
    )
    after_approve = _row_counts()

    reject_phase6q_payment_order_workflow_gate(
        prepared["gate"]["id"], reason="changed mind"
    )
    after_reject = _row_counts()

    archive_phase6q_payment_order_workflow_gate(
        prepared["gate"]["id"], reason="close"
    )
    after_archive = _row_counts()

    for after in (after_prepare, after_approve, after_reject, after_archive):
        assert after["order"] == before["order"]
        assert after["payment"] == before["payment"]
        assert after["shipment"] == before["shipment"]
        assert after["discount_offer_log"] == before["discount_offer_log"]
        assert after["customer"] == before["customer"]
        assert after["lead"] == before["lead"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_full_lifecycle_never_calls_provider_or_whatsapp() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_no_calls"
    )
    with mock.patch(
        "apps.payments.integrations.razorpay_client.create_payment_link"
    ) as create_link, mock.patch(
        "apps.payments.integrations.razorpay_client.capture_payment",
        create=True,
    ) as capture, mock.patch(
        "apps.payments.integrations.razorpay_client.create_refund",
        create=True,
    ) as refund, mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as queue_template, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as send_text, mock.patch(
        "apps.calls.integrations.vapi_client.trigger_call",
        create=True,
    ) as vapi:
        prepared = prepare_phase6q_payment_order_workflow_gate(
            source_attempt_id=attempt.pk
        )
        approve_phase6q_payment_order_workflow_gate(
            prepared["gate"]["id"], reason="ok"
        )
        archive_phase6q_payment_order_workflow_gate(
            prepared["gate"]["id"], reason="close"
        )
        create_link.assert_not_called()
        capture.assert_not_called()
        refund.assert_not_called()
        queue_template.assert_not_called()
        send_text.assert_not_called()
        vapi.assert_not_called()


# ---------------------------------------------------------------------------
# Output sanitization (#22, #23)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True,
    RAZORPAY_KEY_ID="rzp_test_PHASE6Q_PLANTED_KEYID_DO_NOT_LEAK",
    RAZORPAY_KEY_SECRET="PHASE6Q_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
    RAZORPAY_WEBHOOK_SECRET="PHASE6Q_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
)
def test_output_does_not_expose_planted_secrets() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_secret"
    )
    prepared = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    blob = json.dumps(prepared, default=str)
    for planted in (
        "rzp_test_PHASE6Q_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE6Q_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6Q_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted

    readiness = inspect_phase6q_payment_order_workflow_gate_readiness()
    blob = json.dumps(readiness, default=str)
    for planted in (
        "rzp_test_PHASE6Q_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE6Q_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6Q_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted


@pytest.mark.django_db
def test_output_does_not_leak_planted_pii() -> None:
    Customer.objects.create(
        name="Phase6Q Planted Customer",
        phone="+919999111222",
        product_interest="weight-management",
    )
    readiness = inspect_phase6q_payment_order_workflow_gate_readiness()
    blob = json.dumps(readiness, default=str)
    assert "+919999111222" not in blob
    assert "Phase6Q Planted Customer" not in blob


# ---------------------------------------------------------------------------
# Endpoint guards (#24, #25)
# ---------------------------------------------------------------------------


_READ_ENDPOINT_NAMES = (
    "saas-razorpay-payment-order-workflow-gate-readiness",
    "saas-razorpay-payment-order-workflow-gates",
    "saas-razorpay-payment-order-workflow-gate-preview",
)


@pytest.mark.django_db
def test_readiness_endpoint_requires_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse("saas-razorpay-payment-order-workflow-gate-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase6q_shape(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-payment-order-workflow-gate-readiness")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6Q"
    assert body["status"] == "audit_gate_only"
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["apiEndpointCanApprove"] is False


@pytest.mark.django_db
def test_gates_list_endpoint_admin_locked_safety(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-payment-order-workflow-gates")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6Q"
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["apiEndpointCanApprove"] is False
    assert body["realOrderMutationWasMade"] is False


@pytest.mark.django_db
@pytest.mark.parametrize("name", _READ_ENDPOINT_NAMES)
def test_phase_6q_endpoints_reject_non_get_methods(
    name, admin_user, auth_client
) -> None:
    url = reverse(name)
    if name == "saas-razorpay-payment-order-workflow-gate-preview":
        url = url + "?attempt_id=1"
    client = auth_client(admin_user)
    for method in ("post", "patch", "put", "delete"):
        res = getattr(client, method)(url, {})
        assert res.status_code == 405, f"{method} {name} -> {res.status_code}"


# ---------------------------------------------------------------------------
# Audit safety (#26)
# ---------------------------------------------------------------------------


_FORBIDDEN_PAYLOAD_KEYS = (
    "raw_payload",
    "raw_signature",
    "raw_secret",
    "phone",
    "email",
    "address",
    "card",
    "vpa",
    "upi",
    "bank_account",
    "wallet",
)


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_audit_events_only_carry_safe_keys() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_audit"
    )
    prepared = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    approve_phase6q_payment_order_workflow_gate(
        prepared["gate"]["id"], reason="ok"
    )
    reject_phase6q_payment_order_workflow_gate(
        prepared["gate"]["id"], reason="not yet"  # already approved → blocked
    )

    for kind in (AUDIT_KIND_PREPARED, AUDIT_KIND_APPROVED):
        rows = AuditEvent.objects.filter(kind=kind)
        assert rows.exists(), f"missing audit kind {kind}"
        for row in rows:
            payload = row.payload or {}
            assert payload.get("real_order_mutation_was_made") is False
            assert payload.get("real_payment_mutation_was_made") is False
            assert payload.get("business_mutation_was_made") is False
            assert payload.get("customer_notification_sent") is False
            assert payload.get("provider_call_attempted") is False
            for forbidden in _FORBIDDEN_PAYLOAD_KEYS:
                assert forbidden not in payload, (kind, forbidden)


# ---------------------------------------------------------------------------
# safeToStartPhase6R (#27)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_safe_to_start_phase_6r_default_false() -> None:
    report = inspect_phase6q_payment_order_workflow_gate_readiness()
    assert report["safeToStartPhase6R"] is False


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True)
def test_safe_to_start_phase_6r_true_after_approval() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_safe_to_start"
    )
    prepared = prepare_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    approve_phase6q_payment_order_workflow_gate(
        prepared["gate"]["id"], reason="approved for future"
    )
    report = inspect_phase6q_payment_order_workflow_gate_readiness()
    assert report["safeToStartPhase6R"] is True
    assert (
        report["nextAction"]
        == "ready_for_phase_6r_payment_to_whatsapp_courier_readiness_planning"
    )


# ---------------------------------------------------------------------------
# Forbidden actions list visibility
# ---------------------------------------------------------------------------


def test_forbidden_actions_includes_critical_paths() -> None:
    expected = {
        "mutate_real_order_status",
        "mutate_real_payment_status",
        "create_or_update_real_shipment",
        "create_or_update_real_discount_offer",
        "mutate_real_customer",
        "mutate_real_lead",
        "send_whatsapp_template",
        "place_vapi_call",
        "call_razorpay_api",
        "execute_workflow_via_frontend",
        "execute_workflow_via_api_endpoint",
        "approve_gate_via_api_endpoint",
    }
    assert expected.issubset(set(PHASE_6Q_FORBIDDEN_ACTIONS))


# ---------------------------------------------------------------------------
# Preview never creates rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_does_not_create_rows() -> None:
    attempt = _make_full_phase6p_lifecycle(
        source_event_id="evt_phase6q_preview"
    )
    before = _row_counts()
    out = preview_phase6q_payment_order_workflow_gate(
        source_attempt_id=attempt.pk
    )
    after = _row_counts()
    assert out["found"] is True
    assert before["phase6q_gate"] == after["phase6q_gate"]
