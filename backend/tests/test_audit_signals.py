"""Verify the Master Event Ledger is populated by Django signals."""
from __future__ import annotations

from apps.audit.models import AuditEvent
from apps.crm.models import Lead
from apps.orders.models import Order
from apps.payments.models import Payment


def test_lead_creation_writes_audit_event(db) -> None:
    Lead.objects.create(
        id="LD-TEST-1",
        name="Test User",
        phone="+91 9999999999",
        state="Maharashtra",
        city="Pune",
        language="Hindi",
        source="Meta Ads",
        campaign="Test",
        product_interest="Weight Management",
    )
    events = AuditEvent.objects.filter(kind="lead.created")
    assert events.count() == 1
    assert "Test User" in events.first().text


def test_order_creation_writes_audit_event(db) -> None:
    Order.objects.create(
        id="NRG-TEST-1",
        customer_name="Test",
        phone="+91 9999999999",
        product="Weight Management",
        amount=2640,
        state="Maharashtra",
        city="Pune",
    )
    events = AuditEvent.objects.filter(kind="order.created")
    assert events.count() == 1


def test_payment_only_logged_when_paid(db) -> None:
    Payment.objects.create(
        id="PAY-TEST-1",
        order_id="NRG-TEST-1",
        customer="Test",
        amount=499,
        gateway="Razorpay",
        status="Pending",
        type="Advance",
    )
    assert AuditEvent.objects.filter(kind="payment.received").count() == 0

    Payment.objects.create(
        id="PAY-TEST-2",
        order_id="NRG-TEST-1",
        customer="Test",
        amount=499,
        gateway="Razorpay",
        status="Paid",
        type="Advance",
    )
    assert AuditEvent.objects.filter(kind="payment.received").count() == 1
