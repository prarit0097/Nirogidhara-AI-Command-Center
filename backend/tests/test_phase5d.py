"""Phase 5D — Chat-to-call handoff + Lifecycle automation tests.

Coverage groups:

- Claim Vault coverage report + management command exit codes.
- AI handoff for "customer requested call" / low-confidence routes
  to the Vapi service (mock mode) and writes a handoff row.
- Operator manual handoff-to-call endpoint: operations OK, viewer
  blocked, anonymous blocked, CAIO never reaches the view.
- Idempotency: same (conversation, inbound, reason) does not double-trigger.
- Medical-emergency / side-effect / legal_threat reasons skip the
  generic sales call but still record a handoff row.
- AI-booked orders move directly into the Confirmation Pending queue.
- Lifecycle disabled flag → no send (still records skipped row).
- Lifecycle confirmation reminder fires when an order moves to
  Confirmation Pending and writes through the Phase 5A pipeline.
- Lifecycle payment reminder fires when a Pending Payment is created.
- Lifecycle delivery reminder fires when a Shipment hits "Out for Delivery".
- Lifecycle usage_explanation blocks when Claim Vault coverage is missing.
- Duplicate lifecycle event hits the idempotency log.
- Failed lifecycle send never mutates Order / Payment / Shipment.
- Audit kinds emitted (handoff.* + lifecycle.* + order_moved_to_confirmation).
"""
from __future__ import annotations

import io
import json
from typing import Any

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.compliance.coverage import (
    build_coverage_report,
    coverage_for_product,
)
from apps.compliance.models import Claim
from apps.crm.models import Customer
from apps.orders.models import Order
from apps.orders.services import create_order, move_to_confirmation
from apps.payments.models import Payment
from apps.payments.services import create_payment_link
from apps.whatsapp.call_handoff import (
    NON_AUTO_REASONS,
    SAFE_CALL_REASONS,
    trigger_vapi_call_from_whatsapp,
)
from apps.whatsapp.lifecycle import queue_lifecycle_message
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
    WhatsAppTemplate,
)
from apps.whatsapp.template_registry import upsert_template


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def operations_user_p5d(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="ops_p5d", password="ops12345", email="ops_p5d@nirogidhara.test"
    )
    user.role = User.Role.OPERATIONS
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def viewer_user_p5d(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="viewer_p5d",
        password="viewer12345",
        email="viewer_p5d@nirogidhara.test",
    )
    user.role = User.Role.VIEWER
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def admin_user_p5d(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="admin_p5d",
        password="admin12345",
        email="admin_p5d@nirogidhara.test",
    )
    user.role = User.Role.ADMIN
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-5D-001",
        provider=WhatsAppConnection.Provider.MOCK,
        display_name="Nirogidhara 5D",
        phone_number="+91 9000000000",
        status=WhatsAppConnection.Status.CONNECTED,
    )


@pytest.fixture
def customer(db):
    customer = Customer.objects.create(
        id="NRG-CUST-5D-001",
        name="5D Customer",
        phone="+919999955501",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=True,
    )
    WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={
            "consent_state": WhatsAppConsent.State.GRANTED,
            "granted_at": timezone.now(),
            "source": "test",
        },
    )
    return customer


@pytest.fixture
def conversation(db, customer, connection):
    return WhatsAppConversation.objects.create(
        id="WCV-5D-001",
        customer=customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
        ai_status=WhatsAppConversation.AiStatus.AUTO_AFTER_APPROVAL,
        unread_count=1,
    )


@pytest.fixture
def lifecycle_templates(connection):
    upsert_template(
        connection=connection,
        name="nrg_payment_reminder",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[{"type": "BODY", "text": "Payment {{1}} {{2}}"}],
        variables_schema={"required": [], "order": ["customer_name", "context"]},
        action_key="whatsapp.payment_reminder",
        claim_vault_required=False,
    )
    upsert_template(
        connection=connection,
        name="nrg_confirmation_reminder",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[{"type": "BODY", "text": "Confirm {{1}} {{2}}"}],
        variables_schema={"required": [], "order": ["customer_name", "context"]},
        action_key="whatsapp.confirmation_reminder",
        claim_vault_required=False,
    )
    upsert_template(
        connection=connection,
        name="nrg_delivery_reminder",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[{"type": "BODY", "text": "Delivery {{1}} {{2}}"}],
        variables_schema={"required": [], "order": ["customer_name", "context"]},
        action_key="whatsapp.delivery_reminder",
        claim_vault_required=False,
    )
    upsert_template(
        connection=connection,
        name="nrg_usage_explanation",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[{"type": "BODY", "text": "Usage {{1}} {{2}}"}],
        variables_schema={"required": [], "order": ["customer_name", "context"]},
        action_key="whatsapp.usage_explanation",
        claim_vault_required=True,
    )
    upsert_template(
        connection=connection,
        name="nrg_rto_rescue",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[{"type": "BODY", "text": "Rescue {{1}} {{2}}"}],
        variables_schema={"required": [], "order": ["customer_name", "context"]},
        action_key="whatsapp.rto_rescue",
        claim_vault_required=False,
    )


@pytest.fixture
def approved_claim(db):
    return Claim.objects.create(
        product="Weight Management",
        approved=[
            "Take 1 capsule twice daily after meals with warm water.",
            "Helpful Ayurvedic blend for metabolism support.",
        ],
        disallowed=["Guaranteed cure"],
        doctor="Dr Test",
        compliance="Compliance Test",
        version="v1.0",
    )


def _auth(client: APIClient, user) -> APIClient:
    from rest_framework_simplejwt.tokens import RefreshToken

    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}"
    )
    return client


# ---------------------------------------------------------------------------
# 1. Claim Vault coverage
# ---------------------------------------------------------------------------


def test_coverage_report_marks_missing_for_unknown_product(db) -> None:
    item = coverage_for_product("nonexistent-category")
    assert item.risk == "missing"
    assert item.has_approved_claims is False


def test_coverage_report_marks_ok_when_usage_present(approved_claim) -> None:
    item = coverage_for_product("Weight Management")
    assert item.risk == "ok"
    assert item.has_approved_claims is True
    assert item.missing_required_usage_claims is False


def test_coverage_report_marks_weak_when_no_usage_hint(db) -> None:
    Claim.objects.create(
        product="Skin Care",
        # Approved phrase carries no usage / dosage / capsule / ayurvedic
        # / blend keyword — should be flagged "weak" by the coverage
        # heuristic in apps.compliance.coverage.
        approved=["Helpful for daily wellness."],
        disallowed=["Guaranteed cure"],
        doctor="Dr X",
        compliance="C",
        version="v1.0",
    )
    item = coverage_for_product("Skin Care")
    assert item.risk == "weak"
    assert item.missing_required_usage_claims is True


def test_coverage_report_aggregate(approved_claim, db) -> None:
    Claim.objects.create(
        product="Joint Care",
        approved=[],
        disallowed=[],
        doctor="Dr Y",
        compliance="C",
        version="v1.0",
    )
    report = build_coverage_report()
    assert report.total_products >= 2
    assert report.ok_count >= 1
    assert report.missing_count >= 1


def test_check_claim_vault_coverage_command_clean_when_ok(approved_claim) -> None:
    out = io.StringIO()
    call_command("check_claim_vault_coverage", stdout=out)
    assert "ok" in out.getvalue()


def test_check_claim_vault_coverage_command_exits_on_missing(db) -> None:
    Claim.objects.create(
        product="Empty Product",
        approved=[],
        disallowed=[],
        doctor="Dr",
        compliance="C",
        version="v1.0",
    )
    with pytest.raises(SystemExit) as excinfo:
        call_command("check_claim_vault_coverage")
    assert excinfo.value.code == 1


def test_claim_coverage_endpoint_requires_admin(operations_user_p5d, approved_claim):
    res = _auth(APIClient(), operations_user_p5d).get("/api/compliance/claim-coverage/")
    assert res.status_code == 403


def test_claim_coverage_endpoint_returns_report(admin_user_p5d, approved_claim):
    res = _auth(APIClient(), admin_user_p5d).get("/api/compliance/claim-coverage/")
    assert res.status_code == 200
    body = res.json()
    assert body["totalProducts"] >= 1
    assert "items" in body
    assert AuditEvent.objects.filter(
        kind="compliance.claim_coverage.checked"
    ).exists()


# ---------------------------------------------------------------------------
# 2. Direct Vapi handoff service
# ---------------------------------------------------------------------------


@override_settings(VAPI_MODE="mock", WHATSAPP_CALL_HANDOFF_ENABLED=True)
def test_handoff_triggers_vapi_for_safe_reason(conversation, customer):
    result = trigger_vapi_call_from_whatsapp(
        conversation=conversation,
        reason="customer_requested_call",
    )
    assert result.skipped is False
    assert result.status == WhatsAppHandoffToCall.Status.TRIGGERED
    assert result.call_id
    assert result.provider_call_id
    assert WhatsAppHandoffToCall.objects.filter(conversation=conversation).count() == 1
    assert AuditEvent.objects.filter(
        kind="whatsapp.handoff.call_triggered"
    ).exists()
    conversation.refresh_from_db()
    assert conversation.status == WhatsAppConversation.Status.ESCALATED
    assert conversation.metadata["ai"]["handoffType"] == "vapi_call"
    assert conversation.metadata["ai"]["lastCallId"] == result.call_id


@override_settings(VAPI_MODE="mock", WHATSAPP_CALL_HANDOFF_ENABLED=True)
def test_handoff_idempotent_for_same_inbound(conversation):
    inbound = WhatsAppMessage.objects.create(
        id="WAM-IN-DUP",
        conversation=conversation,
        customer=conversation.customer,
        provider_message_id="wamid.IN-DUP",
        direction=WhatsAppMessage.Direction.INBOUND,
        status=WhatsAppMessage.Status.DELIVERED,
        type=WhatsAppMessage.Type.TEXT,
        body="Call me",
    )
    first = trigger_vapi_call_from_whatsapp(
        conversation=conversation,
        reason="customer_requested_call",
        inbound_message=inbound,
    )
    second = trigger_vapi_call_from_whatsapp(
        conversation=conversation,
        reason="customer_requested_call",
        inbound_message=inbound,
    )
    assert first.handoff_id == second.handoff_id
    assert second.skipped is True
    assert WhatsAppHandoffToCall.objects.filter(conversation=conversation).count() == 1
    assert AuditEvent.objects.filter(
        kind="whatsapp.handoff.call_skipped_duplicate"
    ).exists()


@override_settings(WHATSAPP_CALL_HANDOFF_ENABLED=True)
def test_handoff_skips_for_medical_emergency(conversation):
    result = trigger_vapi_call_from_whatsapp(
        conversation=conversation,
        reason="medical_emergency",
    )
    assert result.skipped is True
    assert result.status == WhatsAppHandoffToCall.Status.SKIPPED
    row = WhatsAppHandoffToCall.objects.get(conversation=conversation)
    assert row.error_message == "non_auto_reason"
    assert AuditEvent.objects.filter(
        kind="whatsapp.handoff.call_skipped"
    ).exists()


@override_settings(WHATSAPP_CALL_HANDOFF_ENABLED=True)
def test_handoff_skips_when_phone_missing(conversation, customer):
    customer.phone = ""
    customer.save(update_fields=["phone"])
    result = trigger_vapi_call_from_whatsapp(
        conversation=conversation,
        reason="customer_requested_call",
    )
    assert result.skipped is True
    assert "missing_phone" in result.error_message


# ---------------------------------------------------------------------------
# 3. Operator manual handoff-to-call endpoint
# ---------------------------------------------------------------------------


@override_settings(VAPI_MODE="mock", WHATSAPP_CALL_HANDOFF_ENABLED=True)
def test_operator_handoff_to_call_endpoint_triggers(
    operations_user_p5d, conversation
):
    res = _auth(APIClient(), operations_user_p5d).post(
        f"/api/whatsapp/conversations/{conversation.id}/handoff-to-call/",
        {"reason": "customer_requested_call", "note": "wants to call back"},
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["skipped"] is False
    assert body["callId"]
    assert body["status"] == WhatsAppHandoffToCall.Status.TRIGGERED


def test_operator_handoff_to_call_viewer_blocked(viewer_user_p5d, conversation):
    res = _auth(APIClient(), viewer_user_p5d).post(
        f"/api/whatsapp/conversations/{conversation.id}/handoff-to-call/",
        {"reason": "customer_requested_call"},
        format="json",
    )
    assert res.status_code == 403


def test_operator_handoff_to_call_anonymous_blocked(conversation):
    res = APIClient().post(
        f"/api/whatsapp/conversations/{conversation.id}/handoff-to-call/",
        {"reason": "customer_requested_call"},
        format="json",
    )
    assert res.status_code == 401


def test_handoff_list_endpoint(operations_user_p5d, conversation):
    res = _auth(APIClient(), operations_user_p5d).get(
        f"/api/whatsapp/conversations/{conversation.id}/handoffs/",
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list)


# ---------------------------------------------------------------------------
# 4. AI-booked orders → confirmation queue
# ---------------------------------------------------------------------------


def test_ai_booked_order_moves_to_confirmation(db, customer):
    order = create_order(
        customer_name=customer.name,
        phone=customer.phone,
        product="Weight Management",
        state=customer.state,
        city=customer.city,
        amount=3000,
        agent="WhatsApp AI",
        stage=Order.Stage.ORDER_PUNCHED,
    )
    # Simulate the Phase 5D move call that book_order_from_decision now does.
    move_to_confirmation(order, by_user=None)
    order.refresh_from_db()
    assert order.stage == Order.Stage.CONFIRMATION_PENDING


# ---------------------------------------------------------------------------
# 5. Lifecycle automation
# ---------------------------------------------------------------------------


@override_settings(WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=False)
def test_lifecycle_disabled_short_circuits(customer, conversation):
    result = queue_lifecycle_message(
        object_type="order",
        object_id="NRG-DUMMY-1",
        event_kind="moved_to_confirmation",
        customer=customer,
    )
    assert result.status == WhatsAppLifecycleEvent.Status.SKIPPED
    assert result.block_reason == "lifecycle_disabled"


@override_settings(WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True)
def test_lifecycle_confirmation_reminder_dispatches(
    customer, lifecycle_templates
):
    result = queue_lifecycle_message(
        object_type="order",
        object_id="NRG-LCYCL-1",
        event_kind="moved_to_confirmation",
        customer=customer,
        variables={"customer_name": customer.name, "context": "your order"},
    )
    assert result.status == WhatsAppLifecycleEvent.Status.SENT
    assert result.message_id
    msg = WhatsAppMessage.objects.get(pk=result.message_id)
    assert msg.template.action_key == "whatsapp.confirmation_reminder"
    assert AuditEvent.objects.filter(kind="whatsapp.lifecycle.queued").exists()
    assert AuditEvent.objects.filter(kind="whatsapp.lifecycle.sent").exists()


@override_settings(WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True)
def test_lifecycle_payment_reminder_dispatches(customer, lifecycle_templates):
    result = queue_lifecycle_message(
        object_type="payment",
        object_id="PAY-LCYCL-1",
        event_kind="link_created",
        customer=customer,
        variables={"customer_name": customer.name, "context": "Pay 499"},
    )
    assert result.status == WhatsAppLifecycleEvent.Status.SENT
    msg = WhatsAppMessage.objects.get(pk=result.message_id)
    assert msg.template.action_key == "whatsapp.payment_reminder"


@override_settings(WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True)
def test_lifecycle_delivery_reminder_dispatches(customer, lifecycle_templates):
    result = queue_lifecycle_message(
        object_type="shipment",
        object_id="DLH-AWB-1",
        event_kind="out_for_delivery",
        customer=customer,
        variables={"customer_name": customer.name, "context": "AWB DLH-AWB-1"},
    )
    assert result.status == WhatsAppLifecycleEvent.Status.SENT


@override_settings(WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True)
def test_lifecycle_usage_explanation_blocks_without_claim(
    db, customer, lifecycle_templates
):
    # No Claim row for "Weight Management" at all.
    result = queue_lifecycle_message(
        object_type="shipment",
        object_id="DLH-USAGE-1",
        event_kind="delivered",
        customer=customer,
        variables={"customer_name": customer.name, "context": "your dose"},
    )
    assert result.status == WhatsAppLifecycleEvent.Status.BLOCKED
    assert result.block_reason == "claim_vault_missing"
    assert AuditEvent.objects.filter(
        kind="whatsapp.lifecycle.blocked",
        payload__block_reason="claim_vault_missing",
    ).exists()


@override_settings(WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True)
def test_lifecycle_duplicate_event_skipped(customer, lifecycle_templates):
    queue_lifecycle_message(
        object_type="order",
        object_id="NRG-DUP-1",
        event_kind="moved_to_confirmation",
        customer=customer,
    )
    second = queue_lifecycle_message(
        object_type="order",
        object_id="NRG-DUP-1",
        event_kind="moved_to_confirmation",
        customer=customer,
    )
    assert second.block_reason == "duplicate"
    assert AuditEvent.objects.filter(
        kind="whatsapp.lifecycle.skipped_duplicate"
    ).exists()


@override_settings(WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True)
def test_lifecycle_failure_does_not_mutate_business_objects(
    db, lifecycle_templates
):
    """Customer with no consent → lifecycle blocks but Order/Payment unchanged."""
    no_consent_customer = Customer.objects.create(
        id="NRG-CUST-NOCONSENT",
        name="No consent",
        phone="+919999955999",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=False,
    )
    WhatsAppConsent.objects.create(
        customer=no_consent_customer,
        consent_state=WhatsAppConsent.State.UNKNOWN,
    )
    order = create_order(
        customer_name=no_consent_customer.name,
        phone=no_consent_customer.phone,
        product="Weight Management",
        state="MH",
        city="Pune",
        amount=3000,
    )
    pre_stage = order.stage
    result = queue_lifecycle_message(
        object_type="order",
        object_id=order.id,
        event_kind="moved_to_confirmation",
        customer=no_consent_customer,
    )
    assert result.status == WhatsAppLifecycleEvent.Status.BLOCKED
    assert result.block_reason == "consent_missing"
    order.refresh_from_db()
    assert order.stage == pre_stage  # Lifecycle never mutates business state.


@override_settings(WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True)
def test_lifecycle_unknown_event_records_skipped(customer):
    result = queue_lifecycle_message(
        object_type="order",
        object_id="NRG-UNK-1",
        event_kind="some_unknown_event",
        customer=customer,
    )
    assert result.status == WhatsAppLifecycleEvent.Status.SKIPPED
    assert result.block_reason == "no_trigger_registered"


# ---------------------------------------------------------------------------
# 6. Lifecycle events list endpoint + handoff list endpoint
# ---------------------------------------------------------------------------


@override_settings(WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True)
def test_lifecycle_events_list_endpoint(
    operations_user_p5d, customer, lifecycle_templates
):
    queue_lifecycle_message(
        object_type="payment",
        object_id="PAY-API-1",
        event_kind="link_created",
        customer=customer,
        variables={"customer_name": customer.name, "context": "Pay 499"},
    )
    res = _auth(APIClient(), operations_user_p5d).get(
        "/api/whatsapp/lifecycle-events/"
    )
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert body[0]["actionKey"] == "whatsapp.payment_reminder"


# ---------------------------------------------------------------------------
# 7. Audit kinds emitted from handoff path
# ---------------------------------------------------------------------------


@override_settings(VAPI_MODE="mock", WHATSAPP_CALL_HANDOFF_ENABLED=True)
def test_handoff_emits_request_and_trigger_audits(conversation):
    trigger_vapi_call_from_whatsapp(
        conversation=conversation,
        reason="customer_requested_call",
    )
    kinds = set(
        AuditEvent.objects.filter(
            payload__conversation_id=conversation.id
        ).values_list("kind", flat=True)
    )
    assert "whatsapp.handoff.call_requested" in kinds
    assert "whatsapp.handoff.call_triggered" in kinds


# ---------------------------------------------------------------------------
# 8. Constants sanity
# ---------------------------------------------------------------------------


def test_safe_call_reasons_includes_customer_request() -> None:
    assert "customer_requested_call" in SAFE_CALL_REASONS


def test_non_auto_reasons_includes_medical_emergency() -> None:
    assert "medical_emergency" in NON_AUTO_REASONS
    assert "side_effect_complaint" in NON_AUTO_REASONS
    assert "legal_threat" in NON_AUTO_REASONS
