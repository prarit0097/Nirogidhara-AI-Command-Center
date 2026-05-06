"""Phase 6S — Limited Internal Dispatch Pilot Plan tests.

Asserts the Phase 6S spec requirements:

1.  Readiness command returns Phase 6S shape.
2.  Readiness endpoint returns Phase 6S shape.
3.  Contract includes all 9 events.
4.  Every contract row says ``pilotExecutionAllowedInPhase6S=False``.
5.  Every contract row says ``whatsappSendAllowedInPhase6S=False``.
6.  Every contract row says ``courierBookingAllowedInPhase6S=False``.
7.  Every contract row says ``providerCallAllowedInPhase6S=False``.
8.  Prepare pilot plan fails when ``RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=False``.
9.  Prepare pilot plan succeeds with env override + approved Phase 6R readiness gate.
10. Prepare pilot plan fails if Phase 6R readiness gate is not approved.
11. Prepare pilot plan fails if Phase 6R readiness gate has ``shipment_created=True``.
12. Prepare pilot plan fails if Phase 6R readiness gate has ``whatsapp_message_queued=True``.
13. Prepare pilot plan fails if Phase 6R readiness gate has ``meta_cloud_call_attempted=True``.
14. Prepare pilot plan fails if Phase 6R readiness gate has ``delhivery_call_attempted=True``.
15. Approve changes plan status only.
16. Reject changes plan status only.
17. Archive changes plan status only.
18. No real Order mutation across full lifecycle.
19. No real Payment mutation across full lifecycle.
20. No real Shipment mutation across full lifecycle.
21. No real DiscountOfferLog mutation across full lifecycle.
22. No real Customer / Lead mutation across full lifecycle.
23. No outbound WhatsAppMessage row created across full lifecycle.
24. No Razorpay API call across full lifecycle.
25. No Meta Cloud / Delhivery / Vapi API call across full lifecycle.
26. No raw secret in command/API output.
27. No planted PII in command/API output.
28. Readiness API endpoints are read-only / auth-protected.
29. POST/PATCH/DELETE return 405 on every Phase 6S endpoint.
30. Audit events are safe + contain no secrets.
31. ``safeToStartPhase6T=False`` until at least one pilot plan is approved.
32. Forbidden actions list includes critical send/courier/provider paths.
33. Preview never creates rows.
34. ``assert_phase6s_no_live_execution_or_provider_call`` raises on flipped boolean.
35. Idempotent prepare on the source readiness gate.
36. Approve requires non-empty manual review reason.
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
    RazorpayPaymentDispatchPilotPlan,
    RazorpayPaymentDispatchReadinessGate,
    RazorpayPaymentOrderWorkflowGate,
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)
from apps.payments.razorpay_payment_dispatch_pilot_plan import (
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_REJECTED,
    PHASE_6S_DEFAULT_MAX_PILOT_ORDERS,
    PHASE_6S_FORBIDDEN_ACTIONS,
    PHASE_6S_MAX_SAFE_AMOUNT_PAISE,
    approve_phase6s_payment_dispatch_pilot_plan,
    archive_phase6s_payment_dispatch_pilot_plan,
    assert_phase6s_no_live_execution_or_provider_call,
    build_phase6s_payment_dispatch_pilot_contract,
    inspect_phase6s_payment_dispatch_pilot_plan_readiness,
    prepare_phase6s_payment_dispatch_pilot_plan,
    preview_phase6s_payment_dispatch_pilot_plan,
    reject_phase6s_payment_dispatch_pilot_plan,
)
from apps.payments.razorpay_payment_dispatch_readiness import (
    approve_phase6r_payment_dispatch_readiness_gate,
    prepare_phase6r_payment_dispatch_readiness_gate,
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
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)


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
        "whatsapp_message": WhatsAppMessage.objects.count(),
        "whatsapp_lifecycle_event": (
            WhatsAppLifecycleEvent.objects.count()
        ),
        "whatsapp_handoff": WhatsAppHandoffToCall.objects.count(),
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
        "phase6s_pilot_plan": (
            RazorpayPaymentDispatchPilotPlan.objects.count()
        ),
    }


def _make_safe_event(
    *,
    event_name: str = "payment.captured",
    source_event_id: str = "evt_phase6s_001",
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
        provider_order_id="order_phase6s_synthetic",
        provider_payment_id="pay_phase6s_synthetic",
        amount_paise=amount_paise,
        currency="INR",
        payload_hash="x" * 64,
        scrubbed_keys=[],
        business_mutation_was_made=False,
        customer_notification_sent=False,
        raw_secret_exposed=False,
        full_pii_exposed=False,
    )


def _make_approved_phase6r_readiness(
    *,
    source_event_id: str = "evt_phase6s_full",
) -> RazorpayPaymentDispatchReadinessGate:
    """Walk a webhook event through Phase 6O approve + Phase 6P
    execute + rollback + Phase 6Q prepare + approve + Phase 6R prepare
    + approve. Returns the approved Phase 6R readiness gate.
    """
    with override_settings(
        RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True,
        RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True,
        RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True,
        RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True,
    ):
        event = _make_safe_event(source_event_id=source_event_id)
        prepared_review = prepare_phase6o_sandbox_status_review(event.pk)
        approve_phase6o_sandbox_status_review(
            prepared_review["review"]["id"], reviewed_by=None, reason="ok"
        )
        review_id = prepared_review["review"]["id"]
        executed = execute_phase6p_paid_status_mutation_attempt(
            review_id, confirmed=True, director_signoff_text="Director ok"
        )
        attempt_id = executed["attempt"]["id"]
        rollback_phase6p_paid_status_mutation_attempt(
            attempt_id, confirmed=True, reason="rehearsal"
        )
        prepared_q = prepare_phase6q_payment_order_workflow_gate(
            source_attempt_id=attempt_id
        )
        gate_id_q = prepared_q["gate"]["id"]
        approve_phase6q_payment_order_workflow_gate(
            gate_id_q,
            reviewed_by=None,
            reason="Phase 6Q sign-off for Phase 6S rehearsal",
        )
        prepared_r = prepare_phase6r_payment_dispatch_readiness_gate(
            source_gate_id=gate_id_q
        )
        readiness_id = prepared_r["readiness"]["id"]
        approve_phase6r_payment_dispatch_readiness_gate(
            readiness_id,
            reviewed_by=None,
            reason="Phase 6R sign-off for Phase 6S rehearsal",
        )
    return RazorpayPaymentDispatchReadinessGate.objects.get(
        pk=readiness_id
    )


# ---------------------------------------------------------------------------
# Contract (#3-#7)
# ---------------------------------------------------------------------------


def test_contract_covers_all_nine_events() -> None:
    rows = build_phase6s_payment_dispatch_pilot_contract()
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


def test_every_contract_row_locks_pilot_send_courier_and_provider_off() -> None:
    for row in build_phase6s_payment_dispatch_pilot_contract():
        assert row["pilotExecutionAllowedInPhase6S"] is False, row[
            "razorpayEventName"
        ]
        assert row["whatsappSendAllowedInPhase6S"] is False
        assert row["courierBookingAllowedInPhase6S"] is False
        assert row["providerCallAllowedInPhase6S"] is False
        assert row["customerNotificationAllowed"] is False
        assert row["shipmentEffectAllowed"] is False
        assert row["discountEffectAllowed"] is False
        assert row["idempotencyRequired"] is True
        assert row["rollbackRequired"] is True
        assert row["manualReviewRequired"] is True
        assert row["internalStaffOnly"] is True
        assert row["maxPilotOrders"] == PHASE_6S_DEFAULT_MAX_PILOT_ORDERS
        assert row["maxAmountPaise"] == PHASE_6S_MAX_SAFE_AMOUNT_PAISE


# ---------------------------------------------------------------------------
# Readiness selector + command + endpoint shape (#1, #2, #31)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_selector_returns_phase6s_shape() -> None:
    report = inspect_phase6s_payment_dispatch_pilot_plan_readiness()
    assert report["phase"] == "6S"
    assert report["status"] == "pilot_planning_only"
    assert report["latestCompletedPhase"] == "6R"
    assert report["nextPhase"] == "6T"
    assert report["razorpayPaymentDispatchPilotPlanEnabled"] is False
    assert report["pilotExecutionEnabled"] is False
    assert report["frontendCanExecute"] is False
    assert report["apiEndpointCanExecute"] is False
    assert report["apiEndpointCanApprove"] is False
    assert report["executionPath"] == "cli_only"
    assert report["maxSafeAmountPaise"] == PHASE_6S_MAX_SAFE_AMOUNT_PAISE
    assert report["maxPilotOrders"] == PHASE_6S_DEFAULT_MAX_PILOT_ORDERS
    assert len(report["pilotContract"]) == 9
    assert report["safeToStartPhase6T"] is False
    si = report["safetyInvariants"]
    assert si["pilotExecutionAllowed"] is False
    assert si["liveSendAllowed"] is False
    assert si["courierBookingAllowed"] is False
    assert si["providerCallAllowed"] is False
    assert si["delhiveryCallAllowed"] is False
    assert si["razorpayApiInvocationAllowed"] is False
    assert si["phase6SRespectsKillSwitch"] is True


@pytest.mark.django_db
def test_readiness_command_emits_json() -> None:
    buf = io.StringIO()
    call_command(
        "inspect_razorpay_payment_dispatch_pilot_plan_readiness",
        "--json",
        "--no-audit",
        stdout=buf,
    )
    body = json.loads(buf.getvalue())
    assert body["phase"] == "6S"
    assert body["status"] == "pilot_planning_only"
    assert body["razorpayPaymentDispatchPilotPlanEnabled"] is False


@pytest.mark.django_db
def test_safe_to_start_phase_6t_default_false() -> None:
    report = inspect_phase6s_payment_dispatch_pilot_plan_readiness()
    assert report["safeToStartPhase6T"] is False


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_safe_to_start_phase_6t_true_after_approval() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_safe6t"
    )
    prepared = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    approve_phase6s_payment_dispatch_pilot_plan(
        prepared["plan"]["id"],
        reviewed_by=None,
        reason="approved for future Phase 6T",
    )
    report = inspect_phase6s_payment_dispatch_pilot_plan_readiness()
    assert report["safeToStartPhase6T"] is True
    assert "phase_6t" in report["nextAction"].lower()


# ---------------------------------------------------------------------------
# Prepare gating (#8-#14, #35)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_blocked_when_env_flag_off() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_no_flag"
    )
    out = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    assert out["created"] is False
    assert any(
        "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED" in b
        for b in out["blockers"]
    )
    assert RazorpayPaymentDispatchPilotPlan.objects.count() == 0


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_prepare_succeeds_with_approved_phase6r_readiness() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_ok"
    )
    out = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    assert out["created"] is True
    plan = out["plan"]
    assert plan["pilotExecutionAllowedInPhase6S"] is False
    assert plan["liveSendAllowedInPhase6S"] is False
    assert plan["courierBookingAllowedInPhase6S"] is False
    assert plan["providerCallAllowedInPhase6S"] is False
    assert plan["realOrderMutationWasMade"] is False
    assert plan["realPaymentMutationWasMade"] is False
    assert plan["shipmentMutationWasMade"] is False
    assert plan["shipmentCreated"] is False
    assert plan["awbCreated"] is False
    assert plan["whatsAppMessageCreated"] is False
    assert plan["whatsAppMessageQueued"] is False
    assert plan["customerNotificationSent"] is False
    assert plan["metaCloudCallAttempted"] is False
    assert plan["delhiveryCallAttempted"] is False
    assert plan["razorpayCallAttempted"] is False
    assert plan["providerCallAttempted"] is False
    assert plan["internalOnly"] is True
    assert plan["maxPilotOrders"] == PHASE_6S_DEFAULT_MAX_PILOT_ORDERS
    assert plan["maxAmountPaise"] == PHASE_6S_MAX_SAFE_AMOUNT_PAISE
    assert RazorpayPaymentDispatchPilotPlan.objects.count() == 1


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_prepare_blocked_when_phase6r_readiness_not_approved() -> None:
    """Phase 6R readiness left in PENDING_MANUAL_REVIEW must be refused."""
    with override_settings(
        RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True,
        RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True,
        RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED=True,
        RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED=True,
    ):
        event = _make_safe_event(source_event_id="evt_phase6s_pending_r")
        prepared_review = prepare_phase6o_sandbox_status_review(event.pk)
        approve_phase6o_sandbox_status_review(
            prepared_review["review"]["id"], reviewed_by=None, reason="ok"
        )
        executed = execute_phase6p_paid_status_mutation_attempt(
            prepared_review["review"]["id"],
            confirmed=True,
            director_signoff_text="Director ok",
        )
        rollback_phase6p_paid_status_mutation_attempt(
            executed["attempt"]["id"], confirmed=True, reason="rehearsal"
        )
        prepared_q = prepare_phase6q_payment_order_workflow_gate(
            source_attempt_id=executed["attempt"]["id"]
        )
        approve_phase6q_payment_order_workflow_gate(
            prepared_q["gate"]["id"],
            reviewed_by=None,
            reason="Q signoff",
        )
        prepared_r = prepare_phase6r_payment_dispatch_readiness_gate(
            source_gate_id=prepared_q["gate"]["id"]
        )
    # readiness gate is now PENDING_MANUAL_REVIEW (not approved for 6S)
    out = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=prepared_r["readiness"]["id"]
    )
    assert out["created"] is False
    assert any(
        "phase_6r_readiness_gate_status_must_be_approved_for_future_phase6s" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_prepare_blocked_if_phase6r_shipment_created() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_shipment"
    )
    readiness.shipment_created = True
    readiness.save(update_fields=["shipment_created"])
    out = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    assert out["created"] is False
    assert (
        "phase_6r_readiness_gate_shipment_created" in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_prepare_blocked_if_phase6r_whatsapp_message_queued() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_wa_queued"
    )
    readiness.whatsapp_message_queued = True
    readiness.save(update_fields=["whatsapp_message_queued"])
    out = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    assert out["created"] is False
    assert (
        "phase_6r_readiness_gate_whatsapp_message_queued" in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_prepare_blocked_if_phase6r_meta_cloud_call_attempted() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_meta"
    )
    readiness.meta_cloud_call_attempted = True
    readiness.save(update_fields=["meta_cloud_call_attempted"])
    out = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    assert out["created"] is False
    assert (
        "phase_6r_readiness_gate_meta_cloud_call_attempted"
        in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_prepare_blocked_if_phase6r_delhivery_call_attempted() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_delhivery"
    )
    readiness.delhivery_call_attempted = True
    readiness.save(update_fields=["delhivery_call_attempted"])
    out = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    assert out["created"] is False
    assert (
        "phase_6r_readiness_gate_delhivery_call_attempted"
        in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_prepare_is_idempotent() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_idem"
    )
    first = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    second = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert first["plan"]["id"] == second["plan"]["id"]


# ---------------------------------------------------------------------------
# Approve / reject / archive (#15-#17, #36)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_approve_sets_status_to_approved_for_future_phase6t() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_app"
    )
    prepared = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    out = approve_phase6s_payment_dispatch_pilot_plan(
        prepared["plan"]["id"],
        reviewed_by=None,
        reason="Reviewer signoff for Phase 6S pilot plan",
    )
    assert out["ok"] is True
    assert (
        out["plan"]["status"]
        == RazorpayPaymentDispatchPilotPlan.Status.APPROVED_FOR_FUTURE_PHASE6T
    )
    assert "phase_6t" in out["nextAction"].lower()


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_approve_requires_reason() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_no_reason"
    )
    prepared = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    out = approve_phase6s_payment_dispatch_pilot_plan(
        prepared["plan"]["id"], reviewed_by=None, reason=""
    )
    assert out["ok"] is False
    assert "manual_review_reason_must_be_non_empty" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_reject_sets_status_to_rejected() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_rej"
    )
    prepared = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    out = reject_phase6s_payment_dispatch_pilot_plan(
        prepared["plan"]["id"], reviewed_by=None, reason="not yet"
    )
    assert out["ok"] is True
    assert (
        out["plan"]["status"]
        == RazorpayPaymentDispatchPilotPlan.Status.REJECTED
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_archive_sets_status_to_archived() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_arc"
    )
    prepared = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    out = archive_phase6s_payment_dispatch_pilot_plan(
        prepared["plan"]["id"], archived_by=None, reason="close"
    )
    assert out["ok"] is True
    assert (
        out["plan"]["status"]
        == RazorpayPaymentDispatchPilotPlan.Status.ARCHIVED
    )


# ---------------------------------------------------------------------------
# Mutation safety (#18-#25)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_full_lifecycle_does_not_mutate_real_business_tables(seeded) -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_safe"
    )
    before = _row_counts()

    prepared = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    after_prepare = _row_counts()

    approve_phase6s_payment_dispatch_pilot_plan(
        prepared["plan"]["id"], reason="sign-off ok"
    )
    after_approve = _row_counts()

    reject_phase6s_payment_dispatch_pilot_plan(
        prepared["plan"]["id"], reason="changed mind"
    )
    after_reject = _row_counts()

    archive_phase6s_payment_dispatch_pilot_plan(
        prepared["plan"]["id"], reason="close"
    )
    after_archive = _row_counts()

    for after in (
        after_prepare,
        after_approve,
        after_reject,
        after_archive,
    ):
        assert after["order"] == before["order"]
        assert after["payment"] == before["payment"]
        assert after["shipment"] == before["shipment"]
        assert (
            after["discount_offer_log"] == before["discount_offer_log"]
        )
        assert after["customer"] == before["customer"]
        assert after["lead"] == before["lead"]
        # Phase 6S NEVER creates outbound WhatsAppMessage rows / lifecycle
        # events / handoffs.
        assert after["whatsapp_message"] == before["whatsapp_message"]
        assert (
            after["whatsapp_lifecycle_event"]
            == before["whatsapp_lifecycle_event"]
        )
        assert after["whatsapp_handoff"] == before["whatsapp_handoff"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_full_lifecycle_never_calls_provider_or_whatsapp_or_courier() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_no_calls"
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
        prepared = prepare_phase6s_payment_dispatch_pilot_plan(
            source_readiness_id=readiness.pk
        )
        approve_phase6s_payment_dispatch_pilot_plan(
            prepared["plan"]["id"], reason="ok"
        )
        archive_phase6s_payment_dispatch_pilot_plan(
            prepared["plan"]["id"], reason="close"
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
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_assert_phase6s_no_live_execution_raises_on_flip() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_assert"
    )
    prepared = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    row = RazorpayPaymentDispatchPilotPlan.objects.get(
        pk=prepared["plan"]["id"]
    )
    for field in (
        "pilot_execution_allowed_in_phase6s",
        "live_send_allowed_in_phase6s",
        "courier_booking_allowed_in_phase6s",
        "provider_call_allowed_in_phase6s",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
        "shipment_mutation_was_made",
        "shipment_created",
        "awb_created",
        "whatsapp_message_created",
        "whatsapp_message_queued",
        "customer_notification_sent",
        "meta_cloud_call_attempted",
        "delhivery_call_attempted",
        "razorpay_call_attempted",
        "provider_call_attempted",
    ):
        setattr(row, field, True)
        with pytest.raises(ValueError):
            assert_phase6s_no_live_execution_or_provider_call(row)
        setattr(row, field, False)


# ---------------------------------------------------------------------------
# Output sanitization (#26, #27)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True,
    RAZORPAY_KEY_ID="rzp_test_PHASE6S_PLANTED_KEYID_DO_NOT_LEAK",
    RAZORPAY_KEY_SECRET="PHASE6S_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
    RAZORPAY_WEBHOOK_SECRET="PHASE6S_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
)
def test_output_does_not_expose_planted_secrets() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_secret"
    )
    prepared = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    blob = json.dumps(prepared, default=str)
    for planted in (
        "rzp_test_PHASE6S_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE6S_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6S_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted

    readiness_report = (
        inspect_phase6s_payment_dispatch_pilot_plan_readiness()
    )
    blob = json.dumps(readiness_report, default=str)
    for planted in (
        "rzp_test_PHASE6S_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE6S_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6S_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted


@pytest.mark.django_db
def test_output_does_not_leak_planted_pii() -> None:
    Customer.objects.create(
        name="Phase6S Planted Customer",
        phone="+919999555666",
        product_interest="weight-management",
    )
    readiness_report = (
        inspect_phase6s_payment_dispatch_pilot_plan_readiness()
    )
    blob = json.dumps(readiness_report, default=str)
    assert "+919999555666" not in blob
    assert "Phase6S Planted Customer" not in blob


# ---------------------------------------------------------------------------
# Endpoint guards (#28, #29)
# ---------------------------------------------------------------------------


_READ_ENDPOINT_NAMES = (
    "saas-razorpay-payment-dispatch-pilot-plan-readiness",
    "saas-razorpay-payment-dispatch-pilot-plans",
    "saas-razorpay-payment-dispatch-pilot-plan-preview",
)


@pytest.mark.django_db
def test_readiness_endpoint_requires_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse("saas-razorpay-payment-dispatch-pilot-plan-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase6s_shape(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-payment-dispatch-pilot-plan-readiness")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6S"
    assert body["status"] == "pilot_planning_only"
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["apiEndpointCanApprove"] is False
    assert body["pilotExecutionEnabled"] is False


@pytest.mark.django_db
def test_pilot_plans_list_endpoint_admin_locked_safety(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-payment-dispatch-pilot-plans")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6S"
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["apiEndpointCanApprove"] is False
    assert body["pilotExecutionAllowedInPhase6S"] is False
    assert body["realOrderMutationWasMade"] is False
    assert body["whatsAppMessageCreated"] is False
    assert body["delhiveryCallAttempted"] is False
    assert body["shipmentCreated"] is False
    assert body["awbCreated"] is False


@pytest.mark.django_db
def test_preview_endpoint_requires_readiness_id(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-payment-dispatch-pilot-plan-preview")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("name", _READ_ENDPOINT_NAMES)
def test_phase_6s_endpoints_reject_non_get_methods(
    name, admin_user, auth_client
) -> None:
    url = reverse(name)
    if name == "saas-razorpay-payment-dispatch-pilot-plan-preview":
        url = url + "?readiness_id=1"
    client = auth_client(admin_user)
    for method in ("post", "patch", "put", "delete"):
        res = getattr(client, method)(url, {})
        assert (
            res.status_code == 405
        ), f"{method} {name} -> {res.status_code}"


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
@override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True)
def test_audit_events_only_carry_safe_keys() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_audit"
    )
    prepared = prepare_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    approve_phase6s_payment_dispatch_pilot_plan(
        prepared["plan"]["id"], reason="ok"
    )
    reject_phase6s_payment_dispatch_pilot_plan(
        prepared["plan"]["id"], reason="late"  # already approved → blocked
    )

    for kind in (AUDIT_KIND_PREPARED, AUDIT_KIND_APPROVED):
        rows = AuditEvent.objects.filter(kind=kind)
        assert rows.exists(), f"missing audit kind {kind}"
        for row in rows:
            payload = row.payload or {}
            assert payload.get("pilot_execution_allowed_in_phase6s") is False
            assert payload.get("real_order_mutation_was_made") is False
            assert payload.get("real_payment_mutation_was_made") is False
            assert payload.get("shipment_created") is False
            assert payload.get("awb_created") is False
            assert payload.get("whatsapp_message_created") is False
            assert payload.get("whatsapp_message_queued") is False
            assert payload.get("customer_notification_sent") is False
            assert payload.get("meta_cloud_call_attempted") is False
            assert payload.get("delhivery_call_attempted") is False
            assert payload.get("razorpay_call_attempted") is False
            assert payload.get("provider_call_attempted") is False
            for forbidden in _FORBIDDEN_PAYLOAD_KEYS:
                assert forbidden not in payload, (kind, forbidden)


# ---------------------------------------------------------------------------
# Forbidden actions (#32)
# ---------------------------------------------------------------------------


def test_forbidden_actions_includes_critical_paths() -> None:
    expected = {
        "execute_pilot",
        "start_pilot",
        "run_pilot",
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
        "execute_pilot_via_frontend",
        "execute_pilot_via_api_endpoint",
        "approve_pilot_plan_via_api_endpoint",
    }
    assert expected.issubset(set(PHASE_6S_FORBIDDEN_ACTIONS))


# ---------------------------------------------------------------------------
# Preview never creates rows (#33)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_does_not_create_rows() -> None:
    readiness = _make_approved_phase6r_readiness(
        source_event_id="evt_phase6s_preview"
    )
    before = _row_counts()
    out = preview_phase6s_payment_dispatch_pilot_plan(
        source_readiness_id=readiness.pk
    )
    after = _row_counts()
    assert out["found"] is True
    assert before["phase6s_pilot_plan"] == after["phase6s_pilot_plan"]
