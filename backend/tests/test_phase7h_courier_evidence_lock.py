"""Phase 7H - Courier Execution Evidence Lock tests.

Asserts every Phase 7H safety requirement. Phase 7H is lock-only:
it never calls Delhivery, never creates a ``Shipment`` / AWB row,
never sends or queues WhatsApp, never calls Meta Cloud / Razorpay
/ Vapi, never sends a customer notification, never mutates real
``Order`` / ``Payment`` / ``Customer`` / ``Lead`` /
``DiscountOfferLog`` rows, never edits any ``.env*`` file.
"""
from __future__ import annotations

import importlib
import io
import json
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
)
from apps.payments.razorpay_courier_execution_evidence_lock import (
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_LOCKED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    approve_phase7h_evidence_lock,
    archive_phase7h_evidence_lock,
    assert_phase7h_no_provider_or_business_mutation,
    inspect_phase7h_evidence_lock_readiness,
    prepare_phase7h_evidence_lock,
    preview_phase7h_evidence_lock,
    reject_phase7h_evidence_lock,
)
from apps.shipments.models import RescueAttempt, Shipment, WorkflowStep
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from tests.test_phase7g_courier_execution import (
    _make_approved_phase7g_attempt,
    _phase7g_execute_settings,
    _signoff_text,
)


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


def _make_executed_then_rolled_back_phase7g_attempt(
    *, source_event_id: str
) -> RazorpayCourierExecutionAttempt:
    """Walk a Phase 7G attempt through execute + rollback so it lands
    in `rolled_back_recorded` with provider_call_attempted=True and
    awb_created=True.
    """
    from apps.payments.razorpay_courier_execution import (
        execute_phase7g_courier_one_shot,
        rollback_phase7g_courier_execution_attempt,
    )

    attempt = _make_approved_phase7g_attempt(
        source_event_id=source_event_id
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper",
        return_value={
            "awb": "DLH7H000001",
            "status": "Pickup Scheduled",
            "tracking_url": "https://delhivery.example/track/DLH7H000001",
        },
    ):
        execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    rollback_phase7g_courier_execution_attempt(
        attempt.pk, reason="Phase 7H test fixture"
    )
    attempt.refresh_from_db()
    return attempt


# ---------------------------------------------------------------------------
# Audit-kind + static-file invariants
# ---------------------------------------------------------------------------


def test_phase7h_audit_kinds_within_length_budget() -> None:
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
        assert kind.startswith("phase7h.courier_evidence.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_phase7h_service_module_does_not_import_delhivery_or_meta() -> None:
    """Check actual import lines, not docstring mentions."""
    src_path = importlib.import_module(
        "apps.payments.razorpay_courier_execution_evidence_lock"
    ).__file__
    with open(src_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    forbidden = [
        "from apps.shipments.integrations.delhivery_client import create_awb",
        "from apps.shipments.integrations.delhivery_client import _create_via_sdk",
        "from apps.whatsapp.services import send_freeform_text_message",
        "from apps.whatsapp.services import queue_template_message",
        "from apps.whatsapp.integrations.whatsapp.meta_cloud_client",
        "from apps.payments.integrations.razorpay_client",
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
                    f"Phase 7H service imports forbidden module: "
                    f"{needle}"
                )


# ---------------------------------------------------------------------------
# Readiness + preview + management command
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7h_readiness_command_returns_lock_only_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_phase7h_courier_execution_evidence_lock",
        "--json", "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "7H"
    assert body["status"] == "courier_evidence_lock_only"
    for key in (
        "phase7HCallsDelhivery",
        "phase7HCreatesShipmentRow",
        "phase7HCreatesAwb",
        "phase7HSendsWhatsApp",
        "phase7HQueuesWhatsApp",
        "phase7HCallsMetaCloud",
        "phase7HCallsRazorpay",
        "phase7HSendsCustomerNotification",
        "phase7HMutatesBusinessRow",
        "phase7HLiveCustomerCourierApproved",
    ):
        assert body[key] is False, key


@pytest.mark.django_db
def test_phase7h_preview_eligible_attempt_emits_no_rows() -> None:
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_preview"
    )
    before = _row_counts()
    out = preview_phase7h_evidence_lock(attempt.pk)
    after = _row_counts()
    assert out["found"] is True
    assert out["eligible"] is True
    assert before == after
    assert (
        RazorpayCourierExecutionEvidenceLock.objects.count() == 0
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_PREVIEWED
    ).exists()


# ---------------------------------------------------------------------------
# Prepare eligibility
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7h_prepare_creates_lock_for_eligible_attempt() -> None:
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_prepare_ok"
    )
    before = _row_counts()
    out = prepare_phase7h_evidence_lock(attempt.pk)
    after = _row_counts()

    assert out["created"] is True
    assert out["reused"] is False
    lock_id = out["lock"]["id"]
    row = RazorpayCourierExecutionEvidenceLock.objects.get(pk=lock_id)
    assert (
        row.status
        == RazorpayCourierExecutionEvidenceLock.Status.PENDING_MANUAL_REVIEW
    )
    # Snapshot booleans match the source attempt.
    assert row.shipment_created_snapshot is False
    assert row.business_mutation_was_made_snapshot is False
    assert row.customer_notification_sent_snapshot is False
    assert (
        row.recorded_signoff_window_valid_snapshot is True
    )
    # No business mutation.
    assert before == after
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_PREPARED
    ).exists()


@pytest.mark.django_db
def test_phase7h_prepare_idempotent_on_same_attempt() -> None:
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_prepare_idem"
    )
    a = prepare_phase7h_evidence_lock(attempt.pk)
    b = prepare_phase7h_evidence_lock(attempt.pk)
    assert a["created"] is True
    assert b["created"] is False
    assert b["reused"] is True
    assert (
        RazorpayCourierExecutionEvidenceLock.objects.count() == 1
    )


@pytest.mark.django_db
def test_phase7h_prepare_rejects_attempt_without_provider_call() -> (
    None
):
    """Phase 7H requires provider_call_attempted=True. Phase 7G
    prepare-only attempts (still pending_director_signoff) are
    refused."""
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7h_no_provider"
    )
    out = prepare_phase7h_evidence_lock(attempt.pk)
    assert out["created"] is False
    assert out["lock"] is None
    assert any(
        "phase7h_source_attempt_status_must_be_rolled_back_recorded" in b
        for b in out["blockers"]
    ) or any(
        "phase7h_source_attempt_provider_call_attempted_must_be_true"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7h_prepare_rejects_attempt_with_shipment_created() -> (
    None
):
    """If somehow shipment_created=True on the source, lock prepare
    refuses."""
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_shipment_true"
    )
    attempt.shipment_created = True
    attempt.save(update_fields=["shipment_created"])
    out = prepare_phase7h_evidence_lock(attempt.pk)
    assert out["created"] is False
    assert any(
        "phase7h_source_attempt_shipment_created_must_be_false" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7h_prepare_rejects_attempt_with_business_mutation() -> (
    None
):
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_business_mutation"
    )
    attempt.business_mutation_was_made = True
    attempt.save(update_fields=["business_mutation_was_made"])
    out = prepare_phase7h_evidence_lock(attempt.pk)
    assert out["created"] is False
    assert any(
        "phase7h_source_attempt_business_mutation_was_made_must_be_false"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7h_prepare_rejects_attempt_with_missing_rollback() -> (
    None
):
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_missing_rollback"
    )
    attempt.rollback_status = (
        RazorpayCourierExecutionAttempt.RollbackStatus.PENDING
    )
    attempt.save(update_fields=["rollback_status"])
    out = prepare_phase7h_evidence_lock(attempt.pk)
    assert out["created"] is False
    assert any(
        "phase7h_source_attempt_rollback_status_must_be_recorded_only_no_provider_cancel"
        in b
        for b in out["blockers"]
    )


# ---------------------------------------------------------------------------
# Approve / reject / archive
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7h_approve_locks_evidence_with_reason() -> None:
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_approve_ok"
    )
    prepared = prepare_phase7h_evidence_lock(attempt.pk)
    lock_id = prepared["lock"]["id"]
    AuditEvent.objects.filter(kind=AUDIT_KIND_LOCKED).delete()
    out = approve_phase7h_evidence_lock(
        lock_id, reviewed_by=None,
        reason="Director Phase 7H lock confirmation.",
    )
    assert out["ok"] is True
    row = RazorpayCourierExecutionEvidenceLock.objects.get(pk=lock_id)
    assert (
        row.status
        == RazorpayCourierExecutionEvidenceLock.Status.LOCKED
    )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_LOCKED).exists()


@pytest.mark.django_db
def test_phase7h_approve_requires_non_empty_reason() -> None:
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_no_reason"
    )
    prepared = prepare_phase7h_evidence_lock(attempt.pk)
    out = approve_phase7h_evidence_lock(
        prepared["lock"]["id"], reason=""
    )
    assert out["ok"] is False


@pytest.mark.django_db
def test_phase7h_reject_records_warning_audit() -> None:
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_reject"
    )
    prepared = prepare_phase7h_evidence_lock(attempt.pk)
    AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).delete()
    out = reject_phase7h_evidence_lock(
        prepared["lock"]["id"], reason="Director paused lock review."
    )
    assert out["ok"] is True
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).exists()


@pytest.mark.django_db
def test_phase7h_archive_flips_status() -> None:
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_archive"
    )
    prepared = prepare_phase7h_evidence_lock(attempt.pk)
    out = archive_phase7h_evidence_lock(
        prepared["lock"]["id"], reason="Director archive."
    )
    assert out["ok"] is True
    row = RazorpayCourierExecutionEvidenceLock.objects.get(
        pk=prepared["lock"]["id"]
    )
    assert (
        row.status
        == RazorpayCourierExecutionEvidenceLock.Status.ARCHIVED
    )


# ---------------------------------------------------------------------------
# Defensive guard + API
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7h_guard_raises_when_snapshot_boolean_flipped() -> None:
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_guard"
    )
    prepared = prepare_phase7h_evidence_lock(attempt.pk)
    lock = RazorpayCourierExecutionEvidenceLock.objects.get(
        pk=prepared["lock"]["id"]
    )
    lock.shipment_created_snapshot = True
    lock.save(update_fields=["shipment_created_snapshot"])
    AuditEvent.objects.filter(kind=AUDIT_KIND_BLOCKED).delete()
    with pytest.raises(ValueError):
        assert_phase7h_no_provider_or_business_mutation(lock)
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_BLOCKED
    ).exists()


@pytest.mark.django_db
def test_phase7h_endpoints_reject_non_get_methods(
    admin_user, auth_client
) -> None:
    urls = [
        reverse(
            "saas-delhivery-courier-execution-evidence-lock-readiness"
        ),
        reverse(
            "saas-delhivery-courier-execution-evidence-locks"
        ),
        reverse(
            "saas-delhivery-courier-execution-evidence-lock-preview"
        ) + "?attempt_id=1",
        reverse(
            "saas-delhivery-courier-execution-evidence-lock-detail",
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
def test_phase7h_no_post_endpoint_dispatches_state() -> None:
    """Phase 7H is CLI-only; no POST endpoint may dispatch state."""
    from django.urls import get_resolver

    resolver = get_resolver()
    suspicious = []
    for pattern in resolver.url_patterns:
        if "saas/" not in str(pattern.pattern):
            continue
        for sub in getattr(pattern, "url_patterns", []):
            p = str(sub.pattern)
            if "courier-execution-evidence-lock" in p and any(
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
def test_phase7h_endpoints_require_admin_auth(
    client, viewer_user, admin_user, auth_client
) -> None:
    url = reverse(
        "saas-delhivery-courier-execution-evidence-lock-readiness"
    )
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403
    assert auth_client(admin_user).get(url).status_code == 200


@pytest.mark.django_db
def test_phase7h_inspect_readiness_counts_eligible_attempts() -> None:
    attempt = _make_executed_then_rolled_back_phase7g_attempt(
        source_event_id="evt_phase7h_count"
    )
    out = inspect_phase7h_evidence_lock_readiness()
    assert out["eligiblePhase7GAttemptCount"] == 1
    assert out["phase7HCallsDelhivery"] is False
