"""Phase 2C tests — Delhivery courier adapter + tracking webhook receiver.

Mirrors the structure of ``test_razorpay.py``:

1. Mock-mode AWB creation works without network access.
2. Test-mode AWB creation routes through the SDK adapter (we patch
   ``_create_via_sdk`` so no real network call is made).
3. Webhook ``delivered`` flips Shipment + Order to Delivered, audit logged.
4. Webhook ``ndr`` flags shipment risk + bumps Order rto_risk to High.
5. Webhook ``rto_initiated`` moves Order to RTO + writes danger audit.
6. Webhook duplicate event is idempotent.
7. Webhook with invalid signature returns 400.
8. Auth: anonymous gets 401, viewer gets 403, operations gets 201.
9. Audit ledger captures ``shipment.created`` + ``shipment.delivered``.
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
from apps.payments.models import WebhookEvent
from apps.shipments.integrations.delhivery_client import AwbResult
from apps.shipments.models import Shipment

WEBHOOK_SECRET = "test-delhivery-secret"


# ---------- helpers ----------


def _make_order(**overrides) -> Order:
    defaults = dict(
        id="NRG-DLV-001",
        customer_name="Delhivery Demo",
        phone="+91 9000000000",
        product="Weight Management",
        quantity=1,
        amount=2640,
        discount_pct=12,
        advance_paid=True,
        advance_amount=499,
        state="Maharashtra",
        city="Pune",
        rto_risk=Order.RtoRisk.LOW,
        rto_score=15,
        agent="Calling AI · Vaani-3",
        stage=Order.Stage.DISPATCHED,
    )
    defaults.update(overrides)
    return Order.objects.create(**defaults)


def _make_shipment(order: Order, **overrides) -> Shipment:
    defaults = dict(
        awb="DLH12345678",
        order_id=order.id,
        customer=order.customer_name,
        state=order.state,
        city=order.city,
        status="Pickup Scheduled",
        eta="3 days",
        courier="Delhivery",
    )
    defaults.update(overrides)
    return Shipment.objects.create(**defaults)


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _post_webhook(
    client: APIClient,
    event: dict,
    *,
    secret: str = WEBHOOK_SECRET,
    signature: str | None = None,
):
    body = json.dumps(event).encode("utf-8")
    sig = signature if signature is not None else _sign(body, secret)
    return client.post(
        "/api/webhooks/delhivery/",
        data=body,
        content_type="application/json",
        HTTP_X_DELHIVERY_SIGNATURE=sig,
    )


# ---------- 1. Mock mode ----------


def test_create_mock_shipment_returns_dlh_awb(operations_user, auth_client, settings) -> None:
    settings.DELHIVERY_MODE = "mock"
    order = _make_order()
    client = auth_client(operations_user)
    res = client.post("/api/shipments/", {"orderId": order.id}, format="json")
    assert res.status_code == 201
    body = res.json()
    assert body["awb"].startswith("DLH")
    assert len(body["awb"]) == 11  # DLH + 8 digits
    assert body["orderId"] == order.id
    assert body["status"] == "Pickup Scheduled"
    assert body["trackingUrl"].endswith(body["awb"])
    assert len(body["timeline"]) == 5
    # Persistence: row exists, raw response captured.
    shipment = Shipment.objects.get(awb=body["awb"])
    assert shipment.delhivery_status == "Pickup Scheduled"
    assert shipment.tracking_url == body["trackingUrl"]
    assert shipment.raw_response.get("mode") == "mock"
    # Parent order received the AWB.
    order.refresh_from_db()
    assert order.awb == body["awb"]


# ---------- 2. Test-mode adapter mocked ----------


def test_create_test_mode_shipment_uses_adapter(
    operations_user, auth_client, settings
) -> None:
    settings.DELHIVERY_MODE = "test"
    settings.DELHIVERY_API_BASE_URL = "https://staging-express.delhivery.com"
    settings.DELHIVERY_API_TOKEN = "test_token_xxx"
    settings.DELHIVERY_PICKUP_LOCATION = "Nirogidhara Pune"
    order = _make_order(id="NRG-DLV-TEST")
    client = auth_client(operations_user)

    fake = AwbResult(
        awb="DLH-STAGING-1",
        status="Manifested",
        tracking_url="https://www.delhivery.com/track/package/DLH-STAGING-1",
        raw={"packages": [{"waybill": "DLH-STAGING-1", "status": "Manifested"}]},
    )

    with patch(
        "apps.shipments.integrations.delhivery_client._create_via_sdk",
        return_value=fake,
    ) as mock_sdk:
        res = client.post("/api/shipments/", {"orderId": order.id}, format="json")

    assert res.status_code == 201
    assert mock_sdk.called
    body = res.json()
    assert body["awb"] == "DLH-STAGING-1"
    assert body["trackingUrl"] == fake.tracking_url


# ---------- 3. Auth + role gating ----------


def test_shipment_create_requires_authentication(settings) -> None:
    settings.DELHIVERY_MODE = "mock"
    order = _make_order(id="NRG-DLV-AUTH")
    res = APIClient().post("/api/shipments/", {"orderId": order.id}, format="json")
    assert res.status_code == 401


def test_viewer_cannot_create_shipment(viewer_user, auth_client, settings) -> None:
    settings.DELHIVERY_MODE = "mock"
    order = _make_order(id="NRG-DLV-VIEW")
    client = auth_client(viewer_user)
    res = client.post("/api/shipments/", {"orderId": order.id}, format="json")
    assert res.status_code == 403


# ---------- 4. Webhook: delivered event ----------


def test_webhook_delivered_updates_shipment_and_order(settings) -> None:
    settings.DELHIVERY_MODE = "mock"
    settings.DELHIVERY_WEBHOOK_SECRET = WEBHOOK_SECRET
    order = _make_order(id="NRG-DLV-PAID", stage=Order.Stage.OUT_FOR_DELIVERY)
    shipment = _make_shipment(order, awb="DLH00000001")
    event = {
        "id": "evt_delivered_demo",
        "event": "delivered",
        "awb": shipment.awb,
        "event_time": "2026-04-27T12:00:00Z",
    }
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    shipment.refresh_from_db()
    assert shipment.status == "Delivered"
    assert shipment.delhivery_status == "Delivered"
    order.refresh_from_db()
    assert order.stage == Order.Stage.DELIVERED
    assert WebhookEvent.objects.filter(event_id="evt_delivered_demo").exists()


# ---------- 5. Webhook: NDR risk flag ----------


def test_webhook_ndr_flags_risk(settings) -> None:
    settings.DELHIVERY_MODE = "mock"
    settings.DELHIVERY_WEBHOOK_SECRET = WEBHOOK_SECRET
    order = _make_order(id="NRG-DLV-NDR", rto_risk=Order.RtoRisk.LOW)
    shipment = _make_shipment(order, awb="DLH00000002")
    event = {
        "id": "evt_ndr_demo",
        "event": "ndr",
        "awb": shipment.awb,
        "reason": "Customer not available",
    }
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    shipment.refresh_from_db()
    assert shipment.status == "NDR"
    assert shipment.risk_flag == "NDR"
    order.refresh_from_db()
    assert order.rto_risk == Order.RtoRisk.HIGH
    assert order.rescue_status  # populated, not blank


# ---------- 6. Webhook: RTO initiated ----------


def test_webhook_rto_initiated_moves_order(settings) -> None:
    settings.DELHIVERY_MODE = "mock"
    settings.DELHIVERY_WEBHOOK_SECRET = WEBHOOK_SECRET
    order = _make_order(id="NRG-DLV-RTO", stage=Order.Stage.OUT_FOR_DELIVERY)
    shipment = _make_shipment(order, awb="DLH00000003")
    event = {
        "id": "evt_rto_demo",
        "event": "rto_initiated",
        "awb": shipment.awb,
    }
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    shipment.refresh_from_db()
    assert shipment.status == "RTO Initiated"
    assert shipment.risk_flag == "RTO"
    order.refresh_from_db()
    assert order.stage == Order.Stage.RTO


# ---------- 7. Webhook: duplicate event idempotent ----------


def test_webhook_duplicate_event_idempotent(settings) -> None:
    settings.DELHIVERY_MODE = "mock"
    settings.DELHIVERY_WEBHOOK_SECRET = WEBHOOK_SECRET
    order = _make_order(id="NRG-DLV-DUP")
    shipment = _make_shipment(order, awb="DLH00000004")
    event = {
        "id": "evt_dup_demo",
        "event": "delivered",
        "awb": shipment.awb,
    }
    client = APIClient()
    first = _post_webhook(client, event)
    second = _post_webhook(client, event)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["detail"] == "duplicate"
    assert WebhookEvent.objects.filter(event_id="evt_dup_demo").count() == 1


# ---------- 8. Webhook: invalid signature returns 400 ----------


def test_webhook_invalid_signature_returns_400(settings) -> None:
    settings.DELHIVERY_MODE = "mock"
    settings.DELHIVERY_WEBHOOK_SECRET = WEBHOOK_SECRET
    event = {"id": "evt_bad_sig", "event": "delivered", "awb": "DLH00000099"}
    res = _post_webhook(APIClient(), event, signature="deadbeef")
    assert res.status_code == 400
    assert res.json()["detail"] == "invalid signature"
    assert not WebhookEvent.objects.exists()


# ---------- 9. Webhook: unknown event ignored gracefully ----------


def test_webhook_unknown_event_ignored(settings) -> None:
    settings.DELHIVERY_MODE = "mock"
    settings.DELHIVERY_WEBHOOK_SECRET = WEBHOOK_SECRET
    event = {"id": "evt_unknown", "event": "lost_in_space", "awb": "DLH00000099"}
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    assert res.json()["detail"] == "ignored"


# ---------- 10. Audit ledger captures created + delivered ----------


def test_audit_events_for_shipment_created_and_delivered(
    operations_user, auth_client, settings
) -> None:
    settings.DELHIVERY_MODE = "mock"
    settings.DELHIVERY_WEBHOOK_SECRET = WEBHOOK_SECRET
    order = _make_order(id="NRG-DLV-AUDIT", stage=Order.Stage.DISPATCHED)
    client = auth_client(operations_user)

    AuditEvent.objects.all().delete()

    create_res = client.post("/api/shipments/", {"orderId": order.id}, format="json")
    assert create_res.status_code == 201
    awb = create_res.json()["awb"]

    delivered_event = {
        "id": "evt_audit_delivered",
        "event": "delivered",
        "awb": awb,
    }
    paid_res = _post_webhook(APIClient(), delivered_event)
    assert paid_res.status_code == 200

    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "shipment.created" in kinds
    assert "shipment.delivered" in kinds


# ---------- 11. delhivery_client.create_awb mock-mode unit test ----------


def test_client_mock_mode_returns_unique_dlh_awb(settings) -> None:
    settings.DELHIVERY_MODE = "mock"
    from apps.shipments.integrations import delhivery_client

    result = delhivery_client.create_awb(
        order_id="NRG-12345",
        customer_name="A",
        customer_phone="+91 9000000000",
        address_line="—",
        city="Pune",
        state="Maharashtra",
    )
    assert result.awb.startswith("DLH")
    assert len(result.awb) == 11
    assert result.tracking_url.endswith(result.awb)
    assert (result.raw or {}).get("mode") == "mock"


# ---------- 12. signature verification helper unit test ----------


def test_signature_helper_round_trip() -> None:
    from apps.shipments.integrations.delhivery_client import verify_webhook_signature

    body = b'{"event":"delivered"}'
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig, secret="secret") is True
    assert verify_webhook_signature(body, sig, secret="wrong") is False
    assert verify_webhook_signature(body, "", secret="secret") is False
    assert verify_webhook_signature(body, sig, secret="") is False
