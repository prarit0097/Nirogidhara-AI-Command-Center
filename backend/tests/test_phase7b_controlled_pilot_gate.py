"""Phase 7B - Controlled Pilot Execution Gate (gate-only) tests.

Asserts every Phase 7B safety requirement:

1.  Readiness command returns Phase 7B shape.
2.  Readiness endpoint returns Phase 7B shape.
3.  GET endpoints require auth + admin.
4.  POST/PATCH/PUT/DELETE return 405 on every Phase 7B endpoint.
5.  Preview never creates rows.
6.  Prepare blocked when PHASE7_CONTROLLED_PILOT_GATE_ENABLED=false.
7.  Prepare succeeds with env override + eligible locked Phase 6T chain.
8.  Prepare does not validate current ``RAZORPAY_KEY_ID``.
9.  Invalid / live / blank ``RAZORPAY_KEY_ID`` does not block Phase 7B.
10. Razorpay key never appears raw in any Phase 7B output.
11. Prepare blocked when Phase 6T lock status != ``locked_for_future_controlled_pilot_review``.
12. Prepare blocked when Phase 6T ``future_execution_allowed_by_phase6t=true``.
13. Prepare blocked when Phase 6T ``controlled_pilot_execution_allowed_in_phase6t=true``.
14. Prepare blocked when any Phase 6S -> 6M ancestor is missing.
15. Prepare blocked when any ancestor safety boolean is true.
16. Prepare is idempotent for the same Phase 6T lock.
17. Dry-run writes a ``DryRunRecord`` only.
18. Dry-run flips ``dry_run_passed`` only on full chain pass.
19. Rollback dry-run writes a ``RollbackDryRunRecord`` only.
20. Rollback dry-run flips ``rollback_dry_run_passed`` only on clean rehearsal.
21. Approve refuses without non-empty reason.
22. Approve refuses without ``dry_run_passed=true``.
23. Approve refuses without ``rollback_dry_run_passed=true``.
24. Approve flips status to ``approved_for_future_phase7c_execution_review`` only.
25. Reject / archive flip status only.
26. Provider client methods ``assert_not_called`` across full lifecycle.
27. No Order / Payment / Shipment / DiscountOfferLog / Customer / Lead mutation.
28. No outbound WhatsAppMessage row.
29. No WhatsAppLifecycleEvent row.
30. No Razorpay API call.
31. No Meta Cloud API call.
32. No Delhivery API call.
33. No customer notification.
34. No raw secret / PII in command / API / audit output.
35. Every Phase 7B audit kind ``len <= 64``.
36. AuditEvent payload forbidden keys absent.
37. ``RuntimeKillSwitch`` disabled / unexpected env-flag flip blocks rollback dry-run.
38. No ``execute_*`` function / command / API exists.
39. No Phase 7C module / function / flag is added.
40. API responses never expose raw ``RAZORPAY_KEY_ID`` / secret.
41. ``amount_paise > 100`` in source chain blocks prepare.
42. Source ``provider_environment != test`` blocks prepare.
43. Second approve refused.
44. Multiple dry-run records may stack safely.
45. Multiple rollback dry-run records may stack safely.
46. Defensive guard raises on any flipped locked-False boolean.
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
    RazorpayControlledPilotExecutionGate,
    RazorpayControlledPilotGateDryRunRecord,
    RazorpayControlledPilotGateRollbackDryRunRecord,
    RazorpayPhase6FinalAuditLock,
)
from apps.payments.razorpay_controlled_pilot_gate import (
    AUDIT_KIND_APPROVED_FOR_PHASE7C_REVIEW,
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_DRY_RUN_FAILED,
    AUDIT_KIND_DRY_RUN_PASSED,
    AUDIT_KIND_INVARIANT_VIOLATION,
    AUDIT_KIND_KILL_SWITCH_DISABLED_BLOCKED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    AUDIT_KIND_ROLLBACK_DRY_RUN_FAILED,
    AUDIT_KIND_ROLLBACK_DRY_RUN_PASSED,
    PHASE_7B_FORBIDDEN_ACTIONS,
    PHASE_7B_FORBIDDEN_PAYLOAD_KEYS,
    PHASE_7B_MAX_SAFE_AMOUNT_PAISE,
    approve_phase7b_controlled_pilot_gate,
    archive_phase7b_controlled_pilot_gate,
    assert_phase7b_no_unauthorised_provider_call,
    build_phase7b_controlled_pilot_gate_contract,
    dry_run_phase7b_controlled_pilot_gate,
    inspect_phase7b_controlled_pilot_gate_readiness,
    prepare_phase7b_controlled_pilot_gate,
    preview_phase7b_controlled_pilot_gate,
    reject_phase7b_controlled_pilot_gate,
    rollback_dry_run_phase7b_controlled_pilot_gate,
    summarize_phase7b_controlled_pilot_gates,
)
from apps.payments.razorpay_phase6_final_audit_lock import (
    lock_phase6t_final_audit_record,
    prepare_phase6t_final_audit_lock,
)
from apps.shipments.models import Shipment
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from tests.test_phase6t_final_audit_lock import _make_approved_phase6s_plan


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
        "phase6t_final_audit_lock": (
            RazorpayPhase6FinalAuditLock.objects.count()
        ),
        "phase7b_controlled_pilot_gate": (
            RazorpayControlledPilotExecutionGate.objects.count()
        ),
        "phase7b_dry_run_record": (
            RazorpayControlledPilotGateDryRunRecord.objects.count()
        ),
        "phase7b_rollback_dry_run_record": (
            RazorpayControlledPilotGateRollbackDryRunRecord.objects.count()
        ),
    }


def _make_locked_phase6t_lock(
    *, source_event_id: str = "evt_phase7b_full"
) -> RazorpayPhase6FinalAuditLock:
    """Walk an event through 6N->6T and lock the Phase 6T row."""
    plan = _make_approved_phase6s_plan(source_event_id=source_event_id)
    with override_settings(RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED=True):
        prepared = prepare_phase6t_final_audit_lock(plan.pk)
        lock_id = prepared["auditLock"]["id"]
        lock_phase6t_final_audit_record(
            lock_id, reason="Phase 6T lock for Phase 7B test"
        )
    return RazorpayPhase6FinalAuditLock.objects.get(pk=lock_id)


# ---------------------------------------------------------------------------
# Contract + audit-kind length (#35)
# ---------------------------------------------------------------------------


def test_contract_locks_execution_off_in_phase7b() -> None:
    contract = build_phase7b_controlled_pilot_gate_contract()
    assert contract["phase"] == "7B"
    assert contract["status"] == "controlled_pilot_gate_only"
    assert contract["controlledPilotExecutionAllowedInPhase7B"] is False
    assert contract["liveExecutionAllowedInPhase7B"] is False
    assert contract["providerCallAllowedInPhase7B"] is False
    assert contract["businessMutationAllowedInPhase7B"] is False
    assert contract["customerNotificationAllowedInPhase7B"] is False
    assert contract["whatsappSendAllowedInPhase7B"] is False
    assert contract["whatsappQueueAllowedInPhase7B"] is False
    assert contract["courierBookingAllowedInPhase7B"] is False
    assert contract["shipmentCreationAllowedInPhase7B"] is False
    assert contract["awbCreationAllowedInPhase7B"] is False
    assert contract["frontendExecutionAllowedInPhase7B"] is False
    assert contract["apiExecutionAllowedInPhase7B"] is False
    assert contract["razorpayKeyValidationDeferredToPhase7COrLater"] is True


def test_phase7b_audit_kinds_within_length_budget() -> None:
    audit_kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_DRY_RUN_PASSED,
        AUDIT_KIND_DRY_RUN_FAILED,
        AUDIT_KIND_ROLLBACK_DRY_RUN_PASSED,
        AUDIT_KIND_ROLLBACK_DRY_RUN_FAILED,
        AUDIT_KIND_APPROVED_FOR_PHASE7C_REVIEW,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
        AUDIT_KIND_KILL_SWITCH_DISABLED_BLOCKED,
        AUDIT_KIND_INVARIANT_VIOLATION,
    ]
    for kind in audit_kinds:
        assert kind.startswith("razorpay.controlled_pilot_gate.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_forbidden_actions_includes_critical_paths() -> None:
    expected = {
        "execute_pilot",
        "start_pilot",
        "run_pilot",
        "send_whatsapp_template",
        "queue_whatsapp_outbound",
        "call_meta_cloud_api",
        "call_delhivery_api",
        "create_shipment",
        "create_awb",
        "book_courier_pickup",
        "place_vapi_call",
        "call_razorpay_api",
        "create_payment_link",
        "capture_razorpay_payment",
        "refund_razorpay_payment",
        "mutate_real_order_status",
        "mutate_real_payment_status",
        "mutate_real_customer",
        "mutate_real_lead",
        "execute_pilot_via_frontend",
        "execute_pilot_via_api_endpoint",
        "approve_pilot_via_api_endpoint",
    }
    assert expected.issubset(set(PHASE_7B_FORBIDDEN_ACTIONS))


# ---------------------------------------------------------------------------
# Readiness command + endpoint shape (#1, #2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_command_returns_phase7b_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_razorpay_controlled_pilot_gate_readiness",
        "--json",
        "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "7B"
    assert body["status"] == "controlled_pilot_gate_only"
    assert body["latestCompletedPhase"] == "6T"
    assert body["nextPhase"] == "7C_not_approved"
    assert body["phase7ControlledPilotGateEnabled"] is False
    assert body["phase7BMakesProviderCall"] is False
    assert body["phase7BSendsOrQueuesWhatsApp"] is False
    assert body["phase7BCreatesShipmentOrAwb"] is False
    assert body["phase7BMutatesBusinessRow"] is False
    assert body["phase7BCallsRazorpay"] is False
    assert body["phase7BValidatesLiveRazorpayKey"] is False
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["safeToStartPhase7CExecutionReviewFlow"] is False
    assert len(body["forbiddenActions"]) >= 20


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase7b_shape(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-controlled-pilot-gate-readiness")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "7B"
    assert body["status"] == "controlled_pilot_gate_only"
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["apiEndpointCanApprove"] is False
    assert body["phase7BMakesProviderCall"] is False
    assert body["phase7BValidatesLiveRazorpayKey"] is False


@pytest.mark.django_db
def test_readiness_endpoint_requires_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse("saas-razorpay-controlled-pilot-gate-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


# ---------------------------------------------------------------------------
# POST/PATCH/PUT/DELETE return 405 (#4)
# ---------------------------------------------------------------------------


_PHASE_7B_GET_ENDPOINTS = (
    ("saas-razorpay-controlled-pilot-gate-readiness", None),
    ("saas-razorpay-controlled-pilot-gates", None),
    ("saas-razorpay-controlled-pilot-gate-preview", "?phase6t_lock_id=1"),
)


@pytest.mark.django_db
@pytest.mark.parametrize("name,query", _PHASE_7B_GET_ENDPOINTS)
def test_phase7b_endpoints_reject_non_get_methods(
    name, query, admin_user, auth_client
) -> None:
    url = reverse(name)
    if query:
        url = url + query
    client = auth_client(admin_user)
    for method in ("post", "patch", "put", "delete"):
        res = getattr(client, method)(url, {})
        assert res.status_code == 405, f"{method} {name} -> {res.status_code}"


@pytest.mark.django_db
def test_phase7b_dry_runs_endpoints_reject_non_get_methods(
    admin_user, auth_client
) -> None:
    url_dry = reverse(
        "saas-razorpay-controlled-pilot-gate-dry-runs",
        kwargs={"gate_id": 1},
    )
    url_rb = reverse(
        "saas-razorpay-controlled-pilot-gate-rollback-dry-runs",
        kwargs={"gate_id": 1},
    )
    client = auth_client(admin_user)
    for url in (url_dry, url_rb):
        for method in ("post", "patch", "put", "delete"):
            assert getattr(client, method)(url, {}).status_code == 405


# ---------------------------------------------------------------------------
# Preview never creates rows (#5)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_never_creates_rows() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_preview")
    before = _row_counts()
    out = preview_phase7b_controlled_pilot_gate(lock.pk)
    after = _row_counts()
    assert out["found"] is True
    assert (
        before["phase7b_controlled_pilot_gate"]
        == after["phase7b_controlled_pilot_gate"]
    )
    assert before["phase7b_dry_run_record"] == after["phase7b_dry_run_record"]


# ---------------------------------------------------------------------------
# Prepare gating (#6, #7, #8, #9, #10, #11, #12, #13, #14, #15, #16, #41, #42)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_blocked_when_env_flag_off() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_no_flag")
    out = prepare_phase7b_controlled_pilot_gate(lock.pk)
    assert out["created"] is False
    assert any(
        "PHASE7_CONTROLLED_PILOT_GATE_ENABLED" in b for b in out["blockers"]
    )
    assert RazorpayControlledPilotExecutionGate.objects.count() == 0


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_prepare_succeeds_with_locked_phase6t_chain() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_ok")
    out = prepare_phase7b_controlled_pilot_gate(lock.pk)
    assert out["created"] is True
    gate = out["gate"]
    assert (
        gate["status"]
        == RazorpayControlledPilotExecutionGate.Status.PENDING_MANUAL_REVIEW
    )
    assert gate["controlledPilotExecutionAllowedInPhase7B"] is False
    assert gate["liveExecutionAllowedInPhase7B"] is False
    assert gate["providerCallAllowedInPhase7B"] is False
    assert gate["businessMutationAllowedInPhase7B"] is False
    assert gate["whatsAppSendAllowedInPhase7B"] is False
    assert gate["courierBookingAllowedInPhase7B"] is False
    assert gate["shipmentCreationAllowedInPhase7B"] is False
    assert gate["awbCreationAllowedInPhase7B"] is False
    assert gate["frontendExecutionAllowedInPhase7B"] is False
    assert gate["apiExecutionAllowedInPhase7B"] is False
    assert gate["realOrderMutationWasMade"] is False
    assert gate["realPaymentMutationWasMade"] is False
    assert gate["whatsAppMessageCreated"] is False
    assert gate["whatsAppMessageQueued"] is False
    assert gate["customerNotificationSent"] is False
    assert gate["metaCloudCallAttempted"] is False
    assert gate["delhiveryCallAttempted"] is False
    assert gate["razorpayCallAttempted"] is False
    assert gate["providerCallAttempted"] is False
    assert gate["dryRunPassed"] is False
    assert gate["rollbackDryRunPassed"] is False
    assert gate["fullChainVerified"] is True


@pytest.mark.django_db
@override_settings(
    PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True,
    RAZORPAY_KEY_ID="rzp_live_PLANTED_LIVE_KEY_DO_NOT_LEAK",
)
def test_prepare_does_not_validate_live_razorpay_key_and_does_not_leak() -> None:
    """Phase 7B must accept any key (live, blank, garbage) because it
    makes no provider call. The raw key must never appear in any
    output. Provider-execution key validation belongs to Phase 7C+.
    """
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_keyguard")
    out = prepare_phase7b_controlled_pilot_gate(lock.pk)
    assert out["created"] is True
    blob = json.dumps(out, default=str)
    assert "rzp_live_PLANTED_LIVE_KEY_DO_NOT_LEAK" not in blob
    readiness_blob = json.dumps(
        inspect_phase7b_controlled_pilot_gate_readiness(), default=str
    )
    assert "rzp_live_PLANTED_LIVE_KEY_DO_NOT_LEAK" not in readiness_blob
    summary_blob = json.dumps(
        summarize_phase7b_controlled_pilot_gates(), default=str
    )
    assert "rzp_live_PLANTED_LIVE_KEY_DO_NOT_LEAK" not in summary_blob


@pytest.mark.django_db
@override_settings(
    PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True, RAZORPAY_KEY_ID=""
)
def test_prepare_does_not_block_on_blank_razorpay_key() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_blank_key")
    out = prepare_phase7b_controlled_pilot_gate(lock.pk)
    assert out["created"] is True


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_prepare_blocked_when_phase6t_status_not_locked() -> None:
    plan = _make_approved_phase6s_plan(source_event_id="evt_phase7b_pending")
    with override_settings(RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED=True):
        prepared = prepare_phase6t_final_audit_lock(plan.pk)
    # NOT locked; still PENDING_MANUAL_REVIEW
    out = prepare_phase7b_controlled_pilot_gate(prepared["auditLock"]["id"])
    assert out["created"] is False
    assert any(
        "phase_6t_lock_status_must_be_locked_for_future_controlled_pilot_review"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_prepare_blocked_if_phase6t_future_execution_allowed_true() -> None:
    lock = _make_locked_phase6t_lock(
        source_event_id="evt_phase7b_future_exec_true"
    )
    lock.future_execution_allowed_by_phase6t = True
    lock.save(update_fields=["future_execution_allowed_by_phase6t"])
    out = prepare_phase7b_controlled_pilot_gate(lock.pk)
    assert out["created"] is False
    assert (
        "phase_6t_lock_future_execution_allowed_by_phase6t_must_be_false"
        in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_prepare_blocked_if_phase6t_controlled_pilot_execution_allowed() -> None:
    lock = _make_locked_phase6t_lock(
        source_event_id="evt_phase7b_pilot_exec_true"
    )
    lock.controlled_pilot_execution_allowed_in_phase6t = True
    lock.save(
        update_fields=["controlled_pilot_execution_allowed_in_phase6t"]
    )
    out = prepare_phase7b_controlled_pilot_gate(lock.pk)
    assert out["created"] is False
    assert (
        "phase_6t_lock_controlled_pilot_execution_allowed_in_phase6t_must_be_false"
        in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_prepare_blocked_if_phase6t_safety_boolean_flipped() -> None:
    lock = _make_locked_phase6t_lock(
        source_event_id="evt_phase7b_safety_flip"
    )
    lock.real_order_mutation_was_made = True
    lock.save(update_fields=["real_order_mutation_was_made"])
    out = prepare_phase7b_controlled_pilot_gate(lock.pk)
    assert out["created"] is False
    assert (
        "phase_6t_lock_real_order_mutation_was_made_must_be_false"
        in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_prepare_blocked_when_phase6t_lock_not_found() -> None:
    out = prepare_phase7b_controlled_pilot_gate(99999)
    assert out["created"] is False
    assert "phase_6t_source_final_audit_lock_not_found" in out["blockers"]


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_prepare_blocked_when_amount_too_high() -> None:
    lock = _make_locked_phase6t_lock(
        source_event_id="evt_phase7b_amount_high"
    )
    if lock.source_event_record:
        lock.source_event_record.amount_paise = 200
        lock.source_event_record.save(update_fields=["amount_paise"])
    out = prepare_phase7b_controlled_pilot_gate(lock.pk)
    assert out["created"] is False
    assert any("amount_paise_must_be_<=" in b for b in out["blockers"])


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_prepare_blocked_when_event_environment_not_test() -> None:
    lock = _make_locked_phase6t_lock(
        source_event_id="evt_phase7b_env_not_test"
    )
    if lock.source_event_record:
        # Use any non-TEST value the model allows; choices are TEST/LIVE.
        lock.source_event_record.environment = "live"
        lock.source_event_record.save(update_fields=["environment"])
    out = prepare_phase7b_controlled_pilot_gate(lock.pk)
    assert out["created"] is False
    assert any(
        "phase_6m_event_environment_must_be_test" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_prepare_is_idempotent_per_lock() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_idem")
    first = prepare_phase7b_controlled_pilot_gate(lock.pk)
    second = prepare_phase7b_controlled_pilot_gate(lock.pk)
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert first["gate"]["id"] == second["gate"]["id"]


# ---------------------------------------------------------------------------
# Dry-run + rollback dry-run (#17, #18, #19, #20, #37, #44, #45)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_dry_run_writes_record_only_and_flips_flag_on_pass() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_dryrun")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    before = _row_counts()
    out = dry_run_phase7b_controlled_pilot_gate(gate_id)
    after = _row_counts()
    assert out["ok"] is True
    assert (
        after["phase7b_dry_run_record"]
        == before["phase7b_dry_run_record"] + 1
    )
    assert (
        after["phase7b_controlled_pilot_gate"]
        == before["phase7b_controlled_pilot_gate"]
    )
    gate = RazorpayControlledPilotExecutionGate.objects.get(pk=gate_id)
    assert gate.dry_run_passed is True


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_dry_run_does_not_flip_flag_on_chain_failure() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_dryfail")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    # break the chain by archiving the source pilot plan via status
    lock.real_order_mutation_was_made = True
    lock.save(update_fields=["real_order_mutation_was_made"])
    out = dry_run_phase7b_controlled_pilot_gate(gate_id)
    assert out["ok"] is False
    gate = RazorpayControlledPilotExecutionGate.objects.get(pk=gate_id)
    assert gate.dry_run_passed is False
    assert gate.status == (
        RazorpayControlledPilotExecutionGate.Status.BLOCKED
    )


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_dry_run_records_can_stack() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_stack")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    dry_run_phase7b_controlled_pilot_gate(gate_id)
    dry_run_phase7b_controlled_pilot_gate(gate_id)
    dry_run_phase7b_controlled_pilot_gate(gate_id)
    count = RazorpayControlledPilotGateDryRunRecord.objects.filter(
        gate_id=gate_id
    ).count()
    assert count == 3


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_rollback_dry_run_writes_record_and_passes_when_env_clean() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_rb_ok")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    out = rollback_dry_run_phase7b_controlled_pilot_gate(
        gate_id, reason="rehearsal"
    )
    assert out["ok"] is True
    gate = RazorpayControlledPilotExecutionGate.objects.get(pk=gate_id)
    assert gate.rollback_dry_run_passed is True


@pytest.mark.django_db
@override_settings(
    PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
)
def test_rollback_dry_run_blocks_when_unexpected_flag_true() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_rb_block")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    out = rollback_dry_run_phase7b_controlled_pilot_gate(
        gate_id, reason="rehearsal"
    )
    assert out["ok"] is False
    assert any(
        "WHATSAPP_AI_AUTO_REPLY_ENABLED" in b for b in out["blockers"]
    )
    gate = RazorpayControlledPilotExecutionGate.objects.get(pk=gate_id)
    assert gate.rollback_dry_run_passed is False


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_rollback_dry_run_records_can_stack() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_rb_stack")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    rollback_dry_run_phase7b_controlled_pilot_gate(gate_id, reason="r1")
    rollback_dry_run_phase7b_controlled_pilot_gate(gate_id, reason="r2")
    count = (
        RazorpayControlledPilotGateRollbackDryRunRecord.objects.filter(
            gate_id=gate_id
        ).count()
    )
    assert count == 2


# ---------------------------------------------------------------------------
# Approve / reject / archive (#21, #22, #23, #24, #25, #43)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_approve_refuses_without_reason() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_no_reason")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    dry_run_phase7b_controlled_pilot_gate(gate_id)
    rollback_dry_run_phase7b_controlled_pilot_gate(gate_id, reason="r")
    out = approve_phase7b_controlled_pilot_gate(gate_id, reason="")
    assert out["ok"] is False
    assert "manual_review_reason_must_be_non_empty" in out["blockers"]


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_approve_refuses_without_dry_run_passed() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_no_dry")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    out = approve_phase7b_controlled_pilot_gate(
        gate_id, reason="approve without dry-run"
    )
    assert out["ok"] is False
    assert "phase_7b_dry_run_required" in out["blockers"]


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_approve_refuses_without_rollback_dry_run_passed() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_no_rb")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    dry_run_phase7b_controlled_pilot_gate(gate_id)
    out = approve_phase7b_controlled_pilot_gate(
        gate_id, reason="approve missing rollback rehearsal"
    )
    assert out["ok"] is False
    assert "phase_7b_rollback_dry_run_required" in out["blockers"]


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_approve_status_advances_to_approved_for_future_phase7c_review() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_approve")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    dry_run_phase7b_controlled_pilot_gate(gate_id)
    rollback_dry_run_phase7b_controlled_pilot_gate(gate_id, reason="r")
    out = approve_phase7b_controlled_pilot_gate(
        gate_id, reason="Director sign-off for Phase 7B gate"
    )
    assert out["ok"] is True
    assert out["gate"]["status"] == (
        RazorpayControlledPilotExecutionGate.Status.APPROVED_FOR_FUTURE_PHASE7C_EXECUTION_REVIEW
    )


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_second_approve_refused() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_second")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    dry_run_phase7b_controlled_pilot_gate(gate_id)
    rollback_dry_run_phase7b_controlled_pilot_gate(gate_id, reason="r")
    first = approve_phase7b_controlled_pilot_gate(
        gate_id, reason="first approval"
    )
    assert first["ok"] is True
    second = approve_phase7b_controlled_pilot_gate(
        gate_id, reason="second approval"
    )
    assert second["ok"] is False


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_reject_changes_status_only() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_rej")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    out = reject_phase7b_controlled_pilot_gate(
        prepared["gate"]["id"], reason="not yet"
    )
    assert out["ok"] is True
    assert (
        out["gate"]["status"]
        == RazorpayControlledPilotExecutionGate.Status.REJECTED
    )


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_archive_changes_status_only() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_arc")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    out = archive_phase7b_controlled_pilot_gate(
        prepared["gate"]["id"], reason="close"
    )
    assert out["ok"] is True
    assert (
        out["gate"]["status"]
        == RazorpayControlledPilotExecutionGate.Status.ARCHIVED
    )


# ---------------------------------------------------------------------------
# Mutation safety + provider-call mocks (#26-#33)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_full_lifecycle_does_not_mutate_business_or_call_providers(
    seeded,
) -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_safe")
    before = _row_counts()
    with mock.patch(
        "apps.payments.integrations.razorpay_client.create_payment_link"
    ) as create_link, mock.patch(
        "apps.payments.integrations.razorpay_client.capture_payment",
        create=True,
    ) as capture, mock.patch(
        "apps.payments.integrations.razorpay_client.create_refund",
        create=True,
    ) as refund, mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as queue_template, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as send_text, mock.patch(
        "apps.calls.integrations.vapi_client.trigger_call",
        create=True,
    ) as vapi, mock.patch(
        "apps.shipments.integrations.delhivery_client.create_shipment",
        create=True,
    ) as delhivery_ship, mock.patch(
        "apps.shipments.integrations.delhivery_client.book_pickup",
        create=True,
    ) as delhivery_book:
        prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7b_controlled_pilot_gate(gate_id)
        rollback_dry_run_phase7b_controlled_pilot_gate(
            gate_id, reason="rehearsal"
        )
        approve_phase7b_controlled_pilot_gate(
            gate_id, reason="Director sign-off"
        )
        archive_phase7b_controlled_pilot_gate(gate_id, reason="close")

    create_link.assert_not_called()
    capture.assert_not_called()
    refund.assert_not_called()
    queue_template.assert_not_called()
    send_text.assert_not_called()
    vapi.assert_not_called()
    delhivery_ship.assert_not_called()
    delhivery_book.assert_not_called()

    after = _row_counts()
    for key in (
        "order",
        "payment",
        "shipment",
        "discount_offer_log",
        "customer",
        "lead",
        "whatsapp_message",
        "whatsapp_lifecycle_event",
        "whatsapp_handoff",
    ):
        assert after[key] == before[key], key


# ---------------------------------------------------------------------------
# Defensive guard (#46)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_assert_phase7b_no_unauthorised_provider_call_raises_on_flip() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_assert")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    row = RazorpayControlledPilotExecutionGate.objects.get(
        pk=prepared["gate"]["id"]
    )
    for field in (
        "controlled_pilot_execution_allowed_in_phase7b",
        "live_execution_allowed_in_phase7b",
        "provider_call_allowed_in_phase7b",
        "business_mutation_allowed_in_phase7b",
        "customer_notification_allowed_in_phase7b",
        "whatsapp_send_allowed_in_phase7b",
        "whatsapp_queue_allowed_in_phase7b",
        "courier_booking_allowed_in_phase7b",
        "shipment_creation_allowed_in_phase7b",
        "awb_creation_allowed_in_phase7b",
        "frontend_execution_allowed_in_phase7b",
        "api_execution_allowed_in_phase7b",
        "real_order_mutation_was_made",
        "real_payment_mutation_was_made",
        "shipment_mutation_was_made",
        "shipment_created",
        "awb_created",
        "whatsapp_message_created",
        "whatsapp_message_queued",
        "customer_notification_sent",
        "meta_cloud_call_attempted",
        "delhivery_call_attempted",
        "razorpay_call_attempted",
        "provider_call_attempted",
        "env_flag_flip_detected",
        "raw_secret_exposed",
        "full_pii_exposed",
    ):
        setattr(row, field, True)
        with pytest.raises(ValueError):
            assert_phase7b_no_unauthorised_provider_call(row)
        setattr(row, field, False)


# ---------------------------------------------------------------------------
# Output sanitization (#34, #36, #40)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True,
    RAZORPAY_KEY_ID="rzp_test_PHASE7B_PLANTED_KEYID_DO_NOT_LEAK",
    RAZORPAY_KEY_SECRET="PHASE7B_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
    RAZORPAY_WEBHOOK_SECRET="PHASE7B_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
)
def test_outputs_do_not_expose_planted_secrets() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_secret")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    blob = json.dumps(prepared, default=str)
    for planted in (
        "rzp_test_PHASE7B_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE7B_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE7B_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted

    readiness = inspect_phase7b_controlled_pilot_gate_readiness()
    blob = json.dumps(readiness, default=str)
    for planted in (
        "rzp_test_PHASE7B_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE7B_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE7B_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted


@pytest.mark.django_db
def test_output_does_not_leak_planted_pii() -> None:
    Customer.objects.create(
        name="Phase7B Planted Customer",
        phone="+919999777888",
        product_interest="weight-management",
    )
    readiness = inspect_phase7b_controlled_pilot_gate_readiness()
    blob = json.dumps(readiness, default=str)
    assert "+919999777888" not in blob
    assert "Phase7B Planted Customer" not in blob


@pytest.mark.django_db
@override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True)
def test_audit_payloads_do_not_carry_forbidden_keys() -> None:
    lock = _make_locked_phase6t_lock(source_event_id="evt_phase7b_audit")
    prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    dry_run_phase7b_controlled_pilot_gate(gate_id)
    rollback_dry_run_phase7b_controlled_pilot_gate(gate_id, reason="r")
    approve_phase7b_controlled_pilot_gate(
        gate_id, reason="Director sign-off"
    )

    for kind in (
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_DRY_RUN_PASSED,
        AUDIT_KIND_ROLLBACK_DRY_RUN_PASSED,
        AUDIT_KIND_APPROVED_FOR_PHASE7C_REVIEW,
    ):
        rows = AuditEvent.objects.filter(kind=kind)
        assert rows.exists(), kind
        for row in rows:
            payload = row.payload or {}
            for forbidden in PHASE_7B_FORBIDDEN_PAYLOAD_KEYS:
                assert forbidden not in payload, (kind, forbidden)
            assert (
                payload.get("controlled_pilot_execution_allowed_in_phase7b")
                is False
            )
            assert payload.get("provider_call_attempted") is False
            assert payload.get("real_order_mutation_was_made") is False
            assert payload.get("razorpay_call_attempted") is False
            assert payload.get("whatsapp_message_created") is False


# ---------------------------------------------------------------------------
# Phase 7C absence (#38, #39)
# ---------------------------------------------------------------------------


def test_no_execute_function_exists() -> None:
    module = importlib.import_module(
        "apps.payments.razorpay_controlled_pilot_gate"
    )
    public_attrs = [
        name
        for name in dir(module)
        if not name.startswith("_") and callable(getattr(module, name))
    ]
    for name in public_attrs:
        lower = name.lower()
        # Phase 7B may not ship anything that even smells like execute.
        assert "execute" not in lower, (
            f"Phase 7B module exposes forbidden callable: {name}"
        )


def test_no_phase7c_module_or_flag_added() -> None:
    with pytest.raises(ImportError):
        importlib.import_module(
            "apps.payments.razorpay_phase7c_pilot_execution"
        )
    from django.conf import settings as django_settings
    # Phase 7C flag must not be registered as a Django setting.
    assert not hasattr(django_settings, "PHASE7C_DIRECTOR_APPROVED_EXECUTION")


def test_no_execute_management_command_exists() -> None:
    """Phase 7B (gate-only) must not ship an execute command. Phase
    7D ships its own scoped `execute_razorpay_controlled_pilot_test_order`
    which is gated separately and is NOT a Phase 7B command - this
    test is intentionally scoped to the Phase 7B name pattern only.
    """
    from django.core.management import get_commands

    commands = get_commands()
    for cmd in commands:
        cmd_lower = cmd.lower()
        # Match only Phase 7B gate commands (suffix _pilot_gate or
        # _pilot_gates). Phase 7D commands use _pilot_execution_ /
        # _pilot_test_order_ which are not Phase 7B.
        if (
            "controlled_pilot_gate" in cmd_lower
            or cmd_lower.endswith("controlled_pilot_gates")
        ):
            assert "execute" not in cmd_lower, (
                f"Forbidden Phase 7B execute command exists: {cmd}"
            )
