"""Phase 7I — Final Phase 7 Payment + WhatsApp + Courier Audit Lock tests.

Phase 7I is lock-only meta-audit. The fixture chain wires up a full
Phase 7D + 7E-Live-A + 7G + 7H source chain (with the Meta Cloud
wrapper + Delhivery wrapper both patched at the boundary so no real
network call is made), then exercises prepare / approve / reject /
archive / readiness / preview. Every refusal test asserts no
provider call, no business mutation, no customer notification, no
real-customer flag flip.
"""
from __future__ import annotations

import importlib
import io
import json
from datetime import datetime, timezone
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import (
    Payment,
    RazorpayCourierExecutionAttempt,
    RazorpayCourierExecutionEvidenceLock,
    RazorpayPhase7FinalAuditLock,
    RazorpayWhatsAppInternalSendAttempt,
)
from apps.payments.phase7_final_audit_lock import (
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_LOCKED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    approve_phase7i_final_audit_lock,
    archive_phase7i_final_audit_lock,
    assert_phase7i_no_provider_or_business_mutation,
    inspect_phase7i_final_audit_lock_readiness,
    prepare_phase7i_final_audit_lock,
    preview_phase7i_final_audit_lock,
    reject_phase7i_final_audit_lock,
)
from apps.payments.razorpay_courier_execution_evidence_lock import (
    approve_phase7h_evidence_lock,
    prepare_phase7h_evidence_lock,
)
from apps.shipments.models import RescueAttempt, Shipment, WorkflowStep
from apps.whatsapp.integrations.whatsapp.base import (
    ProviderSendResult,
)
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from tests.test_phase7e_live_internal_whatsapp_send import (
    _ALLOWED_LAST4,
    _ALLOWED_NUMBER,
    _make_approved_attempt as _make_approved_phase7e_live_attempt,
    _phase7e_live_test_settings,
    _structured_signoff as _phase7e_live_structured_signoff,
)
from apps.payments.razorpay_whatsapp_internal_send import (
    execute_phase7e_live_internal_send,
    rollback_phase7e_live_internal_send,
)
from tests.test_phase7g_courier_execution import (
    _make_approved_phase7g_attempt,
    _phase7g_execute_settings,
    _signoff_text as _phase7g_signoff_text,
)
from apps.payments.razorpay_courier_execution import (
    execute_phase7g_courier_one_shot,
    rollback_phase7g_courier_execution_attempt,
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
        "workflow_step": WorkflowStep.objects.count(),
        "rescue_attempt": RescueAttempt.objects.count(),
    }


def _executed_then_rolled_back_phase7e_live(
    *,
    source_event_id: str,
) -> RazorpayWhatsAppInternalSendAttempt:
    """Walk a Phase 7E-Live-A attempt through execute + rollback so
    it lands in rollback_recorded with whatsapp_message_created=True
    and a provider_message_id. The Meta Cloud client is patched.
    """
    attempt = _make_approved_phase7e_live_attempt()
    fake_provider = mock.MagicMock()
    fake_provider.send_template_message = mock.MagicMock(
        return_value=ProviderSendResult(
            provider="meta_cloud",
            provider_message_id=f"wamid.phase7i_{source_event_id}",
            status="sent",
        )
    )
    with _phase7e_live_test_settings(), mock.patch(
        "apps.whatsapp.integrations.whatsapp.meta_cloud_client.MetaCloudProvider",
        mock.MagicMock(return_value=fake_provider),
    ):
        execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=_phase7e_live_structured_signoff(),
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
    rollback_phase7e_live_internal_send(
        attempt.pk, reason="Phase 7I fixture rollback"
    )
    attempt.refresh_from_db()
    return attempt


def _executed_then_rolled_back_phase7g(
    *,
    source_event_id: str,
) -> RazorpayCourierExecutionAttempt:
    attempt = _make_approved_phase7g_attempt(
        source_event_id=source_event_id
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper",
        return_value={
            "awb": f"DLH7I{source_event_id[:6].upper()}",
            "status": "Pickup Scheduled",
            "tracking_url": (
                f"https://delhivery.example/track/DLH7I"
                f"{source_event_id[:6].upper()}"
            ),
        },
    ):
        execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_phase7g_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    rollback_phase7g_courier_execution_attempt(
        attempt.pk, reason="Phase 7I fixture rollback"
    )
    attempt.refresh_from_db()
    return attempt


def _make_locked_phase7h(
    phase7g_attempt: RazorpayCourierExecutionAttempt,
) -> RazorpayCourierExecutionEvidenceLock:
    prepared = prepare_phase7h_evidence_lock(phase7g_attempt.pk)
    lock_id = prepared["lock"]["id"]
    approve_phase7h_evidence_lock(
        lock_id,
        reviewed_by=None,
        reason="Phase 7I fixture: lock Phase 7H evidence",
    )
    return RazorpayCourierExecutionEvidenceLock.objects.get(pk=lock_id)


def _make_full_source_chain(
    *,
    source_event_id: str,
) -> dict:
    """Build a full Phase 7D + 7E-Live-A + 7G + 7H source chain
    consistent with the on-VPS state. Returns the four resolved
    rows.
    """
    phase7e_live = _executed_then_rolled_back_phase7e_live(
        source_event_id=source_event_id
    )
    phase7g = _executed_then_rolled_back_phase7g(
        source_event_id=source_event_id
    )
    phase7h = _make_locked_phase7h(phase7g)
    phase7d = phase7g.source_phase7d_attempt
    return {
        "phase7d": phase7d,
        "phase7e_live": phase7e_live,
        "phase7g": phase7g,
        "phase7h": phase7h,
    }


# ---------------------------------------------------------------------------
# Audit-kind + static-file invariants
# ---------------------------------------------------------------------------


def test_phase7i_audit_kinds_within_length_budget() -> None:
    audit_kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_LOCKED,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
    ]
    assert len(audit_kinds) == 7
    for kind in audit_kinds:
        assert kind.startswith("phase7i.final_audit.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_phase7i_service_module_does_not_import_provider_clients() -> None:
    """Phase 7I never calls a provider — the service module must not
    import any provider client / send helper. Check actual import
    lines (not docstring mentions)."""
    src_path = importlib.import_module(
        "apps.payments.phase7_final_audit_lock"
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
                    f"Phase 7I service imports forbidden module: "
                    f"{needle}"
                )


# ---------------------------------------------------------------------------
# Readiness + management command
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7i_readiness_command_returns_lock_only_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_phase7i_final_audit_lock",
        "--json", "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "7I"
    assert body["status"] == "final_phase7_audit_lock_only"
    for key in (
        "phase7ICallsRazorpay",
        "phase7ICallsMetaCloud",
        "phase7ICallsDelhivery",
        "phase7ICallsVapi",
        "phase7ISendsWhatsApp",
        "phase7IQueuesWhatsApp",
        "phase7ICreatesShipmentRow",
        "phase7ICreatesAwb",
        "phase7ICreatesPaymentLink",
        "phase7ICapturesPayment",
        "phase7IRefundsPayment",
        "phase7ISendsCustomerNotification",
        "phase7IMutatesBusinessRow",
        "phase7ELiveBApproved",
        "phase7GLiveApproved",
    ):
        assert body[key] is False, key


@pytest.mark.django_db
def test_phase7i_readiness_counts_full_chain() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_readiness"
    )
    out = inspect_phase7i_final_audit_lock_readiness()
    assert out["eligiblePhase7HEvidenceLockCount"] >= 1
    assert out["eligiblePhase7ELiveAttemptCount"] >= 1
    assert out["eligiblePhase7GAttemptCount"] >= 1
    assert out["phase7IMutatesBusinessRow"] is False


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7i_preview_with_eligible_chain_emits_no_rows() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_preview"
    )
    before = _row_counts()
    out = preview_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    after = _row_counts()
    assert out["eligible"] is True
    assert out["phase7DAttemptId"] == chain["phase7d"].pk
    assert (
        out["phase7ELiveAttemptId"] == chain["phase7e_live"].pk
    )
    assert out["phase7GAttemptId"] == chain["phase7g"].pk
    assert out["phase7HEvidenceLockId"] == chain["phase7h"].pk
    assert RazorpayPhase7FinalAuditLock.objects.count() == 0
    assert before == after
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_PREVIEWED
    ).exists()


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7i_prepare_success_creates_lock() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_prepare_ok"
    )
    before = _row_counts()
    out = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    after = _row_counts()

    assert out["created"] is True
    assert out["reused"] is False
    lock_id = out["lock"]["id"]
    row = RazorpayPhase7FinalAuditLock.objects.get(pk=lock_id)
    assert (
        row.status
        == RazorpayPhase7FinalAuditLock.Status.PENDING_MANUAL_REVIEW
    )
    # Snapshot the four sources.
    assert row.source_phase7d_attempt_id == chain["phase7d"].pk
    assert (
        row.source_phase7e_live_send_attempt_id
        == chain["phase7e_live"].pk
    )
    assert row.source_phase7g_attempt_id == chain["phase7g"].pk
    assert (
        row.source_phase7h_evidence_lock_id == chain["phase7h"].pk
    )
    # Locked-False snapshot contract intact.
    assert row.phase7d_business_mutation_was_made_snapshot is False
    assert row.phase7e_live_customer_notification_sent_snapshot is False
    assert row.phase7e_live_business_mutation_was_made_snapshot is False
    assert row.phase7e_live_real_customer_phone_used_snapshot is False
    assert row.phase7g_shipment_created_snapshot is False
    assert row.phase7g_business_mutation_was_made_snapshot is False
    assert row.phase7g_customer_notification_sent_snapshot is False
    assert row.phase7h_shipment_created_snapshot is False
    assert row.phase7h_business_mutation_was_made_snapshot is False
    # No business mutation across the prepare path.
    assert before == after
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_PREPARED
    ).exists()


@pytest.mark.django_db
def test_phase7i_prepare_idempotent_on_same_phase7h_lock() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_prepare_idem"
    )
    a = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    b = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    assert a["created"] is True
    assert b["created"] is False
    assert b["reused"] is True
    assert RazorpayPhase7FinalAuditLock.objects.count() == 1


@pytest.mark.django_db
def test_phase7i_prepare_rejects_missing_phase7h_lock() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_no_phase7h"
    )
    out = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=999_999,
    )
    assert out["created"] is False
    assert out["lock"] is None
    assert any(
        "phase7i_source_phase7h_evidence_lock_not_found" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7i_prepare_rejects_unlocked_phase7h() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_unlocked_phase7h"
    )
    # Force the Phase 7H lock back into pending_manual_review.
    chain["phase7h"].status = (
        RazorpayCourierExecutionEvidenceLock.Status.PENDING_MANUAL_REVIEW
    )
    chain["phase7h"].save(update_fields=["status"])
    out = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    assert out["created"] is False
    assert any(
        "phase7i_source_phase7h_evidence_lock_status_must_be_locked" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7i_prepare_rejects_missing_phase7e_live_attempt() -> (
    None
):
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_no_phase7e_live"
    )
    out = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=999_999,
    )
    assert out["created"] is False
    assert any(
        "phase7i_source_phase7e_live_attempt_not_found" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7i_prepare_rejects_phase7e_live_not_rollback_recorded() -> (
    None
):
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_phase7e_executed_only"
    )
    # Push back to executed so it no longer qualifies.
    chain["phase7e_live"].status = (
        RazorpayWhatsAppInternalSendAttempt.Status.EXECUTED
    )
    chain["phase7e_live"].save(update_fields=["status"])
    out = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    assert out["created"] is False
    assert any(
        "phase7i_source_phase7e_live_attempt_status_must_be_rollback_recorded"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7i_prepare_rejects_missing_phase7e_provider_message_id() -> (
    None
):
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_no_msg_id"
    )
    chain["phase7e_live"].provider_message_id = ""
    chain["phase7e_live"].save(update_fields=["provider_message_id"])
    out = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    assert out["created"] is False
    assert any(
        "phase7i_source_phase7e_live_attempt_provider_message_id_must_be_present"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7i_prepare_rejects_real_customer_phone_used() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_real_phone"
    )
    chain["phase7e_live"].real_customer_phone_used = True
    chain["phase7e_live"].save(
        update_fields=["real_customer_phone_used"]
    )
    out = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    assert out["created"] is False
    assert any(
        "phase7i_source_phase7e_live_attempt_real_customer_phone_used_must_be_false"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7i_prepare_rejects_business_mutation_on_phase7g() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_phase7g_mutation"
    )
    chain["phase7g"].business_mutation_was_made = True
    chain["phase7g"].save(
        update_fields=["business_mutation_was_made"]
    )
    out = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    assert out["created"] is False
    assert any(
        "phase7i_source_phase7g_attempt_business_mutation_was_made_must_be_false"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7i_prepare_rejects_shipment_created_on_phase7g() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_phase7g_shipment"
    )
    chain["phase7g"].shipment_created = True
    chain["phase7g"].save(update_fields=["shipment_created"])
    out = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    assert out["created"] is False
    assert any(
        "phase7i_source_phase7g_attempt_shipment_created_must_be_false"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7i_prepare_rejects_customer_notification_on_phase7g() -> (
    None
):
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_phase7g_notify"
    )
    chain["phase7g"].customer_notification_sent = True
    chain["phase7g"].save(
        update_fields=["customer_notification_sent"]
    )
    out = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    assert out["created"] is False
    assert any(
        "phase7i_source_phase7g_attempt_customer_notification_sent_must_be_false"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7i_prepare_rejects_when_kill_switch_disabled() -> None:
    from apps.saas.models import RuntimeKillSwitch

    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_kill_off"
    )
    kill, _ = RuntimeKillSwitch.objects.get_or_create(
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        provider_type="",
        operation_type="",
    )
    kill.enabled = False
    kill.save()
    try:
        out = prepare_phase7i_final_audit_lock(
            phase7g_attempt_id=chain["phase7g"].pk,
            phase7h_evidence_lock_id=chain["phase7h"].pk,
        )
    finally:
        kill.enabled = True
        kill.save()
    assert out["created"] is False
    assert any(
        "runtime_kill_switch_disabled" in b for b in out["blockers"]
    )


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7i_approve_locks_with_reason() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_approve_ok"
    )
    prepared = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    lock_id = prepared["lock"]["id"]
    AuditEvent.objects.filter(kind=AUDIT_KIND_LOCKED).delete()
    out = approve_phase7i_final_audit_lock(
        lock_id, reviewed_by=None, reason="Director Phase 7I lock."
    )
    assert out["ok"] is True
    row = RazorpayPhase7FinalAuditLock.objects.get(pk=lock_id)
    assert row.status == RazorpayPhase7FinalAuditLock.Status.LOCKED
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_LOCKED).exists()


@pytest.mark.django_db
def test_phase7i_approve_refuses_without_reason() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_no_reason"
    )
    prepared = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    out = approve_phase7i_final_audit_lock(
        prepared["lock"]["id"], reason=""
    )
    assert out["ok"] is False


@pytest.mark.django_db
def test_phase7i_reject_records_warning_audit() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_reject"
    )
    prepared = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).delete()
    out = reject_phase7i_final_audit_lock(
        prepared["lock"]["id"],
        reason="Director paused final-audit review.",
    )
    assert out["ok"] is True
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_REJECTED
    ).exists()


@pytest.mark.django_db
def test_phase7i_archive_flips_status() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_archive"
    )
    prepared = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    out = archive_phase7i_final_audit_lock(
        prepared["lock"]["id"], reason="Director archive."
    )
    assert out["ok"] is True
    row = RazorpayPhase7FinalAuditLock.objects.get(
        pk=prepared["lock"]["id"]
    )
    assert (
        row.status == RazorpayPhase7FinalAuditLock.Status.ARCHIVED
    )


# ---------------------------------------------------------------------------
# Defensive guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7i_guard_raises_when_snapshot_boolean_flipped() -> None:
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_guard"
    )
    prepared = prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    lock = RazorpayPhase7FinalAuditLock.objects.get(
        pk=prepared["lock"]["id"]
    )
    lock.phase7g_shipment_created_snapshot = True
    lock.save(update_fields=["phase7g_shipment_created_snapshot"])
    AuditEvent.objects.filter(kind=AUDIT_KIND_BLOCKED).delete()
    with pytest.raises(ValueError):
        assert_phase7i_no_provider_or_business_mutation(lock)
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_BLOCKED
    ).exists()


# ---------------------------------------------------------------------------
# API + 405 + auth
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7i_endpoints_reject_non_get_methods(
    admin_user, auth_client
) -> None:
    urls = [
        reverse("saas-phase7i-final-audit-lock-readiness"),
        reverse("saas-phase7i-final-audit-locks"),
        reverse("saas-phase7i-final-audit-lock-preview")
        + "?phase7g_attempt_id=1&phase7h_evidence_lock_id=1",
        reverse(
            "saas-phase7i-final-audit-lock-detail",
            kwargs={"pk": 1},
        ),
    ]
    client = auth_client(admin_user)
    for url in urls:
        for method in ("post", "patch", "put", "delete"):
            assert (
                getattr(client, method)(url, {}).status_code == 405
            ), f"{method} {url}"


@pytest.mark.django_db
def test_phase7i_endpoints_require_admin_auth(
    client, viewer_user, admin_user, auth_client
) -> None:
    url = reverse("saas-phase7i-final-audit-lock-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403
    assert auth_client(admin_user).get(url).status_code == 200


@pytest.mark.django_db
def test_phase7i_no_post_endpoint_dispatches_state() -> None:
    """Phase 7I is CLI-only; no POST endpoint may dispatch state."""
    from django.urls import get_resolver

    resolver = get_resolver()
    suspicious = []
    for pattern in resolver.url_patterns:
        if "saas/" not in str(pattern.pattern):
            continue
        for sub in getattr(pattern, "url_patterns", []):
            p = str(sub.pattern)
            if "phase7/final-audit-lock" in p and any(
                token in p
                for token in (
                    "approve",
                    "reject",
                    "archive",
                    "execute",
                    "lock-action",
                )
            ):
                suspicious.append(p)
    assert not suspicious, suspicious


@pytest.mark.django_db
def test_phase7i_preview_endpoint_requires_positive_ids(
    admin_user, auth_client
) -> None:
    url = reverse("saas-phase7i-final-audit-lock-preview")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Cross-cutting safety invariant
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7i_full_prepare_no_business_mutation_anywhere() -> None:
    """Across the full prepare path the eleven business / send /
    courier row counts MUST stay constant."""
    chain = _make_full_source_chain(
        source_event_id="evt_phase7i_no_mutation"
    )
    before = _row_counts()
    prepare_phase7i_final_audit_lock(
        phase7g_attempt_id=chain["phase7g"].pk,
        phase7h_evidence_lock_id=chain["phase7h"].pk,
        phase7e_live_attempt_id=chain["phase7e_live"].pk,
    )
    after = _row_counts()
    assert before == after