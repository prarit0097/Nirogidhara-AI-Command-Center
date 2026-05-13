"""Phase 8E - Real Customer Payment -> Order Mutation Pilot tests.

Phase 8E is review / dry-run only against ONE real customer Order
+ Payment candidate. The fixture chain wires up Phase 7I -> 8A ->
8B -> 8C execute+rollback -> 8D locked, then exercises Phase 8E
preview / prepare / select-candidate / dry-run / approve / reject
/ archive paths. Every refusal test asserts no provider call, no
business mutation, no customer notification, no PII leak.
"""
from __future__ import annotations

import importlib
import io
import json

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.orders.models import Order
from apps.payments.models import (
    Payment,
    RazorpayPaymentOrderControlledMutationEvidenceLock,
    RazorpayRealCustomerPaymentOrderMutationCandidate,
    RazorpayRealCustomerPaymentOrderMutationPilotDryRun,
    RazorpayRealCustomerPaymentOrderMutationPilotGate,
)
from apps.payments.phase8d_controlled_mutation_evidence_lock import (
    lock_phase8d_controlled_mutation_evidence_lock,
    prepare_phase8d_controlled_mutation_evidence_lock,
)
from apps.payments.phase8e_real_customer_payment_order_pilot import (
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_CANDIDATE_SELECTED,
    AUDIT_KIND_DRY_RUN_FAILED,
    AUDIT_KIND_DRY_RUN_PASSED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    PHASE_8E_FORBIDDEN_ACTIONS,
    PHASE_8E_FORBIDDEN_PAYLOAD_KEYS,
    _mask_customer_name,
    _mask_phone_last4,
    approve_phase8e_real_customer_payment_order_pilot,
    archive_phase8e_real_customer_payment_order_pilot,
    assert_phase8e_no_business_mutation,
    dry_run_phase8e_real_customer_payment_order_pilot,
    inspect_phase8e_real_customer_payment_order_pilot_readiness,
    prepare_phase8e_real_customer_payment_order_pilot,
    preview_phase8e_real_customer_payment_order_pilot,
    reject_phase8e_real_customer_payment_order_pilot,
    select_phase8e_real_customer_candidate,
)
from tests.test_phase7i_final_audit_lock import _row_counts
from tests.test_phase8c_payment_order_controlled_mutation import (
    _make_real_customer_order_payment,
    _make_sandbox_order_payment,
)
from tests.test_phase8d_controlled_mutation_evidence_lock import (
    _make_phase8c_chain_in_rolled_back_state,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _phase8e_enabled():
    return override_settings(
        PHASE8E_REAL_CUSTOMER_PAYMENT_ORDER_PILOT_ENABLED=True,
    )


def _make_locked_phase8d(
    *, source_event_id: str
) -> RazorpayPaymentOrderControlledMutationEvidenceLock:
    """Build the full Phase 7I -> 8A -> 8B -> 8C execute+rollback
    -> 8D LOCKED chain. Returns the locked Phase 8D row."""
    gate, _attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id=source_event_id
    )
    prepared = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    lock_phase8d_controlled_mutation_evidence_lock(
        prepared["lock"]["id"],
        reviewed_by=None,
        reason="Director Phase 8D lock for Phase 8E fixture.",
    )
    return (
        RazorpayPaymentOrderControlledMutationEvidenceLock.objects.get(
            pk=prepared["lock"]["id"]
        )
    )


def _make_pending_real_customer_pair(
    *, suffix: str
) -> tuple[Order, Payment]:
    """Real-customer Order/Payment pair both at Pending status, NO
    Phase 8C sandbox markers anywhere (the candidate is real)."""
    order_id = f"order_real_pending_{suffix}"[:32]
    payment_id = f"pay_real_pending_{suffix}"[:32]
    order = Order.objects.create(
        id=order_id,
        customer_name="Prarit Sidana",
        phone="+919876543210",
        product="Nirogidhara Weight Management",
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
        customer="Prarit Sidana",
        customer_phone="+919876543210",
        customer_email="prarit@example.com",
        amount=3000,
        gateway=Payment.Gateway.RAZORPAY,
        status=Payment.Status.PENDING,
        type=Payment.Type.ADVANCE,
        gateway_reference_id="plink_RealLiveSafeRef",
        raw_response={"gateway_event_id": "evt_real_test", "secret": "leaky"},
    )
    return order, payment


# ---------------------------------------------------------------------------
# Audit-kind + static-file invariants
# ---------------------------------------------------------------------------


def test_phase8e_audit_kinds_within_length_budget() -> None:
    kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_CANDIDATE_SELECTED,
        AUDIT_KIND_DRY_RUN_PASSED,
        AUDIT_KIND_DRY_RUN_FAILED,
        AUDIT_KIND_APPROVED,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
    ]
    assert len(kinds) == 10
    for kind in kinds:
        assert kind.startswith("phase8e.pilot.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_phase8e_forbidden_actions_cover_real_surface() -> None:
    forbidden = set(PHASE_8E_FORBIDDEN_ACTIONS)
    for required in (
        "execute_real_customer_mutation",
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
        "mutate_real_order_status",
        "mutate_real_order_payment_status",
        "mutate_real_payment_status",
        "approve_phase8f_real_customer_mutation",
        "edit_dotenv_any",
    ):
        assert required in forbidden, required


def test_phase8e_service_module_does_not_import_provider_clients() -> None:
    src_path = importlib.import_module(
        "apps.payments.phase8e_real_customer_payment_order_pilot"
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
                    f"Phase 8E service imports forbidden module: "
                    f"{needle}"
                )


def test_phase8e_forbidden_payload_keys_cover_pii_surface() -> None:
    forbidden = set(PHASE_8E_FORBIDDEN_PAYLOAD_KEYS)
    for required in (
        "phone",
        "customer_phone",
        "email",
        "customer_email",
        "address",
        "card",
        "raw_response",
        "raw_payload",
        "gateway_reference_id",
        "payment_url",
        "customer_name",
        "META_WA_TOKEN",
        "RAZORPAY_KEY_SECRET",
    ):
        assert required in forbidden, required


# ---------------------------------------------------------------------------
# PII masking helpers
# ---------------------------------------------------------------------------


def test_phase8e_mask_phone_last4_extracts_last_four_digits() -> None:
    assert _mask_phone_last4("+91 98765 43210") == "3210"
    assert _mask_phone_last4("9876543210") == "3210"
    assert _mask_phone_last4("123") == ""
    assert _mask_phone_last4("") == ""


def test_phase8e_mask_customer_name_masks_all_but_first_letter() -> None:
    assert _mask_customer_name("Prarit Sidana") == "P***** S*****"
    assert _mask_customer_name("X") == "X"
    assert _mask_customer_name("") == ""


# ---------------------------------------------------------------------------
# Readiness + CLI
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8e_readiness_command_returns_review_only_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_phase8e_real_customer_payment_order_pilot",
        "--json", "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "8E"
    assert body["status"] == "real_customer_payment_order_pilot_review_only"
    for key in (
        "phase8ECallsRazorpay",
        "phase8ECallsMetaCloud",
        "phase8ECallsDelhivery",
        "phase8ECallsVapi",
        "phase8ESendsWhatsApp",
        "phase8EQueuesWhatsApp",
        "phase8ECreatesShipmentRow",
        "phase8ECreatesAwb",
        "phase8ECreatesPaymentLink",
        "phase8ECapturesPayment",
        "phase8ERefundsPayment",
        "phase8ESendsCustomerNotification",
        "phase8EMutatesOrder",
        "phase8EMutatesPayment",
        "phase8EMutatesCustomer",
        "phase8EMutatesLead",
        "phase8EMutatesShipment",
        "phase8EMutatesDiscountOfferLog",
        "phase8EMutatesWhatsAppMessage",
        "phase8EApprovesRealCustomerAutomation",
        "phase8FApproved",
        "phase7ELiveBApproved",
        "phase7GLiveApproved",
        "frontendCanExecute",
        "apiEndpointCanExecute",
        "apiEndpointCanApprove",
    ):
        assert body[key] is False, key
    assert (
        body["executionPath"]
        == "review_dry_run_only_cli_only_no_execute"
    )


@pytest.mark.django_db
def test_phase8e_readiness_reports_eligible_phase8d_when_locked() -> None:
    _make_locked_phase8d(source_event_id="phase8e_ready")
    out = (
        inspect_phase8e_real_customer_payment_order_pilot_readiness()
    )
    assert out["eligiblePhase8DLockCount"] >= 1
    assert out["phase8EMutatesOrder"] is False
    assert out["phase8EApprovesRealCustomerAutomation"] is False


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8e_preview_eligible_chain_emits_no_business_mutation() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_preview")
    before = _row_counts()
    out = preview_phase8e_real_customer_payment_order_pilot(
        phase8d_lock_id=lock.pk
    )
    after = _row_counts()
    assert before == after
    assert out["found"] is True
    assert out["sourcePhase8DLockId"] == lock.pk
    assert (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.count()
        == 0
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_PREVIEWED).exists()


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8e_prepare_blocked_when_env_flag_off() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_prep_off")
    out = prepare_phase8e_real_customer_payment_order_pilot(
        phase8d_lock_id=lock.pk
    )
    assert out["created"] is False
    assert out["gate"] is None
    assert any(
        "PHASE8E_REAL_CUSTOMER_PAYMENT_ORDER_PILOT_ENABLED" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8e_prepare_creates_gate_when_flag_on() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_prep_ok")
    before = _row_counts()
    with _phase8e_enabled():
        out = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
    after = _row_counts()
    assert out["created"] is True
    assert out["reused"] is False
    assert before == after
    gate = RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.get(
        pk=out["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.PENDING_MANUAL_REVIEW
    )
    assert gate.real_customer_pilot_only is True
    assert gate.real_mutation_allowed is False
    assert gate.real_order_mutation_allowed is False
    assert gate.real_payment_mutation_allowed is False
    assert gate.customer_notification_allowed is False
    assert gate.whatsapp_allowed is False
    assert gate.courier_allowed is False
    assert gate.provider_call_allowed is False
    assert gate.phase8f_required is True
    assert gate.rollback_required is True
    assert gate.director_signoff_required is True
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_PREPARED).exists()


@pytest.mark.django_db
def test_phase8e_prepare_idempotent_on_same_phase8d_lock() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_prep_idem")
    with _phase8e_enabled():
        first = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        second = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
            source_phase8d_lock=lock
        ).count()
        == 1
    )


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8e_candidate_selection_blocks_when_payment_order_id_mismatch() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_cand_mismatch")
    order, payment = _make_pending_real_customer_pair(suffix="mismatch")
    # Tamper payment.order_id so it no longer matches Order.id.
    payment.order_id = "some_other_order"
    payment.save(update_fields=["order_id"])
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        out = select_phase8e_real_customer_candidate(
            prep["gate"]["id"],
            order_id=order.id,
            payment_id=payment.id,
        )
    assert out["ok"] is False
    assert any(
        "phase8e_candidate_payment_order_id_must_match_order_id" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8e_candidate_selection_blocks_phase8c_sandbox_row() -> None:
    """Phase 8C sandbox markers (in id / confirmation_notes /
    raw_response.phase8c_sandbox) MUST be rejected: Phase 8E is for
    real-customer review, not sandbox fixture."""
    # Different suffix prefixes for the Phase 8D fixture chain
    # and the standalone sandbox pair we'll try to select, so the
    # Order.id strings don't collide once truncated to 32 chars.
    lock = _make_locked_phase8d(source_event_id="phase8e_cand_sbx_chain")
    order, payment = _make_sandbox_order_payment(suffix="standalone_sbx")
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        out = select_phase8e_real_customer_candidate(
            prep["gate"]["id"],
            order_id=order.id,
            payment_id=payment.id,
        )
    assert out["ok"] is False
    assert any(
        "phase8e_candidate_must_not_be_phase8c_sandbox_row" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8e_candidate_selection_blocks_terminal_order_or_payment_status() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_cand_terminal")
    order, payment = _make_pending_real_customer_pair(suffix="terminal")
    # Mark the order as already DELIVERED (terminal).
    order.stage = Order.Stage.DELIVERED
    order.save(update_fields=["stage"])
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        out = select_phase8e_real_customer_candidate(
            prep["gate"]["id"],
            order_id=order.id,
            payment_id=payment.id,
        )
    assert out["ok"] is False
    assert any(
        "phase8e_candidate_order_stage_terminal_was_" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8e_candidate_masks_phone_to_last4_only() -> None:
    """The persisted candidate row carries only last-4 phone and
    the masked customer name -- never the raw phone or email."""
    lock = _make_locked_phase8d(source_event_id="phase8e_cand_mask")
    order, payment = _make_pending_real_customer_pair(suffix="mask")
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        out = select_phase8e_real_customer_candidate(
            prep["gate"]["id"],
            order_id=order.id,
            payment_id=payment.id,
        )
    cand = (
        RazorpayRealCustomerPaymentOrderMutationCandidate.objects.get(
            pk=out["candidate"]["id"]
        )
    )
    assert cand.order_phone_last4 == "3210"
    assert cand.order_customer_name_masked == "P***** S*****"
    # Raw phone / email / address must not appear in the candidate
    # row in any field.
    fields_to_scan = (
        cand.order_customer_name_masked,
        cand.order_phone_last4,
        cand.payment_gateway,
        cand.payment_reference,
        cand.order_current_payment_status,
        cand.payment_current_status,
    )
    for value in fields_to_scan:
        assert "+919876543210" not in (value or "")
        assert "9876543210" not in (value or "")
        assert "prarit@example.com" not in (value or "")
    # Validation must have passed for a clean real-customer pair.
    assert cand.candidate_validation_passed is True


@pytest.mark.django_db
def test_phase8e_candidate_does_not_expose_raw_provider_payload() -> None:
    """The candidate row + serializer + audit emit must never carry
    Payment.raw_response (which the test fixture deliberately
    pollutes with a `secret` key)."""
    lock = _make_locked_phase8d(source_event_id="phase8e_cand_raw")
    order, payment = _make_pending_real_customer_pair(suffix="raw")
    assert payment.raw_response.get("secret") == "leaky"
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        out = select_phase8e_real_customer_candidate(
            prep["gate"]["id"],
            order_id=order.id,
            payment_id=payment.id,
        )
    candidate_payload = json.dumps(out["candidate"] or {})
    # raw_response payload never serialized.
    assert "raw_response" not in candidate_payload
    assert "secret" not in candidate_payload
    assert "leaky" not in candidate_payload
    # gateway_reference_id is truncated to a prefix only.
    assert "plink_Re" in candidate_payload  # first 8 chars of "plink_RealLiveSafeRef"
    assert "plink_RealLiveSafeRef" not in candidate_payload

    # Audit payload also scrubs the raw fields.
    audit = AuditEvent.objects.filter(
        kind=AUDIT_KIND_CANDIDATE_SELECTED
    ).latest("occurred_at")
    audit_text = json.dumps(audit.payload or {})
    assert "+919876543210" not in audit_text
    assert "prarit@example.com" not in audit_text
    assert "raw_response" not in audit_text
    assert "secret" not in audit_text
    assert "leaky" not in audit_text


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8e_dry_run_passes_with_valid_candidate_and_no_mutation() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_dr_ok")
    order, payment = _make_pending_real_customer_pair(suffix="dr_ok")
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        sel = select_phase8e_real_customer_candidate(
            prep["gate"]["id"],
            order_id=order.id,
            payment_id=payment.id,
        )
        before = _row_counts()
        out = dry_run_phase8e_real_customer_payment_order_pilot(
            prep["gate"]["id"],
            candidate_id=sel["candidate"]["id"],
        )
        after = _row_counts()
    assert out["ok"] is True
    assert out["dryRun"]["passed"] is True
    assert out["dryRun"]["wouldMutateOrder"] is False
    assert out["dryRun"]["wouldMutatePayment"] is False
    assert out["dryRun"]["wouldSendCustomerNotification"] is False
    assert out["dryRun"]["wouldSendWhatsApp"] is False
    assert out["dryRun"]["wouldCallCourier"] is False
    assert out["dryRun"]["wouldCreateShipment"] is False
    assert out["dryRun"]["wouldCallProvider"] is False
    assert (
        out["dryRun"]["newOrderPaymentStatusCandidate"] == "Paid"
    )
    assert out["dryRun"]["newPaymentStatusCandidate"] == "Paid"
    assert before == after
    # Target rows still Pending (no mutation).
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == Order.PaymentStatus.PENDING
    assert payment.status == Payment.Status.PENDING
    gate = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    assert (
        gate.status
        == RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.DRY_RUN_PASSED
    )
    assert gate.dry_run_passed is True
    assert gate.candidate_order_id_snapshot == order.id
    assert gate.candidate_payment_id_snapshot == payment.id
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_DRY_RUN_PASSED
    ).exists()


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8e_approve_refuses_without_dry_run() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_appr_no_dr")
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        out = approve_phase8e_real_customer_payment_order_pilot(
            prep["gate"]["id"],
            reason="Director attempt approve without dry-run.",
        )
    assert out["ok"] is False
    assert any(
        "not_transitionable_to_approved" in b
        or "no_passed_dry_run_present" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8e_approve_succeeds_after_dry_run_and_only_moves_to_future_phase8f() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_appr_ok")
    order, payment = _make_pending_real_customer_pair(suffix="appr_ok")
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        sel = select_phase8e_real_customer_candidate(
            prep["gate"]["id"],
            order_id=order.id,
            payment_id=payment.id,
        )
        dry_run_phase8e_real_customer_payment_order_pilot(
            prep["gate"]["id"],
            candidate_id=sel["candidate"]["id"],
        )
        before = _row_counts()
        out = approve_phase8e_real_customer_payment_order_pilot(
            prep["gate"]["id"],
            reason="Director Phase 8E approve.",
        )
        after = _row_counts()
    assert out["ok"] is True
    assert before == after
    gate = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    assert (
        gate.status
        == "approved_for_future_phase8f_real_customer_controlled_mutation"
    )
    # Target rows still Pending after approval.
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == Order.PaymentStatus.PENDING
    assert payment.status == Payment.Status.PENDING
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_APPROVED).exists()


@pytest.mark.django_db
def test_phase8e_reject_requires_reason_and_marks_status() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_reject")
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        missing = (
            reject_phase8e_real_customer_payment_order_pilot(
                prep["gate"]["id"], reason=""
            )
        )
        assert missing["ok"] is False
        out = reject_phase8e_real_customer_payment_order_pilot(
            prep["gate"]["id"],
            reason="Director Phase 8E reject.",
        )
    assert out["ok"] is True
    gate = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    assert (
        gate.status
        == RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.REJECTED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).exists()


@pytest.mark.django_db
def test_phase8e_archive_records_status_and_writes_audit() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_archive")
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        out = archive_phase8e_real_customer_payment_order_pilot(
            prep["gate"]["id"],
            reason="Director Phase 8E archive.",
        )
    assert out["ok"] is True
    gate = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    assert (
        gate.status
        == RazorpayRealCustomerPaymentOrderMutationPilotGate.Status.ARCHIVED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_ARCHIVED).exists()


# ---------------------------------------------------------------------------
# Defensive invariant guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8e_assert_no_business_mutation_raises_on_flipped_flag() -> None:
    lock = _make_locked_phase8d(source_event_id="phase8e_guard")
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
    gate = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    gate.real_mutation_allowed = True
    before = _row_counts()
    with pytest.raises(ValueError):
        assert_phase8e_no_business_mutation(
            gate, before_counts=before
        )


# ---------------------------------------------------------------------------
# Forensic global no-business-mutation check
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8e_full_lifecycle_never_mutates_business_rows() -> None:
    """prepare -> select-candidate -> dry-run -> approve. Every
    protected business table count stays identical."""
    lock = _make_locked_phase8d(
        source_event_id="phase8e_full_lifecycle"
    )
    order, payment = _make_pending_real_customer_pair(
        suffix="lifecycle"
    )
    snap0 = _row_counts()
    with _phase8e_enabled():
        prep = prepare_phase8e_real_customer_payment_order_pilot(
            phase8d_lock_id=lock.pk
        )
        snap1 = _row_counts()
        sel = select_phase8e_real_customer_candidate(
            prep["gate"]["id"],
            order_id=order.id,
            payment_id=payment.id,
        )
        snap2 = _row_counts()
        dry_run_phase8e_real_customer_payment_order_pilot(
            prep["gate"]["id"],
            candidate_id=sel["candidate"]["id"],
        )
        snap3 = _row_counts()
        approve_phase8e_real_customer_payment_order_pilot(
            prep["gate"]["id"],
            reason="Phase 8E approve full lifecycle.",
        )
        snap4 = _row_counts()
    assert snap0 == snap1 == snap2 == snap3 == snap4
    # Phase 8E rows themselves are allowed to change.
    assert (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.count()
        >= 1
    )
    assert (
        RazorpayRealCustomerPaymentOrderMutationCandidate.objects.count()
        >= 1
    )
    assert (
        RazorpayRealCustomerPaymentOrderMutationPilotDryRun.objects.count()
        >= 1
    )
    # Target Order/Payment status never mutated.
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == Order.PaymentStatus.PENDING
    assert payment.status == Payment.Status.PENDING


# ---------------------------------------------------------------------------
# API endpoint shape + 405 enforcement
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, django_user_model):
    from rest_framework.test import APIClient

    user = django_user_model.objects.create_user(
        username="phase8e_admin",
        email="phase8e_admin@example.com",
        password="ignored-by-force-auth",
    )
    user.is_staff = True
    user.is_superuser = True
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_phase8e_readiness_endpoint_returns_safe_off_shape(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8e-real-customer-payment-order-pilot-readiness"
    )
    r = admin_client.get(url)
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] == "8E"
    assert data["phase8EPaymentOrderPilotEnabled"] is False
    assert data["executionPath"] == (
        "review_dry_run_only_cli_only_no_execute"
    )
    assert data["frontendCanExecute"] is False
    assert data["apiEndpointCanExecute"] is False
    assert data["apiEndpointCanApprove"] is False


@pytest.mark.django_db
def test_phase8e_endpoints_block_write_methods(admin_client) -> None:
    for path in (
        "saas-phase8e-real-customer-payment-order-pilot-readiness",
        "saas-phase8e-real-customer-payment-order-pilot-gates",
        "saas-phase8e-real-customer-payment-order-pilot-preview",
    ):
        url = reverse(path)
        for method in ("post", "patch", "delete"):
            r = getattr(admin_client, method)(
                url, {} if method != "delete" else None
            )
            assert r.status_code == 405, (path, method, r.status_code)


@pytest.mark.django_db
def test_phase8e_preview_endpoint_requires_phase8d_lock_id(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8e-real-customer-payment-order-pilot-preview"
    )
    assert admin_client.get(url).status_code == 400
    assert (
        admin_client.get(url + "?phase8d_lock_id=0").status_code == 400
    )
    assert (
        admin_client.get(
            url + "?phase8d_lock_id=999999"
        ).status_code
        == 200
    )


@pytest.mark.django_db
def test_phase8e_gate_detail_candidates_dry_runs_return_404_when_missing(
    admin_client,
) -> None:
    detail = reverse(
        "saas-phase8e-real-customer-payment-order-pilot-gate-detail",
        kwargs={"pk": 9999},
    )
    cands = reverse(
        "saas-phase8e-real-customer-payment-order-pilot-candidates",
        kwargs={"gate_id": 9999},
    )
    drs = reverse(
        "saas-phase8e-real-customer-payment-order-pilot-dry-runs",
        kwargs={"gate_id": 9999},
    )
    assert admin_client.get(detail).status_code == 404
    assert admin_client.get(cands).status_code == 404
    assert admin_client.get(drs).status_code == 404
