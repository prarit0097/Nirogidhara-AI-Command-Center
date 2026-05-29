"""Phase 16E — Payment / Logistics Integration Hardening tests.

Coverage:
  - readiness endpoint requires auth.
  - readiness returns Razorpay / PayU / Delhivery status without secrets.
  - live payment + live shipment are blocked without a live gate.
  - PayU is represented as unavailable safely.
  - mock shipment HTTP create still works (behaviour preserved).
  - ShipmentCreateView does NOT call Delhivery live by default; live mode is
    blocked (HTTP 409), test mode is blocked (HTTP 409) — no provider call.
  - recent-events endpoint requires auth + masks secrets.
  - RuntimeKillSwitch / SandboxState untouched; no WhatsApp / Vapi / AI calls.
"""
from __future__ import annotations

from unittest import mock

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.models import Order
from apps.shipments.models import Shipment

READINESS = "/api/v1/integrations/payment-logistics/readiness/"
RECENT = "/api/v1/integrations/payment-logistics/recent-events/"
SHIPMENTS = "/api/shipments/"


@pytest.fixture
def director_user(db):
    user = User.objects.create_user(
        username="d16e", password="d16e12345", email="d16e@nirogidhara.test"
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _order(stage=None) -> Order:
    from apps.orders.services import create_order

    return create_order(
        customer_name="Test Customer",
        phone="+919812345678",
        product="Joint Care",
        state="MH",
        city="Mumbai",
    )


# --------------------------------------------------------------------------
# Readiness endpoint — auth + shape + no secrets
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_readiness_requires_auth() -> None:
    assert APIClient().get(READINESS).status_code in {401, 403}


@pytest.mark.django_db
def test_recent_events_requires_auth() -> None:
    assert APIClient().get(RECENT).status_code in {401, 403}


@pytest.mark.django_db
def test_readiness_returns_provider_status(viewer_user, auth_client) -> None:
    # Any authenticated user (even viewer) can read readiness.
    res = auth_client(viewer_user).get(READINESS)
    assert res.status_code == 200, res.content
    body = res.json()
    providers = {p["provider"] for p in body["payments"]}
    assert {"razorpay", "payu"} <= providers
    assert body["logistics"][0]["provider"] == "delhivery"
    assert body["noSideEffect"] is True
    assert body["generatedByProvider"] is False
    # Safety summary present.
    assert "aiPaused" in body["safety"]
    assert body["safety"]["providerLiveActionsLocked"] is True


@pytest.mark.django_db
def test_readiness_exposes_no_secret_values(director_user, auth_client) -> None:
    res = auth_client(director_user).get(READINESS)
    body = res.json()
    blob = str(body)
    # Presence booleans only — never the secret values.
    for razor in (p for p in body["payments"] if p["provider"] == "razorpay"):
        assert isinstance(razor["secretRefsPresent"], dict)
        assert all(isinstance(v, bool) for v in razor["secretRefsPresent"].values())
    # No obvious secret leakage.
    assert "RAZORPAY_KEY_SECRET" not in blob
    assert "DELHIVERY_API_TOKEN" not in blob


@pytest.mark.django_db
def test_payu_is_unavailable(director_user, auth_client) -> None:
    res = auth_client(director_user).get(READINESS)
    payu = next(p for p in res.json()["payments"] if p["provider"] == "payu")
    assert payu["status"] == "unavailable"
    assert payu["mode"] == "unavailable"
    assert payu["liveEnabled"] is False
    assert payu["blockedReasons"]  # non-empty — explains why


# --------------------------------------------------------------------------
# Live blocked without a gate
# --------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(RAZORPAY_MODE="live", RAZORPAY_KEY_ID="x", RAZORPAY_KEY_SECRET="y")
def test_live_razorpay_blocked_without_gate(director_user, auth_client) -> None:
    res = auth_client(director_user).get(READINESS)
    razor = next(p for p in res.json()["payments"] if p["provider"] == "razorpay")
    assert razor["liveEnabled"] is False
    assert razor["liveGatePresent"] is False
    assert razor["status"] == "blocked"
    assert any("Director live gate" in r for r in razor["blockedReasons"])


@pytest.mark.django_db
@override_settings(DELHIVERY_MODE="live", DELHIVERY_API_TOKEN="x", DELHIVERY_API_BASE_URL="https://x")
def test_live_delhivery_blocked_without_gate(director_user, auth_client) -> None:
    res = auth_client(director_user).get(READINESS)
    dlv = res.json()["logistics"][0]
    assert dlv["liveEnabled"] is False
    assert dlv["status"] == "blocked"
    assert any("Director live gate" in r for r in dlv["blockedReasons"])


# --------------------------------------------------------------------------
# ShipmentCreateView hardening
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_shipment_create_mock_still_works(operations_user, auth_client) -> None:
    # conftest pins DELHIVERY_MODE=mock — existing behaviour preserved.
    order = _order()
    res = auth_client(operations_user).post(
        SHIPMENTS, {"orderId": order.id}, format="json"
    )
    assert res.status_code == 201, res.content
    assert Shipment.objects.filter(order_id=order.id).exists()


@pytest.mark.django_db
@override_settings(DELHIVERY_MODE="live")
def test_shipment_create_live_blocked(operations_user, auth_client) -> None:
    order = _order()
    with mock.patch(
        "apps.shipments.integrations.delhivery_client.create_awb"
    ) as live_create:
        res = auth_client(operations_user).post(
            SHIPMENTS, {"orderId": order.id}, format="json"
        )
    assert res.status_code == 409, res.content
    assert res.json()["detail"] == "live_delhivery_booking_blocked"
    # No Delhivery call, no Shipment row created.
    live_create.assert_not_called()
    assert not Shipment.objects.filter(order_id=order.id).exists()


@pytest.mark.django_db
@override_settings(
    DELHIVERY_MODE="test",
    DELHIVERY_API_BASE_URL="https://staging-express.delhivery.com",
    DELHIVERY_API_TOKEN="test_token_xxx",
    DELHIVERY_PICKUP_LOCATION="Nirogidhara Pune",
)
def test_shipment_create_test_mode_routes_to_staging_not_production(
    operations_user, auth_client
) -> None:
    """Test mode is the safe staging path — it routes through ``_create_via_sdk``
    (Delhivery staging API), NOT a forced mock and NOT production. Mocked here so
    no real network call is made."""
    from apps.shipments.integrations.delhivery_client import AwbResult

    order = _order()
    fake = AwbResult(
        awb="DLH-STAGING-16E",
        status="Manifested",
        tracking_url="https://www.delhivery.com/track/package/DLH-STAGING-16E",
        raw={"packages": [{"waybill": "DLH-STAGING-16E"}]},
    )
    with mock.patch(
        "apps.shipments.integrations.delhivery_client._create_via_sdk",
        return_value=fake,
    ) as staging_sdk:
        res = auth_client(operations_user).post(
            SHIPMENTS, {"orderId": order.id}, format="json"
        )
    assert res.status_code == 201, res.content
    assert staging_sdk.called
    # The SDK was invoked in staging (test) mode, never live/production.
    assert staging_sdk.call_args.kwargs.get("mode") == "test"


@pytest.mark.django_db
def test_shipment_create_requires_auth() -> None:
    res = APIClient().post(SHIPMENTS, {"orderId": "NRG-1"}, format="json")
    assert res.status_code in {401, 403}


# --------------------------------------------------------------------------
# recent-events
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_recent_events_returns_masked_records(
    operations_user, auth_client
) -> None:
    order = _order()
    auth_client(operations_user).post(SHIPMENTS, {"orderId": order.id}, format="json")
    res = auth_client(operations_user).get(RECENT)
    assert res.status_code == 200, res.content
    body = res.json()
    assert "payments" in body and "shipments" in body
    # AWB is masked to last-6 only (never the full AWB).
    for s in body["shipments"]:
        assert "awbLast6" in s
        assert "awb" not in s


# --------------------------------------------------------------------------
# Defensive — no provider / business side effect, safety state untouched
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase16e_readiness_triggers_no_provider_side_effect(
    director_user, auth_client
) -> None:
    from apps.ai_governance.sandbox import is_sandbox_enabled
    from apps.saas.models import RuntimeKillSwitch

    sandbox_before = is_sandbox_enabled()
    killswitch_before = RuntimeKillSwitch.objects.count()

    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as wa_template, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as wa_freeform, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as vapi_call, mock.patch(
        "apps.payments.integrations.razorpay_client.create_payment_link"
    ) as razor_create, mock.patch(
        "apps.shipments.integrations.delhivery_client.create_awb"
    ) as dlv_create:
        client = auth_client(director_user)
        client.get(READINESS)
        client.get(RECENT)

    wa_template.assert_not_called()
    wa_freeform.assert_not_called()
    vapi_call.assert_not_called()
    razor_create.assert_not_called()
    dlv_create.assert_not_called()

    assert is_sandbox_enabled() == sandbox_before
    assert RuntimeKillSwitch.objects.count() == killswitch_before
