"""Phase 6O — Razorpay Sandbox Status Mapping + Manual Review tests.

Asserts the 23 spec requirements:

1.  Readiness command returns Phase 6O shape.
2.  Readiness endpoint returns Phase 6O shape.
3.  Event mapping includes all 9 events.
4.  Each mapping has ``mutationAllowedInPhase6O=False``.
5.  Prepare review fails when ``RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=False``.
6.  Prepare review succeeds with env override + synthetic eligible event.
7.  Ineligible event creates no review.
8.  Duplicate prepare is idempotent.
9.  Approve review changes review status only.
10. Reject review changes review status only.
11. Archive review changes review status only.
12. Approving review does not mutate Order.
13. Approving review does not mutate Payment.
14. Approving review does not mutate Shipment.
15. Approving review does not mutate DiscountOfferLog.
16. No Razorpay API call occurs.
17. No WhatsApp/customer notification occurs.
18. No raw secret appears in command/API output.
19. No planted PII appears in command/API output.
20. Endpoints require auth/admin permissions.
21. Unsupported methods return 405.
22. Audit events are safe and contain no secrets.
23. Review approval says future Phase 6P only, not applied.
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
from apps.crm.models import Customer
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import (
    Payment,
    RazorpaySandboxStatusReview,
    RazorpayWebhookEvent,
)
from apps.payments.razorpay_sandbox_status_mapping import (
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_PREPARED,
    PHASE_6O_FORBIDDEN_ACTIONS,
    PHASE_6O_MAX_SAFE_AMOUNT_PAISE,
    approve_phase6o_sandbox_status_review,
    archive_phase6o_sandbox_status_review,
    build_phase6o_event_to_status_mapping,
    inspect_phase6o_sandbox_status_mapping_readiness,
    prepare_phase6o_sandbox_status_review,
    preview_phase6o_status_mapping_for_event,
    reject_phase6o_sandbox_status_review,
    validate_phase6o_event_eligibility,
)
from apps.shipments.models import Shipment


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _row_counts() -> dict[str, int]:
    return {
        "order": Order.objects.count(),
        "payment": Payment.objects.count(),
        "shipment": Shipment.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "customer": Customer.objects.count(),
        "phase6o_review": RazorpaySandboxStatusReview.objects.count(),
    }


def _make_safe_event(
    *,
    event_name: str = "payment.captured",
    source_event_id: str = "evt_phase6o_001",
    amount_paise: int = 100,
    environment: str = RazorpayWebhookEvent.Environment.TEST,
    processing_status: str = RazorpayWebhookEvent.ProcessingStatus.STORED,
    idempotency_status: str = RazorpayWebhookEvent.IdempotencyStatus.FIRST_SEEN,
    signature_valid: bool = True,
    replay_window_valid: bool = True,
    business_mutation_was_made: bool = False,
    customer_notification_sent: bool = False,
    raw_secret_exposed: bool = False,
    full_pii_exposed: bool = False,
    scrubbed_keys: list[str] | None = None,
) -> RazorpayWebhookEvent:
    return RazorpayWebhookEvent.objects.create(
        provider="razorpay",
        source_event_id=source_event_id,
        event_id=source_event_id,
        event_name=event_name,
        environment=environment,
        signature_present=True,
        signature_valid=signature_valid,
        replay_window_valid=replay_window_valid,
        idempotency_status=idempotency_status,
        processing_status=processing_status,
        processing_mode=(
            RazorpayWebhookEvent.ProcessingMode.TEST_MODE_RECORD_ONLY
        ),
        provider_order_id="order_phase6o_synthetic",
        provider_payment_id="pay_phase6o_synthetic",
        amount_paise=amount_paise,
        currency="INR",
        payload_hash="x" * 64,
        scrubbed_keys=scrubbed_keys or [],
        business_mutation_was_made=business_mutation_was_made,
        customer_notification_sent=customer_notification_sent,
        raw_secret_exposed=raw_secret_exposed,
        full_pii_exposed=full_pii_exposed,
    )


# ---------------------------------------------------------------------------
# Mapping shape (#3, #4)
# ---------------------------------------------------------------------------


def test_event_mapping_covers_all_nine_events() -> None:
    mappings = build_phase6o_event_to_status_mapping()
    expected_events = {
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
    assert {row["razorpayEventName"] for row in mappings} == expected_events


def test_every_event_mapping_locks_mutation_off() -> None:
    for row in build_phase6o_event_to_status_mapping():
        assert row["mutationAllowedInPhase6O"] is False, row[
            "razorpayEventName"
        ]
        assert row["customerNotificationAllowed"] is False
        assert row["shipmentEffectAllowed"] is False
        assert row["discountEffectAllowed"] is False
        assert row["idempotencyRequired"] is True
        assert row["rollbackRequired"] is True
        assert (
            row["mutationAllowedInFuturePhase6P"]
            == "only_if_synthetic_review_approved_and_director_signed_off"
        )


# ---------------------------------------------------------------------------
# Readiness selector (#1)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_selector_returns_phase6o_shape() -> None:
    report = inspect_phase6o_sandbox_status_mapping_readiness()
    assert report["phase"] == "6O"
    assert report["status"] == "sandbox_review_only"
    assert report["latestCompletedPhase"] == "6N"
    assert report["nextPhase"] == "6P"
    assert report["businessMutationEnabled"] is False
    assert report["customerNotificationEnabled"] is False
    assert report["providerCallAttempted"] is False
    assert report["razorpaySandboxStatusMappingEnabled"] is False
    assert len(report["eventMappings"]) == 9
    # safeToStartPhase6P is False by default (no approved review yet).
    assert report["safeToStartPhase6P"] is False
    assert "approve_at_least_one_phase6o_review_for_future_phase6p" in (
        report["nextAction"]
    )


@pytest.mark.django_db
def test_readiness_command_emits_json() -> None:
    buf = io.StringIO()
    call_command(
        "inspect_razorpay_sandbox_status_mapping_readiness",
        "--json",
        "--no-audit",
        stdout=buf,
    )
    payload = json.loads(buf.getvalue())
    assert payload["phase"] == "6O"
    assert payload["status"] == "sandbox_review_only"
    assert len(payload["eventMappings"]) == 9


# ---------------------------------------------------------------------------
# Eligibility + prepare gating (#5, #6, #7)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_prepare_review_blocked_without_env_flag() -> None:
    event = _make_safe_event()
    report = prepare_phase6o_sandbox_status_review(event.pk)
    assert report["created"] is False
    assert report["reused"] is False
    assert any(
        "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED" in b
        for b in report["blockers"]
    )
    assert RazorpaySandboxStatusReview.objects.count() == 0


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_prepare_review_succeeds_with_flag_and_eligible_event() -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_ok")
    report = prepare_phase6o_sandbox_status_review(event.pk)
    assert report["created"] is True
    assert report["review"]["mutationAllowedInPhase6O"] is False
    assert report["review"]["businessMutationWasMade"] is False
    assert report["review"]["customerNotificationSent"] is False
    assert RazorpaySandboxStatusReview.objects.count() == 1


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_prepare_review_blocked_when_event_not_allowlisted() -> None:
    event = _make_safe_event(
        event_name="subscription.charged",  # not in Phase 6O allowlist
        source_event_id="evt_phase6o_denied",
    )
    report = prepare_phase6o_sandbox_status_review(event.pk)
    assert report["created"] is False
    assert any("event_name_not_phase6o_allowlisted" in b for b in report["blockers"])
    assert RazorpaySandboxStatusReview.objects.count() == 0


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_prepare_review_blocked_when_amount_exceeds_safe_ceiling() -> None:
    event = _make_safe_event(
        amount_paise=PHASE_6O_MAX_SAFE_AMOUNT_PAISE + 1,
        source_event_id="evt_phase6o_amount_too_big",
    )
    report = prepare_phase6o_sandbox_status_review(event.pk)
    assert report["created"] is False
    assert any("amount_paise_must_be_between" in b for b in report["blockers"])
    assert RazorpaySandboxStatusReview.objects.count() == 0


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_prepare_review_blocked_when_source_event_unsafe() -> None:
    event = _make_safe_event(
        signature_valid=False, source_event_id="evt_phase6o_bad_sig"
    )
    report = prepare_phase6o_sandbox_status_review(event.pk)
    assert report["created"] is False
    assert "source_event_signature_invalid" in report["blockers"]
    assert RazorpaySandboxStatusReview.objects.count() == 0


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_prepare_review_blocked_when_full_pii_present() -> None:
    event = _make_safe_event(
        scrubbed_keys=["card", "vpa"], source_event_id="evt_phase6o_pii"
    )
    report = prepare_phase6o_sandbox_status_review(event.pk)
    assert report["created"] is False
    assert "source_event_full_pii_must_be_absent" in report["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_prepare_is_idempotent_on_duplicate_calls() -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_idempotent")
    first = prepare_phase6o_sandbox_status_review(event.pk)
    second = prepare_phase6o_sandbox_status_review(event.pk)
    assert first["created"] is True
    assert second["created"] is False
    assert second["reused"] is True
    assert first["review"]["id"] == second["review"]["id"]
    assert RazorpaySandboxStatusReview.objects.count() == 1


# ---------------------------------------------------------------------------
# Approve / reject / archive (#9-#11, #23)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_approve_sets_status_to_approved_for_future_phase6p_only() -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_approve")
    prepared = prepare_phase6o_sandbox_status_review(event.pk)
    review_id = prepared["review"]["id"]

    res = approve_phase6o_sandbox_status_review(
        review_id, reviewed_by=None, reason="ok"
    )
    assert res["ok"] is True
    assert (
        res["review"]["status"]
        == RazorpaySandboxStatusReview.Status.APPROVED_FOR_FUTURE_PHASE6P
    )
    # Approval explicitly says "future Phase 6P", never "applied".
    assert "phase_6p" in res["nextAction"].lower()
    assert "applied" not in res["nextAction"].lower()


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_reject_sets_status_to_rejected_only() -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_reject")
    prepared = prepare_phase6o_sandbox_status_review(event.pk)
    res = reject_phase6o_sandbox_status_review(
        prepared["review"]["id"], reason="not synthetic"
    )
    assert res["ok"] is True
    assert (
        res["review"]["status"] == RazorpaySandboxStatusReview.Status.REJECTED
    )


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_archive_sets_status_to_archived_only() -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_archive")
    prepared = prepare_phase6o_sandbox_status_review(event.pk)
    res = archive_phase6o_sandbox_status_review(
        prepared["review"]["id"], reason="cleanup"
    )
    assert res["ok"] is True
    assert (
        res["review"]["status"] == RazorpaySandboxStatusReview.Status.ARCHIVED
    )


# ---------------------------------------------------------------------------
# Mutation safety (#12-#15, #16, #17)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_full_lifecycle_does_not_mutate_business_tables(seeded) -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_full_lifecycle")
    before = _row_counts()

    prepared = prepare_phase6o_sandbox_status_review(event.pk)
    assert prepared["created"] is True

    after_prepare = _row_counts()
    # Only Phase 6O review row count changes; every business row is untouched.
    assert after_prepare["order"] == before["order"]
    assert after_prepare["payment"] == before["payment"]
    assert after_prepare["shipment"] == before["shipment"]
    assert after_prepare["discount_offer_log"] == before["discount_offer_log"]
    assert after_prepare["phase6o_review"] == before["phase6o_review"] + 1

    approve_phase6o_sandbox_status_review(
        prepared["review"]["id"], reason="ok"
    )

    after_approve = _row_counts()
    assert after_approve["order"] == before["order"]
    assert after_approve["payment"] == before["payment"]
    assert after_approve["shipment"] == before["shipment"]
    assert after_approve["discount_offer_log"] == before["discount_offer_log"]


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_full_lifecycle_never_calls_provider_or_whatsapp() -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_no_calls")
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
        prepared = prepare_phase6o_sandbox_status_review(event.pk)
        approve_phase6o_sandbox_status_review(
            prepared["review"]["id"], reason="ok"
        )
        reject_phase6o_sandbox_status_review(  # noqa: F841 — confirm transitions don't dispatch
            prepared["review"]["id"], reason="changed mind"
        )
        archive_phase6o_sandbox_status_review(
            prepared["review"]["id"], reason="close"
        )
        create_link.assert_not_called()
        capture.assert_not_called()
        refund.assert_not_called()
        queue_template.assert_not_called()
        send_text.assert_not_called()
        vapi.assert_not_called()


# ---------------------------------------------------------------------------
# Output sanitization (#18, #19)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True,
    RAZORPAY_KEY_ID="rzp_test_PHASE6O_PLANTED_KEYID_DO_NOT_LEAK",
    RAZORPAY_KEY_SECRET="PHASE6O_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
    RAZORPAY_WEBHOOK_SECRET="PHASE6O_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
)
def test_output_does_not_expose_planted_secrets() -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_secret_scan")
    prepared = prepare_phase6o_sandbox_status_review(event.pk)
    blob = json.dumps(prepared, default=str)
    for planted in (
        "rzp_test_PHASE6O_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE6O_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6O_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted

    readiness = inspect_phase6o_sandbox_status_mapping_readiness()
    blob = json.dumps(readiness, default=str)
    for planted in (
        "rzp_test_PHASE6O_PLANTED_KEYID_DO_NOT_LEAK",
        "PHASE6O_FAKE_SECRET_PLANTED_xxxxxxxxxxxxxxxxxxxx",
        "PHASE6O_FAKE_WEBHOOK_SECRET_xxxxxxxxxxxxxxxxxxxx",
    ):
        assert planted not in blob, planted


@pytest.mark.django_db
def test_output_does_not_leak_planted_pii() -> None:
    Customer.objects.create(
        name="Phase6O Planted Customer",
        phone="+918888777666",
        product_interest="weight-management",
    )
    readiness = inspect_phase6o_sandbox_status_mapping_readiness()
    blob = json.dumps(readiness, default=str)
    assert "+918888777666" not in blob
    assert "Phase6O Planted Customer" not in blob


# ---------------------------------------------------------------------------
# Endpoint guards (#2, #20, #21)
# ---------------------------------------------------------------------------


_READ_ENDPOINT_NAMES = (
    "saas-razorpay-sandbox-status-mapping-readiness",
    "saas-razorpay-sandbox-status-reviews",
)


_WRITE_ENDPOINT_NAMES = (
    "saas-razorpay-sandbox-status-review-prepare",
    # detail / approve / reject / archive are tested with the prepared id below.
)


@pytest.mark.django_db
def test_readiness_endpoint_requires_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse("saas-razorpay-sandbox-status-mapping-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase6o_shape(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-sandbox-status-mapping-readiness")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6O"
    assert body["status"] == "sandbox_review_only"
    assert body["razorpaySandboxStatusMappingEnabled"] is False
    assert len(body["eventMappings"]) == 9


@pytest.mark.django_db
def test_reviews_list_endpoint_admin_returns_locked_safety(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-sandbox-status-reviews")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6O"
    assert body["businessMutationWasMade"] is False
    assert body["customerNotificationSent"] is False
    assert body["providerCallAttempted"] is False
    assert isinstance(body["items"], list)


@pytest.mark.django_db
@pytest.mark.parametrize("name", _READ_ENDPOINT_NAMES)
def test_read_endpoints_reject_non_get_methods(
    name, admin_user, auth_client
) -> None:
    url = reverse(name)
    client = auth_client(admin_user)
    for method in ("patch", "put", "delete"):
        res = getattr(client, method)(url, {})
        assert res.status_code == 405, f"{method} {name} -> {res.status_code}"
    # POST is not defined on these read endpoints, so DRF returns 405.
    assert client.post(url, {}, format="json").status_code == 405


@pytest.mark.django_db
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_prepare_endpoint_admin_only_creates_review(
    admin_user, viewer_user, auth_client, client
) -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_endpoint_prepare")
    url = reverse("saas-razorpay-sandbox-status-review-prepare")

    # Anonymous → 401/403.
    assert client.post(url, {"eventId": event.pk}, format="json").status_code in {401, 403}
    # Viewer → 403.
    assert (
        auth_client(viewer_user)
        .post(url, {"eventId": event.pk}, format="json")
        .status_code
        == 403
    )
    # Admin → creates review.
    res = auth_client(admin_user).post(
        url, {"eventId": event.pk}, format="json"
    )
    assert res.status_code == 201
    body = res.json()
    assert body["created"] is True
    assert body["review"]["mutationAllowedInPhase6O"] is False
    review_id = body["review"]["id"]

    # Approve / reject / archive endpoints accept admin POST and 405 on GET.
    approve_url = reverse(
        "saas-razorpay-sandbox-status-review-approve", args=[review_id]
    )
    assert auth_client(admin_user).get(approve_url).status_code == 405
    res = auth_client(admin_user).post(approve_url, {"reason": "ok"}, format="json")
    assert res.status_code == 200
    assert (
        res.json()["review"]["status"]
        == RazorpaySandboxStatusReview.Status.APPROVED_FOR_FUTURE_PHASE6P
    )


# ---------------------------------------------------------------------------
# Audit safety (#22)
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
@override_settings(RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED=True)
def test_audit_events_only_carry_safe_keys() -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_audit_safe")
    prepared = prepare_phase6o_sandbox_status_review(event.pk)
    approve_phase6o_sandbox_status_review(
        prepared["review"]["id"], reason="ok"
    )

    for kind in (AUDIT_KIND_PREPARED, AUDIT_KIND_APPROVED):
        rows = AuditEvent.objects.filter(kind=kind)
        assert rows.exists(), f"missing audit kind {kind}"
        for row in rows:
            payload = row.payload or {}
            assert payload.get("mutation_allowed_in_phase6o") is False
            assert payload.get("business_mutation_was_made") is False
            assert payload.get("customer_notification_sent") is False
            for forbidden in _FORBIDDEN_PAYLOAD_KEYS:
                assert forbidden not in payload, (kind, forbidden)


# ---------------------------------------------------------------------------
# Forbidden actions list visible (defence in depth for UI checks)
# ---------------------------------------------------------------------------


def test_forbidden_actions_list_includes_critical_paths() -> None:
    expected = {
        "mark_order_paid",
        "mark_payment_captured",
        "create_payment_link",
        "capture_razorpay_payment",
        "refund_razorpay_payment",
        "send_whatsapp_template",
        "create_or_update_shipment",
        "create_or_update_discount_offer",
        "execute_webhook_replay",
        "enable_business_mutation_env_flag",
    }
    assert expected.issubset(set(PHASE_6O_FORBIDDEN_ACTIONS))


# ---------------------------------------------------------------------------
# Eligibility helper covers preview path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preview_with_unknown_event_returns_blockers() -> None:
    out = preview_phase6o_status_mapping_for_event(999999)
    assert out["found"] is False
    assert "razorpay_webhook_event_not_found" in out["blockers"]


@pytest.mark.django_db
def test_preview_with_safe_event_returns_proposed_mapping() -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_preview")
    out = preview_phase6o_status_mapping_for_event(event.pk)
    assert out["found"] is True
    assert out["proposedMapping"] is not None
    assert out["proposedMapping"]["mutationAllowedInPhase6O"] is False


@pytest.mark.django_db
def test_validate_eligibility_short_circuits_on_no_flag() -> None:
    event = _make_safe_event(source_event_id="evt_phase6o_no_flag")
    result = validate_phase6o_event_eligibility(event, require_env_flag=True)
    assert result.eligible is False
    assert any(
        "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED" in b for b in result.blockers
    )

    # Without env flag requirement, the same event is eligible.
    result2 = validate_phase6o_event_eligibility(
        event, require_env_flag=False
    )
    assert result2.eligible is True
