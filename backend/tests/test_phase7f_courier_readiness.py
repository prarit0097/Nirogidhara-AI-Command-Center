"""Phase 7F - Delhivery / Courier Controlled Readiness Gate tests.

Asserts every Phase 7F safety requirement. Phase 7F never calls
Delhivery, never creates a ``Shipment`` / ``WorkflowStep`` /
``RescueAttempt`` row, never creates an AWB, never books a pickup,
never generates a courier label, never sends or queues WhatsApp,
never calls Meta Cloud / Razorpay / Vapi, never sends a customer
notification, never mutates real ``Order`` / ``Payment`` /
``Customer`` / ``Lead`` / ``DiscountOfferLog`` rows, never edits
any ``.env*`` file.
"""
from __future__ import annotations

import importlib
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
    RazorpayCourierReadinessDryRunRecord,
    RazorpayCourierReadinessGate,
    RazorpayWhatsAppInternalNotificationGate,
)
from apps.payments.razorpay_courier_readiness import (
    AUDIT_KIND_APPROVED_FUTURE_COURIER,
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_DRY_RUN_FAILED,
    AUDIT_KIND_DRY_RUN_PASSED,
    AUDIT_KIND_INVARIANT_VIOLATION,
    AUDIT_KIND_KILL_SWITCH_BLOCKED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_RB_DRY_RUN_FAILED,
    AUDIT_KIND_RB_DRY_RUN_PASSED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    PHASE_7F_FORBIDDEN_ACTIONS,
    PHASE_7F_FORBIDDEN_PAYLOAD_KEYS,
    approve_phase7f_gate,
    assert_phase7f_no_courier_or_business_mutation,
    build_phase7f_courier_readiness_contract,
    dry_run_phase7f_gate,
    inspect_phase7f_readiness,
    prepare_phase7f_gate,
    preview_phase7f_gate,
    reject_phase7f_gate,
    rollback_dry_run_phase7f_gate,
    serialize_phase7f_gate,
    summarize_phase7f_gates,
)
from apps.shipments.models import RescueAttempt, Shipment, WorkflowStep
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from tests.test_phase7e_whatsapp_internal_notification import (
    _make_executed_and_rolled_back_phase7d_attempt,
    _phase7e_test_settings,
    _structured_signoff,
    _walk_to_ready_to_approve_gate,
)
from apps.payments.razorpay_whatsapp_internal_notification import (
    approve_phase7e_gate,
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


def _phase7f_test_settings(**overrides):
    base = {
        "PHASE7F_COURIER_READINESS_GATE_ENABLED": True,
        "PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED": True,
        "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED": False,
        "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION": False,
        "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER": False,
        "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED": False,
        "WHATSAPP_AI_AUTO_REPLY_ENABLED": False,
        "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED": False,
        "WHATSAPP_CALL_HANDOFF_ENABLED": False,
        "WHATSAPP_RESCUE_DISCOUNT_ENABLED": False,
        "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED": False,
        "WHATSAPP_REORDER_DAY20_ENABLED": False,
        "WHATSAPP_PROVIDER": "mock",
        "WHATSAPP_LIVE_META_LIMITED_TEST_MODE": True,
        "DELHIVERY_MODE": "mock",
    }
    base.update(overrides)
    return override_settings(**base)


def _make_approved_phase7e_gate(
    *, source_event_id: str
) -> RazorpayWhatsAppInternalNotificationGate:
    """Walk a Phase 7B gate -> Phase 7D execute+rollback -> Phase 7E
    prepare/dry-run/rollback-dry-run/approve. Returns a Phase 7E gate
    in `approved_for_future_phase7f_or_7e_send_review`.
    """
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id=source_event_id, legacy_signoff=False
    )
    reason = (
        "Director sign-off Phase 7E review."
    )
    with _phase7e_test_settings():
        approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason=reason,
            director_signoff=_structured_signoff(attempt.pk),
            acknowledge_source_phase7d_window_violation=False,
        )
    return RazorpayWhatsAppInternalNotificationGate.objects.get(
        pk=gate.pk
    )


# ---------------------------------------------------------------------------
# Contract + audit-kind length
# ---------------------------------------------------------------------------


def test_contract_locks_courier_and_business_mutation_off() -> None:
    contract = build_phase7f_courier_readiness_contract()
    assert contract["phase"] == "7F"
    assert contract["status"] == "courier_readiness_only"
    for key in (
        "phase7FCallsDelhivery",
        "phase7FCreatesShipmentRow",
        "phase7FCreatesAwb",
        "phase7FBooksPickup",
        "phase7FGeneratesLabel",
        "phase7FSendsWhatsApp",
        "phase7FQueuesWhatsApp",
        "phase7FCallsMetaCloud",
        "phase7FCallsRazorpay",
        "phase7FSendsCustomerNotification",
        "phase7FMutatesBusinessRow",
        "phase7FTouchesRealCustomerPhoneNumber",
        "phase7FTouchesRealCustomerAddress",
        "phase7FWritesEnvFile",
        "phase7FImportsDotenv",
        "phase7FApprovalImpliesLiveCourier",
    ):
        assert contract[key] is False, key
    assert (
        contract["phase7FRequiresFutureExecuteWindowGuardForCourier"]
        is True
    )


def test_phase7f_audit_kinds_within_length_budget() -> None:
    audit_kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_DRY_RUN_PASSED,
        AUDIT_KIND_DRY_RUN_FAILED,
        AUDIT_KIND_RB_DRY_RUN_PASSED,
        AUDIT_KIND_RB_DRY_RUN_FAILED,
        AUDIT_KIND_APPROVED_FUTURE_COURIER,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
        AUDIT_KIND_KILL_SWITCH_BLOCKED,
        AUDIT_KIND_INVARIANT_VIOLATION,
    ]
    assert len(audit_kinds) == 13
    for kind in audit_kinds:
        assert kind.startswith("razorpay.courier_readiness.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_forbidden_actions_count_is_31() -> None:
    assert len(PHASE_7F_FORBIDDEN_ACTIONS) == 31


def test_forbidden_actions_includes_critical_paths() -> None:
    expected = {
        "call_delhivery_api",
        "call_delhivery_create_awb",
        "call_delhivery_book_pickup",
        "call_delhivery_generate_label",
        "create_shipment_row",
        "create_workflow_step_row",
        "create_rescue_attempt_row",
        "create_awb",
        "book_courier_pickup",
        "generate_courier_label",
        "send_customer_notification",
        "send_whatsapp_template",
        "send_whatsapp_freeform",
        "queue_whatsapp_outbound",
        "call_meta_cloud_api",
        "call_razorpay_api",
        "create_payment_link",
        "capture_razorpay_payment",
        "refund_razorpay_payment",
        "mutate_real_order_status",
        "mutate_real_payment_status",
        "mutate_real_shipment_status",
        "mutate_real_customer",
        "mutate_real_lead",
        "execute_via_frontend",
        "execute_via_api_endpoint",
        "approve_via_api_endpoint",
        "edit_dotenv_any",
    }
    assert expected.issubset(set(PHASE_7F_FORBIDDEN_ACTIONS))


def test_forbidden_payload_keys_count_is_21() -> None:
    assert len(PHASE_7F_FORBIDDEN_PAYLOAD_KEYS) == 21


# ---------------------------------------------------------------------------
# Service module static-file scans
# ---------------------------------------------------------------------------


def _service_source() -> str:
    src_path = importlib.import_module(
        "apps.payments.razorpay_courier_readiness"
    ).__file__
    with open(src_path, "r", encoding="utf-8") as fh:
        return fh.read()


def test_service_module_does_not_import_delhivery_create_awb() -> None:
    text = _service_source()
    assert (
        "from apps.shipments.integrations.delhivery_client import create_awb"
        not in text
    )
    assert (
        "from apps.shipments.integrations.delhivery_client import _create_via_sdk"
        not in text
    )


def test_service_module_does_not_import_shipments_service_create() -> None:
    text = _service_source()
    forbidden = [
        "from apps.shipments.services import create_shipment",
        "from apps.shipments.services import create_rescue_attempt",
        "from apps.shipments.services import update_rescue_outcome",
    ]
    for needle in forbidden:
        assert needle not in text


def test_service_module_does_not_import_whatsapp_send_helpers() -> None:
    text = _service_source()
    forbidden = [
        "from apps.whatsapp.services import send_freeform_text_message",
        "from apps.whatsapp.services import send_queued_message",
        "from apps.whatsapp.services import queue_template_message",
        "from apps.whatsapp.integrations.whatsapp.meta_cloud_client",
        "import apps.whatsapp.integrations.whatsapp.meta_cloud_client",
    ]
    for needle in forbidden:
        assert needle not in text


def test_service_module_does_not_import_razorpay_client() -> None:
    text = _service_source()
    assert (
        "from apps.payments.integrations.razorpay_client" not in text
    )
    assert (
        "import apps.payments.integrations.razorpay_client" not in text
    )


def test_service_module_does_not_import_dotenv() -> None:
    text = _service_source()
    assert "from dotenv" not in text
    assert "import dotenv" not in text


def test_service_module_does_not_reference_dotenv_files() -> None:
    text = _service_source()
    assert ".env.production" not in text
    assert ".env.live" not in text


# ---------------------------------------------------------------------------
# Readiness command + endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_command_returns_phase7f_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_delhivery_courier_readiness",
        "--json",
        "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "7F"
    assert body["status"] == "courier_readiness_only"
    assert body["latestCompletedPhase"] == "7E"
    assert body["nextPhase"] == "7G_or_courier_live_not_approved"
    for key in (
        "phase7FCallsDelhivery",
        "phase7FCreatesShipmentRow",
        "phase7FCreatesAwb",
        "phase7FBooksPickup",
        "phase7FGeneratesLabel",
        "phase7FSendsCustomerNotification",
        "phase7FMutatesBusinessRow",
        "phase7FCallsMetaCloud",
        "phase7FCallsRazorpay",
        "phase7FSendsWhatsApp",
        "phase7FQueuesWhatsApp",
    ):
        assert body[key] is False
    assert body["phase7DHotfix1Present"] is True


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase7f_shape(
    admin_user, auth_client
) -> None:
    url = reverse("saas-delhivery-courier-readiness")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "7F"
    assert body["status"] == "courier_readiness_only"


@pytest.mark.django_db
def test_readiness_endpoint_requires_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse("saas-delhivery-courier-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


# ---------------------------------------------------------------------------
# POST/PATCH/PUT/DELETE -> 405
# ---------------------------------------------------------------------------


_PHASE_7F_GET_ENDPOINTS = (
    ("saas-delhivery-courier-readiness", None),
    ("saas-delhivery-courier-readiness-gates", None),
    (
        "saas-delhivery-courier-readiness-preview",
        "?phase7e_gate_id=1",
    ),
)


@pytest.mark.django_db
@pytest.mark.parametrize("name,query", _PHASE_7F_GET_ENDPOINTS)
def test_phase7f_endpoints_reject_non_get_methods(
    name, query, admin_user, auth_client
) -> None:
    url = reverse(name)
    if query:
        url = url + query
    client = auth_client(admin_user)
    for method in ("post", "patch", "put", "delete"):
        res = getattr(client, method)(url, {})
        assert res.status_code == 405, (
            f"{method} {name} -> {res.status_code}"
        )


@pytest.mark.django_db
def test_phase7f_detail_and_dry_runs_reject_non_get(
    admin_user, auth_client
) -> None:
    detail = reverse(
        "saas-delhivery-courier-readiness-gate-detail",
        kwargs={"pk": 1},
    )
    dry_runs = reverse(
        "saas-delhivery-courier-readiness-dry-runs",
        kwargs={"gate_id": 1},
    )
    client = auth_client(admin_user)
    for url in (detail, dry_runs):
        for method in ("post", "patch", "put", "delete"):
            assert getattr(client, method)(url, {}).status_code == 405


@pytest.mark.django_db
def test_no_phase7f_post_execute_or_approve_endpoint_exists() -> None:
    """Phase 7F is CLI-only; no POST endpoint may dispatch state."""
    from django.urls import get_resolver

    resolver = get_resolver()
    suspicious = []
    for pattern in resolver.url_patterns:
        if "saas/" not in str(pattern.pattern):
            continue
        for sub in getattr(pattern, "url_patterns", []):
            p = str(sub.pattern)
            if (
                "delhivery/" in p
                or "courier-readiness" in p
            ) and any(
                token in p
                for token in (
                    "approve",
                    "reject",
                    "execute",
                    "send",
                    "create-shipment",
                    "create-awb",
                    "book-pickup",
                    "generate-label",
                )
            ):
                suspicious.append(p)
    assert not suspicious, suspicious


# ---------------------------------------------------------------------------
# Preview never creates rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_never_creates_rows() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_preview"
    )
    before = _row_counts()
    out = preview_phase7f_gate(phase7e_gate.pk)
    after = _row_counts()
    assert out["found"] is True
    assert RazorpayCourierReadinessGate.objects.count() == 0
    assert before == after


@pytest.mark.django_db
def test_preview_endpoint_requires_phase7e_gate_id(
    admin_user, auth_client
) -> None:
    url = reverse("saas-delhivery-courier-readiness-preview")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Prepare gating
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_blocked_when_gate_flag_off() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_no_flag"
    )
    out = prepare_phase7f_gate(phase7e_gate.pk)
    assert out["created"] is False
    assert out["reused"] is False
    assert out["gate"] is None
    assert any(
        "PHASE7F" in b or "phase7f" in b for b in out["blockers"]
    )


@pytest.mark.django_db
def test_prepare_blocked_when_phase7e_gate_not_approved() -> None:
    """Phase 7E gate that is only `pending_manual_review` cannot
    source a Phase 7F gate.
    """
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7f_no_phase7e_appr"
    )
    from apps.payments.razorpay_whatsapp_internal_notification import (
        prepare_phase7e_gate,
    )

    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
    phase7e_gate_id = prepared["gate"]["id"]
    with _phase7f_test_settings():
        out = prepare_phase7f_gate(phase7e_gate_id)
    assert out["created"] is False
    assert any("phase_7e_gate_status" in b for b in out["blockers"])


@pytest.mark.django_db
def test_prepare_creates_gate_with_locked_safety_booleans() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_prepare"
    )
    with _phase7f_test_settings():
        out = prepare_phase7f_gate(phase7e_gate.pk)
    assert out["created"] is True
    gate_id = out["gate"]["id"]
    row = RazorpayCourierReadinessGate.objects.get(pk=gate_id)
    assert (
        row.status
        == RazorpayCourierReadinessGate.Status.PENDING_MANUAL_REVIEW
    )
    invariants = row.safety_invariants_snapshot
    for key in (
        "delhiveryCallAllowedInPhase7F",
        "courierBookingAllowedInPhase7F",
        "shipmentCreationAllowedInPhase7F",
        "awbCreationAllowedInPhase7F",
        "pickupBookingAllowedInPhase7F",
        "labelGenerationAllowedInPhase7F",
        "customerNotificationAllowedInPhase7F",
        "whatsappSendAllowedInPhase7F",
        "whatsappQueueAllowedInPhase7F",
        "metaCloudCallAllowedInPhase7F",
        "razorpayCallAllowedInPhase7F",
        "businessMutationAllowedInPhase7F",
        "realCustomerAllowedInPhase7F",
        "providerCallAttempted",
        "delhiveryCallAttempted",
        "shipmentCreated",
        "awbCreated",
        "pickupBooked",
        "labelGenerated",
        "customerNotificationSent",
        "realOrderMutationWasMade",
        "realPaymentMutationWasMade",
        "realShipmentMutationWasMade",
        "phase7FApprovalImpliesLiveCourier",
    ):
        assert invariants[key] is False, key
    assert row.idempotency_key == (
        f"phase7f::courier_readiness::phase7e_gate::{phase7e_gate.pk}"
    )
    assert row.delhivery_mode_at_prepare == "mock"
    assert row.phase7d_hotfix_1_present is True


@pytest.mark.django_db
def test_prepare_idempotent_on_same_phase7e_gate() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_idem"
    )
    with _phase7f_test_settings():
        a = prepare_phase7f_gate(phase7e_gate.pk)
        b = prepare_phase7f_gate(phase7e_gate.pk)
    assert a["created"] is True
    assert b["created"] is False
    assert b["reused"] is True
    assert RazorpayCourierReadinessGate.objects.count() == 1


@pytest.mark.django_db
def test_prepare_blocked_when_kill_switch_off() -> None:
    from apps.saas.models import RuntimeKillSwitch

    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_kill_off"
    )
    kill, _ = RuntimeKillSwitch.objects.get_or_create(
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        provider_type="",
        operation_type="",
    )
    kill.enabled = False
    kill.save()
    with _phase7f_test_settings():
        out = prepare_phase7f_gate(phase7e_gate.pk)
    assert out["created"] is False
    assert any(
        "kill" in b.lower() or "switch" in b.lower()
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_prepare_blocked_when_delhivery_mode_live() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_live"
    )
    with _phase7f_test_settings(DELHIVERY_MODE="live"):
        out = prepare_phase7f_gate(phase7e_gate.pk)
    assert out["created"] is False
    assert any(
        "DELHIVERY_MODE_must_be_mock_or_test" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "flag_name",
    [
        "WHATSAPP_AI_AUTO_REPLY_ENABLED",
        "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED",
        "WHATSAPP_CALL_HANDOFF_ENABLED",
        "WHATSAPP_RESCUE_DISCOUNT_ENABLED",
        "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED",
        "WHATSAPP_REORDER_DAY20_ENABLED",
    ],
)
def test_prepare_blocked_when_whatsapp_automation_flag_true(
    flag_name,
) -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id=f"evt_phase7f_flag_{flag_name[:8]}"
    )
    with _phase7f_test_settings(**{flag_name: True}):
        out = prepare_phase7f_gate(phase7e_gate.pk)
    assert out["created"] is False
    assert any(flag_name in b for b in out["blockers"])


@pytest.mark.django_db
@pytest.mark.parametrize(
    "flag_name",
    [
        "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED",
        "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION",
        "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER",
        "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED",
    ],
)
def test_prepare_blocked_when_phase7d_or_6k_execute_flag_true(
    flag_name,
) -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id=f"evt_phase7f_pf_{flag_name[:8]}"
    )
    with _phase7f_test_settings(**{flag_name: True}):
        out = prepare_phase7f_gate(phase7e_gate.pk)
    assert out["created"] is False
    assert any(flag_name in b for b in out["blockers"])


# ---------------------------------------------------------------------------
# Dry-run / rollback-dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dry_run_pass_writes_record_and_no_business_row_change() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_dryrun"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        before = _row_counts()
        out = dry_run_phase7f_gate(gate_id)
        after = _row_counts()
    assert out["ok"] is True
    record_count = (
        RazorpayCourierReadinessDryRunRecord.objects.filter(
            gate_id=gate_id, kind="dry_run"
        ).count()
    )
    assert record_count == 1
    assert before == after


@pytest.mark.django_db
def test_dry_run_never_creates_shipment_or_workflow_or_rescue() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_no_courier_rows"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        sh_before = Shipment.objects.count()
        ws_before = WorkflowStep.objects.count()
        ra_before = RescueAttempt.objects.count()
        dry_run_phase7f_gate(gate_id)
    assert Shipment.objects.count() == sh_before
    assert WorkflowStep.objects.count() == ws_before
    assert RescueAttempt.objects.count() == ra_before


@pytest.mark.django_db
def test_dry_run_never_creates_whatsapp_row() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_no_wa"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        wa_before = WhatsAppMessage.objects.count()
        wa_lc_before = WhatsAppLifecycleEvent.objects.count()
        wa_handoff_before = WhatsAppHandoffToCall.objects.count()
        dry_run_phase7f_gate(gate_id)
    assert WhatsAppMessage.objects.count() == wa_before
    assert WhatsAppLifecycleEvent.objects.count() == wa_lc_before
    assert WhatsAppHandoffToCall.objects.count() == wa_handoff_before


@pytest.mark.django_db
def test_dry_run_records_stack_safely() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_stack"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7f_gate(gate_id)
        dry_run_phase7f_gate(gate_id)
        dry_run_phase7f_gate(gate_id)
    assert (
        RazorpayCourierReadinessDryRunRecord.objects.filter(
            gate_id=gate_id, kind="dry_run"
        ).count()
        == 3
    )


@pytest.mark.django_db
def test_rollback_dry_run_requires_reason() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_rb_no_reason"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7f_gate(gate_id)
        out = rollback_dry_run_phase7f_gate(gate_id, reason="")
    assert out["ok"] is False
    assert any("reason" in b for b in out["blockers"])


@pytest.mark.django_db
def test_rollback_dry_run_passes_after_dry_run() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_rb_pass"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7f_gate(gate_id)
        out = rollback_dry_run_phase7f_gate(
            gate_id, reason="Rehearsal complete"
        )
    assert out["ok"] is True
    record_count = (
        RazorpayCourierReadinessDryRunRecord.objects.filter(
            gate_id=gate_id, kind="rollback_dry_run"
        ).count()
    )
    assert record_count == 1


# ---------------------------------------------------------------------------
# Approve gating (NO --director-signoff argument)
# ---------------------------------------------------------------------------


def _walk_to_ready_to_approve_phase7f_gate(
    *, source_event_id: str
) -> RazorpayCourierReadinessGate:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id=source_event_id
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7f_gate(gate_id)
        rollback_dry_run_phase7f_gate(
            gate_id, reason="Approve fixture rehearsal"
        )
    return RazorpayCourierReadinessGate.objects.get(pk=gate_id)


@pytest.mark.django_db
def test_approve_refuses_without_reason() -> None:
    gate = _walk_to_ready_to_approve_phase7f_gate(
        source_event_id="evt_phase7f_appr_no_reason"
    )
    with _phase7f_test_settings():
        out = approve_phase7f_gate(
            gate.pk, reviewed_by=None, reason=""
        )
    assert out["ok"] is False
    assert any("reason" in b for b in out["blockers"])


@pytest.mark.django_db
def test_approve_refuses_when_dry_run_not_passed() -> None:
    """Skip dry-run; approve must refuse."""
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_no_dry"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        out = approve_phase7f_gate(
            gate_id,
            reviewed_by=None,
            reason="Director sign-off Phase 7F approve",
        )
    assert out["ok"] is False
    assert any(
        "phase7f_dry_run_passed_must_be_true" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_approve_refuses_when_rollback_dry_run_not_passed() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_no_rb"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7f_gate(gate_id)
        out = approve_phase7f_gate(
            gate_id,
            reviewed_by=None,
            reason="Director sign-off Phase 7F approve",
        )
    assert out["ok"] is False
    assert any(
        "phase7f_rollback_dry_run_passed_must_be_true" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_approve_succeeds_with_reason_only() -> None:
    """Phase 7F approve does NOT take --director-signoff. A
    non-empty reason is the only argument."""
    gate = _walk_to_ready_to_approve_phase7f_gate(
        source_event_id="evt_phase7f_appr_ok"
    )
    with _phase7f_test_settings():
        out = approve_phase7f_gate(
            gate.pk,
            reviewed_by=None,
            reason="Director sign-off Phase 7F approve",
        )
    assert out["ok"] is True, out.get("blockers")
    row = RazorpayCourierReadinessGate.objects.get(pk=gate.pk)
    assert (
        row.status
        == RazorpayCourierReadinessGate.Status.APPROVED_FOR_FUTURE_PHASE7G_OR_COURIER_EXECUTION_REVIEW
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_APPROVED_FUTURE_COURIER
    ).exists()


@pytest.mark.django_db
def test_second_approve_refused() -> None:
    gate = _walk_to_ready_to_approve_phase7f_gate(
        source_event_id="evt_phase7f_second_appr"
    )
    with _phase7f_test_settings():
        first = approve_phase7f_gate(
            gate.pk,
            reviewed_by=None,
            reason="Director sign-off Phase 7F approve",
        )
        second = approve_phase7f_gate(
            gate.pk,
            reviewed_by=None,
            reason="Director sign-off Phase 7F approve",
        )
    assert first["ok"] is True
    assert second["ok"] is False


@pytest.mark.django_db
def test_approve_does_not_call_delhivery_or_shipments() -> None:
    gate = _walk_to_ready_to_approve_phase7f_gate(
        source_event_id="evt_phase7f_no_delhivery"
    )
    with mock.patch(
        "apps.shipments.integrations.delhivery_client.create_awb"
    ) as awb_mock, mock.patch(
        "apps.shipments.services.create_shipment"
    ) as ship_mock, mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as queue_mock, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as send_mock:
        with _phase7f_test_settings():
            out = approve_phase7f_gate(
                gate.pk,
                reviewed_by=None,
                reason="Director sign-off Phase 7F approve",
            )
    assert out["ok"] is True
    awb_mock.assert_not_called()
    ship_mock.assert_not_called()
    queue_mock.assert_not_called()
    send_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reject_requires_reason() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_rej_no_reason"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        out = reject_phase7f_gate(gate_id, reason="")
    assert out["ok"] is False
    assert any("reason" in b for b in out["blockers"])


@pytest.mark.django_db
def test_reject_changes_status_to_rejected() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_rej_ok"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        out = reject_phase7f_gate(
            gate_id, reason="Director paused future-courier review"
        )
    assert out["ok"] is True
    row = RazorpayCourierReadinessGate.objects.get(pk=gate_id)
    assert row.status == RazorpayCourierReadinessGate.Status.REJECTED
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_REJECTED
    ).exists()


@pytest.mark.django_db
def test_reject_refuses_when_status_already_approved() -> None:
    gate = _walk_to_ready_to_approve_phase7f_gate(
        source_event_id="evt_phase7f_rej_after_appr"
    )
    with _phase7f_test_settings():
        approve_phase7f_gate(
            gate.pk,
            reviewed_by=None,
            reason="Director sign-off Phase 7F approve",
        )
        out = reject_phase7f_gate(
            gate.pk, reason="Director changed mind"
        )
    assert out["ok"] is False
    assert any("refused_for_status" in b for b in out["blockers"])


# ---------------------------------------------------------------------------
# Defensive guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "key",
    [
        "delhiveryCallAllowedInPhase7F",
        "courierBookingAllowedInPhase7F",
        "shipmentCreationAllowedInPhase7F",
        "awbCreationAllowedInPhase7F",
        "pickupBookingAllowedInPhase7F",
        "labelGenerationAllowedInPhase7F",
        "customerNotificationAllowedInPhase7F",
        "whatsappSendAllowedInPhase7F",
        "whatsappQueueAllowedInPhase7F",
        "metaCloudCallAllowedInPhase7F",
        "razorpayCallAllowedInPhase7F",
        "businessMutationAllowedInPhase7F",
        "realCustomerAllowedInPhase7F",
        "providerCallAttempted",
        "delhiveryCallAttempted",
        "shipmentCreated",
        "awbCreated",
        "pickupBooked",
        "labelGenerated",
        "customerNotificationSent",
        "realOrderMutationWasMade",
        "realPaymentMutationWasMade",
        "realShipmentMutationWasMade",
        "phase7FApprovalImpliesLiveCourier",
    ],
)
def test_assert_no_courier_or_business_mutation_raises_on_flipped_boolean(
    key,
) -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id=f"evt_phase7f_guard_{key[:8]}"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
    row = RazorpayCourierReadinessGate.objects.get(pk=gate_id)
    snapshot = dict(row.safety_invariants_snapshot)
    snapshot[key] = True
    row.safety_invariants_snapshot = snapshot
    row.save(update_fields=["safety_invariants_snapshot"])
    with pytest.raises(ValueError):
        assert_phase7f_no_courier_or_business_mutation(row)
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_INVARIANT_VIOLATION
    ).exists()


@pytest.mark.django_db
def test_full_lifecycle_makes_no_courier_call_or_business_row_change() -> None:
    """Run the full Phase 7F lifecycle and confirm every business
    table count is unchanged AND no Delhivery / shipments / WhatsApp
    helper was called."""
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_full_lifecycle"
    )
    before = _row_counts()

    with mock.patch(
        "apps.shipments.integrations.delhivery_client.create_awb"
    ) as awb_mock, mock.patch(
        "apps.shipments.services.create_shipment"
    ) as ship_mock, mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as queue_mock, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as send_mock, mock.patch(
        "apps.whatsapp.services.send_queued_message"
    ) as send_q_mock, mock.patch(
        "apps.payments.razorpay_controlled_pilot_execution._create_order_via_sdk"
    ) as razorpay_mock:
        with _phase7f_test_settings():
            prepared = prepare_phase7f_gate(phase7e_gate.pk)
            gate_id = prepared["gate"]["id"]
            dry_run_phase7f_gate(gate_id)
            rollback_dry_run_phase7f_gate(
                gate_id, reason="Full-lifecycle rehearsal"
            )
            approve_phase7f_gate(
                gate_id,
                reviewed_by=None,
                reason="Director Phase 7F approve",
            )

    after = _row_counts()
    assert before == after
    awb_mock.assert_not_called()
    ship_mock.assert_not_called()
    queue_mock.assert_not_called()
    send_mock.assert_not_called()
    send_q_mock.assert_not_called()
    razorpay_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Audit payload guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_audit_payloads_lack_forbidden_keys() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_audit_keys"
    )
    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7f_gate(gate_id)
        rollback_dry_run_phase7f_gate(
            gate_id, reason="Audit-keys rehearsal"
        )
        approve_phase7f_gate(
            gate_id,
            reviewed_by=None,
            reason="Director Phase 7F approve",
        )

    rows = AuditEvent.objects.filter(
        kind__startswith="razorpay.courier_readiness."
    )
    forbidden = set(PHASE_7F_FORBIDDEN_PAYLOAD_KEYS)

    def _walk_dict_keys(node) -> set[str]:
        seen: set[str] = set()
        if isinstance(node, dict):
            seen.update(node.keys())
            for v in node.values():
                seen.update(_walk_dict_keys(v))
        elif isinstance(node, list):
            for item in node:
                seen.update(_walk_dict_keys(item))
        return seen

    assert rows.count() > 0
    for row in rows:
        keys = _walk_dict_keys(row.payload or {})
        for key in forbidden:
            assert key not in keys, (
                f"forbidden key {key} leaked into audit row {row.pk}"
            )


# ---------------------------------------------------------------------------
# Delhivery env presence (presence-only booleans, never values)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_raw_delhivery_token_in_readiness_output(
    admin_user, auth_client
) -> None:
    fake_token = "DLV_TOKEN_PHASE7F_RAW_LEAK_DETECTOR_xyz"
    with override_settings(DELHIVERY_API_TOKEN=fake_token):
        url = reverse("saas-delhivery-courier-readiness")
        body = json.dumps(auth_client(admin_user).get(url).json())
    assert fake_token not in body


@pytest.mark.django_db
def test_no_raw_delhivery_base_url_in_readiness_output(
    admin_user, auth_client
) -> None:
    fake_url = "https://delhivery-internal-secret-do-not-leak.example.com"
    with override_settings(DELHIVERY_API_BASE_URL=fake_url):
        url = reverse("saas-delhivery-courier-readiness")
        body = json.dumps(auth_client(admin_user).get(url).json())
    assert fake_url not in body


# ---------------------------------------------------------------------------
# Detail / dry-runs 404 paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_detail_endpoint_returns_404_for_unknown_id(
    admin_user, auth_client
) -> None:
    url = reverse(
        "saas-delhivery-courier-readiness-gate-detail",
        kwargs={"pk": 9999},
    )
    res = auth_client(admin_user).get(url)
    assert res.status_code == 404


@pytest.mark.django_db
def test_dry_runs_endpoint_returns_404_for_unknown_id(
    admin_user, auth_client
) -> None:
    url = reverse(
        "saas-delhivery-courier-readiness-dry-runs",
        kwargs={"gate_id": 9999},
    )
    res = auth_client(admin_user).get(url)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Summarize / readiness
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_summarize_counts_all_lifecycle_states() -> None:
    summary = summarize_phase7f_gates(limit=10)
    counts = summary["counts"]
    expected = {
        "draft",
        "pending_manual_review",
        "approved_for_future_phase7g_or_courier_execution_review",
        "rejected",
        "archived",
        "blocked",
    }
    assert expected.issubset(set(counts))


@pytest.mark.django_db
def test_inspect_readiness_reports_phase7e_approved_count() -> None:
    _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_readiness_count"
    )
    report = inspect_phase7f_readiness()
    assert report["phase7EApprovedGateCount"] >= 1
    assert report["phase7DHotfix1Present"] is True


# ---------------------------------------------------------------------------
# Gates list endpoint locks Phase 7F safety booleans
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_gates_list_endpoint_returns_phase7f_safety_locks(
    admin_user, auth_client
) -> None:
    url = reverse("saas-delhivery-courier-readiness-gates")
    body = auth_client(admin_user).get(url).json()
    assert body["phase"] == "7F"
    for key in (
        "frontendCanExecute",
        "apiEndpointCanExecute",
        "apiEndpointCanApprove",
        "phase7FCallsDelhivery",
        "phase7FCreatesShipmentRow",
        "phase7FCreatesAwb",
        "phase7FBooksPickup",
        "phase7FGeneratesLabel",
        "phase7FSendsWhatsApp",
        "phase7FQueuesWhatsApp",
        "phase7FCallsMetaCloud",
        "phase7FCallsRazorpay",
        "phase7FSendsCustomerNotification",
        "phase7FMutatesBusinessRow",
    ):
        assert body[key] is False


# ---------------------------------------------------------------------------
# Serializer never returns raw Delhivery env values
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_serializer_returns_only_presence_booleans_for_delhivery_env() -> None:
    fake_token = "DLV_TOKEN_RAW_DO_NOT_LEAK_xyz_phase7f"
    with override_settings(DELHIVERY_API_TOKEN=fake_token):
        phase7e_gate = _make_approved_phase7e_gate(
            source_event_id="evt_phase7f_serializer"
        )
        with _phase7f_test_settings(DELHIVERY_API_TOKEN=fake_token):
            prepared = prepare_phase7f_gate(phase7e_gate.pk)
            gate_id = prepared["gate"]["id"]
    row = RazorpayCourierReadinessGate.objects.get(pk=gate_id)
    serialized = serialize_phase7f_gate(row)
    body = json.dumps(serialized)
    assert fake_token not in body
    assert serialized["delhiveryEnvTokenPresent"] is True


# ---------------------------------------------------------------------------
# Phase 7D-Hotfix-1 import dependency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_blocked_when_hotfix_1_unimportable() -> None:
    """If apps.saas.utc_window.validate_within_director_window is
    unimportable, prepare must block."""
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7f_no_hotfix"
    )
    with mock.patch(
        "apps.payments.razorpay_courier_readiness._phase7d_hotfix_1_present",
        return_value=False,
    ):
        with _phase7f_test_settings():
            out = prepare_phase7f_gate(phase7e_gate.pk)
    assert out["created"] is False
    assert any(
        "phase7d_hotfix_1_must_be_shipped_before_phase7f_review" in b
        for b in out["blockers"]
    )
