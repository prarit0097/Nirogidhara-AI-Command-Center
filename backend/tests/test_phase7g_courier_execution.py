"""Phase 7G - One-shot Delhivery TEST/MOCK Courier Execution Gate tests.

Asserts every Phase 7G safety requirement. Phase 7G never creates a
``Shipment`` row, never books a courier pickup separately, never
generates / prints a courier label, never sends or queues WhatsApp,
never calls Meta Cloud / Razorpay / Vapi, never sends a customer
notification, never mutates real ``Order`` / ``Payment`` /
``Customer`` / ``Lead`` / ``DiscountOfferLog`` rows, never edits any
``.env*`` file. The actual Delhivery client is patched at the
``apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper``
boundary so the real network is never hit.
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
    RazorpayCourierExecutionAttempt,
    RazorpayCourierExecutionRollback,
    RazorpayCourierReadinessGate,
)
from apps.payments.razorpay_courier_execution import (
    AUDIT_KIND_APPROVED_FOR_ONE_SHOT,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_DUPLICATE_BLOCKED,
    AUDIT_KIND_EXECUTED,
    AUDIT_KIND_FAILED,
    AUDIT_KIND_INVARIANT_VIOLATION,
    AUDIT_KIND_KILL_SWITCH_BLOCKED,
    AUDIT_KIND_MODE_BLOCKED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    AUDIT_KIND_RETRY_PREPARED,
    AUDIT_KIND_ROLLED_BACK,
    PHASE_7G_ALLOWED_DELHIVERY_MODES,
    PHASE_7G_FORBIDDEN_ACTIONS,
    PHASE_7G_FORBIDDEN_PAYLOAD_KEYS,
    PHASE_7G_SYNTHETIC_ADDRESS_LINE_REDACTED,
    PHASE_7G_SYNTHETIC_CUSTOMER_NAME,
    PHASE_7G_SYNTHETIC_PHONE_LAST4,
    PHASE_7G_SYNTHETIC_PIN_PREFIX,
    Phase7GExecutionError,
    approve_phase7g_courier_execution_attempt,
    assert_phase7g_no_unauthorised_mutation,
    build_phase7g_courier_execution_contract,
    execute_phase7g_courier_one_shot,
    inspect_phase7g_courier_execution_readiness,
    prepare_phase7g_courier_execution_attempt,
    preview_phase7g_courier_execution_attempt,
    reject_phase7g_courier_execution_attempt,
    rollback_phase7g_courier_execution_attempt,
    serialize_phase7g_attempt,
    summarize_phase7g_attempts,
    validate_phase7g_source_chain,
)
from apps.payments.razorpay_courier_readiness import approve_phase7f_gate
from apps.shipments.models import RescueAttempt, Shipment, WorkflowStep
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from tests.test_phase7f_courier_readiness import (
    _make_approved_phase7e_gate,
    _phase7f_test_settings,
    _walk_to_ready_to_approve_phase7f_gate,
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


def _phase7g_test_settings(**overrides):
    base = {
        "PHASE7G_COURIER_EXECUTION_ENABLED": True,
        "PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION": False,
        "PHASE7G_ALLOW_DELHIVERY_TEST_AWB": False,
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


def _phase7g_execute_settings(**overrides):
    base = {
        "PHASE7G_COURIER_EXECUTION_ENABLED": True,
        "PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION": True,
        "PHASE7G_ALLOW_DELHIVERY_TEST_AWB": True,
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


def _make_approved_phase7f_gate(
    *, source_event_id: str
) -> RazorpayCourierReadinessGate:
    """Walk Phase 7E approved -> Phase 7F prepare/dry-run/rollback-dry-run/
    approve. Returns a Phase 7F gate in
    ``approved_for_future_phase7g_or_courier_execution_review``.
    """
    gate = _walk_to_ready_to_approve_phase7f_gate(
        source_event_id=source_event_id
    )
    with _phase7f_test_settings():
        approve_phase7f_gate(
            gate.pk,
            reviewed_by=None,
            reason="Director sign-off Phase 7F approve fixture",
        )
    return RazorpayCourierReadinessGate.objects.get(pk=gate.pk)


def _make_approved_phase7g_attempt(
    *, source_event_id: str
) -> RazorpayCourierExecutionAttempt:
    """Walk Phase 7F approved -> Phase 7G prepare -> Phase 7G approve."""
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id=source_event_id
    )
    with _phase7g_test_settings():
        prepared = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
        attempt_id = prepared["attempt"]["id"]
        approve_phase7g_courier_execution_attempt(
            attempt_id,
            reviewed_by=None,
            reason="Director sign-off Phase 7G approve fixture",
        )
    return RazorpayCourierExecutionAttempt.objects.get(pk=attempt_id)


def _structured_signoff(
    phase7f_gate_id: int,
    *,
    begin_offset_seconds: int = -60,
    end_offset_seconds: int = 60,
) -> str:
    """Build a Phase 7G-Hotfix-1 compliant Director sign-off.

    Defaults to a 2-minute window centered on ``datetime.now(tz=UTC)``,
    i.e. begin = now-60s, end = now+60s, so ``validate_within_director_window``
    returns ``valid=True``. Tests override the offsets to exercise the
    "now before start", "now after end", "window > 15 min", and "stale
    window" branches.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    begin = now + timedelta(seconds=begin_offset_seconds)
    end = now + timedelta(seconds=end_offset_seconds)
    begin_iso = begin.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"Director sign-off for Phase 7G one-shot courier "
        f"execution against Phase 7F gate {phase7f_gate_id}. "
        f"BEGIN_UTC={begin_iso} END_UTC={end_iso}"
    )


def _signoff_text(phase7f_gate_id: int) -> str:
    """Hotfix-1 compliant default sign-off used by every happy-path test."""
    return _structured_signoff(phase7f_gate_id)


# ---------------------------------------------------------------------------
# Contract + audit-kind length
# ---------------------------------------------------------------------------


def test_contract_locks_courier_and_business_mutation_off() -> None:
    contract = build_phase7g_courier_execution_contract()
    assert contract["phase"] == "7G"
    assert (
        contract["status"]
        == "delhivery_test_or_mock_one_shot_courier_execution_only"
    )
    for key in (
        "phase7GCallsDelhivery",
        "phase7GCallsDelhiveryDuringPlanning",
        "phase7GCreatesShipmentRow",
        "phase7GBooksCourierPickupSeparately",
        "phase7GGeneratesCourierLabel",
        "phase7GSendsWhatsApp",
        "phase7GQueuesWhatsApp",
        "phase7GCallsMetaCloud",
        "phase7GCallsRazorpay",
        "phase7GCallsVapi",
        "phase7GSendsCustomerNotification",
        "phase7GMutatesBusinessRow",
        "phase7GMutatesRealOrderRow",
        "phase7GMutatesRealPaymentRow",
        "phase7GMutatesRealCustomerRow",
        "phase7GMutatesRealLeadRow",
        "phase7GTouchesRealCustomerPhoneNumber",
        "phase7GTouchesRealCustomerAddress",
        "phase7GWritesEnvFile",
        "phase7GImportsDotenv",
        "phase7GLiveCustomerCourierApproved",
        "phase7GApprovalImpliesLiveCourier",
    ):
        assert contract[key] is False, key
    assert contract["phase7GCreatesAwbRowOnAttemptOnly"] is True
    assert contract["executeIsCliOnly"] is True
    assert contract["manualReviewRequired"] is True


def test_contract_locks_synthetic_payload_constants() -> None:
    contract = build_phase7g_courier_execution_contract()
    assert (
        contract["syntheticPayloadCustomerName"]
        == "Phase 7G TEST"
    )
    assert contract["syntheticPayloadPhoneLast4"] == "0000"
    assert contract["syntheticPayloadAddressLine"] == "[redacted]"
    assert contract["syntheticPayloadPinPrefix"] == "11000"


def test_phase7g_audit_kinds_within_length_budget() -> None:
    audit_kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_APPROVED_FOR_ONE_SHOT,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_EXECUTED,
        AUDIT_KIND_FAILED,
        AUDIT_KIND_ROLLED_BACK,
        AUDIT_KIND_BLOCKED,
        AUDIT_KIND_KILL_SWITCH_BLOCKED,
        AUDIT_KIND_INVARIANT_VIOLATION,
        AUDIT_KIND_MODE_BLOCKED,
        AUDIT_KIND_DUPLICATE_BLOCKED,
    ]
    assert len(audit_kinds) == 13
    for kind in audit_kinds:
        assert kind.startswith("razorpay.courier_execution.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_allowed_delhivery_modes_only_mock_or_test() -> None:
    assert PHASE_7G_ALLOWED_DELHIVERY_MODES == frozenset(
        {"mock", "test"}
    )


def test_forbidden_actions_critical_paths_present() -> None:
    expected = {
        "create_shipment_row",
        "create_workflow_step_row",
        "create_rescue_attempt_row",
        "send_whatsapp_template",
        "send_whatsapp_freeform",
        "queue_whatsapp_outbound",
        "send_customer_notification",
        "call_meta_cloud_api",
        "call_razorpay_api",
        "call_vapi_api",
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
        "reject_via_api_endpoint",
        "edit_dotenv_any",
        "import_dotenv_module",
        "switch_to_delhivery_live_mode",
        "use_real_customer_phone_or_address",
    }
    assert expected.issubset(set(PHASE_7G_FORBIDDEN_ACTIONS))


def test_forbidden_payload_keys_include_token_and_address() -> None:
    expected = {
        "token",
        "phone",
        "customer_phone",
        "email",
        "address",
        "address_line",
        "pincode",
        "DELHIVERY_API_TOKEN",
        "META_WA_TOKEN",
        "RAZORPAY_KEY_SECRET",
        "raw_payload",
        "raw_signature",
        "raw_secret",
    }
    assert expected.issubset(set(PHASE_7G_FORBIDDEN_PAYLOAD_KEYS))


# ---------------------------------------------------------------------------
# Service module static-file scans
# ---------------------------------------------------------------------------


def _service_source() -> str:
    src_path = importlib.import_module(
        "apps.payments.razorpay_courier_execution"
    ).__file__
    with open(src_path, "r", encoding="utf-8") as fh:
        return fh.read()


def test_service_module_does_not_top_level_import_create_awb() -> None:
    text = _service_source()
    # The Delhivery client must be lazy-imported only inside the
    # dedicated wrapper. No top-level import.
    forbidden_top_level = [
        "from apps.shipments.integrations.delhivery_client import create_awb",
        "from apps.shipments.integrations.delhivery_client import _create_via_sdk",
    ]
    for needle in forbidden_top_level:
        # Ensure the needle, if present, is only inside a function body.
        idx = text.find(needle)
        if idx == -1:
            continue
        # Find the nearest preceding line break to its left.
        line_start = text.rfind("\n", 0, idx) + 1
        line = text[line_start:idx]
        assert line.strip().startswith(""), (
            f"{needle} appears outside a function body."
        )
        # Must be inside a def block (4-space indent).
        assert line.startswith("    "), (
            f"{needle} must only be lazy-imported inside a function "
            "body."
        )


def test_service_module_does_not_create_shipment_row() -> None:
    text = _service_source()
    assert "Shipment.objects.create" not in text
    assert "WorkflowStep.objects.create" not in text
    assert "RescueAttempt.objects.create" not in text


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
def test_readiness_command_returns_phase7g_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_delhivery_courier_execution_readiness",
        "--json",
        "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "7G"
    assert (
        body["status"]
        == "delhivery_test_or_mock_one_shot_courier_execution_only"
    )
    assert body["latestCompletedPhase"] == "7F"
    assert (
        body["nextPhase"] == "phase_7g_live_or_phase_7h_not_approved"
    )
    for key in (
        "phase7GCallsDelhivery",
        "phase7GCreatesShipmentRow",
        "phase7GBooksCourierPickupSeparately",
        "phase7GGeneratesCourierLabel",
        "phase7GSendsCustomerNotification",
        "phase7GMutatesBusinessRow",
        "phase7GCallsMetaCloud",
        "phase7GCallsRazorpay",
        "phase7GCallsVapi",
        "phase7GSendsWhatsApp",
        "phase7GQueuesWhatsApp",
        "phase7GLiveCustomerCourierApproved",
    ):
        assert body[key] is False, key
    assert body["phase7GCreatesAwbRowOnAttemptOnly"] is True
    assert body["safeToRunPhase7GExecution"] is False


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase7g_shape(
    admin_user, auth_client
) -> None:
    url = reverse("saas-delhivery-courier-execution-readiness")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "7G"
    assert (
        body["status"]
        == "delhivery_test_or_mock_one_shot_courier_execution_only"
    )


@pytest.mark.django_db
def test_readiness_endpoint_requires_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse("saas-delhivery-courier-execution-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


# ---------------------------------------------------------------------------
# POST/PATCH/PUT/DELETE -> 405 (CLI-only)
# ---------------------------------------------------------------------------


_PHASE_7G_GET_ENDPOINTS = (
    ("saas-delhivery-courier-execution-readiness", None),
    ("saas-delhivery-courier-execution-attempts", None),
    (
        "saas-delhivery-courier-execution-preview",
        "?gate_id=1",
    ),
)


@pytest.mark.django_db
@pytest.mark.parametrize("name,query", _PHASE_7G_GET_ENDPOINTS)
def test_phase7g_endpoints_reject_non_get_methods(
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
def test_phase7g_detail_and_rollbacks_reject_non_get(
    admin_user, auth_client
) -> None:
    detail = reverse(
        "saas-delhivery-courier-execution-attempt-detail",
        kwargs={"pk": 1},
    )
    rollbacks = reverse(
        "saas-delhivery-courier-execution-rollbacks",
        kwargs={"attempt_id": 1},
    )
    client = auth_client(admin_user)
    for url in (detail, rollbacks):
        for method in ("post", "patch", "put", "delete"):
            assert getattr(client, method)(url, {}).status_code == 405


@pytest.mark.django_db
def test_no_phase7g_post_execute_or_approve_endpoint_exists() -> None:
    """Phase 7G is CLI-only; no POST endpoint may dispatch state."""
    from django.urls import get_resolver

    resolver = get_resolver()
    suspicious = []
    for pattern in resolver.url_patterns:
        if "saas/" not in str(pattern.pattern):
            continue
        for sub in getattr(pattern, "url_patterns", []):
            p = str(sub.pattern)
            if "delhivery/courier-execution" in p and any(
                token in p
                for token in (
                    "approve",
                    "reject",
                    "execute",
                    "send",
                    "create-awb",
                    "create-shipment",
                    "book-pickup",
                    "generate-label",
                    "rollback",
                )
            ):
                # rollbacks endpoint is a read-only GET listing; the
                # name token "rollback" matches but the URL is verb-
                # less. The 405 check above already proves no
                # mutating method is accepted.
                if "courier-execution-rollbacks" in p:
                    continue
                suspicious.append(p)
    assert not suspicious, suspicious


# ---------------------------------------------------------------------------
# Preview never creates rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_never_creates_rows() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_preview"
    )
    before = _row_counts()
    out = preview_phase7g_courier_execution_attempt(phase7f_gate.pk)
    after = _row_counts()
    assert out["found"] is True
    assert RazorpayCourierExecutionAttempt.objects.count() == 0
    assert before == after


@pytest.mark.django_db
def test_preview_endpoint_requires_gate_id(
    admin_user, auth_client
) -> None:
    url = reverse("saas-delhivery-courier-execution-preview")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 400


@pytest.mark.django_db
def test_preview_emits_audit_event() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_preview_audit"
    )
    AuditEvent.objects.filter(kind=AUDIT_KIND_PREVIEWED).delete()
    preview_phase7g_courier_execution_attempt(phase7f_gate.pk)
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_PREVIEWED
    ).exists()


# ---------------------------------------------------------------------------
# Validate source chain
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_validate_blocks_when_no_phase7f_gate_id() -> None:
    out = validate_phase7g_source_chain(None, require_env_flag=False)
    assert out.eligible is False
    assert any(
        "phase_7f_source_courier_readiness_gate_not_found" in b
        for b in out.blockers
    )


@pytest.mark.django_db
def test_validate_blocks_when_lifecycle_flag_off() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_no_flag"
    )
    out = validate_phase7g_source_chain(
        phase7f_gate.pk, require_env_flag=True
    )
    assert out.eligible is False
    assert any(
        "PHASE7G_COURIER_EXECUTION_ENABLED_must_be_true" in b
        for b in out.blockers
    )


@pytest.mark.django_db
def test_validate_blocks_when_phase7f_gate_not_approved() -> None:
    phase7e_gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7g_no_phase7f_appr"
    )
    from apps.payments.razorpay_courier_readiness import (
        prepare_phase7f_gate,
    )

    with _phase7f_test_settings():
        prepared = prepare_phase7f_gate(phase7e_gate.pk)
    phase7f_gate_id = prepared["gate"]["id"]
    with _phase7g_test_settings():
        out = validate_phase7g_source_chain(
            phase7f_gate_id, require_env_flag=True
        )
    assert out.eligible is False
    assert any(
        "phase_7f_gate_status_must_be_approved" in b
        for b in out.blockers
    )


@pytest.mark.django_db
def test_validate_blocks_when_delhivery_mode_live() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_live_mode"
    )
    with _phase7g_test_settings(DELHIVERY_MODE="live"):
        out = validate_phase7g_source_chain(
            phase7f_gate.pk, require_env_flag=True
        )
    assert out.eligible is False
    assert any(
        "DELHIVERY_MODE_must_be_mock_or_test" in b
        for b in out.blockers
    )


# ---------------------------------------------------------------------------
# Prepare gating
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_blocked_when_lifecycle_flag_off() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_prep_no_flag"
    )
    out = prepare_phase7g_courier_execution_attempt(phase7f_gate.pk)
    assert out["created"] is False
    assert out["reused"] is False
    assert out["attempt"] is None
    assert RazorpayCourierExecutionAttempt.objects.count() == 0


@pytest.mark.django_db
def test_prepare_creates_attempt_with_locked_safety_booleans() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_prepare"
    )
    with _phase7g_test_settings():
        out = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    assert out["created"] is True
    attempt_id = out["attempt"]["id"]
    row = RazorpayCourierExecutionAttempt.objects.get(pk=attempt_id)
    assert (
        row.status
        == RazorpayCourierExecutionAttempt.Status.PENDING_DIRECTOR_SIGNOFF
    )
    # Locked-False booleans must remain False.
    assert row.shipment_created is False
    assert row.business_mutation_was_made is False
    assert row.real_order_mutation_was_made is False
    assert row.real_payment_mutation_was_made is False
    assert row.real_shipment_mutation_was_made is False
    assert row.customer_notification_sent is False
    # Allowed-True booleans start False.
    assert row.provider_call_attempted is False
    assert row.delhivery_call_attempted is False
    assert row.awb_created is False
    # Synthetic order id minted.
    assert (
        row.synthetic_order_id
        == f"phase7g::courier::gate::{phase7f_gate.pk}::attempt::{row.pk}"
    )
    assert (
        row.idempotency_key
        == f"phase7g::courier_execution::phase7f_gate::{phase7f_gate.pk}"
    )


@pytest.mark.django_db
def test_prepare_synthetic_payload_never_carries_real_pii() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_synth"
    )
    with _phase7g_test_settings():
        out = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    summary = out["attempt"]["syntheticPayloadSummary"]
    assert (
        summary["customer_name"] == PHASE_7G_SYNTHETIC_CUSTOMER_NAME
    )
    assert (
        summary["customer_phone_last4"]
        == PHASE_7G_SYNTHETIC_PHONE_LAST4
    )
    assert (
        summary["address_line"]
        == PHASE_7G_SYNTHETIC_ADDRESS_LINE_REDACTED
    )
    assert (
        summary["pincode_prefix"] == PHASE_7G_SYNTHETIC_PIN_PREFIX
    )
    assert summary["real_customer_data"] is False
    # Real customer phone keys must NEVER appear.
    assert "phone" not in summary
    assert "customer_phone" not in summary
    assert "address" not in summary
    assert "pincode" not in summary


@pytest.mark.django_db
def test_prepare_idempotent_on_same_phase7f_gate() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_idem"
    )
    with _phase7g_test_settings():
        a = prepare_phase7g_courier_execution_attempt(phase7f_gate.pk)
        b = prepare_phase7g_courier_execution_attempt(phase7f_gate.pk)
    assert a["created"] is True
    assert b["created"] is False
    assert b["reused"] is True
    assert RazorpayCourierExecutionAttempt.objects.count() == 1


@pytest.mark.django_db
def test_prepare_writes_prepared_audit_event() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_prep_audit"
    )
    AuditEvent.objects.filter(kind=AUDIT_KIND_PREPARED).delete()
    with _phase7g_test_settings():
        prepare_phase7g_courier_execution_attempt(phase7f_gate.pk)
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_PREPARED
    ).exists()


@pytest.mark.django_db
def test_prepare_does_not_create_shipment_or_workflow_rows() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_prep_no_ship"
    )
    before = _row_counts()
    with _phase7g_test_settings():
        prepare_phase7g_courier_execution_attempt(phase7f_gate.pk)
    after = _row_counts()
    assert before == after


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_approve_refuses_without_reason() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_appr_no_reason"
    )
    with _phase7g_test_settings():
        prepared = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
        out = approve_phase7g_courier_execution_attempt(
            prepared["attempt"]["id"], reason=""
        )
    assert out["ok"] is False


@pytest.mark.django_db
def test_approve_refuses_when_lifecycle_flag_off() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_appr_no_flag"
    )
    with _phase7g_test_settings():
        prepared = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    out = approve_phase7g_courier_execution_attempt(
        prepared["attempt"]["id"],
        reason="Director sign-off Phase 7G approve fixture",
    )
    assert out["ok"] is False
    assert any(
        "PHASE7G_COURIER_EXECUTION_ENABLED_must_be_true" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_approve_succeeds_with_reason() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_appr_ok"
    )
    AuditEvent.objects.filter(
        kind=AUDIT_KIND_APPROVED_FOR_ONE_SHOT
    ).delete()
    with _phase7g_test_settings():
        prepared = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
        out = approve_phase7g_courier_execution_attempt(
            prepared["attempt"]["id"],
            reason="Director sign-off Phase 7G approve fixture",
        )
    assert out["ok"] is True
    assert (
        out["attempt"]["status"]
        == "approved_for_one_shot_courier_test_or_live_review"
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_APPROVED_FOR_ONE_SHOT
    ).exists()


@pytest.mark.django_db
def test_reject_succeeds_with_reason_and_writes_audit() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_reject"
    )
    AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).delete()
    with _phase7g_test_settings():
        prepared = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
        out = reject_phase7g_courier_execution_attempt(
            prepared["attempt"]["id"],
            reason="Director sign-off Phase 7G reject",
        )
    assert out["ok"] is True
    assert out["attempt"]["status"] == "rejected"
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_REJECTED
    ).exists()


@pytest.mark.django_db
def test_reject_refuses_without_reason() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_reject_no_reason"
    )
    with _phase7g_test_settings():
        prepared = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    out = reject_phase7g_courier_execution_attempt(
        prepared["attempt"]["id"], reason=""
    )
    assert out["ok"] is False


# ---------------------------------------------------------------------------
# Execute - all gating refused
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_execute_refuses_without_lifecycle_flag() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_no_flag"
    )
    out = execute_phase7g_courier_one_shot(
        attempt.pk,
        director_signoff=_signoff_text(
            attempt.source_phase7f_gate_id
        ),
        operator_name="Prarit Sidana",
        mode_acknowledgement="mock",
        confirm_one_shot_courier_execution=True,
        rollback_record_only_acknowledged=True,
    )
    assert out["ok"] is False
    assert any(
        "PHASE7G_COURIER_EXECUTION_ENABLED_must_be_true" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_without_director_approved_flag() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_no_dir"
    )
    with _phase7g_execute_settings(
        PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION=False,
    ):
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    assert out["ok"] is False
    assert any(
        "PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_without_allow_test_awb_flag() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_no_allow"
    )
    with _phase7g_execute_settings(
        PHASE7G_ALLOW_DELHIVERY_TEST_AWB=False,
    ):
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    assert out["ok"] is False
    assert any(
        "PHASE7G_ALLOW_DELHIVERY_TEST_AWB" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_with_empty_director_signoff() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_no_sign"
    )
    with _phase7g_execute_settings():
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff="",
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    assert out["ok"] is False
    assert any(
        "director_signoff_must_be_non_empty" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_when_signoff_does_not_mention_gate_id() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_bad_sign"
    )
    with _phase7g_execute_settings():
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff="Some unrelated sign-off text",
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    assert out["ok"] is False
    assert any(
        "director_signoff_must_mention_phase7f_gate_id" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_with_empty_operator_name() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_no_op"
    )
    with _phase7g_execute_settings():
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    assert out["ok"] is False
    assert any(
        "operator_name_must_be_non_empty" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_when_mode_ack_does_not_match() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_mode_ack"
    )
    with _phase7g_execute_settings(DELHIVERY_MODE="mock"):
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="test",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    assert out["ok"] is False
    assert any(
        "mode_acknowledgement_must_match_live_DELHIVERY_MODE" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_without_one_shot_confirmation() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_no_conf"
    )
    with _phase7g_execute_settings():
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=False,
            rollback_record_only_acknowledged=True,
        )
    assert out["ok"] is False
    assert any(
        "confirm_one_shot_courier_execution_must_be_true" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_without_rollback_record_ack() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_no_rb"
    )
    with _phase7g_execute_settings():
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=False,
        )
    assert out["ok"] is False
    assert any(
        "rollback_record_only_acknowledged_must_be_true" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_when_delhivery_mode_live() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_live_mode"
    )
    with _phase7g_execute_settings(DELHIVERY_MODE="live"):
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="live",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    assert out["ok"] is False
    assert any(
        "DELHIVERY_MODE_must_be_mock_or_test" in b
        for b in out["blockers"]
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_MODE_BLOCKED
    ).exists()


@pytest.mark.django_db
def test_execute_refuses_when_kill_switch_disabled() -> None:
    from apps.saas.models import RuntimeKillSwitch

    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_kill_off"
    )
    kill, _ = RuntimeKillSwitch.objects.get_or_create(
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        provider_type="",
        operation_type="",
    )
    kill.enabled = False
    kill.save()
    try:
        with _phase7g_execute_settings():
            out = execute_phase7g_courier_one_shot(
                attempt.pk,
                director_signoff=_signoff_text(
                    attempt.source_phase7f_gate_id
                ),
                operator_name="Prarit Sidana",
                mode_acknowledgement="mock",
                confirm_one_shot_courier_execution=True,
                rollback_record_only_acknowledged=True,
            )
    finally:
        kill.enabled = True
        kill.save()
    assert out["ok"] is False
    assert any(
        "runtime_kill_switch_disabled" in b for b in out["blockers"]
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_KILL_SWITCH_BLOCKED
    ).exists()


# ---------------------------------------------------------------------------
# Execute - happy path with mocked Delhivery wrapper
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_execute_happy_path_records_awb_and_no_business_mutation() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_ok"
    )
    AuditEvent.objects.filter(kind=AUDIT_KIND_EXECUTED).delete()
    before = _row_counts()
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper",
        return_value={
            "awb": "DLH12345678",
            "status": "Pickup Scheduled",
            "tracking_url": "https://delhivery.example/track/DLH12345678",
        },
    ) as patched:
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    after = _row_counts()
    assert out["ok"] is True, out.get("blockers")
    patched.assert_called_once()
    row = RazorpayCourierExecutionAttempt.objects.get(pk=attempt.pk)
    assert row.status == RazorpayCourierExecutionAttempt.Status.EXECUTED
    assert row.provider_call_attempted is True
    assert row.delhivery_call_attempted is True
    assert row.awb_created is True
    assert row.provider_object_id == "DLH12345678"
    # Locked-False stays False.
    assert row.shipment_created is False
    assert row.business_mutation_was_made is False
    assert row.real_order_mutation_was_made is False
    assert row.real_payment_mutation_was_made is False
    assert row.real_shipment_mutation_was_made is False
    assert row.customer_notification_sent is False
    # No Shipment / WorkflowStep / RescueAttempt rows created.
    assert before == after
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_EXECUTED
    ).exists()


@pytest.mark.django_db
def test_execute_records_idempotency_lock_and_safe_response_only() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_idem"
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper",
        return_value={
            "awb": "DLH99999999",
            "status": "Pickup Scheduled",
            "tracking_url": "https://delhivery.example/track/DLH99999999",
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
    row = RazorpayCourierExecutionAttempt.objects.get(pk=attempt.pk)
    assert row.idempotency_lock_acquired is True
    # Safe response summary contains only awb / status / tracking_url.
    assert set(row.safe_response_summary.keys()) == {
        "awb",
        "status",
        "tracking_url",
    }


@pytest.mark.django_db
def test_execute_rejects_second_attempt_on_same_attempt_id() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_dup"
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper",
        return_value={
            "awb": "DLH11111111",
            "status": "Pickup Scheduled",
            "tracking_url": "https://delhivery.example/track/DLH11111111",
        },
    ):
        first = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
        second = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    assert first["ok"] is True
    assert second["ok"] is False
    assert any(
        "phase7g_attempt_already_executed_idempotency_lock" in b
        for b in second["blockers"]
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_DUPLICATE_BLOCKED
    ).exists()


@pytest.mark.django_db
def test_execute_marks_failed_when_wrapper_raises() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_fail"
    )
    AuditEvent.objects.filter(kind=AUDIT_KIND_FAILED).delete()
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper",
        side_effect=Phase7GExecutionError("Delhivery client error"),
    ):
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_text(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    assert out["ok"] is False
    row = RazorpayCourierExecutionAttempt.objects.get(pk=attempt.pk)
    assert row.status == RazorpayCourierExecutionAttempt.Status.FAILED
    # provider_call_attempted still True - the audit + idempotency
    # lock must persist even on SDK failure.
    assert row.provider_call_attempted is True
    assert row.delhivery_call_attempted is True
    # No AWB granted on failure.
    assert row.awb_created is False
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_FAILED
    ).exists()


@pytest.mark.django_db
def test_execute_wrapper_called_at_most_once() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_exec_one_call"
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper",
        return_value={
            "awb": "DLH22222222",
            "status": "Pickup Scheduled",
            "tracking_url": "https://delhivery.example/track/DLH22222222",
        },
    ) as patched:
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
    assert patched.call_count == 1


@pytest.mark.django_db
def test_execute_payload_contains_only_synthetic_data() -> None:
    """The payload passed to the wrapper carries only synthetic data,
    NEVER real customer phone / address / pincode strings."""
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_payload_synth"
    )
    captured: dict[str, dict] = {}

    def fake_wrapper(payload: dict) -> dict:
        captured["payload"] = payload
        return {
            "awb": "DLHFAKE0000",
            "status": "Pickup Scheduled",
            "tracking_url": "https://delhivery.example/track/DLHFAKE0000",
        }

    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper",
        side_effect=fake_wrapper,
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
    payload = captured["payload"]
    assert (
        payload["customer_name"]
        == PHASE_7G_SYNTHETIC_CUSTOMER_NAME
    )
    assert (
        payload["customer_phone_last4"]
        == PHASE_7G_SYNTHETIC_PHONE_LAST4
    )
    assert (
        payload["address_line"]
        == PHASE_7G_SYNTHETIC_ADDRESS_LINE_REDACTED
    )
    assert (
        payload["pincode_prefix"] == PHASE_7G_SYNTHETIC_PIN_PREFIX
    )
    assert payload["real_customer_data"] is False
    assert payload["internal_test_only"] is True
    assert "phone" not in payload
    assert "customer_phone" not in payload
    assert "address" not in payload
    assert "pincode" not in payload


# ---------------------------------------------------------------------------
# Rollback (record-only)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rollback_refuses_without_reason() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_rb_no_reason"
    )
    out = rollback_phase7g_courier_execution_attempt(
        attempt.pk, reason=""
    )
    assert out["ok"] is False


@pytest.mark.django_db
def test_rollback_records_only_no_provider_call() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_rb_record"
    )
    AuditEvent.objects.filter(kind=AUDIT_KIND_ROLLED_BACK).delete()
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper",
        return_value={
            "awb": "DLH33333333",
            "status": "Pickup Scheduled",
            "tracking_url": "https://delhivery.example/track/DLH33333333",
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
    out = rollback_phase7g_courier_execution_attempt(
        attempt.pk, reason="Director-directed rollback"
    )
    assert out["ok"] is True
    row = RazorpayCourierExecutionAttempt.objects.get(pk=attempt.pk)
    assert (
        row.status
        == RazorpayCourierExecutionAttempt.Status.ROLLED_BACK_RECORDED
    )
    assert (
        row.rollback_status
        == RazorpayCourierExecutionAttempt.RollbackStatus.RECORDED_ONLY_NO_PROVIDER_CANCEL
    )
    # The rollback record itself.
    record = RazorpayCourierExecutionRollback.objects.filter(
        attempt=row
    ).first()
    assert record is not None
    assert record.cancellation_attempted is False
    assert record.cancellation_attempted_by_command == ""
    assert record.provider_object_id_recorded == "DLH33333333"
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_ROLLED_BACK
    ).exists()


@pytest.mark.django_db
def test_rollback_status_never_takes_completed_value() -> None:
    """Phase 7G rollback never claims a Delhivery cancel happened."""
    statuses = {
        s.value
        for s in RazorpayCourierExecutionAttempt.RollbackStatus
    }
    assert "completed" not in statuses
    record_statuses = {
        s.value
        for s in RazorpayCourierExecutionRollback.Status
    }
    assert "completed" not in record_statuses


# ---------------------------------------------------------------------------
# Defensive guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_assert_guard_raises_on_flipped_business_mutation_boolean() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_guard_biz"
    )
    attempt.business_mutation_was_made = True
    attempt.save(update_fields=["business_mutation_was_made"])
    AuditEvent.objects.filter(
        kind=AUDIT_KIND_INVARIANT_VIOLATION
    ).delete()
    with pytest.raises(ValueError):
        assert_phase7g_no_unauthorised_mutation(attempt)
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_INVARIANT_VIOLATION
    ).exists()


@pytest.mark.django_db
def test_assert_guard_raises_on_flipped_shipment_created_boolean() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_guard_ship"
    )
    attempt.shipment_created = True
    attempt.save(update_fields=["shipment_created"])
    with pytest.raises(ValueError):
        assert_phase7g_no_unauthorised_mutation(attempt)


@pytest.mark.django_db
def test_assert_guard_passes_when_only_allowed_true_booleans_set() -> None:
    """awb_created / provider_call_attempted / delhivery_call_attempted
    are NOT in the locked-False list. They may be True after a
    successful execute.
    """
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_guard_allowed"
    )
    attempt.awb_created = True
    attempt.provider_call_attempted = True
    attempt.delhivery_call_attempted = True
    attempt.save()
    # Should not raise.
    assert_phase7g_no_unauthorised_mutation(attempt)


# ---------------------------------------------------------------------------
# Serializer + summary
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_serializer_never_returns_director_signoff_text() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_serial"
    )
    attempt.director_signoff_text = (
        "Director sign-off text that must NOT escape the API."
    )
    attempt.save(update_fields=["director_signoff_text"])
    payload = serialize_phase7g_attempt(attempt)
    # Verify presence-only flag is True, but the raw text is never
    # returned.
    assert payload["directorSignoffPresentBoolean"] is True
    forbidden = (
        "Director sign-off text that must NOT escape the API."
    )
    assert forbidden not in json.dumps(payload)


@pytest.mark.django_db
def test_summary_counts_safety_locked_at_zero_after_prepare() -> None:
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_summary"
    )
    with _phase7g_test_settings():
        prepare_phase7g_courier_execution_attempt(phase7f_gate.pk)
    summary = summarize_phase7g_attempts(limit=10)
    counts = summary["counts"]
    assert counts["pendingDirectorSignoff"] == 1
    assert counts["shipmentCreated"] == 0
    assert counts["businessMutationWasMade"] == 0
    assert counts["realOrderMutationWasMade"] == 0
    assert counts["realPaymentMutationWasMade"] == 0
    assert counts["realShipmentMutationWasMade"] == 0
    assert counts["customerNotificationSent"] == 0


# ---------------------------------------------------------------------------
# Endpoint detail / list / preview / rollbacks
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attempts_list_endpoint_admin_only(
    admin_user, viewer_user, client, auth_client
) -> None:
    url = reverse("saas-delhivery-courier-execution-attempts")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403
    assert auth_client(admin_user).get(url).status_code == 200


@pytest.mark.django_db
def test_attempt_detail_endpoint_returns_404_for_missing(
    admin_user, auth_client
) -> None:
    url = reverse(
        "saas-delhivery-courier-execution-attempt-detail",
        kwargs={"pk": 999_999},
    )
    res = auth_client(admin_user).get(url)
    assert res.status_code == 404


@pytest.mark.django_db
def test_attempt_detail_endpoint_returns_locked_false_booleans(
    admin_user, auth_client
) -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_detail"
    )
    url = reverse(
        "saas-delhivery-courier-execution-attempt-detail",
        kwargs={"pk": attempt.pk},
    )
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["shipmentCreated"] is False
    assert body["businessMutationWasMade"] is False
    assert body["realOrderMutationWasMade"] is False
    assert body["realPaymentMutationWasMade"] is False
    assert body["realShipmentMutationWasMade"] is False
    assert body["customerNotificationSent"] is False


@pytest.mark.django_db
def test_rollbacks_endpoint_returns_404_for_missing_attempt(
    admin_user, auth_client
) -> None:
    url = reverse(
        "saas-delhivery-courier-execution-rollbacks",
        kwargs={"attempt_id": 999_999},
    )
    res = auth_client(admin_user).get(url)
    assert res.status_code == 404


@pytest.mark.django_db
def test_attempts_list_endpoint_returns_phase7g_safety_keys(
    admin_user, auth_client
) -> None:
    url = reverse("saas-delhivery-courier-execution-attempts")
    res = auth_client(admin_user).get(url)
    body = res.json()
    assert body["phase"] == "7G"
    for key in (
        "phase7GCallsDelhivery",
        "phase7GCreatesShipmentRow",
        "phase7GBooksCourierPickupSeparately",
        "phase7GGeneratesCourierLabel",
        "phase7GSendsWhatsApp",
        "phase7GQueuesWhatsApp",
        "phase7GCallsMetaCloud",
        "phase7GCallsRazorpay",
        "phase7GCallsVapi",
        "phase7GSendsCustomerNotification",
        "phase7GMutatesBusinessRow",
        "phase7GLiveCustomerCourierApproved",
    ):
        assert body[key] is False
    assert body["phase7GCreatesAwbRowOnAttemptOnly"] is True


# ---------------------------------------------------------------------------
# Audit payload scrubbing
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_audit_event_carries_forbidden_payload_keys() -> None:
    """No Phase 7G audit ever surfaces a token / phone / address /
    raw_secret / verify_token key."""
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_audit_scrub"
    )
    with _phase7g_test_settings():
        prepared = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
        approve_phase7g_courier_execution_attempt(
            prepared["attempt"]["id"],
            reason="Director sign-off Phase 7G approve fixture",
        )
    forbidden_keys = (
        "token",
        "phone",
        "customer_phone",
        "address",
        "address_line",
        "pincode",
        "DELHIVERY_API_TOKEN",
        "META_WA_TOKEN",
        "RAZORPAY_KEY_SECRET",
        "raw_payload",
        "raw_signature",
        "raw_secret",
    )
    qs = AuditEvent.objects.filter(
        kind__startswith="razorpay.courier_execution."
    )
    assert qs.exists()
    for evt in qs:
        payload = evt.payload or {}
        for key in forbidden_keys:
            assert key not in payload, (
                f"Phase 7G audit {evt.kind} carried forbidden key "
                f"{key}"
            )


# ---------------------------------------------------------------------------
# Inspect-readiness selector
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_inspect_readiness_returns_blockers_when_attempt_was_mutated() -> None:
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_readiness_blocked"
    )
    attempt.business_mutation_was_made = True
    attempt.save(update_fields=["business_mutation_was_made"])
    out = inspect_phase7g_courier_execution_readiness()
    assert any(
        "businessMutationWasMade" in b for b in out["blockers"]
    )


# ---------------------------------------------------------------------------
# Phase 7G-Hotfix-1 - Structured UTC Window Guard
#
# Every refusal in this block must complete BEFORE the lazy
# `_create_awb_via_dedicated_wrapper` import + call. The wrapper is
# patched as a `MagicMock` and asserted `assert_not_called` so a
# false-positive that accidentally reaches the network would fail
# the test deterministically.
#
# No real Delhivery call. No AWB. No Shipment row. No business
# mutation. No customer notification. No `.env` edit.
# ---------------------------------------------------------------------------


def _signoff_without_markers(phase7f_gate_id: int) -> str:
    """Free-text-only sign-off; mentions the gate id but has no
    BEGIN_UTC / END_UTC markers."""
    return (
        f"Director sign-off for Phase 7G one-shot courier "
        f"execution against Phase 7F gate {phase7f_gate_id}. "
        f"This is a free-text only signature."
    )


def _signoff_malformed_timestamp(phase7f_gate_id: int) -> str:
    """Malformed BEGIN_UTC / END_UTC values (no trailing 'Z',
    invalid ISO)."""
    return (
        f"Director sign-off for Phase 7G one-shot courier "
        f"execution against Phase 7F gate {phase7f_gate_id}. "
        f"BEGIN_UTC=2026-13-99T99:99:99 END_UTC=not-a-timestamp"
    )


@pytest.mark.django_db
def test_hotfix1_execute_refuses_when_signoff_has_no_structured_markers() -> (
    None
):
    """Free-text-only signoff is refused before the wrapper."""
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_hf1_no_markers"
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper"
    ) as patched:
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_without_markers(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    patched.assert_not_called()
    assert out["ok"] is False
    assert any(
        "phase7g_director_signoff_missing_structured_utc_window" in b
        for b in out["blockers"]
    )
    row = RazorpayCourierExecutionAttempt.objects.get(pk=attempt.pk)
    assert row.provider_call_attempted is False
    assert row.delhivery_call_attempted is False
    assert row.awb_created is False
    assert row.shipment_created is False
    assert row.business_mutation_was_made is False
    assert row.customer_notification_sent is False


@pytest.mark.django_db
def test_hotfix1_execute_refuses_when_signoff_timestamps_are_malformed() -> (
    None
):
    """Malformed BEGIN_UTC / END_UTC -> parser returns None ->
    refusal before the wrapper."""
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_hf1_malformed"
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper"
    ) as patched:
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_malformed_timestamp(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    patched.assert_not_called()
    assert out["ok"] is False
    assert any(
        "phase7g_director_signoff_missing_structured_utc_window" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_hotfix1_execute_refuses_when_now_before_window_start() -> None:
    """now < BEGIN_UTC -> refusal before the wrapper."""
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_hf1_now_before"
    )
    # Window opens 10 minutes in the future, closes 13 minutes in
    # the future (a valid 3-min window, but `now` is before start).
    signoff = _structured_signoff(
        attempt.source_phase7f_gate_id,
        begin_offset_seconds=600,
        end_offset_seconds=780,
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper"
    ) as patched:
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=signoff,
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    patched.assert_not_called()
    assert out["ok"] is False
    assert any(
        "phase7g_now_before_director_signoff_utc_window_start" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_hotfix1_execute_refuses_when_now_after_window_end() -> None:
    """now > END_UTC -> refusal before the wrapper."""
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_hf1_now_after"
    )
    # Window opened 10 minutes ago, closed 5 minutes ago.
    signoff = _structured_signoff(
        attempt.source_phase7f_gate_id,
        begin_offset_seconds=-600,
        end_offset_seconds=-300,
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper"
    ) as patched:
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=signoff,
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    patched.assert_not_called()
    assert out["ok"] is False
    assert any(
        "phase7g_now_after_director_signoff_utc_window_end" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_hotfix1_execute_refuses_when_window_longer_than_15_minutes() -> (
    None
):
    """window_end - window_start > 15 min -> refusal before the
    wrapper. Use a 16-minute window centered on now."""
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_hf1_too_long"
    )
    signoff = _structured_signoff(
        attempt.source_phase7f_gate_id,
        begin_offset_seconds=-2 * 60,
        end_offset_seconds=14 * 60,
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper"
    ) as patched:
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=signoff,
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    patched.assert_not_called()
    assert out["ok"] is False
    assert any(
        "phase7g_director_signoff_window_too_long_max_15_min" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_hotfix1_execute_refuses_when_window_is_stale_past_24h() -> None:
    """window_start more than 24h before now -> refusal before the
    wrapper."""
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_hf1_stale"
    )
    # Window opened 25 hours ago, closed 24h59m ago.
    signoff = _structured_signoff(
        attempt.source_phase7f_gate_id,
        begin_offset_seconds=-25 * 60 * 60,
        end_offset_seconds=-(24 * 60 * 60 + 59 * 60),
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper"
    ) as patched:
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=signoff,
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    patched.assert_not_called()
    assert out["ok"] is False
    assert any(
        "phase7g_director_signoff_window_stale_more_than_24h_old" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_hotfix1_execute_refuses_when_window_end_before_start() -> None:
    """END_UTC <= BEGIN_UTC -> refusal before the wrapper."""
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_hf1_end_before_start"
    )
    signoff = _structured_signoff(
        attempt.source_phase7f_gate_id,
        begin_offset_seconds=120,
        end_offset_seconds=-120,
    )
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper"
    ) as patched:
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=signoff,
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    patched.assert_not_called()
    assert out["ok"] is False
    assert any(
        "phase7g_director_signoff_malformed_structured_utc_window" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_hotfix1_execute_valid_window_reaches_wrapper_and_persists_fields() -> (
    None
):
    """Valid Hotfix-1 window dispatches to the (mocked) wrapper and
    persists `recorded_signoff_window_*` fields on the attempt row.

    Asserts (in addition to the hotfix-1 specifics) that NO
    Shipment / WorkflowStep / RescueAttempt / WhatsAppMessage row
    is created and every locked-False boolean stays False.
    """
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_hf1_valid_window"
    )
    signoff = _structured_signoff(
        attempt.source_phase7f_gate_id,
        begin_offset_seconds=-60,
        end_offset_seconds=120,
    )
    before = _row_counts()
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper",
        return_value={
            "awb": "DLH00112233",
            "status": "Pickup Scheduled",
            "tracking_url": "https://delhivery.example/track/DLH00112233",
        },
    ) as patched:
        out = execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=signoff,
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    after = _row_counts()
    patched.assert_called_once()
    assert out["ok"] is True, out.get("blockers")

    row = RazorpayCourierExecutionAttempt.objects.get(pk=attempt.pk)
    assert row.recorded_signoff_window_valid is True
    assert row.recorded_signoff_window_start_utc is not None
    assert row.recorded_signoff_window_end_utc is not None
    assert (
        row.recorded_signoff_window_end_utc
        > row.recorded_signoff_window_start_utc
    )
    # Phase 7G "no Shipment" invariant - business + send + courier
    # row counts unchanged, locked-False booleans still False.
    assert before == after
    assert row.shipment_created is False
    assert row.business_mutation_was_made is False
    assert row.real_order_mutation_was_made is False
    assert row.real_payment_mutation_was_made is False
    assert row.real_shipment_mutation_was_made is False
    assert row.customer_notification_sent is False
    # Allowed-True booleans are now True.
    assert row.provider_call_attempted is True
    assert row.delhivery_call_attempted is True
    assert row.awb_created is True


@pytest.mark.django_db
def test_hotfix1_window_refusal_records_attempt_blocked_no_provider_call() -> (
    None
):
    """A window-refusal must persist the attempt as `blocked`,
    leave provider_call_attempted=False, and emit no `executed`
    audit row."""
    attempt = _make_approved_phase7g_attempt(
        source_event_id="evt_phase7g_hf1_blocked_state"
    )
    AuditEvent.objects.filter(kind=AUDIT_KIND_EXECUTED).delete()
    with _phase7g_execute_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper"
    ) as patched:
        execute_phase7g_courier_one_shot(
            attempt.pk,
            director_signoff=_signoff_without_markers(
                attempt.source_phase7f_gate_id
            ),
            operator_name="Prarit Sidana",
            mode_acknowledgement="mock",
            confirm_one_shot_courier_execution=True,
            rollback_record_only_acknowledged=True,
        )
    patched.assert_not_called()
    row = RazorpayCourierExecutionAttempt.objects.get(pk=attempt.pk)
    assert (
        row.status
        == RazorpayCourierExecutionAttempt.Status.BLOCKED
    )
    assert row.provider_call_attempted is False
    assert row.delhivery_call_attempted is False
    assert row.awb_created is False
    assert (
        AuditEvent.objects.filter(kind=AUDIT_KIND_EXECUTED).exists()
        is False
    )


def test_hotfix1_service_module_imports_window_helpers_at_top_level() -> None:
    """Static-file scan: the service module must import
    `parse_director_signoff_window` and
    `validate_within_director_window` from `apps.saas.utc_window`
    at the top level, NOT lazily."""
    src_path = importlib.import_module(
        "apps.payments.razorpay_courier_execution"
    ).__file__
    with open(src_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    assert (
        "from apps.saas.utc_window import" in text
    ), "Phase 7G must import the UTC window helpers."
    assert "parse_director_signoff_window" in text
    assert "validate_within_director_window" in text


def test_hotfix1_command_help_text_mentions_begin_utc_end_utc() -> None:
    """The CLI help text must teach operators about BEGIN_UTC /
    END_UTC and the 15-minute cap."""
    src_path = importlib.import_module(
        "apps.payments.management.commands."
        "execute_delhivery_courier_one_shot"
    ).__file__
    with open(src_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    assert "BEGIN_UTC" in text
    assert "END_UTC" in text
    assert "15 minutes" in text or "15-minute" in text or (
        "<= 15" in text
    )


# ---------------------------------------------------------------------------
# Phase 7G-Hotfix-2 - Safe Retry after Pre-Window Block
#
# When `execute_delhivery_courier_one_shot` refuses an attempt
# before the lazy Delhivery wrapper runs (e.g. Hotfix-1 window
# guard hit, kill switch off, mode mismatch), the attempt ends up
# in `rolled_back_recorded` state but every provider / business /
# send boolean stayed False. Hotfix-2 lets the operator
# `prepare_delhivery_courier_execution_attempt --gate-id <ID>`
# again and get a FRESH retry attempt row instead of the original
# terminal row.
#
# Any attempt that actually called Delhivery (provider_call_attempted
# = True) - even if it failed - is NEVER auto-retried; manual
# review is required so the on-call operator can decide whether
# the AWB landed.
# ---------------------------------------------------------------------------


def _force_into_rolled_back_pre_window_state(
    attempt: RazorpayCourierExecutionAttempt,
) -> None:
    """Drop the attempt into the post-Hotfix-1 pre-window-blocked
    terminal state: `rolled_back_recorded` with every provider /
    business / send boolean still False and `executed_at` unset.
    Mirrors Phase 7G VPS attempt id 1 exactly.
    """
    attempt.status = (
        RazorpayCourierExecutionAttempt.Status.ROLLED_BACK_RECORDED
    )
    attempt.rollback_status = (
        RazorpayCourierExecutionAttempt.RollbackStatus.RECORDED_ONLY_NO_PROVIDER_CANCEL
    )
    attempt.executed_at = None
    attempt.provider_call_attempted = False
    attempt.delhivery_call_attempted = False
    attempt.awb_created = False
    attempt.shipment_created = False
    attempt.business_mutation_was_made = False
    attempt.real_order_mutation_was_made = False
    attempt.real_payment_mutation_was_made = False
    attempt.real_shipment_mutation_was_made = False
    attempt.customer_notification_sent = False
    attempt.save()


@pytest.mark.django_db
def test_hotfix2_retry_eligible_terminal_creates_fresh_attempt() -> None:
    """Latest attempt rolled_back_recorded + zero provider/business
    impact -> prepare returns a NEW attempt with a retry-suffixed
    idempotency key. Original row stays immutable."""
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_hf2_retry_ok"
    )
    AuditEvent.objects.filter(
        kind=AUDIT_KIND_RETRY_PREPARED
    ).delete()
    with _phase7g_test_settings():
        first = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    assert first["created"] is True
    original_id = first["attempt"]["id"]
    original_row = RazorpayCourierExecutionAttempt.objects.get(
        pk=original_id
    )
    _force_into_rolled_back_pre_window_state(original_row)
    original_idem = original_row.idempotency_key

    before = _row_counts()
    with _phase7g_test_settings():
        retry = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    after = _row_counts()

    assert retry["created"] is True
    assert retry["reused"] is False
    assert retry["retry"] is True
    assert retry["retrySequence"] == 2
    assert retry["previousAttemptId"] == original_id

    retry_id = retry["attempt"]["id"]
    assert retry_id != original_id
    retry_row = RazorpayCourierExecutionAttempt.objects.get(
        pk=retry_id
    )
    assert (
        retry_row.idempotency_key
        == f"phase7g::courier_execution::phase7f_gate::{phase7f_gate.pk}::retry::2"
    )
    assert retry_row.idempotency_key != original_idem
    assert (
        retry_row.status
        == RazorpayCourierExecutionAttempt.Status.PENDING_DIRECTOR_SIGNOFF
    )

    # Original row is untouched.
    refreshed_original = RazorpayCourierExecutionAttempt.objects.get(
        pk=original_id
    )
    assert (
        refreshed_original.status
        == RazorpayCourierExecutionAttempt.Status.ROLLED_BACK_RECORDED
    )
    assert refreshed_original.idempotency_key == original_idem

    # Phase 7G safety invariants: no Delhivery call, no AWB, no
    # Shipment / WorkflowStep / RescueAttempt / WhatsApp row, no
    # business mutation.
    assert before == after
    assert retry_row.provider_call_attempted is False
    assert retry_row.delhivery_call_attempted is False
    assert retry_row.awb_created is False
    assert retry_row.shipment_created is False
    assert retry_row.business_mutation_was_made is False
    assert retry_row.real_order_mutation_was_made is False
    assert retry_row.real_payment_mutation_was_made is False
    assert retry_row.real_shipment_mutation_was_made is False
    assert retry_row.customer_notification_sent is False

    # Hotfix-2 emits `retry_prepared` (not the original
    # `attempt_prepared`).
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_RETRY_PREPARED
    ).exists()


@pytest.mark.django_db
def test_hotfix2_retry_prepared_audit_kind_within_length_budget() -> None:
    """`razorpay.courier_execution.retry_prepared` must respect the
    Phase 6T-hotfix audit-kind length budget."""
    assert AUDIT_KIND_RETRY_PREPARED.startswith(
        "razorpay.courier_execution."
    )
    assert len(AUDIT_KIND_RETRY_PREPARED) <= 64


@pytest.mark.django_db
def test_hotfix2_terminal_attempt_with_provider_call_does_not_auto_retry() -> (
    None
):
    """If `provider_call_attempted=True` on the terminal row, prepare
    MUST NOT mint a new retry attempt - the original row is reused and
    flagged for manual review."""
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_hf2_provider_touched"
    )
    with _phase7g_test_settings():
        first = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    original_id = first["attempt"]["id"]
    original = RazorpayCourierExecutionAttempt.objects.get(
        pk=original_id
    )
    # Simulate a real Hotfix-1 *post*-wrapper failure: provider call
    # WAS made, then attempt was rolled back.
    original.status = (
        RazorpayCourierExecutionAttempt.Status.ROLLED_BACK_RECORDED
    )
    original.rollback_status = (
        RazorpayCourierExecutionAttempt.RollbackStatus.RECORDED_ONLY_NO_PROVIDER_CANCEL
    )
    original.provider_call_attempted = True
    original.delhivery_call_attempted = True
    original.executed_at = None
    original.save()

    with _phase7g_test_settings():
        out = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    assert out["created"] is False
    assert out["reused"] is True
    assert out["attempt"]["id"] == original_id
    assert (
        out["nextAction"]
        == "phase7g_attempt_terminal_manual_review_required"
    )
    # Exactly one attempt row exists for this gate.
    assert (
        RazorpayCourierExecutionAttempt.objects.filter(
            source_phase7f_gate=phase7f_gate
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_hotfix2_executed_attempt_does_not_auto_retry() -> None:
    """Successfully executed attempts never auto-retry."""
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_hf2_executed_no_retry"
    )
    with _phase7g_test_settings():
        first = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    original_id = first["attempt"]["id"]
    original = RazorpayCourierExecutionAttempt.objects.get(
        pk=original_id
    )
    original.status = (
        RazorpayCourierExecutionAttempt.Status.EXECUTED
    )
    original.provider_call_attempted = True
    original.delhivery_call_attempted = True
    original.awb_created = True
    original.executed_at = mock.MagicMock()  # any truthy datetime-like
    # Use a real datetime to keep ORM happy.
    from datetime import datetime, timezone as _tz

    original.executed_at = datetime.now(tz=_tz.utc)
    original.save()

    with _phase7g_test_settings():
        out = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    assert out["created"] is False
    assert out["reused"] is True
    assert out["attempt"]["id"] == original_id
    assert (
        out["nextAction"]
        == "phase7g_attempt_terminal_manual_review_required"
    )


@pytest.mark.django_db
def test_hotfix2_failed_attempt_is_safe_and_not_auto_retried() -> None:
    """`failed` attempts (post-wrapper failure path) are terminal but
    were already past the wrapper - manual review only."""
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_hf2_failed_no_retry"
    )
    with _phase7g_test_settings():
        first = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    original_id = first["attempt"]["id"]
    original = RazorpayCourierExecutionAttempt.objects.get(
        pk=original_id
    )
    original.status = (
        RazorpayCourierExecutionAttempt.Status.FAILED
    )
    original.provider_call_attempted = True
    original.delhivery_call_attempted = True
    original.save()

    with _phase7g_test_settings():
        out = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    assert out["created"] is False
    assert out["reused"] is True
    assert out["attempt"]["id"] == original_id
    assert (
        out["nextAction"]
        == "phase7g_attempt_terminal_manual_review_required"
    )
    # Confirm Phase 7G never silently flipped any safety boolean.
    refreshed = RazorpayCourierExecutionAttempt.objects.get(
        pk=original_id
    )
    assert refreshed.shipment_created is False
    assert refreshed.business_mutation_was_made is False
    assert refreshed.customer_notification_sent is False


@pytest.mark.django_db
def test_hotfix2_retry_does_not_call_delhivery_wrapper() -> None:
    """The retry path is a database-only operation. The lazy
    `_create_awb_via_dedicated_wrapper` must NEVER be called by
    prepare - asserted with a `MagicMock.assert_not_called` spy."""
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_hf2_no_wrapper"
    )
    with _phase7g_test_settings():
        first = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    original = RazorpayCourierExecutionAttempt.objects.get(
        pk=first["attempt"]["id"]
    )
    _force_into_rolled_back_pre_window_state(original)

    with _phase7g_test_settings(), mock.patch(
        "apps.payments.razorpay_courier_execution._create_awb_via_dedicated_wrapper"
    ) as patched:
        retry = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    patched.assert_not_called()
    assert retry["retry"] is True
    assert retry["retrySequence"] == 2


@pytest.mark.django_db
def test_hotfix2_pending_attempt_is_reused_not_retried() -> None:
    """A pending-director-signoff attempt is still actionable, so
    prepare reuses it instead of minting a new retry."""
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_hf2_pending_reuse"
    )
    with _phase7g_test_settings():
        first = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
        second = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert (
        second["attempt"]["id"] == first["attempt"]["id"]
    )
    assert "retry" not in second or second.get("retry") is not True


@pytest.mark.django_db
def test_hotfix2_retry_sequence_increments_when_retry_blocked_again() -> (
    None
):
    """A chain of pre-window-blocked retries keeps incrementing the
    retry sequence (2, 3, ...). Every row stays immutable. The
    third retry uses ``::retry::3``."""
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_hf2_chain"
    )
    with _phase7g_test_settings():
        original_out = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    original = RazorpayCourierExecutionAttempt.objects.get(
        pk=original_out["attempt"]["id"]
    )
    _force_into_rolled_back_pre_window_state(original)

    with _phase7g_test_settings():
        retry_1 = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    assert retry_1["retrySequence"] == 2
    retry_1_row = RazorpayCourierExecutionAttempt.objects.get(
        pk=retry_1["attempt"]["id"]
    )
    _force_into_rolled_back_pre_window_state(retry_1_row)

    with _phase7g_test_settings():
        retry_2 = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    assert retry_2["retrySequence"] == 3
    retry_2_row = RazorpayCourierExecutionAttempt.objects.get(
        pk=retry_2["attempt"]["id"]
    )
    assert (
        retry_2_row.idempotency_key
        == f"phase7g::courier_execution::phase7f_gate::{phase7f_gate.pk}::retry::3"
    )
    assert (
        RazorpayCourierExecutionAttempt.objects.filter(
            source_phase7f_gate=phase7f_gate
        ).count()
        == 3
    )


@pytest.mark.django_db
def test_hotfix2_retry_attempt_emits_safe_audit_payload_only() -> None:
    """The `retry_prepared` audit payload must NEVER carry tokens /
    phones / addresses / raw secrets."""
    phase7f_gate = _make_approved_phase7f_gate(
        source_event_id="evt_phase7g_hf2_audit_payload"
    )
    with _phase7g_test_settings():
        first = prepare_phase7g_courier_execution_attempt(
            phase7f_gate.pk
        )
    _force_into_rolled_back_pre_window_state(
        RazorpayCourierExecutionAttempt.objects.get(
            pk=first["attempt"]["id"]
        )
    )
    AuditEvent.objects.filter(
        kind=AUDIT_KIND_RETRY_PREPARED
    ).delete()
    with _phase7g_test_settings():
        prepare_phase7g_courier_execution_attempt(phase7f_gate.pk)

    forbidden_keys = (
        "token",
        "phone",
        "customer_phone",
        "address",
        "address_line",
        "pincode",
        "DELHIVERY_API_TOKEN",
        "META_WA_TOKEN",
        "RAZORPAY_KEY_SECRET",
        "raw_payload",
        "raw_signature",
        "raw_secret",
    )
    evt = AuditEvent.objects.filter(
        kind=AUDIT_KIND_RETRY_PREPARED
    ).first()
    assert evt is not None
    for key in forbidden_keys:
        assert key not in (evt.payload or {}), (
            f"retry_prepared audit carried forbidden key {key}"
        )
    # Retry-specific diagnostics are present.
    assert (evt.payload or {}).get("retry_sequence") == 2
    assert (
        (evt.payload or {}).get("previous_attempt_id")
        == first["attempt"]["id"]
    )
