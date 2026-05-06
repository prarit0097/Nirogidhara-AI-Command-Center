"""Phase 6R — Payment → WhatsApp / Courier Dispatch Readiness tests.

Asserts the Phase 6R spec requirements:

1.  Readiness command returns Phase 6R shape.
2.  Readiness endpoint returns Phase 6R shape.
3.  Contract includes all 9 events.
4.  Every contract row says ``whatsappSendAllowedInPhase6R=False``.
5.  Every contract row says ``courierBookingAllowedInPhase6R=False``.
6.  Every contract row says ``providerCallAllowedInPhase6R=False``.
7.  Prepare gate fails when ``RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=False``.
8.  Prepare gate succeeds with env override + approved Phase 6Q gate.
9.  Prepare gate fails if Phase 6Q gate not approved.
10. Prepare gate fails if Phase 6Q gate has ``real_order_mutation_was_made=True``.
11. Prepare gate fails if Phase 6Q gate has ``customer_notification_sent=True``.
12. Prepare gate fails if Phase 6Q gate has ``provider_call_attempted=True``.
13. Prepare is idempotent on the source workflow gate.
14. Approve changes readiness status only.
15. Approve requires non-empty reason text.
16. Reject changes readiness status only.
17. Archive changes readiness status only.
18. No real Order mutation across full lifecycle.
19. No real Payment mutation across full lifecycle.
20. No real Shipment mutation across full lifecycle.
21. No real DiscountOfferLog mutation across full lifecycle.
22. No real Customer / Lead mutation across full lifecycle.
23. No Razorpay API call across full lifecycle.
24. No WhatsApp send / queue / Meta Cloud call across full lifecycle.
25. No Vapi / Delhivery call across full lifecycle.
26. No raw secret in command/API output.
27. No planted PII in command/API output.
28. Readiness API endpoints are read-only / auth-protected.
29. POST/PATCH/DELETE return 405 on every Phase 6R endpoint.
30. Audit events are safe + contain no secrets.
31. ``safeToStartPhase6S=False`` until at least one readiness gate is approved.
32. Forbidden actions list includes critical send/courier/business-mutation paths.
33. Preview never creates rows.
34. ``assert_phase6r_no_live_send_or_courier_mutation`` raises on any flipped boolean.
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
    RazorpayPaymentDispatchReadinessGate,
    RazorpayPaymentOrderWorkflowGate,
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)
from apps.payments.razorpay_payment_dispatch_readiness import (
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_REJECTED,
    PHASE_6R_FORBIDDEN_ACTIONS,
    PHASE_6R_MAX_SAFE_AMOUNT_PAISE,
    approve_phase6r_payment_dispatch_readiness_gate,
    archive_phase6r_payment_dispatch_readiness_gate,
    assert_phase6r_no_live_send_or_courier_mutation,
    build_phase6r_payment_dispatch_readiness_contract,
    inspect_phase6r_payment_dispatch_readiness,
    prepare_phase6r_payment_dispatch_readiness_gate,
    preview_phase6r_payment_dispatch_readiness_gate,
    reject_phase6r_payment_dispatch_readiness_gate,
)
from apps.payments.razorpay_payment_order_workflow_gate import (
    approve_phase6q_payment_order_workflow_gate,
    prepare_phase6q_payment_order_workflow_gate,
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
        "phase6p_attempt": (
            RazorpaySandboxPaidStatusMutationAttempt.objects.count()
        ),
        "phase6p_ledger": RazorpaySandboxPaidStatusLedger.objects.count(),
        "phase6q_gate": RazorpayPaymentOrderWorkflowGate.objects.count(),
        "phase6r_readiness": (
            RazorpayPaymentDispatchReadinessGate.objects.count()
        ),
    }


def _make_safe_event(
    *,
    event_name: str = "payment.captured",
    source_event_id: str = "evt_phase6r_001",
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
        provider_order_id="order_phase6r_synthetic",
        provider_payment_id="pay_phase6r_synthetic",
        amount_paise=amount_paise,
        currency="INR",
        payload_hash="x" * 64,
        scrubbed_keys=[],
        business_mutation_was_made=False,
        customer_notification_sent=False,
        raw_secret_exposed=False,
        full_pii_exposed=False,
    )


def _make_approved_phase6q_gate(
    *,
    source_event_id: str = "evt_phase6r_full",
) -> RazorpayPaymentOrderWorkflowGate:
    """Walk a webhook event through Phase 6O approve + Phase 6P
    execute + rollback + Phase 6Q prepare + approve. Returns the
    approved Phase 6Q gate.
    """
    with override_settings(
        RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True,
        RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True,
        RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True,
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
        rollback_phase6p_paid_status_mutation_attempt(
            attempt_id, confirmed=True, reason="rehearsal"
        )
        prepared_gate = prepare_phase6q_payment_order_workflow_gate(
            source_attempt_id=attempt_id
        )
        gate_id = prepared_gate["gate"]["id"]
        approve_phase6q_payment_order_workflow_gate(
            gate_id,
            reviewed_by=None,
            reason="Phase 6Q sign-off for Phase 6R rehearsal",
        )
    return RazorpayPaymentOrderWorkflowGate.objects.get(pk=gate_id)


# ---------------------------------------------------------------------------
# Contract (#3-#6)
# ---------------------------------------------------------------------------


def test_contract_covers_all_nine_events() -> None:
    rows = build_phase6r_payment_dispatch_readiness_contract()
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


def test_every_contract_row_locks_send_and_courier_off() -> None:
    for row in build_phase6r_payment_dispatch_readiness_contract():
        assert row["whatsappSendAllowedInPhase6R"] is False, row[
            "razorpayEventName"
        ]
        assert row["courierBookingAllowedInPhase6R"] is False
        assert row["providerCallAllowedInPhase6R"] is False
        assert row["customerNotificationAllowed"] is False
        assert row["shipmentEffectAllowed"] is False
        assert row["discountEffectAllowed"] is False
        assert row["idempotencyRequired"] is True
        assert row["rollbackRequired"] is True
        assert row["manualReviewRequired"] is True


# ---------------------------------------------------------------------------
# Readiness selector + command + endpoint shape (#1, #2, #31)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_selector_returns_phase6r_shape() -> None:
    report = inspect_phase6r_payment_dispatch_readiness()
    assert report["phase"] == "6R"
    assert report["status"] == "dispatch_readiness_only"
    assert report["latestCompletedPhase"] == "6Q"
    assert report["nextPhase"] == "6S"
    assert report["razorpayPaymentDispatchReadinessEnabled"] is False
    assert report["frontendCanExecute"] is False
    assert report["apiEndpointCanExecute"] is False
    assert report["apiEndpointCanApprove"] is False
    assert report["executionPath"] == "cli_only"
    assert report["maxSafeAmountPaise"] == PHASE_6R_MAX_SAFE_AMOUNT_PAISE
    assert len(report["readinessContract"]) == 9
    assert report["safeToStartPhase6S"] is False
    assert report["safetyInvariants"]["whatsappSendAllowed"] is False
    assert report["safetyInvariants"]["delhiveryCallAllowed"] is False
    assert report["safetyInvariants"]["phase6RRespectsKillSwitch"] is True


@pytest.mark.django_db
def test_readiness_command_emits_json() -> None:
    buf = io.StringIO()
    call_command(
        "inspect_razorpay_payment_dispatch_readiness",
        "--json",
        "--no-audit",
        stdout=buf,
    )
    body = json.loads(buf.getvalue())
    assert body["phase"] == "6R"
    assert body["status"] == "dispatch_readiness_only"
    assert body["razorpayPaymentDispatchReadinessEnabled"] is False


@pytest.mark.django_db
def test_safe_to_start_phase_6s_default_false() -> None:
    report = inspect_phase6r_payment_dispatch_readiness()
    assert report["safeToStartPhase6S"] is False


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_safe_to_start_phase_6s_true_after_approval() -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_safeS")
    prepared = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    approve_phase6r_payment_dispatch_readiness_gate(
        prepared["readiness"]["id"],
        reviewed_by=None,
        reason="approved for future Phase 6S",
    )
    report = inspect_phase6r_payment_dispatch_readiness()
    assert report["safeToStartPhase6S"] is True
    assert "phase_6s" in report["nextAction"].lower()


# ---------------------------------------------------------------------------
# Prepare gating (#7-#13)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_blocked_when_env_flag_off() -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_no_flag")
    out = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    assert out["created"] is False
    assert any(
        "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED" in b
        for b in out["blockers"]
    )
    assert RazorpayPaymentDispatchReadinessGate.objects.count() == 0


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_prepare_succeeds_with_approved_phase6q_gate() -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_ok")
    out = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    assert out["created"] is True
    readiness = out["readiness"]
    assert readiness["dispatchReadinessAllowedInPhase6R"] is False
    assert readiness["realOrderMutationWasMade"] is False
    assert readiness["realPaymentMutationWasMade"] is False
    assert readiness["shipmentMutationWasMade"] is False
    assert readiness["shipmentCreated"] is False
    assert readiness["whatsAppMessageCreated"] is False
    assert readiness["whatsAppMessageQueued"] is False
    assert readiness["customerNotificationSent"] is False
    assert readiness["metaCloudCallAttempted"] is False
    assert readiness["delhiveryCallAttempted"] is False
    assert readiness["razorpayCallAttempted"] is False
    assert readiness["providerCallAttempted"] is False
    assert RazorpayPaymentDispatchReadinessGate.objects.count() == 1


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_prepare_blocked_when_phase6q_gate_not_approved() -> None:
    """Phase 6Q gate left in PENDING_MANUAL_REVIEW must be refused."""
    with override_settings(
        RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True,
        RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True,
        RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True,
    ):
        event = _make_safe_event(source_event_id="evt_phase6r_pending_q")
        prepared = prepare_phase6o_sandbox_status_review(event.pk)
        approve_phase6o_sandbox_status_review(
            prepared["review"]["id"], reviewed_by=None, reason="ok"
        )
        executed = execute_phase6p_paid_status_mutation_attempt(
            prepared["review"]["id"],
            confirmed=True,
            director_signoff_text="Director ok",
        )
        rollback_phase6p_paid_status_mutation_attempt(
            executed["attempt"]["id"], confirmed=True, reason="rehearsal"
        )
        prepared_gate = prepare_phase6q_payment_order_workflow_gate(
            source_attempt_id=executed["attempt"]["id"]
        )
    # gate is now in PENDING_MANUAL_REVIEW (not approved)
    out = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=prepared_gate["gate"]["id"]
    )
    assert out["created"] is False
    assert any(
        "phase_6q_gate_status_must_be_approved_for_future_phase6r" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_prepare_blocked_if_phase6q_real_order_mutation_was_made() -> None:
    gate = _make_approved_phase6q_gate(
        source_event_id="evt_phase6r_real_order"
    )
    gate.real_order_mutation_was_made = True
    gate.save(update_fields=["real_order_mutation_was_made"])
    out = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    assert out["created"] is False
    assert "phase_6q_gate_real_order_mutation_was_made" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_prepare_blocked_if_phase6q_customer_notification_sent() -> None:
    gate = _make_approved_phase6q_gate(
        source_event_id="evt_phase6r_notify"
    )
    gate.customer_notification_sent = True
    gate.save(update_fields=["customer_notification_sent"])
    out = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    assert out["created"] is False
    assert "phase_6q_gate_customer_notification_sent" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_prepare_blocked_if_phase6q_provider_call_attempted() -> None:
    gate = _make_approved_phase6q_gate(
        source_event_id="evt_phase6r_provider"
    )
    gate.provider_call_attempted = True
    gate.save(update_fields=["provider_call_attempted"])
    out = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    assert out["created"] is False
    assert "phase_6q_gate_provider_call_attempted" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_prepare_is_idempotent() -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_idem")
    first = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    second = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert first["readiness"]["id"] == second["readiness"]["id"]


# ---------------------------------------------------------------------------
# Approve / reject / archive (#14-#17)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_approve_sets_status_to_approved_for_future_phase6s() -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_app")
    prepared = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    out = approve_phase6r_payment_dispatch_readiness_gate(
        prepared["readiness"]["id"],
        reviewed_by=None,
        reason="Reviewer signoff for Phase 6R readiness",
    )
    assert out["ok"] is True
    assert (
        out["readiness"]["status"]
        == RazorpayPaymentDispatchReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE6S
    )
    assert "phase_6s" in out["nextAction"].lower()


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_approve_requires_reason() -> None:
    gate = _make_approved_phase6q_gate(
        source_event_id="evt_phase6r_no_reason"
    )
    prepared = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    out = approve_phase6r_payment_dispatch_readiness_gate(
        prepared["readiness"]["id"], reviewed_by=None, reason=""
    )
    assert out["ok"] is False
    assert "manual_review_reason_must_be_non_empty" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_reject_sets_status_to_rejected() -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_rej")
    prepared = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    out = reject_phase6r_payment_dispatch_readiness_gate(
        prepared["readiness"]["id"], reviewed_by=None, reason="not yet"
    )
    assert out["ok"] is True
    assert (
        out["readiness"]["status"]
        == RazorpayPaymentDispatchReadinessGate.Status.REJECTED
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_archive_sets_status_to_archived() -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_arc")
    prepared = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    out = archive_phase6r_payment_dispatch_readiness_gate(
        prepared["readiness"]["id"], archived_by=None, reason="close"
    )
    assert out["ok"] is True
    assert (
        out["readiness"]["status"]
        == RazorpayPaymentDispatchReadinessGate.Status.ARCHIVED
    )


# ---------------------------------------------------------------------------
# Mutation safety (#18-#25)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_full_lifecycle_does_not_mutate_real_business_tables(seeded) -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_safe")
    before = _row_counts()

    prepared = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    after_prepare = _row_counts()

    approve_phase6r_payment_dispatch_readiness_gate(
        prepared["readiness"]["id"], reason="sign-off ok"
    )
    after_approve = _row_counts()

    reject_phase6r_payment_dispatch_readiness_gate(
        prepared["readiness"]["id"], reason="changed mind"
    )
    after_reject = _row_counts()

    archive_phase6r_payment_dispatch_readiness_gate(
        prepared["readiness"]["id"], reason="close"
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
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_full_lifecycle_never_calls_provider_or_whatsapp_or_courier() -> None:
    gate = _make_approved_phase6q_gate(
        source_event_id="evt_phase6r_no_calls"
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
    ) as vapi, mock.patch(
        "apps.shipments.integrations.delhivery_client.create_shipment",
        create=True,
    ) as delhivery_ship, mock.patch(
        "apps.shipments.integrations.delhivery_client.book_pickup",
        create=True,
    ) as delhivery_book:
        prepared = prepare_phase6r_payment_dispatch_readiness_gate(
            source_gate_id=gate.pk
        )
        approve_phase6r_payment_dispatch_readiness_gate(
            prepared["readiness"]["id"], reason="ok"
        )
        archive_phase6r_payment_dispatch_readiness_gate(
            prepared["readiness"]["id"], reason="close"
        )
        create_link.assert_not_called()
        capture.assert_not_called()
        refund.assert_not_called()
        queue_template.assert_not_called()
        send_text.assert_not_called()
        vapi.assert_not_called()
        delhivery_ship.assert_not_called()
        delhivery_book.assert_not_called()


# ---------------------------------------------------------------------------
# Defensive guard (#34)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_assert_phase6r_no_live_send_or_courier_mutation_raises_on_flip(
) -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_assert")
    prepared = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    row = RazorpayPaymentDispatchReadinessGate.objects.get(
        pk=prepared["readiness"]["id"]
    )
    # Each flipped boolean must trigger the defensive guard.
    for field in (
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
        "shipment_mutation_was_made",
        "shipment_created",
        "whatsapp_message_created",
        "whatsapp_message_queued",
        "customer_notification_sent",
        "meta_cloud_call_attempted",
        "delhivery_call_attempted",
        "razorpay_call_attempted",
        "provider_call_attempted",
        "dispatch_readiness_allowed_in_phase6r",
    ):
        setattr(row, field, True)
        with pytest.raises(ValueError):
            assert_phase6r_no_live_send_or_courier_mutation(row)
        setattr(row, field, False)


# ---------------------------------------------------------------------------
# Output sanitization (#26, #27)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True,
    RAZORPAY_KEY_ID="rzp_test_PHASE6R_PLANTED_KEYID_DO_NOT_LEAK",
    RAZORPAY_KEY_SECRET="PHASE6R_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
    RAZORPAY_WEBHOOK_SECRET="PHASE6R_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
)
def test_output_does_not_expose_planted_secrets() -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_secret")
    prepared = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    blob = json.dumps(prepared, default=str)
    for planted in (
        "rzp_test_PHASE6R_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE6R_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6R_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted

    readiness = inspect_phase6r_payment_dispatch_readiness()
    blob = json.dumps(readiness, default=str)
    for planted in (
        "rzp_test_PHASE6R_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE6R_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6R_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted


@pytest.mark.django_db
def test_output_does_not_leak_planted_pii() -> None:
    Customer.objects.create(
        name="Phase6R Planted Customer",
        phone="+919999333444",
        product_interest="weight-management",
    )
    readiness = inspect_phase6r_payment_dispatch_readiness()
    blob = json.dumps(readiness, default=str)
    assert "+919999333444" not in blob
    assert "Phase6R Planted Customer" not in blob


# ---------------------------------------------------------------------------
# Endpoint guards (#28, #29)
# ---------------------------------------------------------------------------


_READ_ENDPOINT_NAMES = (
    "saas-razorpay-payment-dispatch-readiness",
    "saas-razorpay-payment-dispatch-readiness-gates",
    "saas-razorpay-payment-dispatch-readiness-preview",
)


@pytest.mark.django_db
def test_readiness_endpoint_requires_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse("saas-razorpay-payment-dispatch-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase6r_shape(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-payment-dispatch-readiness")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6R"
    assert body["status"] == "dispatch_readiness_only"
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["apiEndpointCanApprove"] is False


@pytest.mark.django_db
def test_gates_list_endpoint_admin_locked_safety(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-payment-dispatch-readiness-gates")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6R"
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["apiEndpointCanApprove"] is False
    assert body["realOrderMutationWasMade"] is False
    assert body["whatsAppMessageCreated"] is False
    assert body["delhiveryCallAttempted"] is False


@pytest.mark.django_db
def test_preview_endpoint_requires_gate_id(admin_user, auth_client) -> None:
    url = reverse("saas-razorpay-payment-dispatch-readiness-preview")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("name", _READ_ENDPOINT_NAMES)
def test_phase_6r_endpoints_reject_non_get_methods(
    name, admin_user, auth_client
) -> None:
    url = reverse(name)
    if name == "saas-razorpay-payment-dispatch-readiness-preview":
        url = url + "?gate_id=1"
    client = auth_client(admin_user)
    for method in ("post", "patch", "put", "delete"):
        res = getattr(client, method)(url, {})
        assert res.status_code == 405, f"{method} {name} -> {res.status_code}"


# ---------------------------------------------------------------------------
# Audit safety (#30)
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
@override_settings(RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True)
def test_audit_events_only_carry_safe_keys() -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_audit")
    prepared = prepare_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    approve_phase6r_payment_dispatch_readiness_gate(
        prepared["readiness"]["id"], reason="ok"
    )
    reject_phase6r_payment_dispatch_readiness_gate(
        prepared["readiness"]["id"], reason="late"  # already approved → blocked
    )

    for kind in (AUDIT_KIND_PREPARED, AUDIT_KIND_APPROVED):
        rows = AuditEvent.objects.filter(kind=kind)
        assert rows.exists(), f"missing audit kind {kind}"
        for row in rows:
            payload = row.payload or {}
            assert payload.get("real_order_mutation_was_made") is False
            assert payload.get("real_payment_mutation_was_made") is False
            assert payload.get("shipment_created") is False
            assert payload.get("whatsapp_message_created") is False
            assert payload.get("whatsapp_message_queued") is False
            assert payload.get("customer_notification_sent") is False
            assert payload.get("meta_cloud_call_attempted") is False
            assert payload.get("delhivery_call_attempted") is False
            assert payload.get("provider_call_attempted") is False
            for forbidden in _FORBIDDEN_PAYLOAD_KEYS:
                assert forbidden not in payload, (kind, forbidden)


# ---------------------------------------------------------------------------
# Forbidden actions (#32)
# ---------------------------------------------------------------------------


def test_forbidden_actions_includes_critical_paths() -> None:
    expected = {
        "send_whatsapp_template",
        "queue_whatsapp_outbound",
        "create_whatsapp_message_outbound",
        "call_meta_cloud_api",
        "call_delhivery_api",
        "create_shipment",
        "create_awb",
        "book_courier_pickup",
        "place_vapi_call",
        "call_razorpay_api",
        "create_payment_link",
        "capture_razorpay_payment",
        "refund_razorpay_payment",
        "mutate_real_order_status",
        "mutate_real_payment_status",
        "mutate_real_customer",
        "mutate_real_lead",
        "execute_workflow_via_frontend",
        "execute_workflow_via_api_endpoint",
        "approve_readiness_via_api_endpoint",
    }
    assert expected.issubset(set(PHASE_6R_FORBIDDEN_ACTIONS))


# ---------------------------------------------------------------------------
# Preview never creates rows (#33)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_does_not_create_rows() -> None:
    gate = _make_approved_phase6q_gate(source_event_id="evt_phase6r_preview")
    before = _row_counts()
    out = preview_phase6r_payment_dispatch_readiness_gate(
        source_gate_id=gate.pk
    )
    after = _row_counts()
    assert out["found"] is True
    assert before["phase6r_readiness"] == after["phase6r_readiness"]
