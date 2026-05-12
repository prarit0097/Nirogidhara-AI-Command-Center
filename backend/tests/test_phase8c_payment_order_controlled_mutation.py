"""Phase 8C - Controlled Real Payment -> Order Mutation tests.

Phase 8C is a CLI-only one-shot controlled mutation framework. The
fixture chain wires up Phase 7I lock + Phase 8A approved gate +
Phase 8B approved gate, then a fresh sandbox Order + Payment pair
that is proven internal/sandbox/test. Every refusal test asserts
no provider call, no business mutation, no customer notification,
no real-customer flag flip. The single happy-path execute test
runs strictly against the test database fixtures -- never against
production data.
"""
from __future__ import annotations

import importlib
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import (
    Payment,
    RazorpayPaymentOrderControlledMutationAttempt,
    RazorpayPaymentOrderControlledMutationGate,
    RazorpayPaymentOrderControlledMutationRollback,
    RazorpayPaymentOrderMutationReviewGate,
    RazorpayPaymentOrderMutationSandboxGate,
)
from apps.payments.phase7_final_audit_lock import (
    approve_phase7i_final_audit_lock,
    prepare_phase7i_final_audit_lock,
)
from apps.payments.phase8a_payment_order_mutation_sandbox import (
    approve_phase8a_payment_order_mutation_sandbox,
    dry_run_phase8a_payment_order_mutation_sandbox,
    prepare_phase8a_payment_order_mutation_sandbox,
)
from apps.payments.phase8b_payment_order_mutation_review import (
    approve_phase8b_payment_order_mutation_review_gate,
    dry_run_phase8b_payment_order_mutation_review_gate,
    prepare_phase8b_payment_order_mutation_review_gate,
    rollback_dry_run_phase8b_payment_order_mutation_review_gate,
)
from apps.payments.phase8c_payment_order_controlled_mutation import (
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_DRY_RUN_FAILED,
    AUDIT_KIND_DRY_RUN_PASSED,
    AUDIT_KIND_EXECUTED,
    AUDIT_KIND_FAILED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    AUDIT_KIND_ROLLBACK_RECORDED,
    PHASE_8C_FORBIDDEN_ACTIONS,
    approve_phase8c_payment_order_controlled_mutation,
    archive_phase8c_payment_order_controlled_mutation,
    assert_phase8c_no_unauthorized_side_effect,
    dry_run_phase8c_payment_order_controlled_mutation,
    execute_phase8c_payment_order_controlled_mutation,
    inspect_phase8c_payment_order_controlled_mutation_readiness,
    prepare_phase8c_payment_order_controlled_mutation,
    preview_phase8c_payment_order_controlled_mutation,
    reject_phase8c_payment_order_controlled_mutation,
    rollback_phase8c_payment_order_controlled_mutation,
)
from apps.shipments.models import RescueAttempt, Shipment, WorkflowStep
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from tests.test_phase7i_final_audit_lock import (
    _make_full_source_chain,
    _row_counts,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _phase8b_enabled():
    return override_settings(
        PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED=True,
        PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED=True,
    )


def _phase8c_gate_enabled():
    return override_settings(
        PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED=True,
        PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED=True,
        PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED=True,
    )


def _phase8c_execute_settings():
    return override_settings(
        PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED=True,
        PHASE8C_DIRECTOR_APPROVED_ONE_SHOT_MUTATION=True,
        PHASE8C_ALLOW_INTERNAL_ORDER_PAYMENT_MUTATION=True,
    )


def _make_approved_phase8b_gate(
    *, source_event_id: str
) -> RazorpayPaymentOrderMutationReviewGate:
    chain = _make_full_source_chain(source_event_id=source_event_id)
    prepared = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    lock_id = prepared["lock"]["id"]
    approve_phase7i_final_audit_lock(
        lock_id, reviewed_by=None, reason="Director Phase 7I lock."
    )
    with override_settings(
        PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED=True,
    ):
        prep_8a = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock_id
        )
        phase8a_gate_id = prep_8a["gate"]["id"]
        dry_run_phase8a_payment_order_mutation_sandbox(
            phase8a_gate_id,
            synthetic_order_reference=(
                f"phase8a::sandbox::ord_{source_event_id}"
            ),
        )
        approve_phase8a_payment_order_mutation_sandbox(
            phase8a_gate_id,
            reason="Director Phase 8A approve fixture.",
        )
    phase8a_gate = (
        RazorpayPaymentOrderMutationSandboxGate.objects.get(
            pk=phase8a_gate_id
        )
    )
    with _phase8b_enabled():
        prep_8b = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        phase8b_gate_id = prep_8b["gate"]["id"]
        dr = dry_run_phase8b_payment_order_mutation_review_gate(
            phase8b_gate_id,
            target_order_reference=(
                f"phase8b::review::order::{source_event_id}"
            ),
        )
        rollback_dry_run_phase8b_payment_order_mutation_review_gate(
            dr["dryRun"]["id"],
            reason=(
                "Director Phase 8B rollback dry-run for Phase 8C."
            ),
        )
        approve_phase8b_payment_order_mutation_review_gate(
            phase8b_gate_id,
            reason=(
                "Director Phase 8B approve for Phase 8C fixture."
            ),
        )
    return RazorpayPaymentOrderMutationReviewGate.objects.get(
        pk=phase8b_gate_id
    )


def _make_sandbox_order_payment(
    *, suffix: str
) -> tuple[Order, Payment]:
    order_id = f"phase8c-controlled-order-{suffix}"[:32]
    payment_id = f"phase8c-controlled-payment-{suffix}"[:32]
    order = Order.objects.create(
        id=order_id,
        customer_name="Phase 8C Sandbox",
        phone="+91-internal-test-9999",
        product="Phase 8C TEST",
        quantity=1,
        amount=100,
        payment_status=Order.PaymentStatus.PENDING,
        state="Test State",
        city="Test City",
        stage=Order.Stage.ORDER_PUNCHED,
        confirmation_notes="phase8c sandbox fixture",
    )
    payment = Payment.objects.create(
        id=payment_id,
        order_id=order.id,
        customer="Phase 8C Sandbox",
        customer_phone="",
        amount=100,
        gateway=Payment.Gateway.RAZORPAY,
        status=Payment.Status.PENDING,
        type=Payment.Type.ADVANCE,
        gateway_reference_id=f"plink_phase8c_sandbox_{suffix}",
        raw_response={"phase8c_sandbox": True},
    )
    return order, payment


def _make_real_customer_order_payment(
    *, suffix: str
) -> tuple[Order, Payment]:
    order_id = f"order_real_customer_{suffix}"[:32]
    payment_id = f"pay_real_customer_{suffix}"[:32]
    order = Order.objects.create(
        id=order_id,
        customer_name="Real Customer",
        phone="+919999999999",
        product="Real Product",
        quantity=1,
        amount=3000,
        payment_status=Order.PaymentStatus.PENDING,
        state="MH",
        city="Pune",
        stage=Order.Stage.ORDER_PUNCHED,
        confirmation_notes="",
    )
    payment = Payment.objects.create(
        id=payment_id,
        order_id=order.id,
        customer="Real Customer",
        customer_phone="+919999999999",
        amount=3000,
        gateway=Payment.Gateway.RAZORPAY,
        status=Payment.Status.PENDING,
        type=Payment.Type.ADVANCE,
        gateway_reference_id="plink_LiVE_real",
        raw_response={},
    )
    return order, payment


def _structured_signoff(
    *,
    attempt_id: int,
    phase8b_gate_id: int,
    now: datetime,
) -> str:
    begin = now - timedelta(minutes=2)
    end = now + timedelta(minutes=10)
    return (
        f"Director sign-off Phase 8C controlled mutation. "
        f"phase8c_attempt_id_{attempt_id} "
        f"phase8b_gate_id_{phase8b_gate_id} "
        f"BEGIN_UTC={begin.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"END_UTC={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )


# ---------------------------------------------------------------------------
# Audit-kind + static-file invariants
# ---------------------------------------------------------------------------


def test_phase8c_audit_kinds_within_length_budget() -> None:
    kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_DRY_RUN_PASSED,
        AUDIT_KIND_DRY_RUN_FAILED,
        AUDIT_KIND_APPROVED,
        AUDIT_KIND_EXECUTED,
        AUDIT_KIND_ROLLBACK_RECORDED,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
        AUDIT_KIND_FAILED,
    ]
    assert len(kinds) == 12
    for kind in kinds:
        assert kind.startswith("phase8c.payment_order.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_phase8c_forbidden_actions_cover_real_surface() -> None:
    forbidden = set(PHASE_8C_FORBIDDEN_ACTIONS)
    for required in (
        "call_razorpay_api",
        "call_meta_cloud_api",
        "call_delhivery_api",
        "call_vapi_api",
        "send_whatsapp_template",
        "queue_whatsapp_outbound",
        "create_awb",
        "create_shipment_row",
        "create_payment_link",
        "capture_razorpay_payment",
        "refund_razorpay_payment",
        "send_customer_notification",
        "mutate_real_customer",
        "mutate_real_lead",
        "mutate_real_shipment",
        "mutate_real_discount_offer_log",
        "approve_real_customer_automation",
        "approve_phase7e_live_b",
        "approve_phase7g_live",
        "edit_dotenv_any",
    ):
        assert required in forbidden, required


def test_phase8c_service_module_does_not_import_provider_clients() -> None:
    """Phase 8C never calls a provider at module top level. The
    ``apps.saas.utc_window`` helper IS imported inside execute via a
    local lazy import; that's allowed. Static-file scan checks
    actual import lines (not docstring mentions)."""
    src_path = importlib.import_module(
        "apps.payments.phase8c_payment_order_controlled_mutation"
    ).__file__
    with open(src_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    forbidden = [
        "from apps.shipments.integrations.delhivery_client",
        "from apps.whatsapp.services import send_freeform_text_message",
        "from apps.whatsapp.services import queue_template_message",
        "from apps.whatsapp.integrations.whatsapp.meta_cloud_client",
        "from apps.whatsapp.integrations.whatsapp import meta_cloud_client",
        "from apps.payments.integrations.razorpay_client",
        "import razorpay",
        "from dotenv",
        "import dotenv",
    ]
    for needle in forbidden:
        for line in text.splitlines():
            stripped = line.lstrip()
            if not (
                stripped.startswith("from ")
                or stripped.startswith("import ")
            ):
                continue
            if needle in stripped:
                pytest.fail(
                    f"Phase 8C service imports forbidden module: "
                    f"{needle}"
                )


# ---------------------------------------------------------------------------
# Readiness + CLI
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_readiness_command_returns_controlled_mutation_only_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_phase8c_payment_order_controlled_mutation",
        "--json", "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "8C"
    assert body["status"] == "payment_order_controlled_mutation_only"
    for key in (
        "phase8CCallsRazorpay",
        "phase8CCallsMetaCloud",
        "phase8CCallsDelhivery",
        "phase8CCallsVapi",
        "phase8CSendsWhatsApp",
        "phase8CQueuesWhatsApp",
        "phase8CCreatesShipmentRow",
        "phase8CCreatesAwb",
        "phase8CCreatesPaymentLink",
        "phase8CCapturesPayment",
        "phase8CRefundsPayment",
        "phase8CSendsCustomerNotification",
        "phase8CMutatesCustomer",
        "phase8CMutatesLead",
        "phase8CMutatesShipment",
        "phase8CMutatesDiscountOfferLog",
        "phase8CApprovesRealCustomerAutomation",
        "phase7ELiveBApproved",
        "phase7GLiveApproved",
        "frontendCanExecute",
        "apiEndpointCanExecute",
        "apiEndpointCanApprove",
    ):
        assert body[key] is False, key
    assert (
        body["executionPath"]
        == "cli_only_one_shot_controlled_mutation"
    )


@pytest.mark.django_db
def test_phase8c_readiness_reports_eligible_phase8b_when_approved() -> None:
    _make_approved_phase8b_gate(source_event_id="evt_phase8c_ready")
    out = (
        inspect_phase8c_payment_order_controlled_mutation_readiness()
    )
    assert out["eligiblePhase8BGateCount"] >= 1
    assert out["phase8CMutatesCustomer"] is False
    assert out["phase8CApprovesRealCustomerAutomation"] is False


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_preview_with_eligible_gate_emits_no_business_mutation() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_preview"
    )
    before = _row_counts()
    out = preview_phase8c_payment_order_controlled_mutation(
        phase8b_gate_id=phase8b_gate.pk
    )
    after = _row_counts()
    assert before == after
    assert out["found"] is True
    assert out["sourcePhase8BGateId"] == phase8b_gate.pk
    assert (
        RazorpayPaymentOrderControlledMutationGate.objects.count() == 0
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_PREVIEWED).exists()


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_prepare_blocked_when_env_flag_off() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_prep_off"
    )
    out = prepare_phase8c_payment_order_controlled_mutation(
        phase8b_gate_id=phase8b_gate.pk
    )
    assert out["created"] is False
    assert out["gate"] is None
    assert any(
        "PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8c_prepare_creates_gate_when_flag_on() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_prep_ok"
    )
    before = _row_counts()
    with _phase8c_gate_enabled():
        out = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
    after = _row_counts()
    assert out["created"] is True
    assert out["reused"] is False
    row = RazorpayPaymentOrderControlledMutationGate.objects.get(
        pk=out["gate"]["id"]
    )
    assert (
        row.status
        == RazorpayPaymentOrderControlledMutationGate.Status.PENDING_MANUAL_REVIEW
    )
    assert row.controlled_mutation_only is True
    assert row.real_customer_allowed is False
    assert row.customer_notification_allowed is False
    assert row.whatsapp_allowed is False
    assert row.courier_allowed is False
    assert row.provider_call_allowed is False
    assert row.shipment_creation_allowed is False
    assert row.payment_capture_allowed is False
    assert row.refund_allowed is False
    assert row.rollback_required is True
    assert row.director_signoff_required is True
    assert row.structured_utc_window_required is True
    assert before == after
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_PREPARED).exists()


@pytest.mark.django_db
def test_phase8c_prepare_idempotent_on_same_phase8b_gate() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_prep_idem"
    )
    with _phase8c_gate_enabled():
        first = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        second = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert (
        RazorpayPaymentOrderControlledMutationGate.objects.filter(
            source_phase8b_gate=phase8b_gate
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_phase8c_prepare_blocks_if_phase8b_not_approved() -> None:
    # Build chain but stop Phase 8B at dry_run_passed.
    chain = _make_full_source_chain(
        source_event_id="evt_phase8c_unapproved_8b"
    )
    prepared = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    approve_phase7i_final_audit_lock(
        prepared["lock"]["id"],
        reviewed_by=None,
        reason="Lock.",
    )
    with override_settings(
        PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED=True,
    ):
        prep_8a = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=prepared["lock"]["id"]
        )
        dry_run_phase8a_payment_order_mutation_sandbox(
            prep_8a["gate"]["id"],
            synthetic_order_reference=(
                "phase8a::sandbox::ord_no_8b_approve"
            ),
        )
        approve_phase8a_payment_order_mutation_sandbox(
            prep_8a["gate"]["id"],
            reason="Phase 8A approve fixture.",
        )
    with _phase8b_enabled():
        prep_8b = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=prep_8a["gate"]["id"]
        )
        dry_run_phase8b_payment_order_mutation_review_gate(
            prep_8b["gate"]["id"],
            target_order_reference=(
                "phase8b::review::order::no_phase8b_approve"
            ),
        )
        # NOTE: no approve_phase8b_…
    with _phase8c_gate_enabled():
        out = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=prep_8b["gate"]["id"]
        )
    assert out["created"] is False
    assert any(
        "must_be_approved_for_future_phase8c_controlled_mutation_review"
        in b
        for b in out["blockers"]
    )


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_dry_run_blocks_without_target_ids() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_dr_no_ids"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        out = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id="",
            target_payment_id="",
            target_order_reference="",
            target_payment_reference="",
        )
    assert out["ok"] is False
    assert any(
        "target_order_id_required" in b for b in out["blockers"]
    )
    assert any(
        "target_payment_id_required" in b for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8c_dry_run_blocks_unsafe_target_order_payment() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_dr_unsafe"
    )
    real_order, real_payment = _make_real_customer_order_payment(
        suffix="unsafe"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        out = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=real_order.id,
            target_payment_id=real_payment.id,
            target_order_reference=(
                "phase8c::controlled::order::unsafe"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::unsafe"
            ),
        )
    assert out["ok"] is False
    assert any(
        "phase8c_target_order_not_proven_internal_sandbox" in b
        for b in out["blockers"]
    )
    assert any(
        "phase8c_target_payment_not_proven_internal_sandbox" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8c_dry_run_passes_for_internal_sandbox_fixture() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_dr_ok"
    )
    order, payment = _make_sandbox_order_payment(suffix="dr_ok")
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        before = _row_counts()
        out = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::dr_ok"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::dr_ok"
            ),
        )
        after = _row_counts()
    assert out["ok"] is True
    attempt = out["attempt"]
    assert attempt["status"] == "pending_director_signoff"
    assert attempt["targetOrderId"] == order.id
    assert attempt["targetPaymentId"] == payment.id
    assert attempt["orderMutationWasMade"] is False
    assert attempt["paymentMutationWasMade"] is False
    assert attempt["customerNotificationSent"] is False
    assert attempt["whatsAppSent"] is False
    assert attempt["courierCalled"] is False
    assert attempt["providerCallAttempted"] is False
    assert attempt["shipmentCreated"] is False
    assert before == after
    gate = RazorpayPaymentOrderControlledMutationGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderControlledMutationGate.Status.DRY_RUN_PASSED
    )
    assert gate.dry_run_passed is True
    # Status on the target rows is unchanged.
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == Order.PaymentStatus.PENDING
    assert payment.status == Payment.Status.PENDING
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_DRY_RUN_PASSED
    ).exists()


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_approve_refuses_without_dry_run() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_appr_no_dr"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        out = approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director Phase 8C approve.",
        )
    assert out["ok"] is False


@pytest.mark.django_db
def test_phase8c_approve_succeeds_after_dry_run() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_appr_ok"
    )
    order, payment = _make_sandbox_order_payment(suffix="appr_ok")
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::appr_ok"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::appr_ok"
            ),
        )
        before = _row_counts()
        out = approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director Phase 8C approve.",
        )
        after = _row_counts()
    assert out["ok"] is True
    assert before == after
    gate = RazorpayPaymentOrderControlledMutationGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderControlledMutationGate.Status.APPROVED_FOR_ONE_SHOT_CONTROLLED_MUTATION
    )
    # Attempt should also have been promoted.
    promoted = gate.attempts.filter(
        status=(
            RazorpayPaymentOrderControlledMutationAttempt.Status.APPROVED_FOR_ONE_SHOT_MUTATION
        )
    )
    assert promoted.count() == 1
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_APPROVED).exists()


# ---------------------------------------------------------------------------
# Execute (test DB only)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_execute_refuses_missing_env_flags() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_exec_no_flags"
    )
    order, payment = _make_sandbox_order_payment(
        suffix="exec_no_flags"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        out = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::exec_no_flags"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::exec_no_flags"
            ),
        )
        approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director approve.",
        )
    attempt_id = out["attempt"]["id"]
    # Only the gate-enabled flag is on; director-approved and allow-
    # internal flags are still False -> execute must refuse.
    now = datetime.now(timezone.utc)
    result = execute_phase8c_payment_order_controlled_mutation(
        attempt_id,
        director_signoff=_structured_signoff(
            attempt_id=attempt_id,
            phase8b_gate_id=phase8b_gate.pk,
            now=now,
        ),
        operator_name="Director Test",
        confirm_one_shot_mutation=True,
        now=now,
    )
    assert result["ok"] is False
    assert any(
        "PHASE8C_DIRECTOR_APPROVED_ONE_SHOT_MUTATION_must_be_true"
        in b
        for b in result["blockers"]
    )
    assert any(
        "PHASE8C_ALLOW_INTERNAL_ORDER_PAYMENT_MUTATION_must_be_true"
        in b
        for b in result["blockers"]
    )
    # Status on the target rows is unchanged.
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == Order.PaymentStatus.PENDING
    assert payment.status == Payment.Status.PENDING


@pytest.mark.django_db
def test_phase8c_execute_refuses_missing_structured_utc_window() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_exec_no_window"
    )
    order, payment = _make_sandbox_order_payment(
        suffix="exec_no_window"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        out = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::exec_no_window"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::exec_no_window"
            ),
        )
        approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director approve.",
        )
    attempt_id = out["attempt"]["id"]
    with _phase8c_execute_settings():
        result = execute_phase8c_payment_order_controlled_mutation(
            attempt_id,
            director_signoff=(
                f"phase8c_attempt_id_{attempt_id} "
                f"phase8b_gate_id_{phase8b_gate.pk} "
                "no structured BEGIN_UTC / END_UTC markers"
            ),
            operator_name="Director Test",
            confirm_one_shot_mutation=True,
        )
    assert result["ok"] is False
    assert any(
        "director_signoff_missing_structured_utc_window" in b
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_phase8c_execute_refuses_outside_window() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_exec_stale"
    )
    order, payment = _make_sandbox_order_payment(
        suffix="exec_stale"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        out = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::exec_stale"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::exec_stale"
            ),
        )
        approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director approve.",
        )
    attempt_id = out["attempt"]["id"]
    now = datetime.now(timezone.utc)
    # The window is FAR in the past => stale + now>window_end.
    past_signoff = (
        f"phase8c_attempt_id_{attempt_id} "
        f"phase8b_gate_id_{phase8b_gate.pk} "
        "BEGIN_UTC=2020-01-01T00:00:00Z "
        "END_UTC=2020-01-01T00:10:00Z"
    )
    with _phase8c_execute_settings():
        result = execute_phase8c_payment_order_controlled_mutation(
            attempt_id,
            director_signoff=past_signoff,
            operator_name="Director Test",
            confirm_one_shot_mutation=True,
            now=now,
        )
    assert result["ok"] is False
    # The 2020 window is BOTH stale (>24h old) AND ended in the past.
    assert any(
        "phase8c_director_signoff_window_stale" in b
        or "phase8c_now_outside_director_signoff_utc_window_after_end"
        in b
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_phase8c_execute_refuses_unsafe_target() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_exec_unsafe"
    )
    order, payment = _make_sandbox_order_payment(
        suffix="exec_unsafe"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        out = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::exec_unsafe"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::exec_unsafe"
            ),
        )
        approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director approve.",
        )
    attempt_id = out["attempt"]["id"]
    # Tamper the safety proof off the target rows AFTER approve.
    order.confirmation_notes = ""
    order.id_internal_marker_cleared = True  # noqa: just memo
    order.save(update_fields=["confirmation_notes"])
    payment.raw_response = {}
    payment.gateway_reference_id = "plink_LiVE_clean"
    payment.save(
        update_fields=["raw_response", "gateway_reference_id"]
    )
    # The Order.id and Payment.id (PKs) still contain the
    # phase8c-controlled-* markers, so safety check via id still
    # passes. Force the id-based marker to NOT be present by
    # creating a *new* sandbox pair where the PK does NOT contain
    # the marker.
    bad_order = Order.objects.create(
        id="not-marked-order-1",
        customer_name="Bad target",
        phone="+91",
        product="X",
        amount=1,
        payment_status=Order.PaymentStatus.PENDING,
        state="x",
        city="x",
        stage=Order.Stage.ORDER_PUNCHED,
        confirmation_notes="",
    )
    bad_payment = Payment.objects.create(
        id="not-marked-payment-1",
        order_id=bad_order.id,
        customer="bad",
        amount=1,
        gateway=Payment.Gateway.RAZORPAY,
        status=Payment.Status.PENDING,
        type=Payment.Type.ADVANCE,
        gateway_reference_id="plink_clean",
        raw_response={},
    )
    # Replace the attempt's target ids with the unsafe ones.
    attempt = (
        RazorpayPaymentOrderControlledMutationAttempt.objects.get(
            pk=attempt_id
        )
    )
    attempt.target_order_id = bad_order.id
    attempt.target_payment_id = bad_payment.id
    attempt.save(
        update_fields=[
            "target_order_id",
            "target_payment_id",
            "updated_at",
        ]
    )
    now = datetime.now(timezone.utc)
    with _phase8c_execute_settings():
        result = execute_phase8c_payment_order_controlled_mutation(
            attempt_id,
            director_signoff=_structured_signoff(
                attempt_id=attempt_id,
                phase8b_gate_id=phase8b_gate.pk,
                now=now,
            ),
            operator_name="Director Test",
            confirm_one_shot_mutation=True,
            now=now,
        )
    assert result["ok"] is False
    assert any(
        "not_proven_internal_sandbox" in b
        for b in result["blockers"]
    )
    # Target rows untouched.
    bad_order.refresh_from_db()
    bad_payment.refresh_from_db()
    assert bad_order.payment_status == Order.PaymentStatus.PENDING
    assert bad_payment.status == Payment.Status.PENDING


@pytest.mark.django_db
def test_phase8c_execute_succeeds_in_test_db_only_and_mutates_only_target() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_exec_ok"
    )
    order, payment = _make_sandbox_order_payment(suffix="exec_ok")
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        dr = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::exec_ok"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::exec_ok"
            ),
        )
        approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director approve.",
        )
    attempt_id = dr["attempt"]["id"]
    before = _row_counts()
    now = datetime.now(timezone.utc)
    with _phase8c_execute_settings():
        result = execute_phase8c_payment_order_controlled_mutation(
            attempt_id,
            director_signoff=_structured_signoff(
                attempt_id=attempt_id,
                phase8b_gate_id=phase8b_gate.pk,
                now=now,
            ),
            operator_name="Director Test",
            confirm_one_shot_mutation=True,
            now=now,
        )
    after = _row_counts()
    assert result["ok"] is True
    # Row counts unchanged across every protected business table.
    assert before == after
    attempt = (
        RazorpayPaymentOrderControlledMutationAttempt.objects.get(
            pk=attempt_id
        )
    )
    assert (
        attempt.status
        == RazorpayPaymentOrderControlledMutationAttempt.Status.EXECUTED
    )
    assert attempt.order_mutation_was_made is True
    assert attempt.payment_mutation_was_made is True
    assert attempt.business_mutation_was_made is True
    # Locked-False contract intact.
    assert attempt.customer_notification_sent is False
    assert attempt.whatsapp_sent is False
    assert attempt.courier_called is False
    assert attempt.provider_call_attempted is False
    assert attempt.shipment_created is False
    # Sign-off captured.
    assert attempt.director_signoff_text_hash != ""
    assert attempt.recorded_signoff_window_valid is True
    # The target rows' STATUS fields are mutated to "Paid".
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == Order.PaymentStatus.PAID
    assert payment.status == Payment.Status.PAID
    # Gate moves to executed.
    gate = RazorpayPaymentOrderControlledMutationGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderControlledMutationGate.Status.EXECUTED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_EXECUTED).exists()


@pytest.mark.django_db
def test_phase8c_execute_does_not_create_shipment_or_send_whatsapp() -> None:
    """The execute happy-path proves zero growth across Shipment,
    WhatsAppMessage, WhatsAppLifecycleEvent, WhatsAppHandoffToCall,
    Customer, Lead, DiscountOfferLog, WorkflowStep, RescueAttempt
    tables. Row counts must be identical before and after."""
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_no_side_effects"
    )
    order, payment = _make_sandbox_order_payment(
        suffix="no_side_effects"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        dr = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::no_side"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::no_side"
            ),
        )
        approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director approve.",
        )
    counts_before = {
        "shipment": Shipment.objects.count(),
        "whatsapp_message": WhatsAppMessage.objects.count(),
        "whatsapp_lifecycle_event": (
            WhatsAppLifecycleEvent.objects.count()
        ),
        "whatsapp_handoff": WhatsAppHandoffToCall.objects.count(),
        "customer": Customer.objects.count(),
        "lead": Lead.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "workflow_step": WorkflowStep.objects.count(),
        "rescue_attempt": RescueAttempt.objects.count(),
    }
    now = datetime.now(timezone.utc)
    attempt_id = dr["attempt"]["id"]
    with _phase8c_execute_settings():
        execute_phase8c_payment_order_controlled_mutation(
            attempt_id,
            director_signoff=_structured_signoff(
                attempt_id=attempt_id,
                phase8b_gate_id=phase8b_gate.pk,
                now=now,
            ),
            operator_name="Director Test",
            confirm_one_shot_mutation=True,
            now=now,
        )
    counts_after = {
        "shipment": Shipment.objects.count(),
        "whatsapp_message": WhatsAppMessage.objects.count(),
        "whatsapp_lifecycle_event": (
            WhatsAppLifecycleEvent.objects.count()
        ),
        "whatsapp_handoff": WhatsAppHandoffToCall.objects.count(),
        "customer": Customer.objects.count(),
        "lead": Lead.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "workflow_step": WorkflowStep.objects.count(),
        "rescue_attempt": RescueAttempt.objects.count(),
    }
    assert counts_before == counts_after


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_rollback_restores_old_statuses_in_test_db() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_rb_ok"
    )
    order, payment = _make_sandbox_order_payment(suffix="rb_ok")
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        dr = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::rb_ok"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::rb_ok"
            ),
        )
        approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director approve.",
        )
    attempt_id = dr["attempt"]["id"]
    now = datetime.now(timezone.utc)
    with _phase8c_execute_settings():
        execute_phase8c_payment_order_controlled_mutation(
            attempt_id,
            director_signoff=_structured_signoff(
                attempt_id=attempt_id,
                phase8b_gate_id=phase8b_gate.pk,
                now=now,
            ),
            operator_name="Director Test",
            confirm_one_shot_mutation=True,
            now=now,
        )
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == Order.PaymentStatus.PAID
    assert payment.status == Payment.Status.PAID

    before = _row_counts()
    result = rollback_phase8c_payment_order_controlled_mutation(
        attempt_id, reason="Director rollback."
    )
    after = _row_counts()
    assert result["ok"] is True
    rollback = result["rollback"]
    assert rollback["status"] == "rollback_recorded"
    assert rollback["rollbackWasMade"] is True
    # Restored statuses are Pending (the original).
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == Order.PaymentStatus.PENDING
    assert payment.status == Payment.Status.PENDING
    assert before == after  # row counts unchanged
    attempt = (
        RazorpayPaymentOrderControlledMutationAttempt.objects.get(
            pk=attempt_id
        )
    )
    assert (
        attempt.status
        == RazorpayPaymentOrderControlledMutationAttempt.Status.ROLLED_BACK
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_ROLLBACK_RECORDED
    ).exists()


@pytest.mark.django_db
def test_phase8c_rollback_does_not_call_providers_or_send_notification() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_rb_no_send"
    )
    order, payment = _make_sandbox_order_payment(
        suffix="rb_no_send"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        dr = dry_run_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::rb_no_send"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::rb_no_send"
            ),
        )
        approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director approve.",
        )
    attempt_id = dr["attempt"]["id"]
    now = datetime.now(timezone.utc)
    with _phase8c_execute_settings():
        execute_phase8c_payment_order_controlled_mutation(
            attempt_id,
            director_signoff=_structured_signoff(
                attempt_id=attempt_id,
                phase8b_gate_id=phase8b_gate.pk,
                now=now,
            ),
            operator_name="Director Test",
            confirm_one_shot_mutation=True,
            now=now,
        )
    rollback_phase8c_payment_order_controlled_mutation(
        attempt_id, reason="Director rollback."
    )
    rollback = (
        RazorpayPaymentOrderControlledMutationRollback.objects.filter(
            attempt_id=attempt_id
        ).first()
    )
    assert rollback is not None
    assert rollback.customer_notification_sent is False
    assert rollback.whatsapp_sent is False
    assert rollback.courier_called is False
    assert rollback.provider_call_attempted is False


# ---------------------------------------------------------------------------
# Reject / archive
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_reject_requires_reason_and_marks_status() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_reject"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        missing = reject_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"], reason=""
        )
        assert missing["ok"] is False
        out = reject_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director Phase 8C reject.",
        )
    assert out["ok"] is True
    gate = RazorpayPaymentOrderControlledMutationGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderControlledMutationGate.Status.REJECTED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).exists()


@pytest.mark.django_db
def test_phase8c_archive_records_status_and_writes_audit() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_archive"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
        out = archive_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director Phase 8C archive.",
        )
    assert out["ok"] is True
    gate = RazorpayPaymentOrderControlledMutationGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderControlledMutationGate.Status.ARCHIVED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_ARCHIVED).exists()


# ---------------------------------------------------------------------------
# Defensive invariant guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_assert_no_unauthorized_side_effect_raises_on_flipped_flag() -> None:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="evt_phase8c_guard"
    )
    with _phase8c_gate_enabled():
        prep = prepare_phase8c_payment_order_controlled_mutation(
            phase8b_gate_id=phase8b_gate.pk
        )
    gate = RazorpayPaymentOrderControlledMutationGate.objects.get(
        pk=prep["gate"]["id"]
    )
    gate.real_customer_allowed = True
    before = _row_counts()
    with pytest.raises(ValueError):
        assert_phase8c_no_unauthorized_side_effect(
            gate, before_counts=before
        )


# ---------------------------------------------------------------------------
# API endpoint shape + 405 enforcement
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, django_user_model):
    from rest_framework.test import APIClient

    user = django_user_model.objects.create_user(
        username="phase8c_admin",
        email="phase8c_admin@example.com",
        password="ignored-by-force-auth",
    )
    user.is_staff = True
    user.is_superuser = True
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_phase8c_readiness_endpoint_returns_safe_off_shape(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8c-payment-order-controlled-mutation-readiness"
    )
    r = admin_client.get(url)
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] == "8C"
    assert data["phase8CGateEnabled"] is False
    assert data["phase8CDirectorApproved"] is False
    assert data["phase8CAllowInternalMutation"] is False
    assert data["executionPath"] == (
        "cli_only_one_shot_controlled_mutation"
    )
    assert data["frontendCanExecute"] is False
    assert data["apiEndpointCanExecute"] is False
    assert data["apiEndpointCanApprove"] is False


@pytest.mark.django_db
def test_phase8c_endpoints_block_write_methods(admin_client) -> None:
    for path in (
        "saas-phase8c-payment-order-controlled-mutation-readiness",
        "saas-phase8c-payment-order-controlled-mutation-gates",
        "saas-phase8c-payment-order-controlled-mutation-preview",
    ):
        url = reverse(path)
        for method in ("post", "patch", "delete"):
            r = getattr(admin_client, method)(
                url, {} if method != "delete" else None
            )
            assert r.status_code == 405, (path, method, r.status_code)


@pytest.mark.django_db
def test_phase8c_preview_endpoint_requires_phase8b_gate_id(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8c-payment-order-controlled-mutation-preview"
    )
    assert admin_client.get(url).status_code == 400
    assert (
        admin_client.get(url + "?phase8b_gate_id=0").status_code == 400
    )
    assert (
        admin_client.get(
            url + "?phase8b_gate_id=999999"
        ).status_code
        == 200
    )


@pytest.mark.django_db
def test_phase8c_gate_detail_returns_404_when_missing(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8c-payment-order-controlled-mutation-gate-detail",
        kwargs={"pk": 9999},
    )
    assert admin_client.get(url).status_code == 404


@pytest.mark.django_db
def test_phase8c_attempts_endpoint_returns_404_when_gate_missing(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8c-payment-order-controlled-mutation-attempts",
        kwargs={"gate_id": 9999},
    )
    assert admin_client.get(url).status_code == 404


@pytest.mark.django_db
def test_phase8c_rollbacks_endpoint_returns_404_when_attempt_missing(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8c-payment-order-controlled-mutation-rollbacks",
        kwargs={"attempt_id": 9999},
    )
    assert admin_client.get(url).status_code == 404
