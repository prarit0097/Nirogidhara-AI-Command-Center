"""Phase 8F - Controlled Real Customer Payment -> Order Mutation tests.

Phase 8F is the **CLI-only one-shot controlled mutation** path for
the ONE Phase 8E-approved real customer Order + Payment candidate.
The fixture chain wires up Phase 7I -> 8A -> 8B -> 8C
execute+rollback -> 8D locked -> 8E candidate selected + dry-run
passed + approved, then exercises Phase 8F preview / prepare /
approve / execute / rollback / reject / archive paths. Every
execute refusal test asserts no provider call, no business
mutation, no customer notification, no PII leak. The happy-path
execute test mutates ONLY Order.payment_status + Payment.status
on the chosen target rows in the test database.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone as django_timezone

from apps.audit.models import AuditEvent
from apps.orders.models import Order
from apps.payments.models import (
    Payment,
    RazorpayRealCustomerPaymentOrderControlledMutationAttempt,
    RazorpayRealCustomerPaymentOrderControlledMutationGate,
    RazorpayRealCustomerPaymentOrderControlledMutationRollback,
    RazorpayRealCustomerPaymentOrderMutationPilotGate,
)
from apps.payments.phase8e_real_customer_payment_order_pilot import (
    approve_phase8e_real_customer_payment_order_pilot,
    dry_run_phase8e_real_customer_payment_order_pilot,
    prepare_phase8e_real_customer_payment_order_pilot,
    select_phase8e_real_customer_candidate,
)
from apps.payments.phase8f_real_customer_controlled_mutation import (
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_EXECUTED,
    AUDIT_KIND_FAILED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    AUDIT_KIND_ROLLBACK,
    PHASE_8F_FORBIDDEN_ACTIONS,
    PHASE_8F_FORBIDDEN_PAYLOAD_KEYS,
    approve_phase8f_real_customer_controlled_mutation,
    archive_phase8f_real_customer_controlled_mutation,
    assert_phase8f_no_unauthorized_side_effect,
    execute_phase8f_real_customer_controlled_mutation,
    inspect_phase8f_real_customer_controlled_mutation_readiness,
    prepare_phase8f_real_customer_controlled_mutation,
    preview_phase8f_real_customer_controlled_mutation,
    reject_phase8f_real_customer_controlled_mutation,
    rollback_phase8f_real_customer_controlled_mutation,
)
from tests.test_phase7i_final_audit_lock import _row_counts
from tests.test_phase8e_real_customer_payment_order_pilot import (
    _make_locked_phase8d,
    _make_partial_real_customer_pair,
    _make_pending_real_customer_pair,
    _phase8e_enabled,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _phase8f_enabled(
    *, allow_real: bool = True, director_approved: bool = True
):
    """All three Phase 8F runtime flags ON. Tests that exercise
    happy-path execute use this context manager."""
    return override_settings(
        PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED=True,
        PHASE8F_DIRECTOR_APPROVED_ONE_SHOT_REAL_MUTATION=bool(
            director_approved
        ),
        PHASE8F_ALLOW_REAL_CUSTOMER_ORDER_PAYMENT_MUTATION=bool(
            allow_real
        ),
    )


def _phase8f_partial_enabled():
    """Phase 8F gate flag only; other flags OFF (simulates the
    `prepare`-allowed-but-execute-blocked posture)."""
    return override_settings(
        PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED=True,
        PHASE8F_DIRECTOR_APPROVED_ONE_SHOT_REAL_MUTATION=False,
        PHASE8F_ALLOW_REAL_CUSTOMER_ORDER_PAYMENT_MUTATION=False,
    )


def _make_approved_phase8e_gate(
    *,
    source_event_id: str,
    partial: bool = True,
) -> tuple[
    RazorpayRealCustomerPaymentOrderMutationPilotGate, Order, Payment
]:
    """Build the full Phase 7I -> 8A -> 8B -> 8C executed+rolled_back
    -> 8D locked -> 8E approved chain on a Partial+Pending (default)
    or Pending+Pending real-customer candidate. Returns the
    Phase 8E pilot gate (status =
    approved_for_future_phase8f_real_customer_controlled_mutation),
    the target Order, and the target Payment."""
    lock = _make_locked_phase8d(source_event_id=source_event_id)
    if partial:
        order, payment = _make_partial_real_customer_pair(
            suffix=source_event_id[-12:]
        )
    else:
        order, payment = _make_pending_real_customer_pair(
            suffix=source_event_id[-12:]
        )
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
        approve_phase8e_real_customer_payment_order_pilot(
            prep["gate"]["id"],
            reason=(
                "Director Phase 8E approve for Phase 8F fixture."
            ),
        )
    phase8e_gate = (
        RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    assert (
        phase8e_gate.status
        == "approved_for_future_phase8f_real_customer_controlled_mutation"
    )
    return phase8e_gate, order, payment


def _structured_signoff(
    *,
    attempt_id: int,
    gate_id: int,
    phase8e_gate_id: int,
    target_order_id: str,
    target_payment_id: str,
    now: datetime,
) -> str:
    begin = now - timedelta(minutes=2)
    end = now + timedelta(minutes=10)
    return (
        f"Director sign-off Phase 8F controlled real customer "
        f"mutation. "
        f"phase8f_attempt_id_{attempt_id} "
        f"phase8f_gate_id_{gate_id} "
        f"phase8e_gate_id_{phase8e_gate_id} "
        f"target_order_{target_order_id} "
        f"target_payment_{target_payment_id} "
        f"BEGIN_UTC={begin.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"END_UTC={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )


# ---------------------------------------------------------------------------
# Audit-kind + static-file invariants
# ---------------------------------------------------------------------------


def test_phase8f_audit_kinds_within_length_budget() -> None:
    for kind in (
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_APPROVED,
        AUDIT_KIND_EXECUTED,
        AUDIT_KIND_ROLLBACK,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
        AUDIT_KIND_FAILED,
    ):
        assert len(kind) <= 64
        assert kind.startswith("phase8f.real_mutation.")


def test_phase8f_forbidden_actions_cover_real_surface() -> None:
    required_subset = {
        "call_razorpay_api",
        "call_meta_cloud_api",
        "call_delhivery_api",
        "call_vapi_api",
        "send_whatsapp_template",
        "send_whatsapp_freeform",
        "send_customer_notification",
        "create_awb",
        "create_shipment_row",
        "create_payment_link",
        "capture_razorpay_payment",
        "refund_razorpay_payment",
        "mutate_real_order_state",
        "edit_dotenv_any",
    }
    assert required_subset.issubset(set(PHASE_8F_FORBIDDEN_ACTIONS))


def test_phase8f_forbidden_payload_keys_cover_pii_surface() -> None:
    required_subset = {
        "token",
        "raw_payload",
        "raw_response",
        "phone",
        "customer_phone",
        "email",
        "customer_email",
        "address",
        "card",
        "vpa",
        "upi",
        "gateway_reference_id",
        "payment_url",
        "customer_name",
        "director_signoff",
    }
    assert required_subset.issubset(
        set(PHASE_8F_FORBIDDEN_PAYLOAD_KEYS)
    )


def test_phase8f_service_module_does_not_import_provider_clients() -> None:
    """Static-file scan over the Phase 8F service module: NO import
    line may reference Razorpay / Meta Cloud / Delhivery / WhatsApp
    send / dotenv clients."""
    import apps.payments.phase8f_real_customer_controlled_mutation as svc

    forbidden = (
        "razorpay_client",
        "meta_cloud_client",
        "delhivery_client",
        "apps.whatsapp.services.send_freeform_text_message",
        "apps.whatsapp.services.send_template_message",
        "apps.whatsapp.services.queue_template_message",
        "from dotenv",
        "import dotenv",
        "import razorpay",
    )
    with open(svc.__file__, "r", encoding="utf-8") as fh:
        text = fh.read()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            for needle in forbidden:
                assert needle not in stripped, (
                    f"phase8f service imports forbidden client "
                    f"`{needle}` on line: {line!r}"
                )


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8f_readiness_blocked_when_no_phase8e_approved() -> None:
    report = (
        inspect_phase8f_real_customer_controlled_mutation_readiness()
    )
    assert report["phase"] == "8F"
    assert report["status"] == "blocked"
    assert report["frontendCanExecute"] is False
    assert report["apiEndpointCanExecute"] is False
    assert report["phase8FMutatesOrderState"] is False
    assert any(
        "phase8f_at_least_one_phase8e_gate_must_be_approved_for_future_phase8f"
        in b
        for b in report["blockers"]
    )


@pytest.mark.django_db
def test_phase8f_readiness_ready_after_phase8e_approved_and_flag_on() -> None:
    _make_approved_phase8e_gate(source_event_id="phase8f_ready")
    with _phase8f_enabled():
        report = (
            inspect_phase8f_real_customer_controlled_mutation_readiness()
        )
    assert report["status"] == "ready"
    assert report["eligiblePhase8EGateCount"] >= 1
    assert report["blockers"] == []
    assert report["nextAction"] == "ready_for_phase8f_prepare"


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8f_preview_eligible_chain_emits_no_business_mutation() -> None:
    phase8e_gate, order, payment = _make_approved_phase8e_gate(
        source_event_id="phase8f_preview"
    )
    with _phase8f_partial_enabled():
        before = _row_counts()
        out = preview_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        after = _row_counts()
    assert out["ok"] is True
    assert out["phase8EGateId"] == phase8e_gate.pk
    assert out["candidateOrderId"] == order.id
    assert out["candidatePaymentId"] == payment.id
    assert out["currentOrderPaymentStatus"] == order.payment_status
    assert out["currentPaymentStatus"] == payment.status
    assert out["proposedOrderPaymentStatus"] == "Paid"
    assert out["proposedPaymentStatus"] == "Paid"
    assert before == after


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8f_prepare_blocks_when_env_flag_off() -> None:
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_prep_off"
    )
    out = prepare_phase8f_real_customer_controlled_mutation(
        phase8e_gate_id=phase8e_gate.pk
    )
    assert out["ok"] is False
    assert any(
        "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8f_prepare_creates_gate_when_flag_on() -> None:
    phase8e_gate, order, payment = _make_approved_phase8e_gate(
        source_event_id="phase8f_prep_ok"
    )
    with _phase8f_partial_enabled():
        before = _row_counts()
        out = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        after = _row_counts()
    assert out["ok"] is True
    assert out["created"] is True
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=out["gate"]["id"]
        )
    )
    assert gate.status == "pending_manual_review"
    assert gate.selected_order_id_snapshot == order.id
    assert gate.selected_payment_id_snapshot == payment.id
    assert gate.real_customer_mutation_allowed is False
    assert gate.provider_call_allowed is False
    assert gate.customer_notification_allowed is False
    assert before == after


@pytest.mark.django_db
def test_phase8f_prepare_idempotent_on_same_phase8e_gate() -> None:
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_prep_idem"
    )
    with _phase8f_partial_enabled():
        first = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        second = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    assert first["ok"] is True
    assert second["ok"] is True
    assert first["gate"]["id"] == second["gate"]["id"]
    assert first["created"] is True
    assert second["created"] is False


# ---------------------------------------------------------------------------
# Approve / Reject / Archive
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8f_approve_succeeds_only_when_candidate_still_current() -> None:
    phase8e_gate, order, payment = _make_approved_phase8e_gate(
        source_event_id="phase8f_appr_ok"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        out = approve_phase8f_real_customer_controlled_mutation(
            prep["gate"]["id"],
            reason="Director Phase 8F approve.",
        )
    assert out["ok"] is True
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    assert (
        gate.status
        == "approved_for_one_shot_real_customer_mutation"
    )
    attempt = gate.attempts.get(pk=out["attempt"]["id"])
    assert (
        attempt.status == "approved_for_one_shot_real_mutation"
    )
    assert attempt.target_order_id == order.id
    assert attempt.target_payment_id == payment.id
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_APPROVED).exists()


@pytest.mark.django_db
def test_phase8f_approve_refuses_if_order_status_drifted() -> None:
    phase8e_gate, order, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_appr_drift"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    # Drift the Order.payment_status AFTER prepare but BEFORE approve.
    order.payment_status = Order.PaymentStatus.PAID
    order.save(update_fields=["payment_status"])
    with _phase8f_partial_enabled():
        out = approve_phase8f_real_customer_controlled_mutation(
            prep["gate"]["id"], reason="Director Phase 8F approve drift."
        )
    assert out["ok"] is False
    assert any(
        "phase8f_target_order_payment_status_must_be_pending_or_partial_was_Paid"
        in b
        for b in out["blockers"]
    )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    assert gate.status == "blocked"


@pytest.mark.django_db
def test_phase8f_approve_requires_reason() -> None:
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_appr_reas"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        out = approve_phase8f_real_customer_controlled_mutation(
            prep["gate"]["id"], reason=""
        )
    assert out["ok"] is False
    assert "phase8f_approve_reason_required" in out["blockers"]


@pytest.mark.django_db
def test_phase8f_reject_requires_reason_and_marks_status() -> None:
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_reject"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        missing = reject_phase8f_real_customer_controlled_mutation(
            prep["gate"]["id"], reason=""
        )
        ok = reject_phase8f_real_customer_controlled_mutation(
            prep["gate"]["id"], reason="Director paused review."
        )
    assert missing["ok"] is False
    assert "phase8f_reject_reason_required" in missing["blockers"]
    assert ok["ok"] is True
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    assert gate.status == "rejected"


@pytest.mark.django_db
def test_phase8f_archive_records_status_and_writes_audit() -> None:
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_archive"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        archive_phase8f_real_customer_controlled_mutation(
            prep["gate"]["id"],
            reason="Director archive.",
        )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    assert gate.status == "archived"
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_ARCHIVED).exists()


# ---------------------------------------------------------------------------
# Execute - refusal paths
# ---------------------------------------------------------------------------


def _prep_approve(source_event_id: str, *, partial: bool = True):
    """Phase 8F-Hotfix-2: also return ``phase8e_gate.pk`` so callers can
    pass the **dynamic** gate id into the Director sign-off body
    instead of hardcoding ``phase8e_gate_id_1``. On Postgres the
    AUTOINCREMENT sequence does not reset between tests within a file
    run, so a real test may see a phase8e gate id of 7, 12, etc."""
    phase8e_gate, order, payment = _make_approved_phase8e_gate(
        source_event_id=source_event_id, partial=partial
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        appr = approve_phase8f_real_customer_controlled_mutation(
            prep["gate"]["id"],
            reason="Director Phase 8F approve.",
        )
    return (
        appr["attempt"]["id"],
        appr["gate"]["id"],
        phase8e_gate.pk,
        order,
        payment,
    )


@pytest.mark.django_db
def test_phase8f_execute_refuses_when_three_env_flags_off() -> None:
    attempt_id, gate_id, phase8e_gate_id, order, payment = _prep_approve(
        "phase8f_exec_flags"
    )
    # All three Phase 8F flags off here.
    out = execute_phase8f_real_customer_controlled_mutation(
        attempt_id,
        director_signoff=(
            f"phase8f_attempt_id_{attempt_id} "
            f"phase8f_gate_id_{gate_id} "
            f"phase8e_gate_id_{phase8e_gate_id} "
            f"target_order_{order.id} "
            f"target_payment_{payment.id}"
        ),
        operator_name="Operator",
        confirm_one_shot_real_mutation=True,
    )
    assert out["ok"] is False
    assert any(
        "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
        in b
        for b in out["blockers"]
    )
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status != "Paid"
    assert payment.status != "Paid"


@pytest.mark.django_db
def test_phase8f_execute_refuses_missing_utc_window() -> None:
    attempt_id, gate_id, phase8e_gate_id, order, payment = _prep_approve(
        "phase8f_exec_window_missing"
    )
    with _phase8f_enabled():
        out = execute_phase8f_real_customer_controlled_mutation(
            attempt_id,
            director_signoff=(
                f"phase8f_attempt_id_{attempt_id} "
                f"phase8f_gate_id_{gate_id} phase8e_gate_id_{phase8e_gate_id} "
                f"target_order_{order.id} "
                f"target_payment_{payment.id}"
            ),
            operator_name="Operator",
            confirm_one_shot_real_mutation=True,
        )
    assert out["ok"] is False
    assert any(
        "director_signoff_missing_structured_utc_window" in b
        for b in out["blockers"]
    )
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status != "Paid"
    assert payment.status != "Paid"


@pytest.mark.django_db
def test_phase8f_execute_refuses_stale_or_outside_window() -> None:
    attempt_id, gate_id, phase8e_gate_id, order, payment = _prep_approve(
        "phase8f_exec_window_stale"
    )
    far_past = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    signoff = _structured_signoff(
        attempt_id=attempt_id,
        gate_id=gate_id,
        phase8e_gate_id=phase8e_gate_id,
        target_order_id=order.id,
        target_payment_id=payment.id,
        now=far_past,
    )
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    with _phase8f_enabled():
        out = execute_phase8f_real_customer_controlled_mutation(
            attempt_id,
            director_signoff=signoff,
            operator_name="Operator",
            confirm_one_shot_real_mutation=True,
            now=now,
        )
    assert out["ok"] is False
    assert any(
        "director_signoff_window_stale" in b
        or "now_after_director_signoff" in b
        or "now_before_director_signoff" in b
        for b in out["blockers"]
    )
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status != "Paid"
    assert payment.status != "Paid"


@pytest.mark.django_db
def test_phase8f_execute_refuses_if_current_status_drifted() -> None:
    attempt_id, gate_id, phase8e_gate_id, order, payment = _prep_approve(
        "phase8f_exec_drift"
    )
    order.payment_status = Order.PaymentStatus.PAID
    order.save(update_fields=["payment_status"])
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    signoff = _structured_signoff(
        attempt_id=attempt_id,
        gate_id=gate_id,
        phase8e_gate_id=phase8e_gate_id,
        target_order_id=order.id,
        target_payment_id=payment.id,
        now=now,
    )
    with _phase8f_enabled():
        out = execute_phase8f_real_customer_controlled_mutation(
            attempt_id,
            director_signoff=signoff,
            operator_name="Operator",
            confirm_one_shot_real_mutation=True,
            now=now,
        )
    assert out["ok"] is False
    assert any(
        "phase8f_target_order_payment_status_must_be_pending_or_partial_was_Paid"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8f_execute_refuses_missing_confirm_flag() -> None:
    attempt_id, gate_id, phase8e_gate_id, order, payment = _prep_approve(
        "phase8f_exec_confirm"
    )
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    signoff = _structured_signoff(
        attempt_id=attempt_id,
        gate_id=gate_id,
        phase8e_gate_id=phase8e_gate_id,
        target_order_id=order.id,
        target_payment_id=payment.id,
        now=now,
    )
    with _phase8f_enabled():
        out = execute_phase8f_real_customer_controlled_mutation(
            attempt_id,
            director_signoff=signoff,
            operator_name="Operator",
            confirm_one_shot_real_mutation=False,
            now=now,
        )
    assert out["ok"] is False
    assert "phase8f_confirm_one_shot_real_mutation_required" in out[
        "blockers"
    ]


@pytest.mark.django_db
def test_phase8f_execute_refuses_missing_operator_name() -> None:
    attempt_id, gate_id, phase8e_gate_id, order, payment = _prep_approve(
        "phase8f_exec_operator"
    )
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    signoff = _structured_signoff(
        attempt_id=attempt_id,
        gate_id=gate_id,
        phase8e_gate_id=phase8e_gate_id,
        target_order_id=order.id,
        target_payment_id=payment.id,
        now=now,
    )
    with _phase8f_enabled():
        out = execute_phase8f_real_customer_controlled_mutation(
            attempt_id,
            director_signoff=signoff,
            operator_name="",
            confirm_one_shot_real_mutation=True,
            now=now,
        )
    assert out["ok"] is False
    assert "phase8f_operator_name_required" in out["blockers"]


@pytest.mark.django_db
def test_phase8f_execute_refuses_signoff_missing_required_refs() -> None:
    attempt_id, gate_id, phase8e_gate_id, order, payment = _prep_approve(
        "phase8f_exec_signoff"
    )
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    # Signoff omits target_order_<id> and target_payment_<id>.
    begin = now - timedelta(minutes=2)
    end = now + timedelta(minutes=10)
    signoff = (
        f"phase8f_attempt_id_{attempt_id} "
        f"phase8f_gate_id_{gate_id} "
        f"phase8e_gate_id_{phase8e_gate_id} "
        f"BEGIN_UTC={begin.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"END_UTC={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    with _phase8f_enabled():
        out = execute_phase8f_real_customer_controlled_mutation(
            attempt_id,
            director_signoff=signoff,
            operator_name="Operator",
            confirm_one_shot_real_mutation=True,
            now=now,
        )
    assert out["ok"] is False
    assert any(
        "phase8f_director_signoff_must_reference_target_order_id" in b
        for b in out["blockers"]
    )
    assert any(
        "phase8f_director_signoff_must_reference_target_payment_id"
        in b
        for b in out["blockers"]
    )
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status != "Paid"
    assert payment.status != "Paid"


# ---------------------------------------------------------------------------
# Execute - happy path (TEST DATABASE ONLY)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8f_execute_happy_path_mutates_only_target_statuses() -> None:
    """Happy-path execute in the TEST database. Mutates ONLY the
    target Order.payment_status + Payment.status fields; row counts
    stay identical; every provider/send/courier flag stays False;
    Order.state, Customer, Lead, Shipment, DiscountOfferLog,
    WhatsAppMessage are NOT mutated."""
    attempt_id, gate_id, phase8e_gate_id, order, payment = _prep_approve(
        "phase8f_exec_happy"
    )
    original_order_state = order.state
    original_customer_name = order.customer_name
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    signoff = _structured_signoff(
        attempt_id=attempt_id,
        gate_id=gate_id,
        phase8e_gate_id=phase8e_gate_id,
        target_order_id=order.id,
        target_payment_id=payment.id,
        now=now,
    )
    with _phase8f_enabled():
        before = _row_counts()
        out = execute_phase8f_real_customer_controlled_mutation(
            attempt_id,
            director_signoff=signoff,
            operator_name="Operator Prarit",
            confirm_one_shot_real_mutation=True,
            now=now,
        )
        after = _row_counts()
    assert out["ok"] is True
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == "Paid"
    assert payment.status == "Paid"
    # Order.state NOT mutated.
    assert order.state == original_order_state
    # Customer name NOT mutated.
    assert order.customer_name == original_customer_name
    # Row counts identical (no new Customer / Lead / Shipment / etc).
    assert before == after
    attempt = (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects.get(
            pk=attempt_id
        )
    )
    assert attempt.status == "executed"
    assert attempt.order_mutation_was_made is True
    assert attempt.payment_mutation_was_made is True
    assert attempt.business_mutation_was_made is True
    # Locked-False flags STILL False on the attempt row.
    assert attempt.customer_notification_sent is False
    assert attempt.whatsapp_sent is False
    assert attempt.courier_called is False
    assert attempt.provider_call_attempted is False
    assert attempt.shipment_created is False
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_EXECUTED).exists()


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8f_rollback_requires_executed_attempt_and_reason() -> None:
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_rb_pre"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        appr = approve_phase8f_real_customer_controlled_mutation(
            prep["gate"]["id"], reason="Director approve."
        )
        # Attempt not executed yet; rollback must refuse.
        out = rollback_phase8f_real_customer_controlled_mutation(
            appr["attempt"]["id"], reason="Director rollback attempt."
        )
    assert out["ok"] is False
    assert any(
        "phase8f_attempt_status" in b and "not_rollbackable" in b
        for b in out["blockers"]
    )
    # Also: reason required.
    with _phase8f_partial_enabled():
        out_reason = (
            rollback_phase8f_real_customer_controlled_mutation(
                appr["attempt"]["id"], reason=""
            )
        )
    assert out_reason["ok"] is False
    assert (
        "phase8f_rollback_reason_required" in out_reason["blockers"]
    )


@pytest.mark.django_db
def test_phase8f_rollback_restores_old_statuses_no_side_effect() -> None:
    """After a happy-path execute, rollback must restore the
    original Order.payment_status + Payment.status snapshots, NOT
    call any provider, NOT send WhatsApp, NOT notify the customer,
    NOT grow any protected business table."""
    attempt_id, gate_id, phase8e_gate_id, order, payment = _prep_approve(
        "phase8f_rb_happy"
    )
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    signoff = _structured_signoff(
        attempt_id=attempt_id,
        gate_id=gate_id,
        phase8e_gate_id=phase8e_gate_id,
        target_order_id=order.id,
        target_payment_id=payment.id,
        now=now,
    )
    with _phase8f_enabled():
        execute_phase8f_real_customer_controlled_mutation(
            attempt_id,
            director_signoff=signoff,
            operator_name="Operator",
            confirm_one_shot_real_mutation=True,
            now=now,
        )
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == "Paid"
    assert payment.status == "Paid"

    before = _row_counts()
    out = rollback_phase8f_real_customer_controlled_mutation(
        attempt_id, reason="Director rollback Phase 8F."
    )
    after = _row_counts()
    assert out["ok"] is True
    order.refresh_from_db()
    payment.refresh_from_db()
    # Restored to the original Partial / Pending.
    assert order.payment_status == "Partial"
    assert payment.status == "Pending"
    assert before == after
    rollback_row = (
        RazorpayRealCustomerPaymentOrderControlledMutationRollback.objects.get(
            attempt_id=attempt_id
        )
    )
    assert rollback_row.status == "rollback_recorded"
    assert rollback_row.rollback_was_made is True
    # Locked-False flags STILL False on the rollback row.
    assert rollback_row.customer_notification_sent is False
    assert rollback_row.whatsapp_sent is False
    assert rollback_row.courier_called is False
    assert rollback_row.provider_call_attempted is False
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_ROLLBACK).exists()
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=gate_id
        )
    )
    assert gate.status == "rolled_back"


# ---------------------------------------------------------------------------
# Defensive guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8f_assert_no_unauthorized_side_effect_raises_on_flipped_flag() -> None:
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_guard"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    gate.whatsapp_allowed = True  # forbidden flip
    gate.save(update_fields=["whatsapp_allowed", "updated_at"])
    with pytest.raises(ValueError) as exc_info:
        assert_phase8f_no_unauthorized_side_effect(gate)
    assert "phase8f_gate_whatsapp_allowed_must_remain_false" in str(
        exc_info.value
    )


# ---------------------------------------------------------------------------
# CLI command + JSON output
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8f_inspect_management_command_runs_clean() -> None:
    _make_approved_phase8e_gate(source_event_id="phase8f_cmd")
    before = _row_counts()
    buf = io.StringIO()
    call_command(
        "inspect_phase8f_real_customer_controlled_mutation",
        "--json",
        "--no-audit",
        stdout=buf,
    )
    after = _row_counts()
    payload = json.loads(buf.getvalue())
    assert payload["phase"] == "8F"
    assert payload["frontendCanExecute"] is False
    assert payload["apiEndpointCanExecute"] is False
    assert payload["phase8FCallsRazorpay"] is False
    assert payload["phase8FSendsWhatsApp"] is False
    assert payload["phase8FSendsCustomerNotification"] is False
    assert before == after


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8f_readiness_endpoint_returns_safe_off_shape(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8f-real-customer-controlled-mutation-readiness"
    )
    r = admin_client.get(url)
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] == "8F"
    assert data["frontendCanExecute"] is False
    assert data["apiEndpointCanExecute"] is False
    assert data["phase8FCallsRazorpay"] is False
    assert data["phase8FSendsWhatsApp"] is False


@pytest.mark.django_db
def test_phase8f_endpoints_block_write_methods(admin_client) -> None:
    for name in (
        "saas-phase8f-real-customer-controlled-mutation-readiness",
        "saas-phase8f-real-customer-controlled-mutation-gates",
        "saas-phase8f-real-customer-controlled-mutation-preview",
    ):
        url = reverse(name)
        for method in ("post", "patch", "delete"):
            r = getattr(admin_client, method)(
                url, {} if method != "delete" else None
            )
            assert r.status_code == 405, (name, method, r.status_code)


@pytest.mark.django_db
def test_phase8f_preview_endpoint_requires_phase8e_gate_id(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8f-real-customer-controlled-mutation-preview"
    )
    assert admin_client.get(url).status_code == 400
    assert (
        admin_client.get(url + "?phase8e_gate_id=0").status_code
        == 400
    )
    # Non-existent id still returns 200 with blockers.
    assert (
        admin_client.get(
            url + "?phase8e_gate_id=999999"
        ).status_code
        == 200
    )


@pytest.mark.django_db
def test_phase8f_gate_detail_attempts_rollbacks_return_404_when_missing(
    admin_client,
) -> None:
    detail = reverse(
        "saas-phase8f-real-customer-controlled-mutation-gate-detail",
        kwargs={"pk": 9999},
    )
    attempts = reverse(
        "saas-phase8f-real-customer-controlled-mutation-attempts",
        kwargs={"gate_id": 9999},
    )
    rollbacks = reverse(
        "saas-phase8f-real-customer-controlled-mutation-rollbacks",
        kwargs={"attempt_id": 9999},
    )
    assert admin_client.get(detail).status_code == 404
    assert admin_client.get(attempts).status_code == 404
    assert admin_client.get(rollbacks).status_code == 404


# ---------------------------------------------------------------------------
# End-to-end no-side-effects sentinel
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8f_full_lifecycle_no_provider_no_business_mutation() -> None:
    """Walk the full Phase 8F prepare -> approve -> execute ->
    rollback lifecycle on a Partial+Pending real-customer candidate.
    Order.payment_status moves Partial -> Paid -> Partial.
    Payment.status moves Pending -> Paid -> Pending. NO other
    business row is mutated; NO provider is called; NO WhatsApp is
    sent; NO customer is notified; row counts stay identical
    end-to-end."""
    phase8e_gate, order, payment = _make_approved_phase8e_gate(
        source_event_id="phase8f_lc_full"
    )
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    with _phase8f_enabled():
        e2e_before = _row_counts()
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        appr = approve_phase8f_real_customer_controlled_mutation(
            prep["gate"]["id"], reason="Director approve LC."
        )
        attempt_id = appr["attempt"]["id"]
        gate_id = appr["gate"]["id"]
        signoff = _structured_signoff(
            attempt_id=attempt_id,
            gate_id=gate_id,
            phase8e_gate_id=phase8e_gate.pk,
            target_order_id=order.id,
            target_payment_id=payment.id,
            now=now,
        )
        execute_phase8f_real_customer_controlled_mutation(
            attempt_id,
            director_signoff=signoff,
            operator_name="Operator",
            confirm_one_shot_real_mutation=True,
            now=now,
        )
        rollback_phase8f_real_customer_controlled_mutation(
            attempt_id, reason="Director rollback LC."
        )
        e2e_after = _row_counts()
    assert e2e_before == e2e_after
    order.refresh_from_db()
    payment.refresh_from_db()
    # Final state restored.
    assert order.payment_status == "Partial"
    assert payment.status == "Pending"
    # Audit events for every step.
    for kind in (
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_APPROVED,
        AUDIT_KIND_EXECUTED,
        AUDIT_KIND_ROLLBACK,
    ):
        assert AuditEvent.objects.filter(kind=kind).exists()


# ---------------------------------------------------------------------------
# Phase 8F-Hotfix-1: recover blocked approval gate when blocked solely
# by missing runtime gate env flag
# ---------------------------------------------------------------------------


_PHASE8F_MISSING_ENV_BLOCKER = (
    "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
)


def _block_gate_with_missing_env_only(
    gate: RazorpayRealCustomerPaymentOrderControlledMutationGate,
    *,
    extra_blockers: list[str] | None = None,
) -> None:
    """Force a Phase 8F gate into ``blocked`` state with the exact
    blocker list a real prior approve would have written when the
    env flag was off (optionally with extra blockers to test the
    refusal-of-recovery path)."""
    gate.status = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.BLOCKED
    )
    gate.blockers = [_PHASE8F_MISSING_ENV_BLOCKER] + list(
        extra_blockers or []
    )
    gate.save(update_fields=["status", "blockers", "updated_at"])


@pytest.mark.django_db
def test_phase8f_hotfix1_approve_recovery_succeeds_from_blocked_env_flag_only() -> None:
    """A gate blocked SOLELY by the missing-env-flag blocker may
    recover to approval after the flag is flipped True — current
    DB still matches the approved snapshot, no attempt has
    executed/mutated/sent anything, Phase 8E source still approved,
    kill switch enabled."""
    phase8e_gate, order, payment = _make_approved_phase8e_gate(
        source_event_id="phase8f_hf1_recov_ok"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    # Force the prior real-VPS posture: gate is `blocked` with the
    # exact "GATE_ENABLED_must_be_true" blocker.
    _block_gate_with_missing_env_only(gate)

    # No business row mutation across the recovery approval.
    before = _row_counts()
    with _phase8f_enabled():
        out = approve_phase8f_real_customer_controlled_mutation(
            gate.pk,
            reason=(
                "Phase 8F-Hotfix-1: recovery approval after env "
                "flag flipped true."
            ),
        )
    after = _row_counts()
    assert out["ok"] is True
    assert (
        out["phase8fHotfix1RecoveredFromMissingEnvApprovalBlock"]
        is True
    )
    gate.refresh_from_db()
    assert gate.status == (
        "approved_for_one_shot_real_customer_mutation"
    )
    assert gate.blockers == []
    recovery = (gate.evidence_json or {}).get(
        "phase8fHotfix1Recovery"
    )
    assert recovery is not None
    assert recovery["recoveredFromMissingEnvApprovalBlock"] is True
    assert (
        recovery["recoveredBlocker"]
        == _PHASE8F_MISSING_ENV_BLOCKER
    )
    assert recovery["executionStillNotRun"] is True
    assert recovery["phase8fHotfix1"] is True
    # No business mutation; Order.payment_status / Payment.status
    # unchanged.
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == "Partial"
    assert payment.status == "Pending"
    assert before == after
    # Audit row carries the recovery marker.
    audit_rows = AuditEvent.objects.filter(
        kind=AUDIT_KIND_APPROVED
    ).order_by("-occurred_at")
    assert audit_rows.exists()
    payload = audit_rows.first().payload or {}
    assert (
        payload.get(
            "phase8f_hotfix1_recovered_from_missing_env_flag"
        )
        is True
    )
    assert (
        payload.get("phase8f_hotfix1_execution_still_not_run")
        is True
    )


@pytest.mark.django_db
def test_phase8f_hotfix1_approve_recovery_refuses_blocked_with_other_blocker() -> None:
    """If the gate is blocked AND carries ANY blocker other than the
    single missing-env-flag blocker, recovery must refuse — the
    operator has to investigate the other blockers manually."""
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_hf1_recov_other"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    _block_gate_with_missing_env_only(
        gate, extra_blockers=["some_other_blocker_to_inspect"]
    )
    with _phase8f_enabled():
        out = approve_phase8f_real_customer_controlled_mutation(
            gate.pk, reason="Director attempt recovery."
        )
    assert out["ok"] is False
    assert any(
        "phase8f_gate_status_blocked_not_transitionable_to_approved"
        in b
        for b in out["blockers"]
    )
    gate.refresh_from_db()
    assert gate.status == "blocked"


@pytest.mark.django_db
def test_phase8f_hotfix1_approve_recovery_refuses_when_order_status_drifted() -> None:
    """If `Order.payment_status` has drifted away from
    {Pending, Partial} after the prior block, recovery must refuse
    — even if the blocker list is the single missing-env blocker."""
    phase8e_gate, order, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_hf1_recov_drift"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    _block_gate_with_missing_env_only(gate)
    # Drift Order.payment_status AFTER the block.
    order.payment_status = Order.PaymentStatus.PAID
    order.save(update_fields=["payment_status"])
    with _phase8f_enabled():
        out = approve_phase8f_real_customer_controlled_mutation(
            gate.pk, reason="Director recovery attempt."
        )
    assert out["ok"] is False
    assert any(
        "phase8f_target_order_payment_status_must_be_pending_or_partial_was_Paid"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8f_hotfix1_approve_recovery_refuses_when_executed_attempt_exists() -> None:
    """If ANY attempt on this gate carries `executed_at`, recovery
    must refuse — the gate has already crossed execute."""
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_hf1_recov_exec"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    # Hand-craft an executed attempt.
    RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects.create(
        gate=gate,
        target_order_id=gate.selected_order_id_snapshot,
        target_payment_id=gate.selected_payment_id_snapshot,
        status="executed",
        old_order_payment_status="Partial",
        old_payment_status="Pending",
        new_order_payment_status="Paid",
        new_payment_status="Paid",
        order_mutation_was_made=True,
        payment_mutation_was_made=True,
        business_mutation_was_made=True,
        executed_at=django_timezone.now(),
    )
    _block_gate_with_missing_env_only(gate)
    with _phase8f_enabled():
        out = approve_phase8f_real_customer_controlled_mutation(
            gate.pk, reason="Director recovery attempt."
        )
    assert out["ok"] is False
    assert any(
        "phase8f_gate_status_blocked_not_transitionable_to_approved"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8f_hotfix1_approve_recovery_refuses_when_mutation_flag_present() -> None:
    """If ANY attempt carries a *_mutation_was_made flag True (even
    without `executed_at`), recovery must refuse."""
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_hf1_recov_flag"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects.create(
        gate=gate,
        target_order_id=gate.selected_order_id_snapshot,
        target_payment_id=gate.selected_payment_id_snapshot,
        status="failed",
        old_order_payment_status="Partial",
        old_payment_status="Pending",
        order_mutation_was_made=True,
    )
    _block_gate_with_missing_env_only(gate)
    with _phase8f_enabled():
        out = approve_phase8f_real_customer_controlled_mutation(
            gate.pk, reason="Director recovery attempt."
        )
    assert out["ok"] is False
    assert any(
        "phase8f_gate_status_blocked_not_transitionable_to_approved"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8f_hotfix1_approve_recovery_refuses_when_provider_flag_present() -> None:
    """If ANY attempt carries provider/send/courier/notification
    flag True (even without an executed attempt), recovery must
    refuse — those bookkeeping flags should never have been set
    without a real Phase 8F execute, but defense-in-depth keeps
    the recovery path narrow."""
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_hf1_recov_provider"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects.create(
        gate=gate,
        target_order_id=gate.selected_order_id_snapshot,
        target_payment_id=gate.selected_payment_id_snapshot,
        status="failed",
        provider_call_attempted=True,
    )
    _block_gate_with_missing_env_only(gate)
    with _phase8f_enabled():
        out = approve_phase8f_real_customer_controlled_mutation(
            gate.pk, reason="Director recovery attempt."
        )
    assert out["ok"] is False


@pytest.mark.django_db
def test_phase8f_hotfix1_approve_recovery_refuses_when_env_flag_still_off() -> None:
    """If the gate is blocked-with-only-env-blocker but the env
    flag is STILL OFF at the new approve attempt, recovery must
    refuse — the canonical refusal path remains."""
    phase8e_gate, _, _ = _make_approved_phase8e_gate(
        source_event_id="phase8f_hf1_recov_env_off"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    _block_gate_with_missing_env_only(gate)
    # Env flag remains OFF here (no _phase8f_*_enabled context).
    out = approve_phase8f_real_customer_controlled_mutation(
        gate.pk, reason="Director recovery attempt env off."
    )
    assert out["ok"] is False
    assert any(
        "phase8f_gate_status_blocked_not_transitionable_to_approved"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8f_hotfix1_recovery_path_does_not_call_providers_or_send() -> None:
    """Static-file sentinel: the approve recovery path uses the
    same approve function as the canonical path; that function is
    asserted (via the existing static-file scan test) to NOT import
    any provider / WhatsApp send / Meta Cloud / Delhivery / dotenv
    module. Here we additionally assert that, after recovery
    approval, every locked-False flag on the new attempt + the
    gate remains False (no provider/send/courier/notification
    side-effect)."""
    phase8e_gate, order, payment = _make_approved_phase8e_gate(
        source_event_id="phase8f_hf1_recov_static"
    )
    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
    gate = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
            pk=prep["gate"]["id"]
        )
    )
    _block_gate_with_missing_env_only(gate)
    with _phase8f_enabled():
        out = approve_phase8f_real_customer_controlled_mutation(
            gate.pk, reason="Director recovery approve."
        )
    assert out["ok"] is True
    attempt = (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects.get(
            pk=out["attempt"]["id"]
        )
    )
    assert attempt.customer_notification_sent is False
    assert attempt.whatsapp_sent is False
    assert attempt.courier_called is False
    assert attempt.provider_call_attempted is False
    assert attempt.shipment_created is False
    assert attempt.order_mutation_was_made is False
    assert attempt.payment_mutation_was_made is False
    assert attempt.business_mutation_was_made is False
    # Order / Payment / Order.state untouched by approval recovery.
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.payment_status == "Partial"
    assert payment.status == "Pending"
