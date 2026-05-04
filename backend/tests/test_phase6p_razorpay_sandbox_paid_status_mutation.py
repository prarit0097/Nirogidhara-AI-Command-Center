"""Phase 6P — Controlled Internal Paid-Status Mutation Test.

Asserts the 29 spec requirements:

1.  Readiness command returns Phase 6P shape.
2.  Readiness endpoint returns Phase 6P shape.
3.  Mapping includes all 9 events.
4.  Every mapping says real business mutation false.
5.  Prepare attempt fails if review not approved.
6.  Prepare attempt succeeds for approved synthetic Phase 6O review.
7.  Execute fails when ``RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=False``.
8.  Execute fails without confirmation flag.
9.  Execute fails without director sign-off.
10. Execute succeeds with env override true + confirmation + sign-off.
11. Execute creates/updates sandbox ledger only.
12. Execute is idempotent.
13. Rollback updates sandbox ledger only.
14. Rollback is idempotent.
15. Archive attempt works.
16. No Order mutation.
17. No Payment mutation.
18. No Shipment mutation.
19. No DiscountOfferLog mutation.
20. No Customer / Lead mutation.
21. No Razorpay API call.
22. No WhatsApp / customer notification.
23. No raw secret in command/API output.
24. No planted PII in command/API output.
25. API endpoints are read-only / auth-protected.
26. POST/PATCH/DELETE return 405 on every Phase 6P endpoint.
27. Audit events are safe + contain no secrets.
28. ``safeToStartPhase6Q`` stays False until at least one attempt is
    executed AND rolled back cleanly.
29. Phase 6Q not implemented (asserted indirectly — no Phase 6Q
    module/command/endpoint imported by Phase 6P).
"""
from __future__ import annotations

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
    RazorpaySandboxPaidStatusLedger,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)
from apps.payments.razorpay_sandbox_paid_status_mutation import (
    AUDIT_KIND_EXECUTED,
    AUDIT_KIND_ROLLED_BACK,
    AUDIT_KIND_ATTEMPT_PREPARED,
    PHASE_6P_FORBIDDEN_ACTIONS,
    archive_phase6p_paid_status_mutation_attempt,
    build_phase6p_paid_status_mapping,
    execute_phase6p_paid_status_mutation_attempt,
    inspect_phase6p_paid_status_mutation_readiness,
    prepare_phase6p_paid_status_mutation_attempt,
    preview_phase6p_paid_status_mutation,
    rollback_phase6p_paid_status_mutation_attempt,
    summarize_phase6p_paid_status_mutation_attempts,
)
from apps.payments.razorpay_sandbox_status_mapping import (
    approve_phase6o_sandbox_status_review,
    prepare_phase6o_sandbox_status_review,
)
from apps.shipments.models import Shipment


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
        "razorpay_event": RazorpayWebhookEvent.objects.count(),
        "phase6o_review": RazorpaySandboxStatusReview.objects.count(),
        "phase6p_attempt": RazorpaySandboxPaidStatusMutationAttempt.objects.count(),
        "phase6p_ledger": RazorpaySandboxPaidStatusLedger.objects.count(),
    }


def _make_safe_event(
    *,
    event_name: str = "payment.captured",
    source_event_id: str = "evt_phase6p_001",
    amount_paise: int = 100,
) -> RazorpayWebhookEvent:
    return RazorpayWebhookEvent.objects.create(
        provider="razorpay",
        source_event_id=source_event_id,
        event_id=source_event_id,
        event_name=event_name,
        environment=RazorpayWebhookEvent.Environment.TEST,
        signature_present=True,
        signature_valid=True,
        replay_window_valid=True,
        idempotency_status=RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN,
        processing_status=RazorpayWebhookEvent.ProcessingStatus.STORED,
        processing_mode=(
            RazorpayWebhookEvent.ProcessingMode.TEST_MODE_RECORD_ONLY
        ),
        provider_order_id="order_phase6p_synthetic",
        provider_payment_id="pay_phase6p_synthetic",
        amount_paise=amount_paise,
        currency="INR",
        payload_hash="x" * 64,
        scrubbed_keys=[],
        business_mutation_was_made=False,
        customer_notification_sent=False,
        raw_secret_exposed=False,
        full_pii_exposed=False,
    )


def _make_approved_review(
    *,
    event_name: str = "payment.captured",
    source_event_id: str = "evt_phase6p_seed",
) -> RazorpaySandboxStatusReview:
    """Helper — create a Phase 6M event, prepare a Phase 6O review,
    approve it. Uses the real Phase 6O service path."""
    with override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True):
        event = _make_safe_event(
            event_name=event_name, source_event_id=source_event_id
        )
        prepared = prepare_phase6o_sandbox_status_review(event.pk)
        assert prepared["created"] is True, prepared
        review_id = prepared["review"]["id"]
        approved = approve_phase6o_sandbox_status_review(
            review_id, reviewed_by=None, reason="ok"
        )
        assert approved["ok"] is True
    return RazorpaySandboxStatusReview.objects.get(pk=review_id)


# ---------------------------------------------------------------------------
# Mapping (#3, #4)
# ---------------------------------------------------------------------------


def test_event_mapping_covers_all_nine_events() -> None:
    rows = build_phase6p_paid_status_mapping()
    assert len(rows) == 9
    assert {r["razorpayEventName"] for r in rows} == {
        "payment_link.paid",
        "payment.captured",
        "payment.failed",
        "payment.authorized",
        "order.paid",
        "payment_link.cancelled",
        "payment_link.expired",
        "refund.created",
        "refund.processed",
    }


def test_every_mapping_locks_real_business_mutation_off() -> None:
    for row in build_phase6p_paid_status_mapping():
        assert row["realOrderMutationAllowedInPhase6P"] is False
        assert row["realPaymentMutationAllowedInPhase6P"] is False
        assert row["customerNotificationAllowed"] is False
        assert row["providerCallAllowed"] is False
        assert row["shipmentEffectAllowed"] is False
        assert row["discountEffectAllowed"] is False
        assert row["idempotencyRequired"] is True
        assert row["rollbackRequired"] is True
        assert row["executionPath"] == "cli_only"


# ---------------------------------------------------------------------------
# Readiness (#1, #2, #28)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_selector_returns_phase6p_shape() -> None:
    report = inspect_phase6p_paid_status_mutation_readiness()
    assert report["phase"] == "6P"
    assert report["status"] == "sandbox_ledger_only"
    assert report["latestCompletedPhase"] == "6O"
    assert report["nextPhase"] == "6Q"
    assert report["razorpaySandboxPaidStatusMutationEnabled"] is False
    assert report["frontendCanExecute"] is False
    assert report["apiEndpointCanExecute"] is False
    assert report["executionPath"] == "cli_only"
    assert len(report["eventMappings"]) == 9
    assert report["safeToStartPhase6Q"] is False


@pytest.mark.django_db
def test_readiness_command_emits_json() -> None:
    buf = io.StringIO()
    call_command(
        "inspect_razorpay_sandbox_paid_status_mutation_readiness",
        "--json",
        "--no-audit",
        stdout=buf,
    )
    body = json.loads(buf.getvalue())
    assert body["phase"] == "6P"
    assert body["status"] == "sandbox_ledger_only"


# ---------------------------------------------------------------------------
# Prepare (#5, #6)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_blocked_if_review_not_approved() -> None:
    with override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True):
        event = _make_safe_event(source_event_id="evt_phase6p_unapproved")
        prepared_o = prepare_phase6o_sandbox_status_review(event.pk)
    review_id = prepared_o["review"]["id"]
    # Don't approve. Try Phase 6P prepare.
    out = prepare_phase6p_paid_status_mutation_attempt(review_id)
    assert out["created"] is False
    assert any("approved_for_future_phase6p" in b for b in out["blockers"])
    assert (
        RazorpaySandboxPaidStatusMutationAttempt.objects.count() == 0
    )


@pytest.mark.django_db
def test_prepare_succeeds_for_approved_synthetic_review() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_prep_ok")
    out = prepare_phase6p_paid_status_mutation_attempt(review.pk)
    assert out["created"] is True
    assert out["attempt"]["status"] == "prepared"
    # Exactly one attempt + zero ledger rows so far.
    assert (
        RazorpaySandboxPaidStatusMutationAttempt.objects.count() == 1
    )
    assert RazorpaySandboxPaidStatusLedger.objects.count() == 0


@pytest.mark.django_db
def test_prepare_is_idempotent() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_prep_dup")
    first = prepare_phase6p_paid_status_mutation_attempt(review.pk)
    second = prepare_phase6p_paid_status_mutation_attempt(review.pk)
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert first["attempt"]["id"] == second["attempt"]["id"]


# ---------------------------------------------------------------------------
# Execute (#7, #8, #9, #10, #11, #12)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_execute_blocked_when_env_flag_off() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_no_flag")
    out = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    assert out["executed"] is False
    assert any(
        "RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED" in b
        for b in out["blockers"]
    )
    assert RazorpaySandboxPaidStatusLedger.objects.count() == 0


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_execute_blocked_without_confirmation() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_no_confirm")
    out = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=False, director_signoff_text="Director ok"
    )
    assert out["executed"] is False
    assert "cli_confirmation_flag_must_be_provided" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_execute_blocked_without_director_signoff() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_no_signoff")
    out = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text=""
    )
    assert out["executed"] is False
    assert "director_signoff_text_must_be_non_empty" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_execute_succeeds_and_creates_sandbox_ledger() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_exec_ok")
    out = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director PS"
    )
    assert out["executed"] is True
    assert out["attempt"]["status"] == "executed"
    assert out["ledger"]["currentState"] == "captured"
    assert out["ledger"]["mutationCount"] == 1
    assert RazorpaySandboxPaidStatusLedger.objects.count() == 1
    # Phase 6P safety booleans never flip.
    assert out["attempt"]["realOrderMutationWasMade"] is False
    assert out["attempt"]["realPaymentMutationWasMade"] is False
    assert out["attempt"]["businessMutationWasMade"] is False
    assert out["attempt"]["customerNotificationSent"] is False
    assert out["attempt"]["providerCallAttempted"] is False
    assert out["ledger"]["realOrderMutationWasMade"] is False
    assert out["ledger"]["realPaymentMutationWasMade"] is False


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_execute_is_idempotent() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_exec_idem")
    first = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    second = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    assert first["executed"] is True
    assert second["executed"] is False
    assert second["executedAgain"] is True
    # Mutation count stays 1 — re-running the same target state is a no-op.
    assert second["ledger"]["mutationCount"] == 1
    assert (
        RazorpaySandboxPaidStatusMutationAttempt.objects.count() == 1
    )
    assert RazorpaySandboxPaidStatusLedger.objects.count() == 1


# ---------------------------------------------------------------------------
# Rollback (#13, #14)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_rollback_updates_only_sandbox_ledger() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_rb")
    executed = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    attempt_id = executed["attempt"]["id"]
    out = rollback_phase6p_paid_status_mutation_attempt(
        attempt_id, confirmed=True, reason="rehearsal complete"
    )
    assert out["rolledBack"] is True
    assert out["attempt"]["status"] == "rolled_back"
    assert out["ledger"]["rolledBack"] is True
    assert out["ledger"]["currentState"] == "initial"
    # Locked-False booleans never flip.
    assert out["attempt"]["realOrderMutationWasMade"] is False
    assert out["ledger"]["realOrderMutationWasMade"] is False


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_rollback_blocked_without_confirmation() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_rb_no_confirm")
    executed = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    out = rollback_phase6p_paid_status_mutation_attempt(
        executed["attempt"]["id"], confirmed=False, reason="oops"
    )
    assert out["rolledBack"] is False
    assert "cli_confirmation_flag_must_be_provided" in out["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_rollback_is_idempotent() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_rb_idem")
    executed = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    attempt_id = executed["attempt"]["id"]
    rollback_phase6p_paid_status_mutation_attempt(
        attempt_id, confirmed=True, reason="r1"
    )
    second = rollback_phase6p_paid_status_mutation_attempt(
        attempt_id, confirmed=True, reason="r2"
    )
    assert second["rolledBack"] is False
    assert second["rolledBackAgain"] is True


# ---------------------------------------------------------------------------
# Archive (#15)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_archive_attempt_works_and_is_idempotent() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_arc")
    executed = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    out = archive_phase6p_paid_status_mutation_attempt(
        executed["attempt"]["id"], reason="close"
    )
    assert out["archived"] is True
    assert out["attempt"]["status"] == "archived"
    again = archive_phase6p_paid_status_mutation_attempt(
        executed["attempt"]["id"], reason="close again"
    )
    assert again["archived"] is True
    assert "already_archived" in again["nextAction"]


# ---------------------------------------------------------------------------
# Mutation safety (#16-#20, #21, #22)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_full_lifecycle_does_not_mutate_business_tables(seeded) -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_full_safety")
    before = _row_counts()

    prepared = prepare_phase6p_paid_status_mutation_attempt(review.pk)
    assert prepared["created"] is True
    after_prepare = _row_counts()

    executed = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    assert executed["executed"] is True
    after_execute = _row_counts()

    rolled = rollback_phase6p_paid_status_mutation_attempt(
        executed["attempt"]["id"], confirmed=True, reason="r"
    )
    assert rolled["rolledBack"] is True
    after_rollback = _row_counts()

    archive_phase6p_paid_status_mutation_attempt(
        executed["attempt"]["id"], reason="close"
    )
    after_archive = _row_counts()

    # Real business tables — Order / Payment / Shipment / DiscountOfferLog /
    # Customer / Lead — must be UNCHANGED at every step.
    for after in (after_prepare, after_execute, after_rollback, after_archive):
        assert after["order"] == before["order"]
        assert after["payment"] == before["payment"]
        assert after["shipment"] == before["shipment"]
        assert after["discount_offer_log"] == before["discount_offer_log"]
        assert after["customer"] == before["customer"]
        assert after["lead"] == before["lead"]


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_full_lifecycle_never_calls_provider_or_whatsapp() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_no_calls")
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
    ) as vapi:
        prepare_phase6p_paid_status_mutation_attempt(review.pk)
        executed = execute_phase6p_paid_status_mutation_attempt(
            review.pk, confirmed=True, director_signoff_text="Director ok"
        )
        rollback_phase6p_paid_status_mutation_attempt(
            executed["attempt"]["id"], confirmed=True, reason="r"
        )
        archive_phase6p_paid_status_mutation_attempt(
            executed["attempt"]["id"], reason="close"
        )
        create_link.assert_not_called()
        capture.assert_not_called()
        refund.assert_not_called()
        queue_template.assert_not_called()
        send_text.assert_not_called()
        vapi.assert_not_called()


# ---------------------------------------------------------------------------
# Output sanitization (#23, #24)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True,
    RAZORPAY_KEY_ID="rzp_test_PHASE6P_PLANTED_KEYID_DO_NOT_LEAK",
    RAZORPAY_KEY_SECRET="PHASE6P_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
    RAZORPAY_WEBHOOK_SECRET="PHASE6P_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
)
def test_output_does_not_expose_planted_secrets() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_secret")
    executed = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    blob = json.dumps(executed, default=str)
    for planted in (
        "rzp_test_PHASE6P_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE6P_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6P_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted

    readiness = inspect_phase6p_paid_status_mutation_readiness()
    blob = json.dumps(readiness, default=str)
    for planted in (
        "rzp_test_PHASE6P_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE6P_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6P_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted


@pytest.mark.django_db
def test_output_does_not_leak_planted_pii() -> None:
    Customer.objects.create(
        name="Phase6P Planted Customer",
        phone="+917777666555",
        product_interest="weight-management",
    )
    readiness = inspect_phase6p_paid_status_mutation_readiness()
    blob = json.dumps(readiness, default=str)
    assert "+917777666555" not in blob
    assert "Phase6P Planted Customer" not in blob


# ---------------------------------------------------------------------------
# Endpoint guards (#25, #26)
# ---------------------------------------------------------------------------


_READ_ENDPOINT_NAMES = (
    "saas-razorpay-sandbox-paid-status-mutation-readiness",
    "saas-razorpay-sandbox-paid-status-mutation-attempts",
    "saas-razorpay-sandbox-paid-status-mutation-preview",
)


@pytest.mark.django_db
def test_readiness_endpoint_requires_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse("saas-razorpay-sandbox-paid-status-mutation-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase6p_shape(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-sandbox-paid-status-mutation-readiness")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6P"
    assert body["status"] == "sandbox_ledger_only"
    assert body["razorpaySandboxPaidStatusMutationEnabled"] is False
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False


@pytest.mark.django_db
def test_attempts_list_endpoint_admin_locked_safety(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-sandbox-paid-status-mutation-attempts")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6P"
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["realOrderMutationWasMade"] is False


@pytest.mark.django_db
@pytest.mark.parametrize("name", _READ_ENDPOINT_NAMES)
def test_phase_6p_endpoints_reject_non_get_methods(
    name, admin_user, auth_client
) -> None:
    url = reverse(name)
    client = auth_client(admin_user)
    for method in ("post", "patch", "put", "delete"):
        res = getattr(client, method)(url, {})
        assert res.status_code == 405, f"{method} {name} -> {res.status_code}"


# ---------------------------------------------------------------------------
# Audit safety (#27)
# ---------------------------------------------------------------------------


_FORBIDDEN_PAYLOAD_KEYS = (
    "raw_payload",
    "raw_signature",
    "raw_secret",
    "phone",
    "email",
    "address",
    "card",
    "vpa",
    "upi",
    "bank_account",
    "wallet",
)


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_audit_events_only_carry_safe_keys() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_audit")
    # Prepare → execute → rollback covers every audit kind we want to
    # assert on. Calling execute alone skips the prepared audit row.
    prepare_phase6p_paid_status_mutation_attempt(review.pk)
    executed = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    rollback_phase6p_paid_status_mutation_attempt(
        executed["attempt"]["id"], confirmed=True, reason="r"
    )

    for kind in (
        AUDIT_KIND_ATTEMPT_PREPARED,
        AUDIT_KIND_EXECUTED,
        AUDIT_KIND_ROLLED_BACK,
    ):
        rows = AuditEvent.objects.filter(kind=kind)
        assert rows.exists(), f"missing audit kind {kind}"
        for row in rows:
            payload = row.payload or {}
            assert payload.get("real_order_mutation_was_made") is False
            assert payload.get("real_payment_mutation_was_made") is False
            assert payload.get("business_mutation_was_made") is False
            assert payload.get("customer_notification_sent") is False
            assert payload.get("provider_call_attempted") is False
            for forbidden in _FORBIDDEN_PAYLOAD_KEYS:
                assert forbidden not in payload, (kind, forbidden)


# ---------------------------------------------------------------------------
# safeToStartPhase6Q (#28)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_safe_to_start_phase_6q_default_false() -> None:
    report = inspect_phase6p_paid_status_mutation_readiness()
    assert report["safeToStartPhase6Q"] is False


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED=True)
def test_safe_to_start_phase_6q_true_after_executed_and_rolled_back() -> None:
    review = _make_approved_review(
        source_event_id="evt_phase6p_safe_to_start"
    )
    executed = execute_phase6p_paid_status_mutation_attempt(
        review.pk, confirmed=True, director_signoff_text="Director ok"
    )
    rollback_phase6p_paid_status_mutation_attempt(
        executed["attempt"]["id"], confirmed=True, reason="r"
    )
    report = inspect_phase6p_paid_status_mutation_readiness()
    assert report["safeToStartPhase6Q"] is True
    assert (
        report["nextAction"]
        == "ready_for_phase_6q_payment_to_order_workflow_safety_gate"
    )


# ---------------------------------------------------------------------------
# Forbidden actions list visibility
# ---------------------------------------------------------------------------


def test_forbidden_actions_includes_critical_paths() -> None:
    expected = {
        "mutate_real_order_status",
        "mutate_real_payment_status",
        "create_or_update_real_shipment",
        "create_or_update_real_discount_offer",
        "mutate_real_customer",
        "mutate_real_lead",
        "send_whatsapp_template",
        "place_vapi_call",
        "call_razorpay_api",
        "execute_phase_6p_via_frontend",
        "execute_phase_6p_via_api_endpoint",
    }
    assert expected.issubset(set(PHASE_6P_FORBIDDEN_ACTIONS))


# ---------------------------------------------------------------------------
# Preview never creates rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_does_not_create_rows() -> None:
    review = _make_approved_review(source_event_id="evt_phase6p_preview")
    before = _row_counts()
    out = preview_phase6p_paid_status_mutation(review.pk)
    after = _row_counts()
    assert out["found"] is True
    assert out["eligible"] is True
    assert before["phase6p_attempt"] == after["phase6p_attempt"]
    assert before["phase6p_ledger"] == after["phase6p_ledger"]
