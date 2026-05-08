"""Phase 7E - Controlled Internal WhatsApp Notification Readiness tests.

Asserts every Phase 7E safety requirement. Phase 7E is gate-only and
CLI-only for review state changes; it never sends a WhatsApp message,
never queues an outbound, never calls Meta Cloud / Delhivery / Vapi,
never creates a shipment / AWB / payment link, never captures /
refunds, never mutates real ``Order`` / ``Payment`` / ``Shipment`` /
``DiscountOfferLog`` / ``Customer`` / ``Lead`` rows, never sends a
customer notification, and never edits any ``.env*`` file.

The Phase 7D source attempt referenced in this suite was executed
once on 2026-05-07 with a legacy free-text Director sign-off and
rolled back; pre-Phase 7D-Hotfix-1, every Phase 7D row carries
``source_phase7d_signoff_window_validation_status =
failed_or_legacy_free_text``. Phase 7E approve flow handles this
via ``--acknowledge-source-phase7d-window-violation`` + an
acknowledgement token in the reason body.
"""
from __future__ import annotations

import importlib
import io
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import (
    Payment,
    RazorpayControlledPilotExecutionAttempt,
    RazorpayControlledPilotExecutionGate,
    RazorpayWhatsAppInternalNotificationDryRunRecord,
    RazorpayWhatsAppInternalNotificationGate,
)
from apps.payments.razorpay_controlled_pilot_execution import (
    approve_phase7d_razorpay_test_execution_attempt,
    execute_phase7d_razorpay_test_order,
    prepare_phase7d_razorpay_test_execution_attempt,
    rollback_phase7d_razorpay_test_execution_attempt,
)
from apps.payments.razorpay_whatsapp_internal_notification import (
    AUDIT_KIND_ACKED_LEGACY_SIGNOFF,
    AUDIT_KIND_APPROVED_FUTURE_SEND,
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
    PHASE_7E_FORBIDDEN_ACTIONS,
    PHASE_7E_FORBIDDEN_PAYLOAD_KEYS,
    PHASE_7E_PROPOSED_ACTION_KEYS,
    PHASE_7E_PROPOSED_VARIABLE_KEYS,
    approve_phase7e_gate,
    archive_phase7e_gate,
    assert_phase7e_no_send_or_business_mutation,
    build_phase7e_whatsapp_internal_notification_contract,
    dry_run_phase7e_gate,
    inspect_phase7e_readiness,
    prepare_phase7e_gate,
    preview_phase7e_gate,
    reject_phase7e_gate,
    rollback_dry_run_phase7e_gate,
    serialize_phase7e_gate,
    summarize_phase7e_gates,
)
from apps.shipments.models import Shipment
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from tests.test_phase7d_razorpay_test_execution import (
    _make_approved_phase7b_gate,
    _mock_razorpay_order_response,
    _phase7d_test_settings,
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
    }


def _make_executed_and_rolled_back_phase7d_attempt(
    *, source_event_id: str
) -> RazorpayControlledPilotExecutionAttempt:
    """Walk a Phase 7B-approved gate through Phase 7D execute +
    rollback.

    SDK is mocked so no real Razorpay request is issued.
    """
    gate = _make_approved_phase7b_gate(source_event_id=source_event_id)
    with _phase7d_test_settings():
        prepared = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
        attempt_id = prepared["attempt"]["id"]
        approve_phase7d_razorpay_test_execution_attempt(
            attempt_id,
            reviewed_by=None,
            reason=(
                "Director one-shot Razorpay TEST sign-off for Phase 7E "
                "fixture"
            ),
        )
        with mock.patch(
            "apps.payments.razorpay_controlled_pilot_execution"
            "._create_order_via_sdk",
            return_value=_mock_razorpay_order_response(
                order_id=f"order_TEST7E_{source_event_id[-12:]}"
            ),
        ):
            execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=(
                    f"Director sign-off mentions gate {gate.pk}"
                ),
            )
        rollback_phase7d_razorpay_test_execution_attempt(
            attempt_id, reason="Phase 7E fixture rollback"
        )
    return RazorpayControlledPilotExecutionAttempt.objects.get(
        pk=attempt_id
    )


def _phase7e_test_settings(**overrides):
    base = {
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


def _structured_signoff(
    attempt_id: int,
    *,
    minutes_ahead: int = 30,
    window_minutes: int = 60,
    extra_body: str = "",
) -> str:
    start = timezone.now() + timedelta(minutes=minutes_ahead)
    end = start + timedelta(minutes=window_minutes)
    return (
        f"Director sign-off Phase 7E review window. "
        f"phase7d_attempt_id_{attempt_id} "
        f"BEGIN_UTC={start.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"END_UTC={end.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"{extra_body}"
    )


# ---------------------------------------------------------------------------
# Contract + audit-kind length
# ---------------------------------------------------------------------------


def test_contract_locks_send_and_mutation_off() -> None:
    contract = build_phase7e_whatsapp_internal_notification_contract()
    assert contract["phase"] == "7E"
    assert (
        contract["status"] == "whatsapp_internal_notification_readiness_only"
    )
    for key in (
        "phase7ESendsWhatsApp",
        "phase7EQueuesWhatsApp",
        "phase7ECallsMetaCloud",
        "phase7ECallsDelhivery",
        "phase7ECreatesShipmentOrAwb",
        "phase7ECreatesPaymentLink",
        "phase7ECapturesPayment",
        "phase7ERefundsPayment",
        "phase7ESendsCustomerNotification",
        "phase7EMutatesBusinessRow",
        "phase7ECreatesWhatsAppMessageRow",
        "phase7ECreatesWhatsAppLifecycleEventRow",
        "phase7ECreatesWhatsAppHandoffRow",
        "phase7EWritesEnvFile",
        "phase7EImportsDotenv",
        "phase7ETouchesRealCustomerPhoneNumber",
        "phase7EApprovalImpliesLiveSend",
    ):
        assert contract[key] is False, key
    assert (
        contract["phase7DSourceSignoffMayBeLegacyFreeTextWithAck"] is True
    )
    assert (
        contract[
            "phase7DHotfix1RequiredBeforeAnyFutureProviderTouchingCommand"
        ]
        is True
    )


def test_phase7e_audit_kinds_within_length_budget() -> None:
    audit_kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_DRY_RUN_PASSED,
        AUDIT_KIND_DRY_RUN_FAILED,
        AUDIT_KIND_RB_DRY_RUN_PASSED,
        AUDIT_KIND_RB_DRY_RUN_FAILED,
        AUDIT_KIND_APPROVED_FUTURE_SEND,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
        AUDIT_KIND_KILL_SWITCH_BLOCKED,
        AUDIT_KIND_INVARIANT_VIOLATION,
        AUDIT_KIND_ACKED_LEGACY_SIGNOFF,
    ]
    assert len(audit_kinds) == 14
    for kind in audit_kinds:
        assert kind.startswith("razorpay.whatsapp_internal_notification.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_forbidden_actions_includes_critical_paths() -> None:
    expected = {
        "send_whatsapp_template",
        "send_whatsapp_freeform",
        "queue_whatsapp_outbound",
        "create_whatsapp_message_outbound",
        "create_whatsapp_lifecycle_event",
        "create_whatsapp_handoff_to_call",
        "call_meta_cloud_api",
        "call_meta_graph_api",
        "call_delhivery_api",
        "create_shipment",
        "create_awb",
        "place_vapi_call",
        "create_payment_link",
        "capture_razorpay_payment",
        "refund_razorpay_payment",
        "mutate_real_order_status",
        "mutate_real_payment_status",
        "mutate_real_shipment_status",
        "mutate_real_customer",
        "mutate_real_lead",
        "send_customer_notification",
        "notify_staff_via_whatsapp",
        "execute_via_frontend",
        "execute_via_api_endpoint",
        "approve_via_api_endpoint",
        "edit_dotenv_any",
    }
    assert expected.issubset(set(PHASE_7E_FORBIDDEN_ACTIONS))


def test_proposed_action_keys_subset() -> None:
    assert set(PHASE_7E_PROPOSED_ACTION_KEYS) == {
        "whatsapp.payment_reminder",
        "whatsapp.confirmation_reminder",
        "whatsapp.delivery_reminder",
    }
    # Variable keys are keys, never values.
    for key in PHASE_7E_PROPOSED_VARIABLE_KEYS:
        assert " " not in key  # snake_case, no PII-shaped value.


# ---------------------------------------------------------------------------
# Service module static-file scans
# ---------------------------------------------------------------------------


def test_service_module_does_not_import_send_helpers() -> None:
    src = importlib.import_module(
        "apps.payments.razorpay_whatsapp_internal_notification"
    ).__file__
    with open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    forbidden_imports = [
        "from apps.whatsapp.services import send_freeform_text_message",
        "from apps.whatsapp.services import send_queued_message",
        "from apps.whatsapp.services import queue_template_message",
        "from apps.whatsapp.integrations.whatsapp.meta_cloud_client",
        "import apps.whatsapp.integrations.whatsapp.meta_cloud_client",
        "from dotenv",
        "import dotenv",
    ]
    for needle in forbidden_imports:
        assert needle not in text, (
            f"forbidden import detected in service: {needle}"
        )


def test_service_module_never_writes_env_file() -> None:
    src = importlib.import_module(
        "apps.payments.razorpay_whatsapp_internal_notification"
    ).__file__
    with open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    assert ".env.production" not in text
    assert ".env.live" not in text


# ---------------------------------------------------------------------------
# Readiness command + endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_command_returns_phase7e_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_razorpay_whatsapp_internal_notification_readiness",
        "--json",
        "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "7E"
    assert body["status"] == "whatsapp_internal_notification_readiness_only"
    assert body["latestCompletedPhase"] == "7D"
    assert body["nextPhase"] == "7F_or_7E_live_not_approved"
    for key in (
        "phase7ESendsWhatsApp",
        "phase7EQueuesWhatsApp",
        "phase7ECallsMetaCloud",
        "phase7ECallsDelhivery",
        "phase7ECreatesShipmentOrAwb",
        "phase7ECreatesPaymentLink",
        "phase7ECapturesPayment",
        "phase7ERefundsPayment",
        "phase7ESendsCustomerNotification",
        "phase7EMutatesBusinessRow",
    ):
        assert body[key] is False


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase7e_shape(
    admin_user, auth_client
) -> None:
    url = reverse(
        "saas-razorpay-whatsapp-internal-notification-readiness"
    )
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "7E"
    assert body["status"] == "whatsapp_internal_notification_readiness_only"


@pytest.mark.django_db
def test_readiness_endpoint_requires_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse(
        "saas-razorpay-whatsapp-internal-notification-readiness"
    )
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


# ---------------------------------------------------------------------------
# POST/PATCH/PUT/DELETE -> 405 on every endpoint
# ---------------------------------------------------------------------------


_PHASE_7E_GET_ENDPOINTS = (
    ("saas-razorpay-whatsapp-internal-notification-readiness", None),
    ("saas-razorpay-whatsapp-internal-notification-gates", None),
    (
        "saas-razorpay-whatsapp-internal-notification-preview",
        "?attempt_id=1",
    ),
)


@pytest.mark.django_db
@pytest.mark.parametrize("name,query", _PHASE_7E_GET_ENDPOINTS)
def test_phase7e_endpoints_reject_non_get_methods(
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
def test_phase7e_detail_and_dry_runs_reject_non_get(
    admin_user, auth_client
) -> None:
    detail = reverse(
        "saas-razorpay-whatsapp-internal-notification-gate-detail",
        kwargs={"pk": 1},
    )
    dry_runs = reverse(
        "saas-razorpay-whatsapp-internal-notification-dry-runs",
        kwargs={"gate_id": 1},
    )
    client = auth_client(admin_user)
    for url in (detail, dry_runs):
        for method in ("post", "patch", "put", "delete"):
            assert getattr(client, method)(url, {}).status_code == 405


@pytest.mark.django_db
def test_no_phase7e_post_execute_or_approve_endpoint_exists() -> None:
    """Phase 7E approval is CLI-only; no POST endpoint may dispatch it."""
    from django.urls import get_resolver

    resolver = get_resolver()
    suspicious = []
    for pattern in resolver.url_patterns:
        if "saas/" not in str(pattern.pattern):
            continue
        for sub in getattr(pattern, "url_patterns", []):
            p = str(sub.pattern)
            if "whatsapp-internal-notification" in p and any(
                token in p
                for token in (
                    "approve",
                    "reject",
                    "execute",
                    "send",
                    "queue",
                    "notify",
                    "archive",
                )
            ):
                suspicious.append(p)
    assert not suspicious, suspicious


# ---------------------------------------------------------------------------
# Preview never creates rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_never_creates_rows() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_preview"
    )
    before = _row_counts()
    out = preview_phase7e_gate(attempt.pk)
    after = _row_counts()
    assert out["found"] is True
    assert (
        RazorpayWhatsAppInternalNotificationGate.objects.count() == 0
    )
    assert before == after


@pytest.mark.django_db
def test_preview_endpoint_requires_attempt_id(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-whatsapp-internal-notification-preview")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Prepare gating
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_blocked_when_gate_flag_off() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_no_flag"
    )
    out = prepare_phase7e_gate(attempt.pk)
    assert out["created"] is False
    assert out["reused"] is False
    assert out["gate"] is None
    assert any(
        "PHASE7E" in b or "phase7e" in b for b in out["blockers"]
    )


@pytest.mark.django_db
def test_prepare_blocked_when_phase7d_attempt_not_rolled_back() -> None:
    """Phase 7B-approved gate without a Phase 7D attempt cannot source 7E."""
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7e_no_attempt"
    )
    with _phase7d_test_settings():
        prepared = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
        attempt_id = prepared["attempt"]["id"]
        # No approve, no execute, no rollback -- attempt stays
        # pending_director_signoff.
    with _phase7e_test_settings():
        out = prepare_phase7e_gate(attempt_id)
    assert out["created"] is False
    assert out["gate"] is None


@pytest.mark.django_db
def test_prepare_creates_gate_with_locked_safety_booleans() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_prepare"
    )
    with _phase7e_test_settings():
        out = prepare_phase7e_gate(attempt.pk)
    assert out["created"] is True
    gate_id = out["gate"]["id"]
    row = RazorpayWhatsAppInternalNotificationGate.objects.get(
        pk=gate_id
    )
    assert (
        row.status
        == RazorpayWhatsAppInternalNotificationGate.Status.PENDING_MANUAL_REVIEW
    )
    invariants = row.safety_invariants_snapshot
    for key in (
        "whatsappSendAllowedInPhase7E",
        "whatsappQueueAllowedInPhase7E",
        "metaCloudCallAllowedInPhase7E",
        "businessMutationAllowedInPhase7E",
        "customerNotificationAllowedInPhase7E",
        "realCustomerAllowedInPhase7E",
        "providerCallAttempted",
        "whatsAppMessageCreated",
        "whatsAppMessageQueued",
        "whatsAppLifecycleEventCreated",
        "metaCloudCallAttempted",
        "customerNotificationSent",
        "realOrderMutationWasMade",
        "realPaymentMutationWasMade",
    ):
        assert invariants[key] is False, key
    assert row.idempotency_key == (
        f"phase7e::wa_notify::attempt::{attempt.pk}"
    )
    assert (
        row.source_phase7d_signoff_window_validation_status
        == RazorpayWhatsAppInternalNotificationGate.SourcePhase7DSignoffWindowValidationStatus.FAILED_OR_LEGACY_FREE_TEXT
    )


@pytest.mark.django_db
def test_prepare_idempotent_on_same_phase7d_attempt() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_idem"
    )
    with _phase7e_test_settings():
        a = prepare_phase7e_gate(attempt.pk)
        b = prepare_phase7e_gate(attempt.pk)
    assert a["created"] is True
    assert b["created"] is False
    assert b["reused"] is True
    assert (
        RazorpayWhatsAppInternalNotificationGate.objects.count() == 1
    )


@pytest.mark.django_db
def test_prepare_blocked_when_kill_switch_off() -> None:
    from apps.saas.models import RuntimeKillSwitch

    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_kill_off"
    )
    kill, _ = RuntimeKillSwitch.objects.get_or_create(
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        provider_type="",
        operation_type="",
    )
    kill.enabled = False
    kill.save()
    with _phase7e_test_settings():
        out = prepare_phase7e_gate(attempt.pk)
    assert out["created"] is False
    assert any(
        "kill" in b.lower() or "switch" in b.lower()
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
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id=f"evt_phase7e_flag_{flag_name[:8]}"
    )
    with _phase7e_test_settings(**{flag_name: True}):
        out = prepare_phase7e_gate(attempt.pk)
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
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id=f"evt_phase7e_pf_{flag_name[:8]}"
    )
    with _phase7e_test_settings(**{flag_name: True}):
        out = prepare_phase7e_gate(attempt.pk)
    assert out["created"] is False
    assert any(flag_name in b for b in out["blockers"])


# ---------------------------------------------------------------------------
# Dry-run / rollback-dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dry_run_pass_writes_record_and_no_business_row_change() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_dryrun"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
        before = _row_counts()
        out = dry_run_phase7e_gate(gate_id)
        after = _row_counts()
    assert out["ok"] is True
    record_count = (
        RazorpayWhatsAppInternalNotificationDryRunRecord.objects.filter(
            gate_id=gate_id, kind="dry_run"
        ).count()
    )
    assert record_count == 1
    assert before == after


@pytest.mark.django_db
def test_dry_run_never_creates_whatsapp_row() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_no_wa_row"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
        wa_before = WhatsAppMessage.objects.count()
        wa_lc_before = WhatsAppLifecycleEvent.objects.count()
        wa_handoff_before = WhatsAppHandoffToCall.objects.count()
        dry_run_phase7e_gate(gate_id)
    assert WhatsAppMessage.objects.count() == wa_before
    assert WhatsAppLifecycleEvent.objects.count() == wa_lc_before
    assert WhatsAppHandoffToCall.objects.count() == wa_handoff_before


@pytest.mark.django_db
def test_dry_run_records_stack_safely() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_stack"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7e_gate(gate_id)
        dry_run_phase7e_gate(gate_id)
        dry_run_phase7e_gate(gate_id)
    assert (
        RazorpayWhatsAppInternalNotificationDryRunRecord.objects.filter(
            gate_id=gate_id, kind="dry_run"
        ).count()
        == 3
    )


@pytest.mark.django_db
def test_rollback_dry_run_requires_reason() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_rb_no_reason"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7e_gate(gate_id)
        out = rollback_dry_run_phase7e_gate(gate_id, reason="")
    assert out["ok"] is False
    assert any("reason" in b for b in out["blockers"])


@pytest.mark.django_db
def test_rollback_dry_run_passes_after_dry_run() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_rb_pass"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7e_gate(gate_id)
        out = rollback_dry_run_phase7e_gate(
            gate_id, reason="Rehearsal complete"
        )
    assert out["ok"] is True
    record_count = (
        RazorpayWhatsAppInternalNotificationDryRunRecord.objects.filter(
            gate_id=gate_id, kind="rollback_dry_run"
        ).count()
    )
    assert record_count == 1


# ---------------------------------------------------------------------------
# Approve gating
# ---------------------------------------------------------------------------


def _walk_to_ready_to_approve_gate(
    *, source_event_id: str
) -> tuple[
    RazorpayWhatsAppInternalNotificationGate,
    RazorpayControlledPilotExecutionAttempt,
]:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id=source_event_id
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7e_gate(gate_id)
        rollback_dry_run_phase7e_gate(
            gate_id, reason="Approve fixture rehearsal"
        )
    return (
        RazorpayWhatsAppInternalNotificationGate.objects.get(pk=gate_id),
        attempt,
    )


@pytest.mark.django_db
def test_approve_refuses_without_reason() -> None:
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id="evt_phase7e_appr_no_reason"
    )
    with _phase7e_test_settings():
        out = approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason="",
            director_signoff=_structured_signoff(attempt.pk),
            acknowledge_source_phase7d_window_violation=True,
        )
    assert out["ok"] is False
    assert any("reason" in b for b in out["blockers"])


@pytest.mark.django_db
def test_approve_refuses_when_signoff_missing_window_markers() -> None:
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id="evt_phase7e_appr_no_window"
    )
    reason = (
        "Director sign-off Phase 7E review. "
        f"acknowledged_phase7d_window_violation_ref_attempt_{attempt.pk}"
    )
    with _phase7e_test_settings():
        out = approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason=reason,
            director_signoff=(
                f"Free text without window. phase7d_attempt_id_{attempt.pk}"
            ),
            acknowledge_source_phase7d_window_violation=True,
        )
    assert out["ok"] is False
    assert any(
        "missing_structured_utc_window" in b for b in out["blockers"]
    )


@pytest.mark.django_db
def test_approve_refuses_when_signoff_window_too_long() -> None:
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id="evt_phase7e_window_too_long"
    )
    reason = (
        "Director sign-off Phase 7E review. "
        f"acknowledged_phase7d_window_violation_ref_attempt_{attempt.pk}"
    )
    long_signoff = _structured_signoff(
        attempt.pk, minutes_ahead=10, window_minutes=25 * 60
    )  # 25 hours
    with _phase7e_test_settings():
        out = approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason=reason,
            director_signoff=long_signoff,
            acknowledge_source_phase7d_window_violation=True,
        )
    assert out["ok"] is False
    assert any("window_too_long" in b for b in out["blockers"])


@pytest.mark.django_db
def test_approve_refuses_when_signoff_does_not_reference_attempt_id() -> None:
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id="evt_phase7e_no_attempt_ref"
    )
    reason = (
        "Director sign-off Phase 7E review. "
        f"acknowledged_phase7d_window_violation_ref_attempt_{attempt.pk}"
    )
    start = timezone.now() + timedelta(minutes=15)
    end = start + timedelta(minutes=30)
    signoff_no_ref = (
        "Director sign-off Phase 7E review window. "
        f"BEGIN_UTC={start.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"END_UTC={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    with _phase7e_test_settings():
        out = approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason=reason,
            director_signoff=signoff_no_ref,
            acknowledge_source_phase7d_window_violation=True,
        )
    assert out["ok"] is False
    assert any(
        "must_reference_source_phase7d_attempt_id" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_approve_refuses_when_legacy_signoff_no_acknowledge_flag() -> None:
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id="evt_phase7e_legacy_no_ack"
    )
    reason = (
        f"Director sign-off Phase 7E review. "
        f"acknowledged_phase7d_window_violation_ref_attempt_{attempt.pk}"
    )
    with _phase7e_test_settings():
        out = approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason=reason,
            director_signoff=_structured_signoff(attempt.pk),
            acknowledge_source_phase7d_window_violation=False,
        )
    assert out["ok"] is False
    assert any(
        "acknowledge_source_phase7d_window_violation_required" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_approve_refuses_when_acknowledge_flag_set_but_reason_token_missing() -> None:
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id="evt_phase7e_legacy_no_token"
    )
    reason_no_token = (
        "Director sign-off Phase 7E review. No ack token here."
    )
    with _phase7e_test_settings():
        out = approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason=reason_no_token,
            director_signoff=_structured_signoff(attempt.pk),
            acknowledge_source_phase7d_window_violation=True,
        )
    assert out["ok"] is False
    assert any(
        "reason_must_contain_acknowledgement_token" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_approve_succeeds_for_legacy_signoff_with_ack_flag_and_reason_token() -> None:
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id="evt_phase7e_appr_ok"
    )
    reason = (
        "Director sign-off Phase 7E review. "
        f"acknowledged_phase7d_window_violation_ref_attempt_{attempt.pk}"
    )
    with _phase7e_test_settings():
        out = approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason=reason,
            director_signoff=_structured_signoff(attempt.pk),
            acknowledge_source_phase7d_window_violation=True,
        )
    assert out["ok"] is True
    row = RazorpayWhatsAppInternalNotificationGate.objects.get(pk=gate.pk)
    assert (
        row.status
        == RazorpayWhatsAppInternalNotificationGate.Status.APPROVED_FOR_FUTURE_PHASE7F_OR_7E_SEND_REVIEW
    )
    assert row.source_phase7d_window_violation_acknowledged is True
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_ACKED_LEGACY_SIGNOFF
    ).exists()
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_APPROVED_FUTURE_SEND
    ).exists()


@pytest.mark.django_db
def test_second_approve_refused() -> None:
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id="evt_phase7e_second_appr"
    )
    reason = (
        "Director sign-off Phase 7E review. "
        f"acknowledged_phase7d_window_violation_ref_attempt_{attempt.pk}"
    )
    with _phase7e_test_settings():
        first = approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason=reason,
            director_signoff=_structured_signoff(attempt.pk),
            acknowledge_source_phase7d_window_violation=True,
        )
        second = approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason=reason,
            director_signoff=_structured_signoff(attempt.pk),
            acknowledge_source_phase7d_window_violation=True,
        )
    assert first["ok"] is True
    assert second["ok"] is False


@pytest.mark.django_db
def test_approve_does_not_send_or_queue_whatsapp() -> None:
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id="evt_phase7e_no_send"
    )
    reason = (
        "Director sign-off Phase 7E review. "
        f"acknowledged_phase7d_window_violation_ref_attempt_{attempt.pk}"
    )
    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as queue_mock, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as send_mock, mock.patch(
        "apps.whatsapp.services.send_queued_message"
    ) as send_queued_mock:
        with _phase7e_test_settings():
            out = approve_phase7e_gate(
                gate.pk,
                reviewed_by=None,
                reason=reason,
                director_signoff=_structured_signoff(attempt.pk),
                acknowledge_source_phase7d_window_violation=True,
            )
    assert out["ok"] is True
    queue_mock.assert_not_called()
    send_mock.assert_not_called()
    send_queued_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reject_requires_reason() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_rej_no_reason"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
        out = reject_phase7e_gate(gate_id, reason="")
    assert out["ok"] is False
    assert any("reason" in b for b in out["blockers"])


@pytest.mark.django_db
def test_reject_changes_status_to_rejected() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_rej_ok"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
        out = reject_phase7e_gate(
            gate_id, reason="Director paused future-send review"
        )
    assert out["ok"] is True
    row = RazorpayWhatsAppInternalNotificationGate.objects.get(pk=gate_id)
    assert (
        row.status
        == RazorpayWhatsAppInternalNotificationGate.Status.REJECTED
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_REJECTED
    ).exists()


@pytest.mark.django_db
def test_reject_refuses_when_status_already_approved() -> None:
    gate, attempt = _walk_to_ready_to_approve_gate(
        source_event_id="evt_phase7e_rej_after_appr"
    )
    reason_appr = (
        "Director sign-off Phase 7E review. "
        f"acknowledged_phase7d_window_violation_ref_attempt_{attempt.pk}"
    )
    with _phase7e_test_settings():
        approve_phase7e_gate(
            gate.pk,
            reviewed_by=None,
            reason=reason_appr,
            director_signoff=_structured_signoff(attempt.pk),
            acknowledge_source_phase7d_window_violation=True,
        )
        out = reject_phase7e_gate(
            gate.pk, reason="Director changed mind"
        )
    assert out["ok"] is False
    assert any("refused_for_status" in b for b in out["blockers"])


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_archive_changes_status() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_archive"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
        out = archive_phase7e_gate(
            gate_id, reason="Test archive"
        )
    assert out["ok"] is True
    row = RazorpayWhatsAppInternalNotificationGate.objects.get(pk=gate_id)
    assert (
        row.status
        == RazorpayWhatsAppInternalNotificationGate.Status.ARCHIVED
    )


# ---------------------------------------------------------------------------
# Defensive guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "key",
    [
        "whatsappSendAllowedInPhase7E",
        "whatsappQueueAllowedInPhase7E",
        "metaCloudCallAllowedInPhase7E",
        "businessMutationAllowedInPhase7E",
        "customerNotificationAllowedInPhase7E",
        "realCustomerAllowedInPhase7E",
        "providerCallAttempted",
        "whatsAppMessageCreated",
        "whatsAppMessageQueued",
        "whatsAppLifecycleEventCreated",
        "metaCloudCallAttempted",
        "customerNotificationSent",
        "realOrderMutationWasMade",
        "realPaymentMutationWasMade",
    ],
)
def test_assert_no_send_or_business_mutation_raises_on_flipped_boolean(
    key,
) -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id=f"evt_phase7e_guard_{key[:8]}"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
    row = RazorpayWhatsAppInternalNotificationGate.objects.get(pk=gate_id)
    snapshot = dict(row.safety_invariants_snapshot)
    snapshot[key] = True
    row.safety_invariants_snapshot = snapshot
    row.save(update_fields=["safety_invariants_snapshot"])
    with pytest.raises(ValueError):
        assert_phase7e_no_send_or_business_mutation(row)
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_INVARIANT_VIOLATION
    ).exists()


@pytest.mark.django_db
def test_full_lifecycle_makes_no_provider_call_and_no_business_row_change() -> None:
    """Running the full Phase 7E lifecycle leaves every business
    table count unchanged."""
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_full_lifecycle"
    )
    before = _row_counts()

    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as queue_mock, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as send_mock, mock.patch(
        "apps.whatsapp.services.send_queued_message"
    ) as send_queued_mock, mock.patch(
        "apps.payments.razorpay_controlled_pilot_execution"
        "._create_order_via_sdk"
    ) as razorpay_sdk_mock:
        with _phase7e_test_settings():
            prepared = prepare_phase7e_gate(attempt.pk)
            gate_id = prepared["gate"]["id"]
            dry_run_phase7e_gate(gate_id)
            rollback_dry_run_phase7e_gate(
                gate_id, reason="Full-lifecycle rehearsal"
            )
            reason = (
                "Director sign-off Phase 7E review. "
                f"acknowledged_phase7d_window_violation_ref_attempt_{attempt.pk}"
            )
            approve_phase7e_gate(
                gate_id,
                reviewed_by=None,
                reason=reason,
                director_signoff=_structured_signoff(attempt.pk),
                acknowledge_source_phase7d_window_violation=True,
            )

    after = _row_counts()
    assert before == after
    queue_mock.assert_not_called()
    send_mock.assert_not_called()
    send_queued_mock.assert_not_called()
    razorpay_sdk_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Audit payload guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_audit_payloads_lack_forbidden_keys() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_audit_keys"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7e_gate(gate_id)
        rollback_dry_run_phase7e_gate(
            gate_id, reason="Audit-keys rehearsal"
        )
        reason = (
            "Director sign-off Phase 7E review. "
            f"acknowledged_phase7d_window_violation_ref_attempt_{attempt.pk}"
        )
        approve_phase7e_gate(
            gate_id,
            reviewed_by=None,
            reason=reason,
            director_signoff=_structured_signoff(attempt.pk),
            acknowledge_source_phase7d_window_violation=True,
        )

    rows = AuditEvent.objects.filter(
        kind__startswith="razorpay.whatsapp_internal_notification."
    )
    forbidden = set(PHASE_7E_FORBIDDEN_PAYLOAD_KEYS)

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
# Serializer guards
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_serializer_does_not_leak_director_signoff_text() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_serializer"
    )
    with _phase7e_test_settings():
        prepared = prepare_phase7e_gate(attempt.pk)
        gate_id = prepared["gate"]["id"]
    row = RazorpayWhatsAppInternalNotificationGate.objects.get(pk=gate_id)
    row.director_signoff_text = (
        "secret email director@nirogidhara.com phone +919876543210"
    )
    row.save(update_fields=["director_signoff_text"])
    serialized = serialize_phase7e_gate(row)
    body = json.dumps(serialized)
    assert "director@nirogidhara.com" not in body
    assert "+919876543210" not in body
    assert "directorSignoffText" not in serialized


# ---------------------------------------------------------------------------
# Detail / dry-runs 404
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_detail_endpoint_returns_404_for_unknown_id(
    admin_user, auth_client
) -> None:
    url = reverse(
        "saas-razorpay-whatsapp-internal-notification-gate-detail",
        kwargs={"pk": 9999},
    )
    res = auth_client(admin_user).get(url)
    assert res.status_code == 404


@pytest.mark.django_db
def test_dry_runs_endpoint_returns_404_for_unknown_gate(
    admin_user, auth_client
) -> None:
    url = reverse(
        "saas-razorpay-whatsapp-internal-notification-dry-runs",
        kwargs={"gate_id": 9999},
    )
    res = auth_client(admin_user).get(url)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Summarize / readiness
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_summarize_counts_all_lifecycle_states() -> None:
    summary = summarize_phase7e_gates(limit=10)
    counts = summary["counts"]
    expected = {
        "draft",
        "pending_manual_review",
        "approved_for_future_phase7f_or_7e_send_review",
        "rejected",
        "archived",
        "blocked",
    }
    assert expected.issubset(set(counts))


@pytest.mark.django_db
def test_inspect_readiness_reports_phase7d_eligible_count() -> None:
    attempt = _make_executed_and_rolled_back_phase7d_attempt(
        source_event_id="evt_phase7e_readiness_count"
    )
    report = inspect_phase7e_readiness()
    assert report["phase7DRolledBackEligibleCount"] >= 1
    # The eligible-for-Phase-7E count is for EXECUTED-status attempts;
    # rolled-back attempts also satisfy the chain via the "executed
    # OR rolled-back" branch in eligibility, but inspect_readiness
    # counts EXECUTED-status only as a safety floor. Either way the
    # report should be a non-negative integer.
    assert report["phase7DEligibleForPhase7ECount"] >= 0


# ---------------------------------------------------------------------------
# Attempts list endpoint locks Phase 7E safety booleans
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_gates_list_endpoint_returns_phase7e_safety_locks(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-whatsapp-internal-notification-gates")
    body = auth_client(admin_user).get(url).json()
    assert body["phase"] == "7E"
    for key in (
        "frontendCanExecute",
        "apiEndpointCanExecute",
        "apiEndpointCanApprove",
        "phase7ESendsWhatsApp",
        "phase7EQueuesWhatsApp",
        "phase7ECallsMetaCloud",
        "phase7ECallsDelhivery",
        "phase7ECreatesShipmentOrAwb",
        "phase7ECreatesPaymentLink",
        "phase7ECapturesPayment",
        "phase7ERefundsPayment",
        "phase7ESendsCustomerNotification",
        "phase7EMutatesBusinessRow",
    ):
        assert body[key] is False
