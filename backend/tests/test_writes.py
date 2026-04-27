"""Phase 2A tests — auth, role gating, state machine, audit ledger.

These cover the 13 write endpoints introduced in Phase 2A. The Phase 1
read-endpoint suite stays in ``test_endpoints.py`` and continues to pass
unchanged.
"""
from __future__ import annotations

import re

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.crm.models import Lead
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.shipments.models import RescueAttempt, Shipment


# ---------- Helpers ----------


def _audit_kinds() -> list[str]:
    return list(AuditEvent.objects.values_list("kind", flat=True))


def _make_order(**overrides) -> Order:
    defaults = dict(
        id="NRG-90001",
        customer_name="Test Customer",
        phone="+91 9999999999",
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
        stage=Order.Stage.ORDER_PUNCHED,
    )
    defaults.update(overrides)
    return Order.objects.create(**defaults)


# ---------- 1-2. Auth + role gating ----------


def test_writes_require_authentication() -> None:
    res = APIClient().post(
        "/api/leads/",
        {"name": "Anon", "phone": "+91 9000000000", "state": "MH", "city": "Pune"},
        format="json",
    )
    assert res.status_code == 401


def test_viewer_blocked_from_writes(viewer_user, auth_client) -> None:
    client = auth_client(viewer_user)
    res = client.post(
        "/api/leads/",
        {"name": "Viewer", "phone": "+91 9000000001", "state": "MH", "city": "Pune"},
        format="json",
    )
    assert res.status_code == 403


# ---------- 3-5. CRM lead writes ----------


def test_operations_can_create_lead(operations_user, auth_client) -> None:
    client = auth_client(operations_user)
    before = AuditEvent.objects.count()
    res = client.post(
        "/api/leads/",
        {
            "name": "Suresh Patel",
            "phone": "+91 9000000010",
            "state": "Maharashtra",
            "city": "Pune",
            "language": "Marathi",
            "source": "Meta Ads",
            "campaign": "Monsoon Detox '25",
            "productInterest": "Weight Management",
        },
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Suresh Patel"
    assert body["productInterest"] == "Weight Management"
    assert Lead.objects.filter(pk=body["id"]).exists()
    assert "lead.created" in _audit_kinds()
    assert AuditEvent.objects.count() > before


def test_lead_update_logs_audit(operations_user, auth_client) -> None:
    Lead.objects.create(
        id="LD-99001",
        name="Old Name",
        phone="+91 9000000020",
        state="Maharashtra",
        city="Pune",
        language="Hindi",
        source="Meta Ads",
        campaign="X",
        product_interest="Weight Management",
    )
    AuditEvent.objects.all().delete()  # drop the lead.created from above
    client = auth_client(operations_user)
    res = client.patch(
        "/api/leads/LD-99001/",
        {"name": "New Name", "qualityScore": 88},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["name"] == "New Name"
    assert res.json()["qualityScore"] == 88
    assert "lead.updated" in _audit_kinds()


def test_lead_assign_logs_audit(operations_user, auth_client) -> None:
    Lead.objects.create(
        id="LD-99002",
        name="Unassigned",
        phone="+91 9000000021",
        state="Maharashtra",
        city="Pune",
        language="Hindi",
        source="Meta Ads",
        campaign="X",
        product_interest="Weight Management",
    )
    AuditEvent.objects.all().delete()
    client = auth_client(operations_user)
    res = client.post(
        "/api/leads/LD-99002/assign/",
        {"assignee": "Priya (Human)"},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["assignee"] == "Priya (Human)"
    assert "lead.assigned" in _audit_kinds()


# ---------- 6-7. Customer upsert ----------


def test_customer_upsert_create_branch(operations_user, auth_client) -> None:
    client = auth_client(operations_user)
    res = client.post(
        "/api/customers/",
        {
            "name": "New Customer",
            "phone": "+91 9000000030",
            "state": "Karnataka",
            "city": "Bengaluru",
            "language": "English",
            "productInterest": "Immunity Booster",
            "consent": {"call": True, "whatsapp": True, "marketing": False},
        },
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "New Customer"
    assert body["consent"] == {"call": True, "whatsapp": True, "marketing": False}
    assert "customer.upserted" in _audit_kinds()


def test_customer_upsert_update_branch(operations_user, auth_client, seeded) -> None:
    AuditEvent.objects.all().delete()
    client = auth_client(operations_user)
    res = client.patch(
        "/api/customers/CU-5000/",
        {"satisfaction": 5, "consent": {"marketing": True}},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["satisfaction"] == 5
    assert res.json()["consent"]["marketing"] is True
    assert "customer.upserted" in _audit_kinds()


# ---------- 8. Order create ----------


def test_create_order_succeeds_and_logs(operations_user, auth_client) -> None:
    client = auth_client(operations_user)
    before = AuditEvent.objects.count()
    res = client.post(
        "/api/orders/",
        {
            "customerName": "Rajesh Kumar",
            "phone": "+91 9000000040",
            "product": "Weight Management",
            "quantity": 1,
            "amount": 2640,
            "discountPct": 12,
            "advancePaid": True,
            "advanceAmount": 499,
            "state": "Maharashtra",
            "city": "Pune",
            "agent": "Calling AI · Vaani-3",
        },
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["customerName"] == "Rajesh Kumar"
    assert body["stage"] == "Order Punched"
    assert re.fullmatch(r"NRG-\d+", body["id"])
    assert Order.objects.filter(pk=body["id"]).exists()
    assert "order.created" in _audit_kinds()
    assert AuditEvent.objects.count() > before


# ---------- 9-10. Order transitions ----------


def test_order_transition_valid(operations_user, auth_client) -> None:
    order = _make_order(stage=Order.Stage.ORDER_PUNCHED)
    client = auth_client(operations_user)
    res = client.post(
        f"/api/orders/{order.id}/transition/",
        {"stage": "Confirmation Pending"},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["stage"] == "Confirmation Pending"
    assert "order.status_changed" in _audit_kinds()


def test_order_transition_invalid_blocked(operations_user, auth_client) -> None:
    order = _make_order(stage=Order.Stage.DELIVERED)
    client = auth_client(operations_user)
    res = client.post(
        f"/api/orders/{order.id}/transition/",
        {"stage": "Order Punched"},
        format="json",
    )
    assert res.status_code == 400
    body = res.json()
    assert "Cannot move from Delivered" in body["detail"]


def test_move_to_confirmation_convenience(operations_user, auth_client) -> None:
    order = _make_order(stage=Order.Stage.ORDER_PUNCHED)
    client = auth_client(operations_user)
    res = client.post(f"/api/orders/{order.id}/move-to-confirmation/", format="json")
    assert res.status_code == 200
    assert res.json()["stage"] == "Confirmation Pending"


# ---------- 12-14. Confirmation outcomes ----------


def test_confirm_order_outcome_confirmed(operations_user, auth_client) -> None:
    order = _make_order(stage=Order.Stage.CONFIRMATION_PENDING)
    client = auth_client(operations_user)
    res = client.post(
        f"/api/orders/{order.id}/confirm/",
        {"outcome": "confirmed", "notes": "address verified"},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["stage"] == "Confirmed"
    assert body["confirmationOutcome"] == "confirmed"
    assert "confirmation.outcome" in _audit_kinds()


def test_confirm_order_outcome_rescue_needed(operations_user, auth_client) -> None:
    order = _make_order(stage=Order.Stage.CONFIRMATION_PENDING)
    client = auth_client(operations_user)
    res = client.post(
        f"/api/orders/{order.id}/confirm/",
        {"outcome": "rescue_needed", "notes": "weak address"},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["stage"] == "Confirmation Pending"  # stage stays
    assert body["confirmationOutcome"] == "rescue_needed"
    order.refresh_from_db()
    assert "Rescue Needed" in order.rescue_status
    assert "confirmation.outcome" in _audit_kinds()


def test_confirm_order_outcome_cancelled(operations_user, auth_client) -> None:
    order = _make_order(stage=Order.Stage.CONFIRMATION_PENDING)
    client = auth_client(operations_user)
    res = client.post(
        f"/api/orders/{order.id}/confirm/",
        {"outcome": "cancelled", "notes": "wrong number"},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["stage"] == "Cancelled"
    assert "confirmation.outcome" in _audit_kinds()


# ---------- 15. Payment link ----------


def test_payment_link_creates_payment_and_url(operations_user, auth_client) -> None:
    order = _make_order(stage=Order.Stage.CONFIRMED)
    client = auth_client(operations_user)
    res = client.post(
        "/api/payments/links/",
        {"orderId": order.id, "amount": 499, "gateway": "Razorpay", "type": "Advance"},
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["payment"]["status"] == "Pending"
    assert body["payment"]["orderId"] == order.id
    assert body["paymentUrl"].startswith("https://razorpay.example/pay/")
    assert Payment.objects.filter(pk=body["payment"]["id"]).exists()
    assert "payment.link_created" in _audit_kinds()


# ---------- 16. Shipment create ----------


def test_create_shipment_generates_awb_and_timeline(operations_user, auth_client) -> None:
    order = _make_order(stage=Order.Stage.DISPATCHED)
    client = auth_client(operations_user)
    res = client.post("/api/shipments/", {"orderId": order.id}, format="json")
    assert res.status_code == 201
    body = res.json()
    assert re.fullmatch(r"DLH\d{8}", body["awb"])
    assert body["orderId"] == order.id
    assert len(body["timeline"]) == 5
    assert Shipment.objects.filter(awb=body["awb"]).exists()
    assert "shipment.created" in _audit_kinds()
    # Parent order received the AWB.
    order.refresh_from_db()
    assert order.awb == body["awb"]


# ---------- 17. Rescue attempt + update ----------


def test_rescue_attempt_create_and_update(operations_user, auth_client) -> None:
    order = _make_order(stage=Order.Stage.OUT_FOR_DELIVERY, rto_risk=Order.RtoRisk.HIGH)
    client = auth_client(operations_user)
    create_res = client.post(
        "/api/rto/rescue/",
        {"orderId": order.id, "channel": "AI Call", "notes": "first attempt"},
        format="json",
    )
    assert create_res.status_code == 201
    rescue_id = create_res.json()["id"]
    assert RescueAttempt.objects.filter(pk=rescue_id).exists()
    assert "rescue.attempted" in _audit_kinds()

    order.refresh_from_db()
    assert order.rescue_status == "Pending"

    update_res = client.patch(
        f"/api/rto/rescue/{rescue_id}/",
        {"outcome": "Convinced", "notes": "agreed to receive"},
        format="json",
    )
    assert update_res.status_code == 200
    assert update_res.json()["outcome"] == "Convinced"
    assert "rescue.updated" in _audit_kinds()

    order.refresh_from_db()
    assert order.rescue_status == "Convinced"


# ---------- 18. Full workflow ledger growth ----------


def test_audit_ledger_grows_with_workflow(operations_user, auth_client) -> None:
    AuditEvent.objects.all().delete()
    client = auth_client(operations_user)

    # 1. Create lead.
    lead_res = client.post(
        "/api/leads/",
        {"name": "Workflow Test", "phone": "+91 9000000050", "state": "Maharashtra", "city": "Pune"},
        format="json",
    )
    assert lead_res.status_code == 201

    # 2. Create order.
    order_res = client.post(
        "/api/orders/",
        {
            "customerName": "Workflow Test",
            "phone": "+91 9000000050",
            "product": "Weight Management",
            "amount": 2640,
            "discountPct": 12,
            "state": "Maharashtra",
            "city": "Pune",
        },
        format="json",
    )
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]

    # 3. Move to confirmation.
    move_res = client.post(f"/api/orders/{order_id}/move-to-confirmation/", format="json")
    assert move_res.status_code == 200

    # 4. Confirm.
    confirm_res = client.post(
        f"/api/orders/{order_id}/confirm/",
        {"outcome": "confirmed"},
        format="json",
    )
    assert confirm_res.status_code == 200

    # 5. Payment link.
    pay_res = client.post(
        "/api/payments/links/",
        {"orderId": order_id, "amount": 499, "gateway": "Razorpay", "type": "Advance"},
        format="json",
    )
    assert pay_res.status_code == 201

    # 6. Transition Confirmed → Dispatched, then create shipment.
    client.post(f"/api/orders/{order_id}/transition/", {"stage": "Dispatched"}, format="json")
    ship_res = client.post("/api/shipments/", {"orderId": order_id}, format="json")
    assert ship_res.status_code == 201

    # 7. Rescue attempt.
    rescue_res = client.post(
        "/api/rto/rescue/",
        {"orderId": order_id, "channel": "AI Call"},
        format="json",
    )
    assert rescue_res.status_code == 201

    # Verify the ledger captured every step.
    kinds = set(_audit_kinds())
    expected = {
        "lead.created",
        "order.created",
        "order.status_changed",
        "confirmation.outcome",
        "payment.link_created",
        "shipment.created",
        "rescue.attempted",
    }
    assert expected <= kinds, f"missing: {expected - kinds}"
    assert AuditEvent.objects.count() >= 7
