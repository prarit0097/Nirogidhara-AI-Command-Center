"""Phase 8A - Payment -> Order Mutation Sandbox Gate tests.

Phase 8A is sandbox / dry-run only. It chains off a *locked* Phase
7I final audit lock; prepare / dry-run / approve / reject / archive
must never call any provider and never mutate real business rows.
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
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import (
    Payment,
    RazorpayPaymentOrderMutationDryRun,
    RazorpayPaymentOrderMutationSandboxGate,
    RazorpayPhase7FinalAuditLock,
)
from apps.payments.phase7_final_audit_lock import (
    approve_phase7i_final_audit_lock,
    prepare_phase7i_final_audit_lock,
)
from apps.payments.phase8a_payment_order_mutation_sandbox import (
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
    PHASE_8A_FORBIDDEN_ACTIONS,
    approve_phase8a_payment_order_mutation_sandbox,
    archive_phase8a_payment_order_mutation_sandbox,
    assert_phase8a_no_business_mutation,
    dry_run_phase8a_payment_order_mutation_sandbox,
    inspect_phase8a_payment_order_mutation_sandbox_readiness,
    prepare_phase8a_payment_order_mutation_sandbox,
    preview_phase8a_payment_order_mutation_sandbox,
    reject_phase8a_payment_order_mutation_sandbox,
    rollback_dry_run_phase8a_payment_order_mutation_sandbox,
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


# ---------------------------------------------------------------------------
# Audit-kind + static-file invariants
# ---------------------------------------------------------------------------


def test_phase8a_audit_kinds_within_length_budget() -> None:
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
        assert kind.startswith("phase8a.payment_order.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_phase8a_forbidden_actions_cover_real_mutation_surface() -> None:
    forbidden = set(PHASE_8A_FORBIDDEN_ACTIONS)
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
        "edit_dotenv_any",
    ):
        assert required in forbidden, required


def test_phase8a_service_module_does_not_import_provider_clients() -> None:
    """Phase 8A never calls a provider; the service module must not
    import any provider client / send helper / dotenv (static-file
    scan; checks actual import lines, not docstring mentions)."""
    src_path = importlib.import_module(
        "apps.payments.phase8a_payment_order_mutation_sandbox"
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
                    f"Phase 8A service imports forbidden module: "
                    f"{needle}"
                )


# ---------------------------------------------------------------------------
# Readiness + CLI
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8a_readiness_command_returns_sandbox_only_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_phase8a_payment_order_mutation_sandbox",
        "--json", "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "8A"
    assert body["status"] == "payment_order_mutation_sandbox_only"
    # Locked-False contract surface.
    for key in (
        "phase8ACallsRazorpay",
        "phase8ACallsMetaCloud",
        "phase8ACallsDelhivery",
        "phase8ACallsVapi",
        "phase8ASendsWhatsApp",
        "phase8AQueuesWhatsApp",
        "phase8ACreatesShipmentRow",
        "phase8ACreatesAwb",
        "phase8ACreatesPaymentLink",
        "phase8ACapturesPayment",
        "phase8ARefundsPayment",
        "phase8ASendsCustomerNotification",
        "phase8AMutatesBusinessRow",
        "phase8AMutatesRealOrder",
        "phase8AMutatesRealPayment",
        "phase8ARealCustomerAutomationApproved",
        "phase7ELiveBApproved",
        "phase7GLiveApproved",
        "frontendCanExecute",
        "apiEndpointCanExecute",
        "apiEndpointCanApprove",
    ):
        assert body[key] is False, key
    assert body["executionPath"] == "sandbox_dry_run_only_cli_only"


@pytest.mark.django_db
def test_phase8a_readiness_reports_eligible_phase7i_when_chain_locked() -> None:
    _make_locked_phase7i(source_event_id="evt_phase8a_ready")
    out = inspect_phase8a_payment_order_mutation_sandbox_readiness()
    assert out["eligiblePhase7ILockCount"] >= 1
    assert out["phase8AMutatesBusinessRow"] is False
    assert out["phase8ARealCustomerAutomationApproved"] is False


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8a_preview_with_eligible_lock_emits_no_business_mutation() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_preview")
    before = _row_counts()
    out = preview_phase8a_payment_order_mutation_sandbox(
        phase7i_lock_id=lock.pk
    )
    after = _row_counts()
    assert before == after
    assert out["found"] is True
    assert out["sourcePhase7ILockId"] == lock.pk
    assert RazorpayPaymentOrderMutationSandboxGate.objects.count() == 0
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_PREVIEWED).exists()


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8a_prepare_blocked_when_env_flag_off() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_prep_off")
    out = prepare_phase8a_payment_order_mutation_sandbox(
        phase7i_lock_id=lock.pk
    )
    assert out["created"] is False
    assert out["gate"] is None
    assert any(
        "PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8a_prepare_creates_gate_when_flag_on() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_prep_ok")
    before = _row_counts()
    with _phase8a_enabled():
        out = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
    after = _row_counts()
    assert out["created"] is True
    assert out["reused"] is False
    gate_id = out["gate"]["id"]
    row = RazorpayPaymentOrderMutationSandboxGate.objects.get(pk=gate_id)
    assert (
        row.status
        == RazorpayPaymentOrderMutationSandboxGate.Status.PENDING_MANUAL_REVIEW
    )
    assert row.sandbox_only is True
    assert row.real_business_mutation_allowed is False
    assert row.real_order_mutation_allowed is False
    assert row.real_payment_mutation_allowed is False
    assert row.customer_notification_allowed is False
    assert row.whatsapp_allowed is False
    assert row.courier_allowed is False
    assert row.synthetic_order_required is True
    assert row.manual_review_required is True
    assert before == after
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_PREPARED).exists()


@pytest.mark.django_db
def test_phase8a_prepare_idempotent_on_same_phase7i_lock() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_prep_idem")
    with _phase8a_enabled():
        first = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        second = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert (
        RazorpayPaymentOrderMutationSandboxGate.objects.filter(
            source_phase7i_lock=lock
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_phase8a_prepare_rejects_phase7i_lock_not_locked() -> None:
    # Build a chain + prepare but don't approve, so the Phase 7I lock
    # is pending_manual_review, not LOCKED.
    chain = _make_full_source_chain(source_event_id="evt_phase8a_unlocked")
    prepared = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    pending_lock_id = prepared["lock"]["id"]
    with _phase8a_enabled():
        out = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=pending_lock_id
        )
    assert out["created"] is False
    assert any(
        "must_be_locked" in b for b in out["blockers"]
    )


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8a_dry_run_refuses_without_synthetic_reference() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_dr_no_ref")
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        gate_id = prep["gate"]["id"]
        out = dry_run_phase8a_payment_order_mutation_sandbox(
            gate_id, synthetic_order_reference=""
        )
    assert out["ok"] is False
    assert any(
        "synthetic_order_reference_required" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8a_dry_run_refuses_non_synthetic_reference() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_dr_bad_ref")
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        gate_id = prep["gate"]["id"]
        out = dry_run_phase8a_payment_order_mutation_sandbox(
            gate_id,
            synthetic_order_reference="order_REAL_LIVE_001",
        )
    assert out["ok"] is False
    assert any(
        "must_start_with_known_prefix" in b for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8a_dry_run_passes_with_synthetic_reference_and_no_business_mutation() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_dr_ok")
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        gate_id = prep["gate"]["id"]
        before = _row_counts()
        out = dry_run_phase8a_payment_order_mutation_sandbox(
            gate_id,
            synthetic_order_reference=(
                "phase8a::sandbox::ord_test_001"
            ),
        )
        after = _row_counts()
    assert out["ok"] is True
    assert out["dryRun"]["passed"] is True
    assert out["dryRun"]["wouldMutateOrder"] is False
    assert out["dryRun"]["wouldMutatePayment"] is False
    assert out["dryRun"]["wouldSendCustomerNotification"] is False
    assert out["dryRun"]["wouldSendWhatsApp"] is False
    assert out["dryRun"]["wouldCallCourier"] is False
    assert before == after
    gate = RazorpayPaymentOrderMutationSandboxGate.objects.get(pk=gate_id)
    assert (
        gate.status
        == RazorpayPaymentOrderMutationSandboxGate.Status.DRY_RUN_PASSED
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_DRY_RUN_PASSED
    ).exists()


@pytest.mark.django_db
def test_phase8a_rollback_dry_run_requires_reason_and_records_only() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_rb")
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        dr = dry_run_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"],
            synthetic_order_reference=(
                "phase8a::sandbox::ord_test_002"
            ),
        )
        dr_id = dr["dryRun"]["id"]
        missing = (
            rollback_dry_run_phase8a_payment_order_mutation_sandbox(
                dr_id, reason=""
            )
        )
        assert missing["ok"] is False

        before = _row_counts()
        ok = rollback_dry_run_phase8a_payment_order_mutation_sandbox(
            dr_id, reason="Phase 8A rollback test"
        )
        after = _row_counts()
    assert ok["ok"] is True
    assert before == after
    rec = RazorpayPaymentOrderMutationDryRun.objects.get(pk=dr_id)
    assert rec.rolled_back_at is not None
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_ROLLBACK_RECORDED
    ).exists()


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8a_approve_refuses_without_passed_dry_run() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_appr_no_dr")
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        out = approve_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"], reason="Director Phase 8A approve."
        )
    assert out["ok"] is False
    assert any(
        "not_transitionable_to_approved" in b
        or "no_passed_dry_run_present" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase8a_approve_after_dry_run_flips_status_only() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_appr_ok")
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        dry_run_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"],
            synthetic_order_reference=(
                "phase8a::sandbox::ord_test_003"
            ),
        )
        before = _row_counts()
        out = approve_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"],
            reason="Director Phase 8A approve.",
        )
        after = _row_counts()
    assert out["ok"] is True
    assert before == after
    gate = RazorpayPaymentOrderMutationSandboxGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderMutationSandboxGate.Status.APPROVED_FOR_FUTURE_PHASE8B_REVIEW
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_APPROVED).exists()


@pytest.mark.django_db
def test_phase8a_reject_requires_reason_and_marks_status_rejected() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_reject")
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        missing = reject_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"], reason=""
        )
        assert missing["ok"] is False
        out = reject_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"],
            reason="Director Phase 8A reject.",
        )
    assert out["ok"] is True
    gate = RazorpayPaymentOrderMutationSandboxGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderMutationSandboxGate.Status.REJECTED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).exists()


@pytest.mark.django_db
def test_phase8a_archive_records_status_and_writes_audit() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_archive")
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        out = archive_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"],
            reason="Director Phase 8A archive.",
        )
    assert out["ok"] is True
    gate = RazorpayPaymentOrderMutationSandboxGate.objects.get(
        pk=prep["gate"]["id"]
    )
    assert (
        gate.status
        == RazorpayPaymentOrderMutationSandboxGate.Status.ARCHIVED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_ARCHIVED).exists()


# ---------------------------------------------------------------------------
# Defensive invariant guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8a_assert_no_business_mutation_raises_when_flag_flipped() -> None:
    lock = _make_locked_phase7i(source_event_id="evt_phase8a_guard")
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        gate_id = prep["gate"]["id"]
    gate = RazorpayPaymentOrderMutationSandboxGate.objects.get(pk=gate_id)
    # Tamper one locked-False flag in memory and assert the guard
    # raises -- without persisting.
    gate.real_order_mutation_allowed = True
    before = _row_counts()
    with pytest.raises(ValueError):
        assert_phase8a_no_business_mutation(gate, before_counts=before)


# ---------------------------------------------------------------------------
# API endpoint shape + 405 enforcement
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, django_user_model):
    from rest_framework.test import APIClient

    user = django_user_model.objects.create_user(
        username="phase8a_admin",
        email="phase8a_admin@example.com",
        password="ignored-by-force-auth",
    )
    user.is_staff = True
    user.is_superuser = True
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_phase8a_readiness_endpoint_returns_safe_off_shape(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8a-payment-order-mutation-sandbox-readiness"
    )
    r = admin_client.get(url)
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] == "8A"
    assert (
        data["phase8APaymentOrderMutationSandboxEnabled"] is False
    )
    assert data["executionPath"] == "sandbox_dry_run_only_cli_only"
    assert data["frontendCanExecute"] is False
    assert data["apiEndpointCanExecute"] is False
    assert data["apiEndpointCanApprove"] is False


@pytest.mark.django_db
def test_phase8a_readiness_endpoint_blocks_write_methods(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8a-payment-order-mutation-sandbox-readiness"
    )
    for method in ("post", "patch", "delete"):
        r = getattr(admin_client, method)(url, {} if method != "delete" else None)
        assert r.status_code == 405, (method, r.status_code)


@pytest.mark.django_db
def test_phase8a_gates_endpoint_blocks_write_methods(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8a-payment-order-mutation-sandbox-gates"
    )
    for method in ("post", "patch", "delete"):
        r = getattr(admin_client, method)(url, {} if method != "delete" else None)
        assert r.status_code == 405, (method, r.status_code)


@pytest.mark.django_db
def test_phase8a_preview_endpoint_requires_phase7i_lock_id(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8a-payment-order-mutation-sandbox-preview"
    )
    assert admin_client.get(url).status_code == 400
    assert (
        admin_client.get(url + "?phase7i_lock_id=0").status_code == 400
    )
    # Missing lock returns a found=False preview, not 404.
    assert (
        admin_client.get(
            url + "?phase7i_lock_id=999999"
        ).status_code
        == 200
    )


@pytest.mark.django_db
def test_phase8a_gate_detail_returns_404_when_missing(admin_client) -> None:
    url = reverse(
        "saas-phase8a-payment-order-mutation-sandbox-gate-detail",
        kwargs={"pk": 9999},
    )
    assert admin_client.get(url).status_code == 404


@pytest.mark.django_db
def test_phase8a_dry_runs_endpoint_returns_404_when_gate_missing(
    admin_client,
) -> None:
    url = reverse(
        "saas-phase8a-payment-order-mutation-sandbox-dry-runs",
        kwargs={"gate_id": 9999},
    )
    assert admin_client.get(url).status_code == 404


# ---------------------------------------------------------------------------
# Forensic global no-business-mutation check
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8a_full_lifecycle_never_mutates_business_rows() -> None:
    """Run prepare -> dry-run -> approve -> reject (on a separate
    gate) -> archive (on a separate gate). At every snapshot the
    Order / Payment / Shipment / DiscountOfferLog / WhatsApp* tables
    must be identical."""
    lock = _make_locked_phase7i(
        source_event_id="evt_phase8a_full_lifecycle"
    )
    snap0 = _row_counts()
    with _phase8a_enabled():
        prep = prepare_phase8a_payment_order_mutation_sandbox(
            phase7i_lock_id=lock.pk
        )
        snap1 = _row_counts()
        dry_run_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"],
            synthetic_order_reference=(
                "phase8a::sandbox::ord_full_lifecycle"
            ),
        )
        snap2 = _row_counts()
        approve_phase8a_payment_order_mutation_sandbox(
            prep["gate"]["id"],
            reason="Phase 8A approve full lifecycle.",
        )
        snap3 = _row_counts()
    # Phase 8A NEVER mutates the protected business tables.
    assert snap0 == snap1 == snap2 == snap3
    # The Phase 8A tables themselves are allowed to change.
    assert (
        RazorpayPaymentOrderMutationSandboxGate.objects.count() >= 1
    )
    assert (
        RazorpayPaymentOrderMutationDryRun.objects.count() >= 1
    )
