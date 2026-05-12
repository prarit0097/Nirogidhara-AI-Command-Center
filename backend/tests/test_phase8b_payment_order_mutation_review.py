"""Phase 8B - Payment -> Order Mutation Review Gate tests.

Phase 8B is review / dry-run only. It chains off an approved Phase
8A sandbox gate (which itself chains off a locked Phase 7I lock);
prepare / dry-run / approve / reject / archive must never call any
provider and never mutate real business rows.
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
from apps.payments.models import (
    RazorpayPaymentOrderMutationReviewDryRun,
    RazorpayPaymentOrderMutationReviewGate,
    RazorpayPaymentOrderMutationSandboxGate,
    RazorpayPhase7FinalAuditLock,
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
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_DRY_RUN_FAILED,
    AUDIT_KIND_DRY_RUN_PASSED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    AUDIT_KIND_ROLLBACK_RECORDED,
    PHASE_8B_FORBIDDEN_ACTIONS,
    approve_phase8b_payment_order_mutation_review_gate,
    archive_phase8b_payment_order_mutation_review_gate,
    assert_phase8b_no_business_mutation,
    dry_run_phase8b_payment_order_mutation_review_gate,
    inspect_phase8b_payment_order_mutation_review_readiness,
    prepare_phase8b_payment_order_mutation_review_gate,
    preview_phase8b_payment_order_mutation_review_gate,
    reject_phase8b_payment_order_mutation_review_gate,
    rollback_dry_run_phase8b_payment_order_mutation_review_gate,
)
from tests.test_phase7i_final_audit_lock import (
    _make_full_source_chain,
    _row_counts,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_locked_phase7i(*, source_event_id: str) -> RazorpayPhase7FinalAuditLock:
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
    return RazorpayPhase7FinalAuditLock.objects.get(pk=lock_id)


def _phase8a_enabled():
    return override_settings(
        PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED=True
    )


def _phase8b_enabled():
    return override_settings(
        PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED=True,
        PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED=True,
    )


def _make_approved_phase8a_gate(
    *, source_event_id: str
) -> RazorpayPaymentOrderMutationSandboxGate:
    lock = _make_locked_phase7i(source_event_id=source_event_id)
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        dry_run_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"],
            synthetic_order_reference=(
                f"phase8a::sandbox::ord_{source_event_id}"
            ),
        )
        approve_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"],
            reason=(
                "Director Phase 8A approve for Phase 8B fixture."
            ),
        )
    return RazorpayPaymentOrderMutationSandboxGate.objects.get(
        pk=prep["gate"]["id"]
    )


# ---------------------------------------------------------------------------
# Audit-kind + static-file invariants
# ---------------------------------------------------------------------------


def test_phase8b_audit_kinds_within_length_budget() -> None:
    kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_DRY_RUN_PASSED,
        AUDIT_KIND_DRY_RUN_FAILED,
        AUDIT_KIND_ROLLBACK_RECORDED,
        AUDIT_KIND_APPROVED,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
    ]
    assert len(kinds) == 10
    for kind in kinds:
        assert kind.startswith("phase8b.payment_order.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_phase8b_forbidden_actions_cover_real_mutation_surface() -> None:
    forbidden = set(PHASE_8B_FORBIDDEN_ACTIONS)
    for required in (
        "mutate_real_order_status",
        "mutate_real_payment_status",
        "send_customer_notification",
        "send_whatsapp_template",
        "queue_whatsapp_outbound",
        "create_shipment_row",
        "create_awb",
        "create_payment_link",
        "capture_razorpay_payment",
        "refund_razorpay_payment",
        "call_razorpay_api",
        "call_meta_cloud_api",
        "call_delhivery_api",
        "call_vapi_api",
        "approve_phase8c_real_mutation",
        "approve_real_customer_automation",
        "edit_dotenv_any",
    ):
        assert required in forbidden, required


def test_phase8b_service_module_does_not_import_provider_clients() -> None:
    """Phase 8B never calls a provider; the service module must not
    import any provider client / send helper / dotenv (static-file
    scan; checks actual import lines, not docstring mentions)."""
    src_path = importlib.import_module(
        "apps.payments.phase8b_payment_order_mutation_review"
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
                    f"Phase 8B service imports forbidden module: "
                    f"{needle}"
                )


# ---------------------------------------------------------------------------
# Readiness + CLI
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8b_readiness_command_returns_review_only_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_phase8b_payment_order_mutation_review_gate",
        "--json", "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "8B"
    assert body["status"] == "payment_order_mutation_review_gate_only"
    for key in (
        "phase8BCallsRazorpay",
        "phase8BCallsMetaCloud",
        "phase8BCallsDelhivery",
        "phase8BCallsVapi",
        "phase8BSendsWhatsApp",
        "phase8BQueuesWhatsApp",
        "phase8BCreatesShipmentRow",
        "phase8BCreatesAwb",
        "phase8BCreatesPaymentLink",
        "phase8BCapturesPayment",
        "phase8BRefundsPayment",
        "phase8BSendsCustomerNotification",
        "phase8BMutatesBusinessRow",
        "phase8BMutatesRealOrder",
        "phase8BMutatesRealPayment",
        "phase8BApprovesPhase8C",
        "phase8BApprovesRealCustomerAutomation",
        "phase8CApproved",
        "phase7ELiveBApproved",
        "phase7GLiveApproved",
        "frontendCanExecute",
        "apiEndpointCanExecute",
        "apiEndpointCanApprove",
    ):
        assert body[key] is False, key
    assert body["executionPath"] == "review_dry_run_only_cli_only"


@pytest.mark.django_db
def test_phase8b_readiness_reports_eligible_phase8a_when_approved() -> None:
    _make_approved_phase8a_gate(source_event_id="evt_phase8b_ready")
    out = inspect_phase8b_payment_order_mutation_review_readiness()
    assert out["eligiblePhase8AGateCount"] >= 1
    assert out["phase8BMutatesBusinessRow"] is False
    assert out["phase8BApprovesPhase8C"] is False
    assert out["phase8BApprovesRealCustomerAutomation"] is False


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8b_preview_with_eligible_gate_emits_no_business_mutation() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_preview"
    )
    before = _row_counts()
    out = preview_phase8b_payment_order_mutation_review_gate(
        phase8a_gate_id=phase8a_gate.pk
    )
    after = _row_counts()
    assert before == after
    assert out["found"] is True
    assert out["sourcePhase8AGateId"] == phase8a_gate.pk
    assert (
        RazorpayPaymentOrderMutationReviewGate.objects.count() == 0
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_PREVIEWED).exists()


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8b_prepare_blocked_when_env_flag_off() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_prep_off"
    )
    out = prepare_phase8b_payment_order_mutation_review_gate(
        phase8a_gate_id=phase8a_gate.pk
    )
    assert out["created"] is False
    assert out["gate"] is None
    assert any(
        "PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8b_prepare_creates_gate_when_flag_on() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_prep_ok"
    )
    before = _row_counts()
    with _phase8b_enabled():
        out = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
    after = _row_counts()
    assert out["created"] is True
    assert out["reused"] is False
    gate_id = out["gate"]["id"]
    row = RazorpayPaymentOrderMutationReviewGate.objects.get(pk=gate_id)
    assert (
        row.status
        == RazorpayPaymentOrderMutationReviewGate.Status.PENDING_MANUAL_REVIEW
    )
    assert row.review_only is True
    assert row.real_mutation_allowed is False
    assert row.real_order_mutation_allowed is False
    assert row.real_payment_mutation_allowed is False
    assert row.customer_notification_allowed is False
    assert row.whatsapp_allowed is False
    assert row.courier_allowed is False
    assert row.phase8c_required is True
    assert row.manual_review_required is True
    assert before == after
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_PREPARED).exists()


@pytest.mark.django_db
def test_phase8b_prepare_idempotent_on_same_phase8a_gate() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_prep_idem"
    )
    with _phase8b_enabled():
        first = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        second = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert (
        RazorpayPaymentOrderMutationReviewGate.objects.filter(
            source_phase8a_gate=phase8a_gate
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_phase8b_prepare_rejects_phase8a_gate_not_approved() -> None:
    # Build a Phase 7I lock + Phase 8A gate but stop at
    # pending_manual_review.
    lock = _make_locked_phase7i(
        source_event_id="evt_phase8b_unapproved_8a"
    )
    with _phase8a_enabled():
        prep_8a = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        phase8a_gate_id = prep_8a["gate"]["id"]
    with _phase8b_enabled():
        out = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate_id
        )
    assert out["created"] is False
    assert any(
        "must_be_approved_for_future_phase8b_review" in b
        for b in out["blockers"]
    )


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8b_dry_run_refuses_without_target_reference() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_dr_no_ref"
    )
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        gate_id = prep["gate"]["id"]
        out = dry_run_phase8b_payment_order_mutation_review_gate(
            gate_id, target_order_reference=""
        )
    assert out["ok"] is False
    assert any(
        "target_order_reference_required" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8b_dry_run_refuses_non_review_target_reference() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_dr_bad_ref"
    )
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        gate_id = prep["gate"]["id"]
        out = dry_run_phase8b_payment_order_mutation_review_gate(
            gate_id,
            target_order_reference="order_REAL_LIVE_001",
        )
    assert out["ok"] is False
    assert any(
        "must_start_with_known_review_prefix" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8b_dry_run_passes_with_review_reference_and_no_mutation() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_dr_ok"
    )
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        gate_id = prep["gate"]["id"]
        before = _row_counts()
        out = dry_run_phase8b_payment_order_mutation_review_gate(
            gate_id,
            target_order_reference=(
                "phase8b::review::order::001"
            ),
        )
        after = _row_counts()
    assert out["ok"] is True
    assert out["dryRun"]["passed"] is True
    assert out["dryRun"]["wouldMutateOrder"] is False
    assert out["dryRun"]["wouldMutatePayment"] is False
    assert out["dryRun"]["wouldNotifyCustomer"] is False
    assert out["dryRun"]["wouldSendWhatsApp"] is False
    assert out["dryRun"]["wouldCallCourier"] is False
    assert out["dryRun"]["wouldCreateShipment"] is False
    assert (
        out["dryRun"]["proposedNewOrderStatus"]
        == "paid_review_candidate"
    )
    assert (
        out["dryRun"]["proposedNewPaymentStatus"]
        == "captured_review_candidate"
    )
    assert before == after
    gate = RazorpayPaymentOrderMutationReviewGate.objects.get(pk=gate_id)
    assert (
        gate.status
        == RazorpayPaymentOrderMutationReviewGate.Status.DRY_RUN_PASSED
    )
    assert gate.dry_run_passed is True
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_DRY_RUN_PASSED
    ).exists()


@pytest.mark.django_db
def test_phase8b_rollback_dry_run_requires_reason_and_records_only() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_rb"
    )
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        dr = dry_run_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"],
            target_order_reference=(
                "phase8b::review::order::002"
            ),
        )
        dr_id = dr["dryRun"]["id"]
        missing = (
            rollback_dry_run_phase8b_payment_order_mutation_review_gate(
                dr_id, reason=""
            )
        )
        assert missing["ok"] is False

        before = _row_counts()
        ok = rollback_dry_run_phase8b_payment_order_mutation_review_gate(
            dr_id, reason="Phase 8B rollback test"
        )
        after = _row_counts()
    assert ok["ok"] is True
    assert before == after
    rec = RazorpayPaymentOrderMutationReviewDryRun.objects.get(pk=dr_id)
    assert rec.rollback_recorded is True
    assert rec.rolled_back_at is not None
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_ROLLBACK_RECORDED
    ).exists()


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8b_approve_refuses_without_passed_dry_run() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_appr_no_dr"
    )
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        out = approve_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"],
            reason="Director Phase 8B approve.",
        )
    assert out["ok"] is False
    assert any(
        "not_transitionable_to_approved" in b
        or "no_passed_dry_run_present" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8b_approve_refuses_without_rollback_dry_run_recorded() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_appr_no_rb"
    )
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        dry_run_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"],
            target_order_reference=(
                "phase8b::review::order::003"
            ),
        )
        out = approve_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"],
            reason="Director Phase 8B approve.",
        )
    assert out["ok"] is False
    assert any(
        "no_rollback_dry_run_recorded" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8b_approve_after_dry_run_and_rollback_flips_status_only() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_appr_ok"
    )
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        dr = dry_run_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"],
            target_order_reference=(
                "phase8b::review::order::004"
            ),
        )
        rollback_dry_run_phase8b_payment_order_mutation_review_gate(
            dr["dryRun"]["id"],
            reason="Director Phase 8B rollback dry-run.",
        )
        before = _row_counts()
        out = approve_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"],
            reason="Director Phase 8B approve.",
        )
        after = _row_counts()
    assert out["ok"] is True
    assert before == after
    gate = RazorpayPaymentOrderMutationReviewGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderMutationReviewGate.Status.APPROVED_FOR_FUTURE_PHASE8C_CONTROLLED_MUTATION_REVIEW
    )
    assert gate.dry_run_passed is True
    assert gate.rollback_dry_run_passed is True
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_APPROVED).exists()


@pytest.mark.django_db
def test_phase8b_reject_requires_reason_and_marks_status_rejected() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_reject"
    )
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        missing = reject_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"], reason=""
        )
        assert missing["ok"] is False
        out = reject_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"],
            reason="Director Phase 8B reject.",
        )
    assert out["ok"] is True
    gate = RazorpayPaymentOrderMutationReviewGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderMutationReviewGate.Status.REJECTED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).exists()


@pytest.mark.django_db
def test_phase8b_archive_records_status_and_writes_audit() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_archive"
    )
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        out = archive_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"],
            reason="Director Phase 8B archive.",
        )
    assert out["ok"] is True
    gate = RazorpayPaymentOrderMutationReviewGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderMutationReviewGate.Status.ARCHIVED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_ARCHIVED).exists()


# ---------------------------------------------------------------------------
# Defensive invariant guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8b_assert_no_business_mutation_raises_when_flag_flipped() -> None:
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_guard"
    )
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        gate_id = prep["gate"]["id"]
    gate = RazorpayPaymentOrderMutationReviewGate.objects.get(pk=gate_id)
    # Tamper one locked-False flag in memory and assert the guard
    # raises -- without persisting.
    gate.real_order_mutation_allowed = True
    before = _row_counts()
    with pytest.raises(ValueError):
        assert_phase8b_no_business_mutation(gate, before_counts=before)


# ---------------------------------------------------------------------------
# API endpoint shape + 405 enforcement
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, django_user_model):
    from rest_framework.test import APIClient

    user = django_user_model.objects.create_user(
        username="phase8b_admin",
        email="phase8b_admin@example.com",
        password="ignored-by-force-auth",
    )
    user.is_staff = True
    user.is_superuser = True
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_phase8b_readiness_endpoint_returns_safe_off_shape(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8b-payment-order-mutation-review-readiness"
    )
    r = admin_client.get(url)
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] == "8B"
    assert (
        data["phase8BPaymentOrderMutationReviewGateEnabled"] is False
    )
    assert data["executionPath"] == "review_dry_run_only_cli_only"
    assert data["frontendCanExecute"] is False
    assert data["apiEndpointCanExecute"] is False
    assert data["apiEndpointCanApprove"] is False


@pytest.mark.django_db
def test_phase8b_readiness_endpoint_blocks_write_methods(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8b-payment-order-mutation-review-readiness"
    )
    for method in ("post", "patch", "delete"):
        r = getattr(admin_client, method)(
            url, {} if method != "delete" else None
        )
        assert r.status_code == 405, (method, r.status_code)


@pytest.mark.django_db
def test_phase8b_gates_endpoint_blocks_write_methods(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8b-payment-order-mutation-review-gates"
    )
    for method in ("post", "patch", "delete"):
        r = getattr(admin_client, method)(
            url, {} if method != "delete" else None
        )
        assert r.status_code == 405, (method, r.status_code)


@pytest.mark.django_db
def test_phase8b_preview_endpoint_requires_phase8a_gate_id(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8b-payment-order-mutation-review-preview"
    )
    assert admin_client.get(url).status_code == 400
    assert (
        admin_client.get(url + "?phase8a_gate_id=0").status_code == 400
    )
    # Missing gate returns a found=False preview, not 404.
    assert (
        admin_client.get(
            url + "?phase8a_gate_id=999999"
        ).status_code
        == 200
    )


@pytest.mark.django_db
def test_phase8b_gate_detail_returns_404_when_missing(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8b-payment-order-mutation-review-gate-detail",
        kwargs={"pk": 9999},
    )
    assert admin_client.get(url).status_code == 404


@pytest.mark.django_db
def test_phase8b_dry_runs_endpoint_returns_404_when_gate_missing(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8b-payment-order-mutation-review-dry-runs",
        kwargs={"gate_id": 9999},
    )
    assert admin_client.get(url).status_code == 404


# ---------------------------------------------------------------------------
# Forensic global no-business-mutation check
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8b_full_lifecycle_never_mutates_business_rows() -> None:
    """Run prepare -> dry-run -> rollback -> approve. At every
    snapshot the Order / Payment / Shipment / DiscountOfferLog /
    WhatsApp* tables must be identical."""
    phase8a_gate = _make_approved_phase8a_gate(
        source_event_id="evt_phase8b_full_lifecycle"
    )
    snap0 = _row_counts()
    with _phase8b_enabled():
        prep = prepare_phase8b_payment_order_mutation_review_gate(
            phase8a_gate_id=phase8a_gate.pk
        )
        snap1 = _row_counts()
        dr = dry_run_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"],
            target_order_reference=(
                "phase8b::review::order::full_lifecycle"
            ),
        )
        snap2 = _row_counts()
        rollback_dry_run_phase8b_payment_order_mutation_review_gate(
            dr["dryRun"]["id"],
            reason="Phase 8B rollback dry-run full lifecycle.",
        )
        snap3 = _row_counts()
        approve_phase8b_payment_order_mutation_review_gate(
            prep["gate"]["id"],
            reason="Phase 8B approve full lifecycle.",
        )
        snap4 = _row_counts()
    # Phase 8B NEVER mutates the protected business tables.
    assert snap0 == snap1 == snap2 == snap3 == snap4
    # The Phase 8B tables themselves are allowed to change.
    assert (
        RazorpayPaymentOrderMutationReviewGate.objects.count() >= 1
    )
    assert (
        RazorpayPaymentOrderMutationReviewDryRun.objects.count() >= 1
    )
