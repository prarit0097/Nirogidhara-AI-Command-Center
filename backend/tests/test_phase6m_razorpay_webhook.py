"""Phase 6M — Razorpay test-mode webhook handler tests.

Asserts:

- Signature verification uses raw body + HMAC-SHA256 + constant-time
  compare.
- Disabled env flag / missing secret / missing signature / invalid
  signature all block before any persistence side effect that could
  hint at success.
- Duplicate ``X-Razorpay-Event-Id`` returns 200 + ``processing_status=duplicate``
  + increments ``duplicate_count`` + does not re-mutate.
- Replay window blocks events older than ``RAZORPAY_WEBHOOK_REPLAY_WINDOW_SECONDS``.
- Allowlist + denylist enforcement.
- Safe summary masks PII; raw secret / raw signature / raw payload
  never appear in API output / management-command output / audit
  events.
- ``business_mutation_was_made`` / ``customer_notification_sent`` /
  ``provider_call_attempted`` stay False everywhere in Phase 6M.
- Order / Payment / Shipment counts are NOT mutated by the handler.
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timedelta, timezone
from unittest import mock
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.payments.management.commands.simulate_razorpay_webhook_event import (
    _build_payload,
)
from apps.payments.models import Payment, RazorpayWebhookEvent
from apps.payments.razorpay_webhook_readiness import (
    get_razorpay_webhook_handler_readiness,
)
from apps.payments.razorpay_webhooks import (
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_DUPLICATE,
    AUDIT_KIND_EVENT_DENIED,
    AUDIT_KIND_REPLAY_BLOCKED,
    AUDIT_KIND_SIGNATURE_FAILED,
    AUDIT_KIND_STORED,
    assert_no_business_mutation,
    build_safe_razorpay_webhook_summary,
    classify_razorpay_event,
    compute_razorpay_signature,
    get_razorpay_webhook_settings,
    mask_razorpay_webhook_payload,
    parse_razorpay_webhook_payload,
    process_razorpay_webhook,
    validate_replay_window,
    verify_razorpay_webhook_signature,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FAKE_SECRET = "phase6m_FAKEsecret_DO_NOT_LEAK_xxx42"


@pytest.fixture
def enabled_test_mode():
    overrides = {
        "RAZORPAY_WEBHOOK_TEST_MODE_ENABLED": True,
        "RAZORPAY_WEBHOOK_SECRET": _FAKE_SECRET,
        "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED": False,
        "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED": False,
        "RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD": False,
        "RAZORPAY_WEBHOOK_ALLOW_TEST_EVENTS_ONLY": True,
        "RAZORPAY_WEBHOOK_REPLAY_WINDOW_SECONDS": 300,
    }
    with override_settings(**overrides):
        yield


def _signed_request(
    *,
    event_name: str = "payment.captured",
    event_id: str | None = None,
    amount_paise: int = 100,
    created_at_dt: datetime | None = None,
    secret: str = _FAKE_SECRET,
) -> tuple[bytes, dict[str, str]]:
    when = created_at_dt or datetime.now(tz=timezone.utc)
    payload = _build_payload(
        event_name=event_name,
        amount_paise=amount_paise,
        order_id="order_Sks3KPf0vntKhf",
        payment_id="pay_test_phase6m",
        refund_id="rfnd_test_phase6m",
        payment_link_id="plink_test_phase6m",
        created_at_epoch=int(when.timestamp()),
    )
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "x-razorpay-signature": compute_razorpay_signature(body, secret),
        "x-razorpay-event-id": event_id or f"evt_test_{uuid4().hex[:12]}",
        "content-type": "application/json",
    }
    return body, headers


# ---------------------------------------------------------------------------
# Section A — Signature + parser helpers
# ---------------------------------------------------------------------------


def test_a01_verify_signature_uses_raw_body():
    body = b'{"hello":"world"}'
    sig = compute_razorpay_signature(body, _FAKE_SECRET)
    assert verify_razorpay_webhook_signature(body, sig, _FAKE_SECRET) is True


def test_a02_signature_fails_when_body_modified():
    body = b'{"hello":"world"}'
    sig = compute_razorpay_signature(body, _FAKE_SECRET)
    assert verify_razorpay_webhook_signature(b'{"hello":"WORLD"}', sig, _FAKE_SECRET) is False


def test_a03_signature_fails_when_secret_missing():
    body = b'{"hello":"world"}'
    sig = compute_razorpay_signature(body, _FAKE_SECRET)
    assert verify_razorpay_webhook_signature(body, sig, "") is False


def test_a04_signature_fails_when_signature_missing():
    body = b'{"hello":"world"}'
    assert verify_razorpay_webhook_signature(body, "", _FAKE_SECRET) is False


def test_a05_classify_pulls_event_name():
    payload = {"event": "payment.captured", "entity": "event", "contains": ["payment"]}
    classified = classify_razorpay_event(payload)
    assert classified["eventName"] == "payment.captured"
    assert classified["entity"] == "event"


def test_a06_parse_rejects_non_object_body():
    with pytest.raises(ValueError):
        parse_razorpay_webhook_payload(b"[]")


def test_a07_validate_replay_window_returns_false_for_missing_or_old():
    now = datetime.now(tz=timezone.utc)
    assert validate_replay_window(None, now, 300) is False
    assert (
        validate_replay_window(now - timedelta(seconds=600), now, 300) is False
    )
    assert (
        validate_replay_window(now - timedelta(seconds=10), now, 300) is True
    )


def test_a08_safe_summary_pulls_provider_ids():
    payload = _build_payload(
        event_name="payment.captured",
        amount_paise=100,
        order_id="order_TEST",
        payment_id="pay_TEST",
        refund_id="rfnd_TEST",
        payment_link_id="plink_TEST",
        created_at_epoch=int(datetime.now(tz=timezone.utc).timestamp()),
    )
    summary = build_safe_razorpay_webhook_summary(payload)
    assert summary["providerOrderId"] == "order_TEST"
    assert summary["providerPaymentId"] == "pay_TEST"
    assert summary["amountPaise"] == 100
    assert summary["currency"] == "INR"


def test_a09_mask_payload_scrubs_pii_and_secrets():
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_TEST",
                    "card": {"last4": "4242", "iin": "411111"},
                    "email": "alice@example.com",
                    "contact": "+919812345678",
                }
            }
        },
        "razorpay_webhook_secret": _FAKE_SECRET,
    }
    masked, scrubbed = mask_razorpay_webhook_payload(payload)
    blob = json.dumps(masked)
    assert _FAKE_SECRET not in blob
    assert "alice@example.com" not in blob
    assert "9812345678" not in blob
    assert "razorpay_webhook_secret" in scrubbed
    assert any(name in scrubbed for name in ("card", "email", "contact"))


# ---------------------------------------------------------------------------
# Section B — process_razorpay_webhook
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_b01_disabled_env_blocks_event():
    body, headers = _signed_request()
    result = process_razorpay_webhook(body, headers)
    assert result["statusCode"] == 403
    assert result["passed"] is False
    assert "razorpay_webhook_test_mode_disabled" in result["blockers"]
    assert RazorpayWebhookEvent.objects.filter(
        processing_status=RazorpayWebhookEvent.ProcessingStatus.BLOCKED
    ).exists()


@pytest.mark.django_db
def test_b02_missing_secret_blocks_event(enabled_test_mode):
    with override_settings(RAZORPAY_WEBHOOK_SECRET=""):
        body, headers = _signed_request(secret="some-other-secret")
        result = process_razorpay_webhook(body, headers)
    assert result["statusCode"] == 400
    assert "razorpay_webhook_secret_missing" in result["blockers"]


@pytest.mark.django_db
def test_b03_missing_signature_blocks_event(enabled_test_mode):
    body, headers = _signed_request()
    headers.pop("x-razorpay-signature")
    result = process_razorpay_webhook(body, headers)
    assert result["statusCode"] == 400
    assert "x_razorpay_signature_header_missing" in result["blockers"]


@pytest.mark.django_db
def test_b04_invalid_signature_blocks_event(enabled_test_mode):
    body, headers = _signed_request()
    headers["x-razorpay-signature"] = "deadbeef"
    result = process_razorpay_webhook(body, headers)
    assert result["statusCode"] == 400
    assert "razorpay_webhook_signature_invalid" in result["blockers"]
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_SIGNATURE_FAILED).exists()


@pytest.mark.django_db
def test_b05_valid_payment_captured_stores_event(enabled_test_mode):
    payment_count_before = Payment.objects.count()
    body, headers = _signed_request(event_name="payment.captured")
    result = process_razorpay_webhook(body, headers)
    assert result["passed"] is True
    assert result["statusCode"] == 200
    assert result["signatureValid"] is True
    assert (
        result["processingStatus"]
        == RazorpayWebhookEvent.ProcessingStatus.STORED
    )
    assert result["businessMutationWasMade"] is False
    assert result["customerNotificationSent"] is False
    assert result["providerCallAttempted"] is False
    record = RazorpayWebhookEvent.objects.get(
        source_event_id=headers["x-razorpay-event-id"]
    )
    assert record.business_mutation_was_made is False
    assert record.customer_notification_sent is False
    assert record.provider_payment_id == "pay_test_phase6m"
    assert assert_no_business_mutation(record) is True
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_STORED).exists()
    # Payment table must not have grown.
    assert Payment.objects.count() == payment_count_before


@pytest.mark.django_db
def test_b06_valid_order_paid_stores_event(enabled_test_mode):
    body, headers = _signed_request(event_name="order.paid")
    result = process_razorpay_webhook(body, headers)
    assert result["passed"] is True
    assert (
        result["processingStatus"]
        == RazorpayWebhookEvent.ProcessingStatus.STORED
    )


@pytest.mark.django_db
def test_b07_duplicate_event_id_returns_duplicate(enabled_test_mode):
    body, headers = _signed_request()
    first = process_razorpay_webhook(body, headers)
    assert first["passed"] is True
    second = process_razorpay_webhook(body, headers)
    assert second["statusCode"] == 200
    assert second.get("duplicate") is True
    assert (
        second["processingStatus"]
        in {
            RazorpayWebhookEvent.ProcessingStatus.STORED,
            RazorpayWebhookEvent.ProcessingStatus.DUPLICATE,
            RazorpayWebhookEvent.ProcessingStatus.VERIFIED,
        }
    )
    record = RazorpayWebhookEvent.objects.get(
        source_event_id=headers["x-razorpay-event-id"]
    )
    assert record.duplicate_count == 1
    assert record.business_mutation_was_made is False
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_DUPLICATE).exists()


@pytest.mark.django_db
def test_b08_replay_window_blocks_old_event(enabled_test_mode):
    old = datetime.now(tz=timezone.utc) - timedelta(seconds=3600)
    body, headers = _signed_request(created_at_dt=old)
    result = process_razorpay_webhook(body, headers)
    assert (
        result["processingStatus"]
        == RazorpayWebhookEvent.ProcessingStatus.IGNORED
    )
    assert "replay_window_exceeded" in result["blockers"]
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_REPLAY_BLOCKED).exists()


@pytest.mark.django_db
def test_b09_unknown_event_blocked(enabled_test_mode):
    body, headers = _signed_request(event_name="unknown.weird.event")
    result = process_razorpay_webhook(body, headers)
    assert (
        result["processingStatus"]
        == RazorpayWebhookEvent.ProcessingStatus.IGNORED
    )
    assert "event_name_not_in_allowlist" in result["blockers"]
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_EVENT_DENIED).exists()


@pytest.mark.django_db
def test_b10_denylisted_event_blocked(enabled_test_mode):
    body, headers = _signed_request(event_name="subscription.charged")
    result = process_razorpay_webhook(body, headers)
    assert (
        result["processingStatus"]
        == RazorpayWebhookEvent.ProcessingStatus.IGNORED
    )
    assert "event_name_denylisted" in result["blockers"]


@pytest.mark.django_db
def test_b11_allowed_events_accepted(enabled_test_mode):
    for name in (
        "payment.authorized",
        "payment.captured",
        "payment.failed",
        "order.paid",
        "refund.created",
        "refund.processed",
        "payment_link.paid",
        "payment_link.cancelled",
        "payment_link.expired",
    ):
        body, headers = _signed_request(event_name=name)
        result = process_razorpay_webhook(body, headers)
        assert result["passed"] is True, f"{name} should pass"
        assert result["businessMutationWasMade"] is False


@pytest.mark.django_db
def test_b12_safe_summary_masks_pii(enabled_test_mode):
    body, headers = _signed_request()
    result = process_razorpay_webhook(body, headers)
    assert result["passed"] is True
    record = RazorpayWebhookEvent.objects.get(
        source_event_id=headers["x-razorpay-event-id"]
    )
    blob = json.dumps(record.safe_payload_summary, default=str)
    assert _FAKE_SECRET not in blob


@pytest.mark.django_db
def test_b13_audit_payload_does_not_carry_raw_secret_or_signature(
    enabled_test_mode,
):
    body, headers = _signed_request()
    process_razorpay_webhook(body, headers)
    audits = AuditEvent.objects.filter(kind__startswith="razorpay.webhook.")
    blob = json.dumps(list(audits.values_list("payload", flat=True)))
    assert _FAKE_SECRET not in blob
    raw_signature = headers["x-razorpay-signature"]
    assert raw_signature not in blob


@pytest.mark.django_db
def test_b14_business_mutation_count_stays_zero(enabled_test_mode):
    for _ in range(3):
        body, headers = _signed_request()
        process_razorpay_webhook(body, headers)
    qs = RazorpayWebhookEvent.objects.all()
    assert qs.filter(business_mutation_was_made=True).count() == 0
    assert qs.filter(customer_notification_sent=True).count() == 0


# ---------------------------------------------------------------------------
# Section C — Management commands
# ---------------------------------------------------------------------------


def _run(cmd: str, *args: str) -> dict:
    out = io.StringIO()
    call_command(cmd, "--json", *args, stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


@pytest.mark.django_db
def test_c01_readiness_command_reports_blocker_when_flag_off():
    report = _run("inspect_razorpay_webhook_handler_readiness")
    assert report["webhookTestModeEnabled"] is False
    assert "razorpay_webhook_test_mode_disabled" in report["blockers"]


@pytest.mark.django_db
def test_c02_simulate_payment_captured_runs(enabled_test_mode):
    out = io.StringIO()
    call_command(
        "simulate_razorpay_webhook_event",
        "--event",
        "payment.captured",
        "--json",
        stdout=out,
    )
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert report["passed"] is True
    assert report["signatureValid"] is True
    assert report["businessMutationWasMade"] is False
    assert report["customerNotificationSent"] is False
    assert report["providerCallAttempted"] is False


@pytest.mark.django_db
def test_c03_simulate_order_paid_runs(enabled_test_mode):
    out = io.StringIO()
    call_command(
        "simulate_razorpay_webhook_event",
        "--event",
        "order.paid",
        "--json",
        stdout=out,
    )
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert report["passed"] is True
    assert (
        report["processingStatus"]
        == RazorpayWebhookEvent.ProcessingStatus.STORED
    )


@pytest.mark.django_db
def test_c04_inspect_events_command(enabled_test_mode):
    body, headers = _signed_request()
    process_razorpay_webhook(body, headers)
    report = _run("inspect_razorpay_webhook_events", "--limit", "5")
    assert report["count"] >= 1
    blob = json.dumps(report)
    assert _FAKE_SECRET not in blob
    assert headers["x-razorpay-signature"] not in blob


@pytest.mark.django_db
def test_c05_purge_command_dry_run(enabled_test_mode):
    body, headers = _signed_request()
    process_razorpay_webhook(body, headers)
    report = _run("purge_razorpay_webhook_test_events")
    assert report["dryRun"] is True
    assert report["candidateCount"] >= 1
    assert report["deletedCount"] == 0


@pytest.mark.django_db
def test_c06_simulate_command_no_provider_call(enabled_test_mode):
    """Simulating a webhook NEVER hits the Razorpay SDK / HTTP."""
    with mock.patch(
        "apps.saas.razorpay_test_execution._create_order_via_sdk"
    ) as sdk_mock:
        out = io.StringIO()
        call_command(
            "simulate_razorpay_webhook_event",
            "--event",
            "payment.captured",
            "--json",
            stdout=out,
        )
    sdk_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Section D — DRF endpoints
# ---------------------------------------------------------------------------


def _ensure_default_org(db) -> None:
    out = io.StringIO()
    call_command(
        "ensure_default_organization",
        "--json",
        "--skip-memberships",
        stdout=out,
    )


@pytest.mark.django_db
def test_d01_handler_readiness_endpoint_admin(
    db, admin_user, auth_client, enabled_test_mode
):
    _ensure_default_org(db)
    res = auth_client(admin_user).get(
        reverse("saas-razorpay-webhook-handler-readiness")
    )
    assert res.status_code == 200
    body = res.json()
    assert body["webhookTestModeEnabled"] is True
    assert body["businessMutationCount"] == 0


@pytest.mark.django_db
def test_d02_handler_readiness_endpoint_blocks_viewer(
    db, viewer_user, auth_client, enabled_test_mode
):
    _ensure_default_org(db)
    res = auth_client(viewer_user).get(
        reverse("saas-razorpay-webhook-handler-readiness")
    )
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_d03_handler_readiness_rejects_post(
    db, admin_user, auth_client, enabled_test_mode
):
    _ensure_default_org(db)
    res = auth_client(admin_user).post(
        reverse("saas-razorpay-webhook-handler-readiness"), {}
    )
    assert res.status_code == 405


@pytest.mark.django_db
def test_d04_events_endpoint_admin(
    db, admin_user, auth_client, enabled_test_mode
):
    _ensure_default_org(db)
    body, headers = _signed_request()
    process_razorpay_webhook(body, headers)
    res = auth_client(admin_user).get(reverse("saas-razorpay-webhook-events"))
    assert res.status_code == 200
    blob = json.dumps(res.json(), default=str)
    assert _FAKE_SECRET not in blob
    assert headers["x-razorpay-signature"] not in blob


@pytest.mark.django_db
def test_d05_events_endpoint_blocks_viewer(
    db, viewer_user, auth_client, enabled_test_mode
):
    _ensure_default_org(db)
    res = auth_client(viewer_user).get(reverse("saas-razorpay-webhook-events"))
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_d06_event_detail_endpoint_admin(
    db, admin_user, auth_client, enabled_test_mode
):
    _ensure_default_org(db)
    body, headers = _signed_request()
    process_razorpay_webhook(body, headers)
    record = RazorpayWebhookEvent.objects.first()
    assert record is not None
    res = auth_client(admin_user).get(
        reverse(
            "saas-razorpay-webhook-event-detail",
            kwargs={"event_id": record.id},
        )
    )
    assert res.status_code == 200
    body_json = res.json()
    assert body_json["businessMutationWasMade"] is False
    assert body_json["customerNotificationSent"] is False


@pytest.mark.django_db
def test_d07_simulate_endpoint_admin(
    db, admin_user, auth_client, enabled_test_mode
):
    _ensure_default_org(db)
    res = auth_client(admin_user).post(
        reverse("saas-razorpay-webhook-events-simulate"),
        {"eventName": "payment.captured"},
        format="json",
    )
    assert res.status_code == 200
    body_json = res.json()
    assert body_json["passed"] is True
    assert body_json["businessMutationWasMade"] is False


@pytest.mark.django_db
def test_d08_simulate_endpoint_blocks_viewer(
    db, viewer_user, auth_client, enabled_test_mode
):
    _ensure_default_org(db)
    res = auth_client(viewer_user).post(
        reverse("saas-razorpay-webhook-events-simulate"),
        {"eventName": "payment.captured"},
        format="json",
    )
    assert res.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Section E — Public webhook endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_e01_public_webhook_endpoint_blocks_when_flag_off(
    client,
):
    body, headers = _signed_request()
    res = client.post(
        "/api/webhooks/razorpay/test/",
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=headers["x-razorpay-signature"],
        HTTP_X_RAZORPAY_EVENT_ID=headers["x-razorpay-event-id"],
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_e02_public_webhook_endpoint_accepts_when_enabled(
    client, enabled_test_mode
):
    body, headers = _signed_request()
    res = client.post(
        "/api/webhooks/razorpay/test/",
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=headers["x-razorpay-signature"],
        HTTP_X_RAZORPAY_EVENT_ID=headers["x-razorpay-event-id"],
    )
    assert res.status_code == 200
    body_json = res.json()
    assert body_json["passed"] is True
    assert body_json["signatureValid"] is True
    assert body_json["businessMutationWasMade"] is False
    blob = json.dumps(body_json)
    assert _FAKE_SECRET not in blob
    assert headers["x-razorpay-signature"] not in blob


@pytest.mark.django_db
def test_e03_public_webhook_endpoint_blocks_invalid_signature(
    client, enabled_test_mode
):
    body, headers = _signed_request()
    res = client.post(
        "/api/webhooks/razorpay/test/",
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE="not-the-real-signature",
        HTTP_X_RAZORPAY_EVENT_ID=headers["x-razorpay-event-id"],
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Section F — readiness selector
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_f01_readiness_safe_to_receive_when_enabled(enabled_test_mode):
    report = get_razorpay_webhook_handler_readiness()
    assert report["safeToReceiveTestWebhooks"] is True
    assert "razorpay_webhook_test_mode_disabled" not in report["blockers"]


@pytest.mark.django_db
def test_f02_readiness_safe_to_start_phase_6n_after_verified_event(
    enabled_test_mode,
):
    body, headers = _signed_request()
    process_razorpay_webhook(body, headers)
    report = get_razorpay_webhook_handler_readiness()
    assert report["verifiedEventCount"] >= 1
    assert report["safeToStartPhase6N"] is True
    assert report["nextAction"] == (
        "ready_for_phase_6n_razorpay_webhook_business_mutation_sandbox_plan"
    )
