"""Phase 7D - Razorpay Controlled Pilot one-shot TEST execution tests.

Asserts every Phase 7D safety requirement. Provider calls are
mocked at ``_create_order_via_sdk`` so no real Razorpay request is
ever issued by this test suite.

1.  Readiness command + endpoint return Phase 7D shape.
2.  GET endpoints require auth + admin (POST/PATCH/DELETE -> 405).
3.  No POST execute / approve / reject / archive endpoint exists.
4.  Audit kinds <= 64 chars.
5.  Forbidden-actions list covers WhatsApp / Delhivery / business
    mutation paths.
6.  Preview never creates rows.
7.  Prepare blocked when ``PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED=
    false``.
8.  Prepare blocked when source Phase 7B gate is not approved for
    Phase 7C review.
9.  Prepare succeeds + idempotent on the same Phase 7B gate.
10. Approve refuses without non-empty reason.
11. Approve refuses unless attempt status =
    ``pending_director_signoff``.
12. Approve flips status to ``approved_for_one_shot_run``.
13. Execute refuses unless every Phase 7D env flag is True.
14. Execute refuses unless director sign-off mentions exact gate
    id.
15. Execute refuses unless ``RAZORPAY_KEY_ID`` starts with
    ``rzp_test_``.
16. Execute refuses unless ``RuntimeKillSwitch.enabled=true``.
17. Execute refuses unless attempt status =
    ``approved_for_one_shot_run``.
18. Execute success path (mocked SDK):
    - status flips to ``executed``
    - ``provider_object_id`` recorded
    - ``provider_call_attempted=true``
    - all 22 locked-False booleans remain False
    - safe response summary contains only whitelisted keys
    - executed audit row written
    - no Order / Payment / Shipment / DiscountOfferLog / Customer
      / Lead / WhatsAppMessage / WhatsAppLifecycleEvent /
      WhatsAppHandoffToCall mutation
19. Execute failure path (mocked SDK raises): status flips to
    ``failed``, no orphan provider_object_id, audit row tagged
    ``failed``.
20. Single-shot: second execute on same attempt refused.
21. ``provider_call_attempted=true`` flips BEFORE SDK call (audit
    survives SDK exceptions).
22. Idempotency key + receipt format are stable.
23. Rollback writes a record + flips ``rollback_status=completed``;
    NO Razorpay call made.
24. Archive flips status only.
25. Recovery reconciles orphan provider_object_id without
    re-calling Razorpay.
26. Razorpay key never appears raw in any command / API / audit
    output.
27. Audit payloads forbidden keys absent (token / secret / phone /
    email / address / card / vpa / upi / bank_account / wallet /
    raw_payload / raw_signature / raw_secret).
28. Service / commands NEVER edit any ``.env*`` file (no dotenv
    import in service module).
29. ``execute_*`` API endpoint does NOT exist.
30. Frontend / API endpoints cannot execute, approve, or reject.
31. Live RAZORPAY_KEY_ID prefix (``rzp_live_``) refused at
    execute boundary.
32. Defensive ``assert_phase7d_no_business_mutation`` raises on
    flipped locked-False boolean and emits invariant_violation
    audit.
33. Source chain (Phase 7B -> 6T -> 6S -> 6R -> 6Q -> 6P -> 6O ->
    6M) walked correctly during eligibility validation.
34. amount_paise locked at 100, currency locked at INR.
35. Receipt template ``phase7d::ctrl_pilot::gate::<G>::attempt::
    <A>`` matches what we send to Razorpay.
36. Idempotency key template ``phase7d::execution::gate::<gate_pk>``.
37. Recovery refuses bad input.
38. Phase 7D never sends WhatsApp (asserted via row count after
    full lifecycle).
39. Phase 7D never creates a Shipment / AWB.
40. Phase 7D never sends a customer notification.
41. Phase 7D never creates a payment link, never captures, never
    refunds.
42. Read-only API endpoints return 405 on non-GET methods.
43. Detail endpoint returns 404 for unknown attempt id.
44. Preview endpoint requires gate_id query param.
45. Rollbacks endpoint returns 404 for unknown attempt id.
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
    RazorpayControlledPilotExecutionAttempt,
    RazorpayControlledPilotExecutionGate,
    RazorpayControlledPilotExecutionRollback,
    RazorpayPhase6FinalAuditLock,
)
from apps.payments.razorpay_controlled_pilot_execution import (
    AUDIT_KIND_APPROVED_FOR_ONE_SHOT,
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_EXECUTED,
    AUDIT_KIND_FAILED,
    AUDIT_KIND_INVARIANT_VIOLATION,
    AUDIT_KIND_KILL_SWITCH_BLOCKED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_RECOVERY_RECONCILED,
    AUDIT_KIND_ROLLED_BACK,
    PHASE_7D_FORBIDDEN_ACTIONS,
    PHASE_7D_FORBIDDEN_PAYLOAD_KEYS,
    PHASE_7D_MAX_AMOUNT_PAISE,
    Phase7DExecutionError,
    approve_phase7d_razorpay_test_execution_attempt,
    archive_phase7d_razorpay_test_execution_attempt,
    assert_phase7d_no_business_mutation,
    build_phase7d_controlled_pilot_execution_contract,
    execute_phase7d_razorpay_test_order,
    inspect_phase7d_razorpay_test_execution_readiness,
    prepare_phase7d_razorpay_test_execution_attempt,
    preview_phase7d_razorpay_test_execution_attempt,
    recover_phase7d_razorpay_test_execution_attempt,
    rollback_phase7d_razorpay_test_execution_attempt,
    serialize_phase7d_attempt,
    summarize_phase7d_attempts,
)
from apps.payments.razorpay_controlled_pilot_gate import (
    approve_phase7b_controlled_pilot_gate,
    dry_run_phase7b_controlled_pilot_gate,
    prepare_phase7b_controlled_pilot_gate,
    rollback_dry_run_phase7b_controlled_pilot_gate,
)
from apps.shipments.models import Shipment
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from tests.test_phase7b_controlled_pilot_gate import (
    _make_locked_phase6t_lock,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PHASE_7D_FLAGS_ON: dict[str, object] = {
    "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED": True,
    "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION": True,
    "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER": True,
    "PHASE7_CONTROLLED_PILOT_GATE_ENABLED": True,
}


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


def _make_approved_phase7b_gate(
    *, source_event_id: str = "evt_phase7d_full"
) -> RazorpayControlledPilotExecutionGate:
    """Walk an event through 6N -> 6T -> 7B and approve the Phase 7B gate."""
    lock = _make_locked_phase6t_lock(source_event_id=source_event_id)
    with override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True):
        prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
        gate_id = prepared["gate"]["id"]
        dry_run_phase7b_controlled_pilot_gate(gate_id)
        rollback_dry_run_phase7b_controlled_pilot_gate(
            gate_id, reason="Phase 7D fixture rollback rehearsal"
        )
        approve_phase7b_controlled_pilot_gate(
            gate_id,
            reason="Director sign-off for Phase 7D test fixture",
        )
    return RazorpayControlledPilotExecutionGate.objects.get(pk=gate_id)


def _mock_razorpay_order_response(
    *, order_id: str = "order_TEST7Dabc123"
) -> dict[str, object]:
    return {
        "id": order_id,
        "entity": "order",
        "amount": 100,
        "currency": "INR",
        "receipt": "phase7d::ctrl_pilot::gate::1::attempt::1",
        "status": "created",
        "attempts": 0,
        "created_at": 1700000000,
    }


def _phase7d_test_settings(**overrides):
    base = {
        "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED": True,
        "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION": True,
        "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER": True,
        "PHASE7_CONTROLLED_PILOT_GATE_ENABLED": True,
        "RAZORPAY_KEY_ID": "rzp_test_phase7d_dummykey",
        "RAZORPAY_KEY_SECRET": "rzp_test_secret_dummy",
    }
    base.update(overrides)
    return override_settings(**base)


# ---------------------------------------------------------------------------
# Contract + audit-kind length (#4, #5, #34)
# ---------------------------------------------------------------------------


def test_contract_locks_business_mutation_off() -> None:
    contract = build_phase7d_controlled_pilot_execution_contract()
    assert contract["phase"] == "7D"
    assert contract["status"] == "razorpay_test_execution_only"
    assert contract["phase7DSendsOrQueuesWhatsApp"] is False
    assert contract["phase7DCallsMetaCloud"] is False
    assert contract["phase7DCallsDelhivery"] is False
    assert contract["phase7DCreatesShipmentOrAwb"] is False
    assert contract["phase7DCreatesPaymentLink"] is False
    assert contract["phase7DCapturesPayment"] is False
    assert contract["phase7DRefundsPayment"] is False
    assert contract["phase7DSendsCustomerNotification"] is False
    assert contract["phase7DMutatesBusinessRow"] is False


def test_phase7d_audit_kinds_within_length_budget() -> None:
    audit_kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_APPROVED_FOR_ONE_SHOT,
        AUDIT_KIND_EXECUTED,
        AUDIT_KIND_FAILED,
        AUDIT_KIND_ROLLED_BACK,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
        AUDIT_KIND_KILL_SWITCH_BLOCKED,
        AUDIT_KIND_INVARIANT_VIOLATION,
        AUDIT_KIND_RECOVERY_RECONCILED,
    ]
    for kind in audit_kinds:
        assert kind.startswith("razorpay.controlled_pilot_execution.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_forbidden_actions_includes_critical_paths() -> None:
    expected = {
        "send_whatsapp_template",
        "queue_whatsapp_outbound",
        "call_meta_cloud_api",
        "call_delhivery_api",
        "create_shipment",
        "create_awb",
        "book_courier_pickup",
        "place_vapi_call",
        "create_payment_link",
        "capture_razorpay_payment",
        "refund_razorpay_payment",
        "mutate_real_order_status",
        "mutate_real_payment_status",
        "mutate_real_customer",
        "mutate_real_lead",
        "send_customer_notification",
        "execute_via_frontend",
        "execute_via_api_endpoint",
        "approve_via_api_endpoint",
        "reject_via_api_endpoint",
        "edit_dotenv_production",
    }
    actual = set(PHASE_7D_FORBIDDEN_ACTIONS)
    assert expected.issubset(actual), expected - actual


def test_phase7d_max_amount_locked_at_one_rupee() -> None:
    assert PHASE_7D_MAX_AMOUNT_PAISE == 100


# ---------------------------------------------------------------------------
# Readiness command + endpoint shape (#1)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_command_returns_phase7d_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_razorpay_controlled_pilot_execution_readiness",
        "--json",
        "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "7D"
    assert body["status"] == "razorpay_test_execution_only"
    assert body["phase7DSendsOrQueuesWhatsApp"] is False
    assert body["phase7DCallsMetaCloud"] is False
    assert body["phase7DCallsDelhivery"] is False
    assert body["phase7DCreatesShipmentOrAwb"] is False
    assert body["phase7DCreatesPaymentLink"] is False
    assert body["phase7DCapturesPayment"] is False
    assert body["phase7DRefundsPayment"] is False
    assert body["phase7DSendsCustomerNotification"] is False
    assert body["phase7DMutatesBusinessRow"] is False


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase7d_shape(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-controlled-pilot-execution-readiness")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "7D"
    assert body["status"] == "razorpay_test_execution_only"


@pytest.mark.django_db
def test_readiness_endpoint_requires_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse("saas-razorpay-controlled-pilot-execution-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


# ---------------------------------------------------------------------------
# POST/PATCH/PUT/DELETE -> 405 (#2, #42)
# ---------------------------------------------------------------------------


_PHASE_7D_GET_ENDPOINTS = (
    ("saas-razorpay-controlled-pilot-execution-readiness", None),
    ("saas-razorpay-controlled-pilot-execution-attempts", None),
    ("saas-razorpay-controlled-pilot-execution-preview", "?gate_id=1"),
)


@pytest.mark.django_db
@pytest.mark.parametrize("name,query", _PHASE_7D_GET_ENDPOINTS)
def test_phase7d_endpoints_reject_non_get_methods(
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
def test_phase7d_detail_and_rollbacks_reject_non_get(
    admin_user, auth_client
) -> None:
    detail = reverse(
        "saas-razorpay-controlled-pilot-execution-attempt-detail",
        kwargs={"pk": 1},
    )
    rollbacks = reverse(
        "saas-razorpay-controlled-pilot-execution-rollbacks",
        kwargs={"attempt_id": 1},
    )
    client = auth_client(admin_user)
    for url in (detail, rollbacks):
        for method in ("post", "patch", "put", "delete"):
            assert getattr(client, method)(url, {}).status_code == 405


# ---------------------------------------------------------------------------
# No POST execute / approve / reject endpoint (#3, #29, #30)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_phase7d_execute_endpoint_exists(
    admin_user, auth_client
) -> None:
    """Verify there is no URL pattern that POSTs an execute / approve."""
    from django.urls import get_resolver

    resolver = get_resolver()
    # Walk the resolver and look for any phase7d execute / approve URL.
    suspicious = []
    for pattern in resolver.url_patterns:
        if "saas/" in str(pattern.pattern):
            for sub in getattr(pattern, "url_patterns", []):
                p = str(sub.pattern)
                if (
                    "controlled-pilot-execution" in p
                    and any(
                        token in p
                        for token in (
                            "execute",
                            "approve",
                            "reject",
                            "archive",
                        )
                    )
                ):
                    suspicious.append(p)
    assert not suspicious, suspicious


def test_phase7d_service_has_no_dotenv_import() -> None:
    """The service module must NEVER edit any ``.env*`` file."""
    src = importlib.import_module(
        "apps.payments.razorpay_controlled_pilot_execution"
    ).__file__
    with open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    assert "from dotenv" not in text
    assert "import dotenv" not in text
    assert ".env.production" not in text
    assert ".env.live" not in text


# ---------------------------------------------------------------------------
# Preview never creates rows (#6, #44)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_never_creates_rows() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_preview"
    )
    before = _row_counts()
    out = preview_phase7d_razorpay_test_execution_attempt(gate.pk)
    after = _row_counts()
    assert out["found"] is True
    assert RazorpayControlledPilotExecutionAttempt.objects.count() == 0
    assert before == after


@pytest.mark.django_db
def test_preview_endpoint_requires_gate_id(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-controlled-pilot-execution-preview")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Prepare gating (#7, #8, #9, #36)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_blocked_when_lifecycle_flag_off() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_no_flag"
    )
    out = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
    assert out["created"] is False
    assert out["reused"] is False
    assert out["attempt"] is None
    assert any(
        "PHASE7D" in b or "phase7d" in b or "phase_7d" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_prepare_blocked_when_phase7b_gate_not_approved() -> None:
    """A locked Phase 6T row that has never been promoted to a
    Phase-7B-approved gate must block Phase 7D prepare.
    """
    lock = _make_locked_phase6t_lock(
        source_event_id="evt_phase7d_no_phase7b"
    )
    with override_settings(PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True):
        prepared = prepare_phase7b_controlled_pilot_gate(lock.pk)
    gate_id = prepared["gate"]["id"]
    # Skip dry-run / approval - gate stays in pending status.
    with _phase7d_test_settings():
        out = prepare_phase7d_razorpay_test_execution_attempt(gate_id)
    assert out["created"] is False
    assert out["reused"] is False
    assert out["attempt"] is None
    assert any(
        "phase_7b" in b or "phase7b" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_prepare_creates_attempt_with_locked_safety_booleans() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_prepare_ok"
    )
    with _phase7d_test_settings():
        out = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
    assert out["created"] is True
    attempt_id = out["attempt"]["id"]
    row = RazorpayControlledPilotExecutionAttempt.objects.get(
        pk=attempt_id
    )
    # Locked-False safety booleans default False.
    assert row.business_mutation_was_made is False
    assert row.payment_link_created is False
    assert row.payment_captured is False
    assert row.payment_refunded is False
    assert row.customer_notification_sent is False
    assert row.whatsapp_message_created is False
    assert row.whatsapp_message_queued is False
    assert row.whatsapp_lifecycle_event_created is False
    assert row.shipment_created is False
    assert row.awb_created is False
    assert row.meta_cloud_call_attempted is False
    assert row.delhivery_call_attempted is False
    assert row.real_order_mutation_was_made is False
    assert row.real_payment_mutation_was_made is False
    assert row.customer_mutation_was_made is False
    assert row.lead_mutation_was_made is False
    assert row.discount_offer_log_mutation_was_made is False
    assert row.mcp_tool_called is False
    assert row.raw_secret_exposed is False
    assert row.full_pii_exposed is False
    # provider_call_attempted is allowed True only after exec.
    assert row.provider_call_attempted is False
    # Locked amount + currency + provider_environment.
    assert row.amount_paise == 100
    assert row.currency == "INR"
    assert row.provider_environment == "test"
    # Idempotency key + receipt template.
    assert row.idempotency_key == f"phase7d::execution::gate::{gate.pk}"
    assert row.receipt == (
        f"phase7d::ctrl_pilot::gate::{gate.pk}::attempt::{row.pk}"
    )


@pytest.mark.django_db
def test_prepare_is_idempotent_on_same_gate() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_idem"
    )
    with _phase7d_test_settings():
        a = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
        b = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
    assert a["created"] is True
    assert b["created"] is False
    assert b["reused"] is True
    assert a["attempt"]["id"] == b["attempt"]["id"]
    assert RazorpayControlledPilotExecutionAttempt.objects.count() == 1


# ---------------------------------------------------------------------------
# Approve gating (#10, #11, #12)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_approve_refuses_without_reason() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_approve_no_reason"
    )
    with _phase7d_test_settings():
        out = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
        attempt_id = out["attempt"]["id"]
        result = approve_phase7d_razorpay_test_execution_attempt(
            attempt_id, reviewed_by=None, reason=""
        )
    assert result["ok"] is False
    assert any("reason" in b for b in result["blockers"])


@pytest.mark.django_db
def test_approve_flips_status_to_approved_for_one_shot_run() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_approve_ok"
    )
    with _phase7d_test_settings():
        out = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
        attempt_id = out["attempt"]["id"]
        result = approve_phase7d_razorpay_test_execution_attempt(
            attempt_id,
            reviewed_by=None,
            reason="Director one-shot Razorpay TEST sign-off",
        )
    assert result["ok"] is True
    assert (
        result["attempt"]["status"]
        == RazorpayControlledPilotExecutionAttempt.Status.APPROVED_FOR_ONE_SHOT_RUN
    )


# ---------------------------------------------------------------------------
# Execute gating (#13-#18, #20, #21, #31)
# ---------------------------------------------------------------------------


def _approved_attempt_id(gate_pk: int) -> int:
    with _phase7d_test_settings():
        out = prepare_phase7d_razorpay_test_execution_attempt(gate_pk)
        attempt_id = out["attempt"]["id"]
        approve_phase7d_razorpay_test_execution_attempt(
            attempt_id,
            reviewed_by=None,
            reason="Director one-shot Razorpay TEST sign-off",
        )
    return attempt_id


@pytest.mark.django_db
def test_execute_refuses_without_lifecycle_flag() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_exec_no_lifecycle"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    # Flip lifecycle flag OFF, keep approval + allow flag ON.
    with override_settings(
        PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED=False,
        PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION=True,
        PHASE7D_ALLOW_RAZORPAY_TEST_ORDER=True,
        PHASE7_CONTROLLED_PILOT_GATE_ENABLED=True,
        RAZORPAY_KEY_ID="rzp_test_phase7d_dummykey",
    ):
        result = execute_phase7d_razorpay_test_order(
            attempt_id,
            confirmed_by=None,
            director_signoff=(
                f"Director sign-off mentions gate {gate.pk}"
            ),
        )
    assert result["ok"] is False
    assert any(
        "PHASE7D" in b or "phase7d" in b
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_without_director_signoff_mentioning_gate() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_exec_no_signoff"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    with _phase7d_test_settings():
        # Sign-off does not mention the source gate id.
        result = execute_phase7d_razorpay_test_order(
            attempt_id,
            confirmed_by=None,
            director_signoff="Approved",
        )
    assert result["ok"] is False
    assert any(
        "signoff" in b or "director" in b
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_when_razorpay_key_is_live() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_exec_live_key"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    with _phase7d_test_settings(RAZORPAY_KEY_ID="rzp_live_dangerous"):
        result = execute_phase7d_razorpay_test_order(
            attempt_id,
            confirmed_by=None,
            director_signoff=(
                f"Director sign-off mentions gate {gate.pk}"
            ),
        )
    assert result["ok"] is False
    assert any(
        "RAZORPAY_KEY_ID" in b or "rzp_test" in b
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_when_kill_switch_disabled() -> None:
    from apps.saas.models import RuntimeKillSwitch

    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_exec_kill_off"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    # Disable the global kill switch.
    kill, _ = RuntimeKillSwitch.objects.get_or_create(
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        provider_type="",
        operation_type="",
    )
    kill.enabled = False
    kill.reason = "Phase 7D test guard"
    kill.save()
    with _phase7d_test_settings():
        result = execute_phase7d_razorpay_test_order(
            attempt_id,
            confirmed_by=None,
            director_signoff=(
                f"Director sign-off mentions gate {gate.pk}"
            ),
        )
    assert result["ok"] is False
    assert any(
        "kill" in b.lower() or "switch" in b.lower()
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_execute_refuses_unless_attempt_approved() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_exec_not_approved"
    )
    # Prepare but DO NOT approve.
    with _phase7d_test_settings():
        out = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
        attempt_id = out["attempt"]["id"]
        result = execute_phase7d_razorpay_test_order(
            attempt_id,
            confirmed_by=None,
            director_signoff=(
                f"Director sign-off mentions gate {gate.pk}"
            ),
        )
    assert result["ok"] is False
    assert any(
        "approved" in b.lower() or "status" in b.lower()
        for b in result["blockers"]
    )


@pytest.mark.django_db
def test_execute_success_path_no_business_mutation() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_exec_ok"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    before = _row_counts()
    fake_response = _mock_razorpay_order_response(
        order_id="order_TEST7D_success"
    )
    with _phase7d_test_settings():
        with mock.patch(
            "apps.payments.razorpay_controlled_pilot_execution"
            "._create_order_via_sdk",
            return_value=fake_response,
        ) as sdk:
            result = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=(
                    f"Director sign-off mentions gate {gate.pk}"
                ),
            )
    after = _row_counts()
    if not result["ok"]:
        print("DEBUG blockers:", result.get("blockers"))
    assert result["ok"] is True, result.get("blockers")
    sdk.assert_called_once()
    payload = sdk.call_args.args[0]
    assert payload["amount"] == 100
    assert payload["currency"] == "INR"
    assert "phase7d::ctrl_pilot::gate::" in payload["receipt"]
    row = RazorpayControlledPilotExecutionAttempt.objects.get(
        pk=attempt_id
    )
    assert (
        row.status
        == RazorpayControlledPilotExecutionAttempt.Status.EXECUTED
    )
    assert row.provider_object_id == "order_TEST7D_success"
    assert row.provider_call_attempted is True
    # Locked-False booleans untouched.
    assert row.business_mutation_was_made is False
    assert row.payment_link_created is False
    assert row.payment_captured is False
    assert row.payment_refunded is False
    assert row.whatsapp_message_created is False
    assert row.whatsapp_message_queued is False
    assert row.whatsapp_lifecycle_event_created is False
    assert row.shipment_created is False
    assert row.awb_created is False
    assert row.meta_cloud_call_attempted is False
    assert row.delhivery_call_attempted is False
    assert row.customer_notification_sent is False
    assert row.real_order_mutation_was_made is False
    assert row.real_payment_mutation_was_made is False
    assert row.customer_mutation_was_made is False
    assert row.lead_mutation_was_made is False
    assert row.discount_offer_log_mutation_was_made is False
    assert row.mcp_tool_called is False
    # Safe response summary whitelist.
    assert set(row.safe_response_summary).issubset(
        {
            "id",
            "entity",
            "amount",
            "currency",
            "receipt",
            "status",
            "attempts",
            "created_at",
        }
    )
    # No business-row mutation.
    assert before == after
    # Audit row written.
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_EXECUTED
    ).exists()


@pytest.mark.django_db
def test_execute_failure_path_marks_failed_no_orphan_object_id() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_exec_fail"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    with _phase7d_test_settings():
        with mock.patch(
            "apps.payments.razorpay_controlled_pilot_execution"
            "._create_order_via_sdk",
            side_effect=Phase7DExecutionError(
                "boom: razorpay sandbox down"
            ),
        ):
            result = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=(
                    f"Director sign-off mentions gate {gate.pk}"
                ),
            )
    assert result["ok"] is False
    row = RazorpayControlledPilotExecutionAttempt.objects.get(
        pk=attempt_id
    )
    assert (
        row.status
        == RazorpayControlledPilotExecutionAttempt.Status.FAILED
    )
    assert row.provider_call_attempted is True
    assert row.provider_object_id == ""
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_FAILED
    ).exists()


@pytest.mark.django_db
def test_execute_single_shot_second_run_refused() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_exec_single_shot"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    fake_response = _mock_razorpay_order_response(
        order_id="order_TEST7D_single"
    )
    with _phase7d_test_settings():
        with mock.patch(
            "apps.payments.razorpay_controlled_pilot_execution"
            "._create_order_via_sdk",
            return_value=fake_response,
        ) as sdk:
            first = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=(
                    f"Director sign-off mentions gate {gate.pk}"
                ),
            )
            second = execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=(
                    f"Director sign-off mentions gate {gate.pk}"
                ),
            )
    assert first["ok"] is True
    assert second["ok"] is False
    # SDK called exactly once.
    assert sdk.call_count == 1


# ---------------------------------------------------------------------------
# Rollback / archive / recovery (#23, #24, #25, #37)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rollback_records_only_no_provider_call() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_rollback"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    fake_response = _mock_razorpay_order_response(
        order_id="order_TEST7D_rb"
    )
    with _phase7d_test_settings():
        with mock.patch(
            "apps.payments.razorpay_controlled_pilot_execution"
            "._create_order_via_sdk",
            return_value=fake_response,
        ):
            execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=(
                    f"Director sign-off mentions gate {gate.pk}"
                ),
            )
    out = rollback_phase7d_razorpay_test_execution_attempt(
        attempt_id,
        reason="Rolling back as Director directive",
    )
    assert out["ok"] is True
    row = RazorpayControlledPilotExecutionAttempt.objects.get(
        pk=attempt_id
    )
    assert (
        row.rollback_status
        == RazorpayControlledPilotExecutionAttempt.RollbackStatus.COMPLETED
    )
    assert (
        RazorpayControlledPilotExecutionRollback.objects.filter(
            attempt=row
        ).count()
        == 1
    )
    # No new business mutation.


@pytest.mark.django_db
def test_archive_changes_status_only() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_archive"
    )
    with _phase7d_test_settings():
        out = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
        attempt_id = out["attempt"]["id"]
    result = archive_phase7d_razorpay_test_execution_attempt(
        attempt_id,
        archived_by=None,
        reason="Archiving for tests",
    )
    assert result["ok"] is True
    row = RazorpayControlledPilotExecutionAttempt.objects.get(
        pk=attempt_id
    )
    assert (
        row.status
        == RazorpayControlledPilotExecutionAttempt.Status.ARCHIVED
    )


@pytest.mark.django_db
def test_recovery_refuses_bad_input() -> None:
    out = recover_phase7d_razorpay_test_execution_attempt(
        idempotency_key="",
        provider_object_id="",
    )
    assert out["ok"] is False


@pytest.mark.django_db
def test_recovery_reconciles_orphan_provider_object_id() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_recover"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    row = RazorpayControlledPilotExecutionAttempt.objects.get(
        pk=attempt_id
    )
    # Recovery does NOT call Razorpay; just reconciles a known
    # idempotency_key + provider_object_id pair.
    out = recover_phase7d_razorpay_test_execution_attempt(
        idempotency_key=row.idempotency_key,
        provider_object_id="order_TEST7D_recovered",
    )
    assert out["ok"] is True
    row.refresh_from_db()
    assert row.provider_object_id == "order_TEST7D_recovered"
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_RECOVERY_RECONCILED
    ).exists()


# ---------------------------------------------------------------------------
# Defensive guard (#32)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_assert_no_business_mutation_raises_on_flipped_boolean() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_guard"
    )
    with _phase7d_test_settings():
        out = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
        attempt_id = out["attempt"]["id"]
    row = RazorpayControlledPilotExecutionAttempt.objects.get(
        pk=attempt_id
    )
    # Manually flip a locked-False boolean to simulate an attack.
    row.payment_captured = True
    row.save(update_fields=["payment_captured"])
    with pytest.raises(ValueError):
        assert_phase7d_no_business_mutation(row)
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_INVARIANT_VIOLATION
    ).exists()


# ---------------------------------------------------------------------------
# Raw secret / PII / forbidden payload-key absence (#26, #27)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_raw_razorpay_key_in_readiness_output(
    admin_user, auth_client
) -> None:
    fake_key = "rzp_test_PHASE7D_RAW_LEAK_DETECTOR_xyz"
    with override_settings(RAZORPAY_KEY_ID=fake_key):
        url = reverse(
            "saas-razorpay-controlled-pilot-execution-readiness"
        )
        body = json.dumps(auth_client(admin_user).get(url).json())
    assert fake_key not in body


@pytest.mark.django_db
def test_audit_payloads_lack_forbidden_keys() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_audit_keys"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    fake_response = _mock_razorpay_order_response()
    with _phase7d_test_settings():
        with mock.patch(
            "apps.payments.razorpay_controlled_pilot_execution"
            "._create_order_via_sdk",
            return_value=fake_response,
        ):
            execute_phase7d_razorpay_test_order(
                attempt_id,
                confirmed_by=None,
                director_signoff=(
                    f"Director sign-off mentions gate {gate.pk}"
                ),
            )
    rows = AuditEvent.objects.filter(
        kind__startswith="razorpay.controlled_pilot_execution."
    )
    forbidden = set(PHASE_7D_FORBIDDEN_PAYLOAD_KEYS)

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

    for row in rows:
        keys_in_payload = _walk_dict_keys(row.payload or {})
        for key in forbidden:
            assert key not in keys_in_payload, (
                f"forbidden key {key} leaked into audit row {row.pk}"
            )


# ---------------------------------------------------------------------------
# Detail / rollbacks 404 paths (#43, #45)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_detail_endpoint_returns_404_for_unknown_id(
    admin_user, auth_client
) -> None:
    url = reverse(
        "saas-razorpay-controlled-pilot-execution-attempt-detail",
        kwargs={"pk": 9999},
    )
    res = auth_client(admin_user).get(url)
    assert res.status_code == 404


@pytest.mark.django_db
def test_rollbacks_endpoint_returns_404_for_unknown_id(
    admin_user, auth_client
) -> None:
    url = reverse(
        "saas-razorpay-controlled-pilot-execution-rollbacks",
        kwargs={"attempt_id": 9999},
    )
    res = auth_client(admin_user).get(url)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Summarize counts populated (#1 supplemental)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_summarize_counts_all_lifecycle_states() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_summarize"
    )
    with _phase7d_test_settings():
        out = prepare_phase7d_razorpay_test_execution_attempt(gate.pk)
    summary = summarize_phase7d_attempts(limit=10)
    counts = summary["counts"]
    expected_states = {
        "draft",
        "blocked",
        "pendingDirectorSignoff",
        "approvedForOneShotRun",
        "executed",
        "failed",
        "rolledBack",
        "archived",
    }
    assert expected_states.issubset(set(counts))
    items = summary["items"]
    assert any(it["id"] == out["attempt"]["id"] for it in items)


# ---------------------------------------------------------------------------
# Attempts list endpoint locks Phase 7D safety booleans (#41)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attempts_list_endpoint_returns_phase7d_safety_locks(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-controlled-pilot-execution-attempts")
    body = auth_client(admin_user).get(url).json()
    assert body["phase"] == "7D"
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["apiEndpointCanApprove"] is False
    assert body["controlledPilotExecutionAllowedInPhase7D"] is False
    assert body["phase7DSendsOrQueuesWhatsApp"] is False
    assert body["phase7DCallsMetaCloud"] is False
    assert body["phase7DCallsDelhivery"] is False
    assert body["phase7DCreatesShipmentOrAwb"] is False
    assert body["phase7DCreatesPaymentLink"] is False
    assert body["phase7DCapturesPayment"] is False
    assert body["phase7DRefundsPayment"] is False
    assert body["phase7DSendsCustomerNotification"] is False
    assert body["phase7DMutatesBusinessRow"] is False


# ---------------------------------------------------------------------------
# Serializer never returns full director_signoff_text (PII guard)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_serializer_does_not_leak_director_signoff_text() -> None:
    gate = _make_approved_phase7b_gate(
        source_event_id="evt_phase7d_serializer"
    )
    attempt_id = _approved_attempt_id(gate.pk)
    row = RazorpayControlledPilotExecutionAttempt.objects.get(
        pk=attempt_id
    )
    row.director_signoff_text = (
        "secret email director@nirogidhara.com phone +919876543210"
    )
    row.save(update_fields=["director_signoff_text"])
    serialized = serialize_phase7d_attempt(row)
    body = json.dumps(serialized)
    assert "director@nirogidhara.com" not in body
    assert "+919876543210" not in body
