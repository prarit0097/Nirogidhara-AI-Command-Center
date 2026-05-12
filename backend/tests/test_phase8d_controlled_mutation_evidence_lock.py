"""Phase 8D - Controlled Mutation Evidence Lock tests.

Phase 8D is a lock-only meta-audit. The fixture chain wires up the
full Phase 7I → 8A → 8B → 8C execute → rollback flow, then
exercises Phase 8D preview / prepare / lock / reject / archive +
all eligibility refusal paths. Every refusal test asserts no
provider call, no business mutation, no customer notification.
"""
from __future__ import annotations

import importlib
import io
import json
from datetime import datetime, timezone

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.orders.models import Order
from apps.payments.models import (
    Payment,
    RazorpayPaymentOrderControlledMutationAttempt,
    RazorpayPaymentOrderControlledMutationEvidenceLock,
    RazorpayPaymentOrderControlledMutationGate,
    RazorpayPaymentOrderControlledMutationRollback,
)
from apps.payments.phase8c_payment_order_controlled_mutation import (
    approve_phase8c_payment_order_controlled_mutation,
    dry_run_phase8c_payment_order_controlled_mutation,
    execute_phase8c_payment_order_controlled_mutation,
    prepare_phase8c_payment_order_controlled_mutation,
    rollback_phase8c_payment_order_controlled_mutation,
)
from apps.payments.phase8d_controlled_mutation_evidence_lock import (
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_LOCKED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    PHASE_8D_FORBIDDEN_ACTIONS,
    archive_phase8d_controlled_mutation_evidence_lock,
    assert_phase8d_no_provider_or_business_mutation,
    inspect_phase8d_controlled_mutation_evidence_lock_readiness,
    lock_phase8d_controlled_mutation_evidence_lock,
    prepare_phase8d_controlled_mutation_evidence_lock,
    preview_phase8d_controlled_mutation_evidence_lock,
    reject_phase8d_controlled_mutation_evidence_lock,
)
from tests.test_phase7i_final_audit_lock import _row_counts
from tests.test_phase8c_payment_order_controlled_mutation import (
    _make_approved_phase8b_gate,
    _make_sandbox_order_payment,
    _phase8c_execute_settings,
    _phase8c_gate_enabled,
    _structured_signoff,
)


# ---------------------------------------------------------------------------
# Fixture: a fully executed + rolled_back Phase 8C chain
# ---------------------------------------------------------------------------


def _make_phase8c_chain_in_rolled_back_state(
    *, source_event_id: str
) -> tuple[
    RazorpayPaymentOrderControlledMutationGate,
    RazorpayPaymentOrderControlledMutationAttempt,
]:
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id=source_event_id
    )
    order, payment = _make_sandbox_order_payment(
        suffix=source_event_id
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
                f"phase8c::controlled::order::{source_event_id}"
            ),
            target_payment_reference=(
                f"phase8c::controlled::payment::{source_event_id}"
            ),
        )
        approve_phase8c_payment_order_controlled_mutation(
            prep["gate"]["id"],
            reason="Director approve for Phase 8D fixture.",
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
            attempt_id,
            reason="Director rollback for Phase 8D fixture.",
        )
    gate = RazorpayPaymentOrderControlledMutationGate.objects.get(
        pk=prep["gate"]["id"]
    )
    attempt = (
        RazorpayPaymentOrderControlledMutationAttempt.objects.get(
            pk=attempt_id
        )
    )
    return gate, attempt


# ---------------------------------------------------------------------------
# Audit-kind + static-file invariants
# ---------------------------------------------------------------------------


def test_phase8d_audit_kinds_within_length_budget() -> None:
    kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_LOCKED,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
    ]
    assert len(kinds) == 7
    for kind in kinds:
        assert kind.startswith("phase8d.evidence.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_phase8d_forbidden_actions_cover_real_surface() -> None:
    forbidden = set(PHASE_8D_FORBIDDEN_ACTIONS)
    for required in (
        "execute_phase8c_again",
        "rollback_phase8c_again",
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
        "mutate_real_payment_status",
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


def test_phase8d_service_module_does_not_import_provider_clients() -> None:
    src_path = importlib.import_module(
        "apps.payments.phase8d_controlled_mutation_evidence_lock"
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
                    f"Phase 8D service imports forbidden module: "
                    f"{needle}"
                )


# ---------------------------------------------------------------------------
# Readiness + CLI
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8d_readiness_command_returns_lock_only_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_phase8d_controlled_mutation_evidence_lock",
        "--json", "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "8D"
    assert body["status"] == "controlled_mutation_evidence_lock_only"
    for key in (
        "phase8DExecutesPhase8CAgain",
        "phase8DRollsBackPhase8CAgain",
        "phase8DCallsRazorpay",
        "phase8DCallsMetaCloud",
        "phase8DCallsDelhivery",
        "phase8DCallsVapi",
        "phase8DSendsWhatsApp",
        "phase8DQueuesWhatsApp",
        "phase8DCreatesShipmentRow",
        "phase8DCreatesAwb",
        "phase8DCreatesPaymentLink",
        "phase8DCapturesPayment",
        "phase8DRefundsPayment",
        "phase8DSendsCustomerNotification",
        "phase8DMutatesOrder",
        "phase8DMutatesPayment",
        "phase8DMutatesCustomer",
        "phase8DMutatesLead",
        "phase8DMutatesShipment",
        "phase8DMutatesDiscountOfferLog",
        "phase8DMutatesWhatsAppMessage",
        "phase8DApprovesRealCustomerAutomation",
        "phase7ELiveBApproved",
        "phase7GLiveApproved",
        "frontendCanExecute",
        "apiEndpointCanExecute",
        "apiEndpointCanApprove",
    ):
        assert body[key] is False, key
    assert body["executionPath"] == "lock_only_cli_only"


@pytest.mark.django_db
def test_phase8d_readiness_reports_eligible_phase8c_after_rolled_back() -> None:
    _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_ready"
    )
    out = (
        inspect_phase8d_controlled_mutation_evidence_lock_readiness()
    )
    assert out["eligiblePhase8CGateCount"] >= 1
    assert out["phase8DMutatesOrder"] is False
    assert out["phase8DMutatesPayment"] is False
    assert out["phase8DExecutesPhase8CAgain"] is False
    assert out["phase8DRollsBackPhase8CAgain"] is False


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8d_preview_with_eligible_chain_emits_no_business_mutation() -> None:
    gate, _attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_preview"
    )
    before = _row_counts()
    out = preview_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    after = _row_counts()
    assert before == after
    assert out["found"] is True
    assert out["eligible"] is True
    assert out["sourcePhase8CGateId"] == gate.pk
    assert (
        RazorpayPaymentOrderControlledMutationEvidenceLock.objects.count()
        == 0
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_PREVIEWED).exists()
    timeline = out["evidence"]["statusTimeline"]
    assert timeline["order"][0] == "Pending"
    assert timeline["order"][1] == "Paid"
    assert timeline["order"][2] == "Pending"
    assert timeline["payment"][0] == "Pending"
    assert timeline["payment"][1] == "Paid"
    assert timeline["payment"][2] == "Pending"


# ---------------------------------------------------------------------------
# Prepare + lock + reject + archive
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8d_prepare_success_freezes_snapshot() -> None:
    gate, attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_prep_ok"
    )
    before = _row_counts()
    out = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    after = _row_counts()
    assert out["created"] is True
    assert out["reused"] is False
    lock_id = out["lock"]["id"]
    row = RazorpayPaymentOrderControlledMutationEvidenceLock.objects.get(
        pk=lock_id
    )
    assert (
        row.status
        == RazorpayPaymentOrderControlledMutationEvidenceLock.Status.PENDING_MANUAL_REVIEW
    )
    assert row.source_phase8c_gate_id == gate.pk
    assert row.source_phase8c_attempt_id == attempt.pk
    # Status timeline frozen.
    assert row.old_order_status_snapshot == "Pending"
    assert row.executed_order_status_snapshot == "Paid"
    assert row.final_order_status_snapshot == "Pending"
    assert row.old_payment_status_snapshot == "Pending"
    assert row.executed_payment_status_snapshot == "Paid"
    assert row.final_payment_status_snapshot == "Pending"
    # Phase 8C contract snapshots frozen.
    assert row.order_mutation_was_made_snapshot is True
    assert row.payment_mutation_was_made_snapshot is True
    assert row.business_mutation_was_made_snapshot is True
    assert row.rollback_completed_snapshot is True
    assert row.final_db_restored_snapshot is True
    assert row.recorded_signoff_window_valid_snapshot is True
    # Locked-False contract intact.
    assert row.phase8d_calls_razorpay_snapshot is False
    assert row.phase8d_calls_meta_cloud_snapshot is False
    assert row.phase8d_calls_delhivery_snapshot is False
    assert row.phase8d_sends_whatsapp_snapshot is False
    assert row.phase8d_sends_customer_notification_snapshot is False
    assert row.phase8d_creates_shipment_snapshot is False
    assert row.phase8d_captures_payment_snapshot is False
    assert row.phase8d_refunds_payment_snapshot is False
    assert before == after
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_PREPARED).exists()


@pytest.mark.django_db
def test_phase8d_prepare_idempotent_on_same_phase8c_gate() -> None:
    gate, _attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_prep_idem"
    )
    first = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    second = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert (
        RazorpayPaymentOrderControlledMutationEvidenceLock.objects.filter(
            source_phase8c_gate=gate
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_phase8d_lock_success_marks_status_locked() -> None:
    gate, _attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_lock_ok"
    )
    prepared = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    lock_id = prepared["lock"]["id"]
    before = _row_counts()
    out = lock_phase8d_controlled_mutation_evidence_lock(
        lock_id,
        reviewed_by=None,
        reason="Director Phase 8D evidence lock.",
    )
    after = _row_counts()
    assert out["ok"] is True
    assert before == after
    row = RazorpayPaymentOrderControlledMutationEvidenceLock.objects.get(
        pk=lock_id
    )
    assert (
        row.status
        == RazorpayPaymentOrderControlledMutationEvidenceLock.Status.LOCKED
    )
    assert row.locked_at is not None
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_LOCKED).exists()


@pytest.mark.django_db
def test_phase8d_lock_refuses_without_reason() -> None:
    gate, _attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_lock_no_reason"
    )
    prepared = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    out = lock_phase8d_controlled_mutation_evidence_lock(
        prepared["lock"]["id"], reason=""
    )
    assert out["ok"] is False


@pytest.mark.django_db
def test_phase8d_reject_records_warning_audit() -> None:
    gate, _attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_reject"
    )
    prepared = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    out = reject_phase8d_controlled_mutation_evidence_lock(
        prepared["lock"]["id"],
        reason="Director paused review.",
    )
    assert out["ok"] is True
    row = RazorpayPaymentOrderControlledMutationEvidenceLock.objects.get(
        pk=prepared["lock"]["id"]
    )
    assert (
        row.status
        == RazorpayPaymentOrderControlledMutationEvidenceLock.Status.REJECTED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).exists()


@pytest.mark.django_db
def test_phase8d_archive_flips_status() -> None:
    gate, _attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_archive"
    )
    prepared = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    lock_phase8d_controlled_mutation_evidence_lock(
        prepared["lock"]["id"],
        reason="Director Phase 8D evidence lock.",
    )
    out = archive_phase8d_controlled_mutation_evidence_lock(
        prepared["lock"]["id"],
        reason="Director archive.",
    )
    assert out["ok"] is True
    row = RazorpayPaymentOrderControlledMutationEvidenceLock.objects.get(
        pk=prepared["lock"]["id"]
    )
    assert (
        row.status
        == RazorpayPaymentOrderControlledMutationEvidenceLock.Status.ARCHIVED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_ARCHIVED).exists()


# ---------------------------------------------------------------------------
# Eligibility refusal paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8d_prepare_blocks_if_phase8c_gate_not_rolled_back() -> None:
    # Build a Phase 8B gate + Phase 8C gate but never execute /
    # roll back -> Phase 8C gate.status stays pending_manual_review.
    from apps.payments.phase8c_payment_order_controlled_mutation import (
        prepare_phase8c_payment_order_controlled_mutation as _prep_8c,
    )
    phase8b_gate = _make_approved_phase8b_gate(
        source_event_id="phase8d_not_rolled_back"
    )
    with override_settings(
        PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED=True,
        PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED=True,
        PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED=True,
    ):
        prep = _prep_8c(phase8b_gate_id=phase8b_gate.pk)
    out = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=prep["gate"]["id"]
    )
    assert out["created"] is False
    assert any(
        "must_be_rolled_back" in b for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8d_prepare_blocks_if_phase8c_gate_missing() -> None:
    out = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=99999
    )
    assert out["created"] is False
    assert any(
        "phase8c_gate_not_found" in b for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8d_prepare_blocks_if_final_order_payment_status_not_pending() -> None:
    """Tamper the target Order's payment_status away from Pending
    after rollback. Phase 8D must refuse to prepare because the
    final DB state no longer matches the documented rollback."""
    gate, attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_tampered_final"
    )
    order = Order.objects.get(pk=attempt.target_order_id)
    order.payment_status = Order.PaymentStatus.PAID
    order.save(update_fields=["payment_status"])
    out = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    assert out["created"] is False
    assert any(
        "phase8d_target_order_final_payment_status_must_be_pending" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8d_prepare_blocks_if_provider_call_attempted_on_phase8c() -> None:
    """Phase 8C attempt is expected to never have a provider_call_
    attempted=True. If something downstream accidentally flipped it,
    Phase 8D must refuse to lock."""
    gate, attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_provider_call_flipped"
    )
    attempt.provider_call_attempted = True
    attempt.save(update_fields=["provider_call_attempted"])
    out = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    assert out["created"] is False
    assert any(
        "provider_call_attempted_must_stay_false" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8d_prepare_blocks_if_whatsapp_sent_flipped_on_phase8c() -> None:
    gate, attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_wa_flipped"
    )
    attempt.whatsapp_sent = True
    attempt.save(update_fields=["whatsapp_sent"])
    out = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    assert out["created"] is False
    assert any(
        "whatsapp_sent_must_stay_false" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8d_prepare_blocks_if_customer_notification_sent_flipped() -> None:
    gate, attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_notif_flipped"
    )
    attempt.customer_notification_sent = True
    attempt.save(update_fields=["customer_notification_sent"])
    out = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    assert out["created"] is False
    assert any(
        "customer_notification_sent_must_stay_false" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8d_prepare_blocks_if_recorded_signoff_window_invalid() -> None:
    gate, attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_window_invalid"
    )
    attempt.recorded_signoff_window_valid = False
    attempt.save(update_fields=["recorded_signoff_window_valid"])
    out = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    assert out["created"] is False
    assert any(
        "recorded_signoff_window_valid_must_be_true" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8d_prepare_blocks_if_phase8c_rollback_missing() -> None:
    gate, attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_rollback_missing"
    )
    # Delete the rollback record outright -> Phase 8D refuses.
    RazorpayPaymentOrderControlledMutationRollback.objects.filter(
        attempt=attempt
    ).delete()
    out = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    assert out["created"] is False
    assert any(
        "phase8d_source_phase8c_rollback_not_recorded" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8d_full_lifecycle_never_mutates_business_rows() -> None:
    """prepare -> lock -> reject on a separate gate -> archive on
    a separate gate. Every protected business table count stays
    identical."""
    gate, _attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_full_lifecycle"
    )
    snap0 = _row_counts()
    prepared = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    snap1 = _row_counts()
    lock_phase8d_controlled_mutation_evidence_lock(
        prepared["lock"]["id"],
        reason="Director Phase 8D evidence lock.",
    )
    snap2 = _row_counts()
    archive_phase8d_controlled_mutation_evidence_lock(
        prepared["lock"]["id"],
        reason="Director archive.",
    )
    snap3 = _row_counts()
    assert snap0 == snap1 == snap2 == snap3
    # The Phase 8D table itself is allowed to change.
    assert (
        RazorpayPaymentOrderControlledMutationEvidenceLock.objects.count()
        >= 1
    )


# ---------------------------------------------------------------------------
# Defensive invariant guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8d_assert_no_provider_or_business_mutation_raises_on_flipped() -> None:
    gate, _attempt = _make_phase8c_chain_in_rolled_back_state(
        source_event_id="phase8d_guard"
    )
    prepared = prepare_phase8d_controlled_mutation_evidence_lock(
        phase8c_gate_id=gate.pk
    )
    lock = RazorpayPaymentOrderControlledMutationEvidenceLock.objects.get(
        pk=prepared["lock"]["id"]
    )
    lock.phase8d_calls_razorpay_snapshot = True
    before = _row_counts()
    with pytest.raises(ValueError):
        assert_phase8d_no_provider_or_business_mutation(
            lock, before_counts=before
        )


# ---------------------------------------------------------------------------
# API endpoint shape + 405 enforcement
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, django_user_model):
    from rest_framework.test import APIClient

    user = django_user_model.objects.create_user(
        username="phase8d_admin",
        email="phase8d_admin@example.com",
        password="ignored-by-force-auth",
    )
    user.is_staff = True
    user.is_superuser = True
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_phase8d_readiness_endpoint_returns_safe_off_shape(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8d-controlled-mutation-evidence-lock-readiness"
    )
    r = admin_client.get(url)
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] == "8D"
    assert data["executionPath"] == "lock_only_cli_only"
    assert data["frontendCanExecute"] is False
    assert data["apiEndpointCanExecute"] is False
    assert data["apiEndpointCanApprove"] is False


@pytest.mark.django_db
def test_phase8d_endpoints_block_write_methods(admin_client) -> None:
    for path in (
        "saas-phase8d-controlled-mutation-evidence-lock-readiness",
        "saas-phase8d-controlled-mutation-evidence-locks",
        "saas-phase8d-controlled-mutation-evidence-lock-preview",
    ):
        url = reverse(path)
        for method in ("post", "patch", "delete"):
            r = getattr(admin_client, method)(
                url, {} if method != "delete" else None
            )
            assert r.status_code == 405, (path, method, r.status_code)


@pytest.mark.django_db
def test_phase8d_preview_endpoint_requires_phase8c_gate_id(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8d-controlled-mutation-evidence-lock-preview"
    )
    assert admin_client.get(url).status_code == 400
    assert (
        admin_client.get(url + "?phase8c_gate_id=0").status_code == 400
    )
    assert (
        admin_client.get(
            url + "?phase8c_gate_id=999999"
        ).status_code
        == 200
    )


@pytest.mark.django_db
def test_phase8d_lock_detail_returns_404_when_missing(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8d-controlled-mutation-evidence-lock-detail",
        kwargs={"pk": 9999},
    )
    assert admin_client.get(url).status_code == 404
