"""Phase 2B tests — Razorpay payment-link integration + webhook receiver.

Covers:
1. Mock-mode payment-link creation works without network access.
2. Test-mode payment-link creation routes through the SDK adapter (we patch
   ``_create_via_sdk`` so no real network call is made).
3. Webhook ``payment_link.paid`` flips Payment to Paid + bubbles up to Order.
4. Webhook duplicate event is idempotent (no double-update).
5. Webhook with invalid signature returns 400.
6. Auth: anonymous gets 401, viewer gets 403, operations gets 201.
7. Audit ledger captures both ``payment.link_created`` and ``payment.received``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.orders.models import Order
from apps.payments.integrations.razorpay_client import PaymentLinkResult
from apps.payments.models import Payment, WebhookEvent

WEBHOOK_SECRET = "test-webhook-secret"


# ---------- helpers ----------


def _make_order(**overrides) -> Order:
    defaults = dict(
        id="NRG-RZP-001",
        customer_name="Razorpay Demo",
        phone="+91 9000000000",
        product="Weight Management",
        quantity=1,
        amount=2640,
        discount_pct=12,
        advance_paid=False,
        advance_amount=0,
        state="Maharashtra",
        city="Pune",
        rto_risk=Order.RtoRisk.LOW,
        rto_score=15,
        agent="Calling AI · Vaani-3",
        stage=Order.Stage.CONFIRMED,
    )
    defaults.update(overrides)
    return Order.objects.create(**defaults)


def _create_payment(order: Order, **overrides) -> Payment:
    defaults = dict(
        id="PAY-RZP-001",
        order_id=order.id,
        customer=order.customer_name,
        amount=499,
        gateway=Payment.Gateway.RAZORPAY,
        status=Payment.Status.PENDING,
        type=Payment.Type.ADVANCE,
        gateway_reference_id="plink_test_demo",
        payment_url="https://rzp.example/pay/plink_test_demo",
    )
    defaults.update(overrides)
    return Payment.objects.create(**defaults)


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _post_webhook(client: APIClient, event: dict, *, secret: str = WEBHOOK_SECRET, signature: str | None = None):
    body = json.dumps(event).encode("utf-8")
    sig = signature if signature is not None else _sign(body, secret)
    return client.post(
        "/api/webhooks/razorpay/",
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sig,
    )


# ---------- 1. Mock mode ----------


def test_create_mock_payment_link_works(operations_user, auth_client, settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    order = _make_order()
    client = auth_client(operations_user)
    res = client.post(
        "/api/payments/links/",
        {
            "orderId": order.id,
            "amount": 499,
            "customerName": "Razorpay Demo",
            "customerPhone": "9000000000",
            "customerEmail": "demo@example.com",
        },
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    # Both flat (Phase 2B) + nested (Phase 2A) keys are present.
    assert body["paymentId"].startswith("PAY-")
    assert body["gateway"] == "razorpay"
    assert body["status"] == "pending"
    assert body["paymentUrl"].startswith("https://razorpay.example/pay/")
    assert body["gatewayReferenceId"].startswith("plink_mock_")
    assert body["payment"]["paymentUrl"] == body["paymentUrl"]
    # Persistence: Payment row + reference id stored.
    payment = Payment.objects.get(pk=body["paymentId"])
    assert payment.gateway_reference_id == body["gatewayReferenceId"]
    assert payment.payment_url == body["paymentUrl"]


# ---------- 2. Test-mode adapter mocked ----------


def test_create_test_mode_payment_link_uses_adapter(operations_user, auth_client, settings) -> None:
    settings.RAZORPAY_MODE = "test"
    settings.RAZORPAY_KEY_ID = "rzp_test_xxx"
    settings.RAZORPAY_KEY_SECRET = "secret_xxx"
    order = _make_order(id="NRG-RZP-TEST")
    client = auth_client(operations_user)

    fake = PaymentLinkResult(
        plink_id="plink_TestSandbox123",
        short_url="https://rzp.io/i/abcd1234",
        status="created",
        raw={"id": "plink_TestSandbox123", "short_url": "https://rzp.io/i/abcd1234"},
    )

    with patch(
        "apps.payments.integrations.razorpay_client._create_via_sdk",
        return_value=fake,
    ) as mock_sdk:
        res = client.post(
            "/api/payments/links/",
            {
                "orderId": order.id,
                "amount": 499,
                "customerName": "Razorpay Demo",
                "customerPhone": "9000000000",
                "customerEmail": "demo@example.com",
            },
            format="json",
        )

    assert res.status_code == 201
    assert mock_sdk.called
    body = res.json()
    assert body["gatewayReferenceId"] == "plink_TestSandbox123"
    assert body["paymentUrl"] == "https://rzp.io/i/abcd1234"


# ---------- 3. Auth + role gating ----------


def test_payment_link_create_requires_authentication(settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    order = _make_order(id="NRG-RZP-AUTH")
    res = APIClient().post(
        "/api/payments/links/",
        {
            "orderId": order.id,
            "amount": 499,
            "customerName": "Anon",
            "customerPhone": "9000000000",
            "customerEmail": "a@b.com",
        },
        format="json",
    )
    assert res.status_code == 401


def test_viewer_cannot_create_payment_link(viewer_user, auth_client, settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    order = _make_order(id="NRG-RZP-VIEW")
    client = auth_client(viewer_user)
    res = client.post(
        "/api/payments/links/",
        {
            "orderId": order.id,
            "amount": 499,
            "customerName": "Viewer",
            "customerPhone": "9000000000",
            "customerEmail": "v@b.com",
        },
        format="json",
    )
    assert res.status_code == 403


# ---------- 4. AuditEvents ----------


def test_audit_events_created_for_link_and_received(operations_user, auth_client, settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    settings.RAZORPAY_WEBHOOK_SECRET = WEBHOOK_SECRET
    order = _make_order(id="NRG-RZP-AUDIT")
    client = auth_client(operations_user)

    AuditEvent.objects.all().delete()

    create_res = client.post(
        "/api/payments/links/",
        {
            "orderId": order.id,
            "amount": 499,
            "customerName": "Audit Demo",
            "customerPhone": "9000000000",
            "customerEmail": "audit@b.com",
        },
        format="json",
    )
    assert create_res.status_code == 201
    plink = create_res.json()["gatewayReferenceId"]

    # Trigger paid webhook so the post_save signal fires `payment.received`.
    paid_event = {
        "id": "evt_paid_audit",
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": {"id": plink}}},
    }
    paid_res = _post_webhook(APIClient(), paid_event)
    assert paid_res.status_code == 200

    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "payment.link_created" in kinds
    assert "payment.received" in kinds


# ---------- 5. Webhook: paid event updates payment + order ----------


def test_webhook_payment_link_paid_updates_payment(settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    settings.RAZORPAY_WEBHOOK_SECRET = WEBHOOK_SECRET
    order = _make_order(id="NRG-RZP-PAID")
    payment = _create_payment(
        order, id="PAY-RZP-PAID-1", gateway_reference_id="plink_paid_demo"
    )
    event = {
        "id": "evt_paid_demo",
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": {"id": "plink_paid_demo"}}},
    }
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID
    order.refresh_from_db()
    assert order.payment_status == Order.PaymentStatus.PAID
    assert order.advance_paid is True
    assert order.advance_amount == payment.amount
    # The idempotency table now has the event recorded.
    assert WebhookEvent.objects.filter(event_id="evt_paid_demo").exists()


# ---------- 6. Webhook: duplicate event is idempotent ----------


def test_webhook_duplicate_event_idempotent(settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    settings.RAZORPAY_WEBHOOK_SECRET = WEBHOOK_SECRET
    order = _make_order(id="NRG-RZP-DUP")
    payment = _create_payment(
        order, id="PAY-RZP-DUP-1", gateway_reference_id="plink_dup_demo"
    )
    event = {
        "id": "evt_dup_demo",
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": {"id": "plink_dup_demo"}}},
    }
    client = APIClient()
    first = _post_webhook(client, event)
    second = _post_webhook(client, event)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["detail"] == "duplicate"
    assert WebhookEvent.objects.filter(event_id="evt_dup_demo").count() == 1


# ---------- 7. Webhook: invalid signature returns 400 ----------


def test_webhook_invalid_signature_returns_400(settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    settings.RAZORPAY_WEBHOOK_SECRET = WEBHOOK_SECRET
    event = {
        "id": "evt_bad_sig",
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": {"id": "plink_anything"}}},
    }
    res = _post_webhook(APIClient(), event, signature="deadbeef")
    assert res.status_code == 400
    assert res.json()["detail"] == "invalid signature"
    assert not WebhookEvent.objects.exists()


# ---------- 8. Webhook: missing signature also rejected ----------


def test_webhook_missing_signature_returns_400(settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    settings.RAZORPAY_WEBHOOK_SECRET = WEBHOOK_SECRET
    event = {"id": "evt_nosig", "event": "payment_link.paid", "payload": {}}
    body = json.dumps(event).encode("utf-8")
    res = APIClient().post(
        "/api/webhooks/razorpay/", data=body, content_type="application/json"
    )
    assert res.status_code == 400


# ---------- 9. Webhook: unknown event ignored gracefully ----------


def test_webhook_unknown_event_ignored(settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    settings.RAZORPAY_WEBHOOK_SECRET = WEBHOOK_SECRET
    event = {"id": "evt_unknown", "event": "order.created", "payload": {}}
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    assert res.json()["detail"] == "ignored"


# ---------- 10. Webhook: payment_link.expired flips to Expired ----------


def test_webhook_expired_updates_status(settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    settings.RAZORPAY_WEBHOOK_SECRET = WEBHOOK_SECRET
    order = _make_order(id="NRG-RZP-EXP")
    payment = _create_payment(
        order, id="PAY-RZP-EXP-1", gateway_reference_id="plink_exp_demo"
    )
    event = {
        "id": "evt_exp_demo",
        "event": "payment_link.expired",
        "payload": {"payment_link": {"entity": {"id": "plink_exp_demo"}}},
    }
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.EXPIRED


# ---------- 11. razorpay_client.create_payment_link mock-mode unit test ----------


def test_client_mock_mode_returns_deterministic_url(settings) -> None:
    settings.RAZORPAY_MODE = "mock"
    from apps.payments.integrations import razorpay_client

    result_a = razorpay_client.create_payment_link(
        order_id="NRG-12345", amount=499, customer_name="A"
    )
    result_b = razorpay_client.create_payment_link(
        order_id="NRG-12345", amount=499, customer_name="A"
    )
    assert result_a.plink_id == result_b.plink_id
    assert result_a.short_url == "https://razorpay.example/pay/plink_mock_NRG_12345_499"


# ---------- 12. signature verification helper unit test ----------


def test_signature_helper_round_trip() -> None:
    from apps.payments.integrations.razorpay_client import verify_webhook_signature

    body = b'{"event":"payment_link.paid"}'
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig, secret="secret") is True
    assert verify_webhook_signature(body, sig, secret="wrong") is False
    assert verify_webhook_signature(body, "", secret="secret") is False
    assert verify_webhook_signature(body, sig, secret="") is False
