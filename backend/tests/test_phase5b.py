"""Phase 5B — Inbound WhatsApp Inbox + Customer 360 Timeline tests.

Phase 5B is manual-only inbox + internal notes + read receipts +
per-conversation manual template send, all routed through Phase 5A's
``queue_template_message`` so the consent + Claim Vault + matrix +
CAIO + idempotency gates stay in force.

Scope of these tests:
- inbox summary (counts + AI suggestions disabled placeholder)
- conversation list filters (status / unread / search / assignedTo)
- conversation messages endpoint shape
- internal notes (create + list)
- viewer cannot create notes; anonymous blocked
- mark-read resets unreadCount
- PATCH conversation safe fields only (status / assignedTo / tags / subject)
- inbound webhook increments unreadCount + updates lastMessage*
- inbound message does not auto-reply / does not mutate Order/Payment
- opt-out keyword still updates consent
- per-conversation send-template routes through queue_template_message
  (no consent → 403; rejected/inactive template → 400; CAIO → 403)
- audit events emitted for note / read / manual send / inbound
- customer timeline endpoint returns WhatsApp-only items
- Phase 5A regression: 50 existing tests stay green (asserted by full
  pytest run elsewhere)
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.whatsapp import services
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppInternalNote,
    WhatsAppMessage,
    WhatsAppTemplate,
)
from apps.whatsapp.template_registry import upsert_template


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def director_user_p5b(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="director_p5b",
        password="director12345",
        email="director_p5b@nirogidhara.test",
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def admin_user_p5b(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="admin_p5b",
        password="admin12345",
        email="admin_p5b@nirogidhara.test",
    )
    user.role = User.Role.ADMIN
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def operations_user_p5b(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="ops_p5b",
        password="ops12345",
        email="ops_p5b@nirogidhara.test",
    )
    user.role = User.Role.OPERATIONS
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def viewer_user_p5b(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="viewer_p5b",
        password="viewer12345",
        email="viewer_p5b@nirogidhara.test",
    )
    user.role = User.Role.VIEWER
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-5B001",
        provider=WhatsAppConnection.Provider.MOCK,
        display_name="Nirogidhara 5B",
        phone_number="+91 9000099991",
        status=WhatsAppConnection.Status.CONNECTED,
    )


@pytest.fixture
def customer(db):
    customer = Customer.objects.create(
        id="NRG-CUST-5B001",
        name="P5B Customer",
        phone="+919999999001",
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
def customer_no_consent(db):
    return Customer.objects.create(
        id="NRG-CUST-5B002",
        name="No Consent",
        phone="+919999999002",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=False,
    )


@pytest.fixture
def template(db, connection):
    template, _ = upsert_template(
        connection=connection,
        name="nrg_payment_reminder",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[{"type": "BODY", "text": "Hi {{1}}, due {{2}}"}],
        variables_schema={"required": ["customer_name", "context"], "order": ["customer_name", "context"]},
        action_key="whatsapp.payment_reminder",
        claim_vault_required=False,
    )
    return template


@pytest.fixture
def conversation(db, customer, connection):
    return WhatsAppConversation.objects.create(
        id="WCV-5B-001",
        customer=customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
        ai_status=WhatsAppConversation.AiStatus.DISABLED,
        unread_count=2,
        last_message_text="hi there",
        last_message_at=timezone.now(),
        last_inbound_at=timezone.now(),
    )


def _auth(client: APIClient, user) -> APIClient:
    from rest_framework_simplejwt.tokens import RefreshToken

    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}"
    )
    return client


# ---------------------------------------------------------------------------
# 1. Inbox summary
# ---------------------------------------------------------------------------


def test_inbox_summary_returns_counts_and_disabled_ai(
    operations_user_p5b, conversation
) -> None:
    res = _auth(APIClient(), operations_user_p5b).get("/api/whatsapp/inbox/")
    assert res.status_code == 200
    body = res.json()
    assert "conversations" in body
    assert "counts" in body
    assert body["counts"]["all"] >= 1
    assert body["counts"]["unread"] >= 1
    assert body["aiSuggestions"]["enabled"] is False
    # Phase 5C now ships; the inbox AI block reflects real provider /
    # auto-reply status. With AI_PROVIDER=disabled (test default) we
    # always see ``provider_disabled`` and ``enabled=False``.
    assert body["aiSuggestions"]["enabled"] is False
    assert body["aiSuggestions"]["status"] in {
        "provider_disabled",
        "auto_reply_off",
        "auto",
        "disabled",
    }
    assert "provider" in body["aiSuggestions"]
    assert "autoReplyEnabled" in body["aiSuggestions"]


def test_inbox_summary_anonymous_blocked() -> None:
    res = APIClient().get("/api/whatsapp/inbox/")
    assert res.status_code == 401


def test_inbox_summary_viewer_can_read(viewer_user_p5b, conversation) -> None:
    res = _auth(APIClient(), viewer_user_p5b).get("/api/whatsapp/inbox/")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# 2. Conversation list filters
# ---------------------------------------------------------------------------


def test_conversation_list_filter_unread(
    operations_user_p5b, conversation, customer, connection
) -> None:
    # Add a second conversation with unread_count=0.
    other = Customer.objects.create(
        id="NRG-CUST-5B003",
        name="Another",
        phone="+919999999003",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=True,
    )
    WhatsAppConversation.objects.create(
        id="WCV-5B-002",
        customer=other,
        connection=connection,
        unread_count=0,
    )
    client = _auth(APIClient(), operations_user_p5b)
    res = client.get("/api/whatsapp/conversations/?unread=true")
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()}
    assert conversation.id in ids
    assert "WCV-5B-002" not in ids


def test_conversation_list_filter_status(operations_user_p5b, conversation) -> None:
    conversation.status = WhatsAppConversation.Status.RESOLVED
    conversation.save(update_fields=["status"])
    res = _auth(APIClient(), operations_user_p5b).get(
        "/api/whatsapp/conversations/?status=resolved"
    )
    assert res.status_code == 200
    rows = res.json()
    assert any(r["id"] == conversation.id for r in rows)


def test_conversation_list_search_by_customer_name(
    operations_user_p5b, conversation
) -> None:
    res = _auth(APIClient(), operations_user_p5b).get(
        "/api/whatsapp/conversations/?q=P5B"
    )
    assert res.status_code == 200
    rows = res.json()
    assert any(r["customerName"] == "P5B Customer" for r in rows)


def test_conversation_serializer_exposes_customer_and_assigned_username(
    operations_user_p5b, conversation
) -> None:
    conversation.assigned_to = operations_user_p5b
    conversation.save(update_fields=["assigned_to"])
    res = _auth(APIClient(), operations_user_p5b).get(
        f"/api/whatsapp/conversations/{conversation.id}/"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["customerName"] == "P5B Customer"
    assert body["customerPhone"].startswith("+919999999001") or body[
        "customerPhone"
    ].endswith("9001")
    assert body["assignedToUsername"] == operations_user_p5b.username


# ---------------------------------------------------------------------------
# 3. Internal notes
# ---------------------------------------------------------------------------


def test_create_internal_note_operations(
    operations_user_p5b, conversation
) -> None:
    res = _auth(APIClient(), operations_user_p5b).post(
        f"/api/whatsapp/conversations/{conversation.id}/notes/",
        {"body": "Customer asked for callback", "metadata": {"tag": "callback"}},
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["body"] == "Customer asked for callback"
    assert body["authorName"] == operations_user_p5b.username
    assert AuditEvent.objects.filter(
        kind="whatsapp.internal_note.created"
    ).exists()


def test_list_internal_notes_authenticated(
    operations_user_p5b, viewer_user_p5b, conversation
) -> None:
    WhatsAppInternalNote.objects.create(
        conversation=conversation,
        author=operations_user_p5b,
        body="seed note",
    )
    res = _auth(APIClient(), viewer_user_p5b).get(
        f"/api/whatsapp/conversations/{conversation.id}/notes/"
    )
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["body"] == "seed note"


def test_viewer_cannot_create_internal_note(
    viewer_user_p5b, conversation
) -> None:
    res = _auth(APIClient(), viewer_user_p5b).post(
        f"/api/whatsapp/conversations/{conversation.id}/notes/",
        {"body": "should not work"},
        format="json",
    )
    assert res.status_code == 403


def test_anonymous_cannot_create_internal_note(conversation) -> None:
    res = APIClient().post(
        f"/api/whatsapp/conversations/{conversation.id}/notes/",
        {"body": "anon"},
        format="json",
    )
    assert res.status_code == 401


def test_create_note_rejects_empty_body(
    operations_user_p5b, conversation
) -> None:
    res = _auth(APIClient(), operations_user_p5b).post(
        f"/api/whatsapp/conversations/{conversation.id}/notes/",
        {"body": ""},
        format="json",
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# 4. Mark-read
# ---------------------------------------------------------------------------


def test_mark_read_resets_unread(operations_user_p5b, conversation) -> None:
    assert conversation.unread_count == 2
    res = _auth(APIClient(), operations_user_p5b).post(
        f"/api/whatsapp/conversations/{conversation.id}/mark-read/",
        {},
        format="json",
    )
    assert res.status_code == 200
    conversation.refresh_from_db()
    assert conversation.unread_count == 0
    assert AuditEvent.objects.filter(kind="whatsapp.conversation.read").exists()


def test_mark_read_idempotent_when_already_zero(
    operations_user_p5b, conversation
) -> None:
    conversation.unread_count = 0
    conversation.save(update_fields=["unread_count"])
    audit_before = AuditEvent.objects.filter(
        kind="whatsapp.conversation.read"
    ).count()
    res = _auth(APIClient(), operations_user_p5b).post(
        f"/api/whatsapp/conversations/{conversation.id}/mark-read/",
        {},
        format="json",
    )
    assert res.status_code == 200
    assert (
        AuditEvent.objects.filter(kind="whatsapp.conversation.read").count()
        == audit_before
    )


def test_viewer_cannot_mark_read(viewer_user_p5b, conversation) -> None:
    res = _auth(APIClient(), viewer_user_p5b).post(
        f"/api/whatsapp/conversations/{conversation.id}/mark-read/",
        {},
        format="json",
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 5. PATCH conversation safe-field update
# ---------------------------------------------------------------------------


def test_patch_conversation_status_writes_audit(
    operations_user_p5b, conversation
) -> None:
    res = _auth(APIClient(), operations_user_p5b).patch(
        f"/api/whatsapp/conversations/{conversation.id}/",
        {"status": "resolved"},
        format="json",
    )
    assert res.status_code == 200
    conversation.refresh_from_db()
    assert conversation.status == "resolved"
    assert conversation.resolved_at is not None
    assert AuditEvent.objects.filter(kind="whatsapp.conversation.updated").exists()


def test_patch_conversation_assignment_emits_audit(
    operations_user_p5b, conversation
) -> None:
    res = _auth(APIClient(), operations_user_p5b).patch(
        f"/api/whatsapp/conversations/{conversation.id}/",
        {"assignedToId": operations_user_p5b.pk},
        format="json",
    )
    assert res.status_code == 200
    conversation.refresh_from_db()
    assert conversation.assigned_to_id == operations_user_p5b.pk
    assert AuditEvent.objects.filter(kind="whatsapp.conversation.assigned").exists()


def test_patch_conversation_tags_and_subject(
    operations_user_p5b, conversation
) -> None:
    res = _auth(APIClient(), operations_user_p5b).patch(
        f"/api/whatsapp/conversations/{conversation.id}/",
        {"tags": ["vip", "callback"], "subject": "Pending payment"},
        format="json",
    )
    assert res.status_code == 200
    conversation.refresh_from_db()
    assert conversation.tags == ["vip", "callback"]
    assert conversation.subject == "Pending payment"


def test_patch_conversation_rejects_unsafe_fields(
    operations_user_p5b, conversation
) -> None:
    res = _auth(APIClient(), operations_user_p5b).patch(
        f"/api/whatsapp/conversations/{conversation.id}/",
        {"unreadCount": 99, "customerId": "NRG-EVIL"},
        format="json",
    )
    # The unsafe field gets ignored by the serializer; result is a 400
    # because no safe fields were supplied.
    assert res.status_code == 400
    conversation.refresh_from_db()
    assert conversation.unread_count == 2  # untouched


def test_viewer_cannot_patch_conversation(viewer_user_p5b, conversation) -> None:
    res = _auth(APIClient(), viewer_user_p5b).patch(
        f"/api/whatsapp/conversations/{conversation.id}/",
        {"status": "pending"},
        format="json",
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 6. Inbound webhook increments unread + does not auto-reply / mutate orders
# ---------------------------------------------------------------------------


def _inbound_body(customer: Customer, wamid: str = "wamid.IN-5B-1") -> bytes:
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "ENTRY-5B",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "PNID"},
                                "messages": [
                                    {
                                        "id": wamid,
                                        "from": customer.phone.replace("+", ""),
                                        "type": "text",
                                        "text": {"body": "Hello there"},
                                        "timestamp": "1714290000",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")


def test_inbound_webhook_increments_unread_and_updates_last_message(
    customer, connection
) -> None:
    body = _inbound_body(customer, wamid="wamid.IN-5B-A")
    APIClient().post(
        "/api/webhooks/whatsapp/meta/",
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=anything",
    )
    convo = WhatsAppConversation.objects.filter(customer=customer).first()
    assert convo is not None
    assert convo.unread_count == 1
    assert convo.last_inbound_at is not None
    assert convo.last_message_text == "Hello there"


def test_inbound_webhook_does_not_auto_reply(customer, connection) -> None:
    body = _inbound_body(customer, wamid="wamid.IN-5B-B")
    APIClient().post(
        "/api/webhooks/whatsapp/meta/",
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=anything",
    )
    outbound = WhatsAppMessage.objects.filter(
        customer=customer, direction=WhatsAppMessage.Direction.OUTBOUND
    )
    assert outbound.count() == 0


def test_inbound_webhook_does_not_mutate_order_or_payment(
    customer, connection
) -> None:
    order = Order.objects.create(
        id="NRG-5B-1",
        customer_name=customer.name,
        phone=customer.phone,
        product="Weight Management",
        quantity=1,
        amount=2999,
        state="MH",
        city="Pune",
        rto_risk=Order.RtoRisk.LOW,
        rto_score=10,
        agent="Calling AI",
        stage=Order.Stage.ORDER_PUNCHED,
    )
    payment = Payment.objects.create(
        id="PAY-5B-1",
        order_id=order.id,
        customer=customer.name,
        amount=499,
    )
    APIClient().post(
        "/api/webhooks/whatsapp/meta/",
        data=_inbound_body(customer, wamid="wamid.IN-5B-C"),
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=anything",
    )
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.stage == Order.Stage.ORDER_PUNCHED
    assert order.amount == 2999
    assert payment.amount == 499


def test_inbound_optout_keyword_revokes_consent(customer, connection) -> None:
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "ENTRY-OPT",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "PNID"},
                                "messages": [
                                    {
                                        "id": "wamid.IN-OPTOUT",
                                        "from": customer.phone.replace("+", ""),
                                        "type": "text",
                                        "text": {"body": "STOP please"},
                                        "timestamp": "1714290000",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")
    APIClient().post(
        "/api/webhooks/whatsapp/meta/",
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=anything",
    )
    customer.refresh_from_db()
    assert customer.consent_whatsapp is False
    consent = WhatsAppConsent.objects.get(customer=customer)
    assert consent.consent_state == WhatsAppConsent.State.OPTED_OUT


# ---------------------------------------------------------------------------
# 7. Per-conversation send-template
# ---------------------------------------------------------------------------


def test_conversation_send_template_happy_path(
    operations_user_p5b, conversation, template
) -> None:
    res = _auth(APIClient(), operations_user_p5b).post(
        f"/api/whatsapp/conversations/{conversation.id}/send-template/",
        {
            "actionKey": "whatsapp.payment_reminder",
            "variables": {"customer_name": "P5B", "context": "₹499"},
        },
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["message"]["status"] in {"sent", "queued"}
    assert body["conversationId"] == conversation.id
    assert AuditEvent.objects.filter(
        kind="whatsapp.template.manual_send_requested"
    ).exists()


def test_conversation_send_template_blocks_when_consent_revoked(
    operations_user_p5b, conversation, customer, template
) -> None:
    customer.consent_whatsapp = False
    customer.save(update_fields=["consent_whatsapp"])
    WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={"consent_state": WhatsAppConsent.State.REVOKED},
    )
    res = _auth(APIClient(), operations_user_p5b).post(
        f"/api/whatsapp/conversations/{conversation.id}/send-template/",
        {"actionKey": "whatsapp.payment_reminder"},
        format="json",
    )
    assert res.status_code == 403
    assert res.json()["blockReason"] == "consent_missing"


def test_conversation_send_template_blocks_when_template_inactive(
    operations_user_p5b, conversation, template
) -> None:
    template.is_active = False
    template.save(update_fields=["is_active"])
    res = _auth(APIClient(), operations_user_p5b).post(
        f"/api/whatsapp/conversations/{conversation.id}/send-template/",
        {
            "actionKey": "whatsapp.payment_reminder",
            "templateId": template.id,
            "variables": {"customer_name": "P5B", "context": "₹499"},
        },
        format="json",
    )
    assert res.status_code == 400
    assert res.json()["blockReason"] in {
        "template_inactive",
        "template_not_approved",
    }


def test_conversation_send_template_blocks_caio_actor(
    director_user_p5b, conversation, template
) -> None:
    """CAIO can never send. The matrix engine rejects the actor_agent
    upstream — but the manual operator endpoint never reads
    ``actor_agent`` from request body, so this test verifies the
    service-entry guard via direct call."""
    with pytest.raises(services.WhatsAppServiceError) as excinfo:
        services.queue_template_message(
            customer=conversation.customer,
            action_key="whatsapp.payment_reminder",
            template=template,
            variables={"customer_name": "P5B", "context": "₹499"},
            actor_role="director",
            actor_agent="caio",
            triggered_by="manual_inbox",
        )
    assert excinfo.value.block_reason == "caio_no_send"


def test_conversation_send_template_anonymous_blocked(conversation) -> None:
    res = APIClient().post(
        f"/api/whatsapp/conversations/{conversation.id}/send-template/",
        {"actionKey": "whatsapp.payment_reminder"},
        format="json",
    )
    assert res.status_code == 401


def test_conversation_send_template_viewer_blocked(
    viewer_user_p5b, conversation, template
) -> None:
    res = _auth(APIClient(), viewer_user_p5b).post(
        f"/api/whatsapp/conversations/{conversation.id}/send-template/",
        {"actionKey": "whatsapp.payment_reminder"},
        format="json",
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 8. Customer timeline
# ---------------------------------------------------------------------------


def test_customer_timeline_returns_whatsapp_only_items(
    operations_user_p5b, conversation, template
) -> None:
    # Outbound message via the service.
    queued = services.queue_template_message(
        customer=conversation.customer,
        action_key="whatsapp.payment_reminder",
        template=template,
        variables={"customer_name": "P5B", "context": "₹499"},
        actor_role="operations",
        triggered_by="test",
    )
    services.send_queued_message(queued.message.id)
    # Note + inbound message.
    WhatsAppInternalNote.objects.create(
        conversation=conversation,
        author=operations_user_p5b,
        body="customer wants callback",
    )
    APIClient().post(
        "/api/webhooks/whatsapp/meta/",
        data=_inbound_body(conversation.customer, wamid="wamid.IN-TIMELINE"),
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=anything",
    )

    res = _auth(APIClient(), operations_user_p5b).get(
        f"/api/whatsapp/customers/{conversation.customer_id}/timeline/"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["customerId"] == conversation.customer_id
    assert body["consentWhatsapp"] is True
    kinds = {item["kind"] for item in body["items"]}
    assert "message" in kinds
    assert "internal_note" in kinds
    # Ensure WhatsApp-only — no order/payment/call rows leak in.
    assert kinds.issubset({"message", "internal_note", "status_event"})
    assert body["aiSuggestions"]["enabled"] is False


def test_customer_timeline_404_for_unknown_customer(operations_user_p5b) -> None:
    res = _auth(APIClient(), operations_user_p5b).get(
        "/api/whatsapp/customers/NRG-DOES-NOT-EXIST/timeline/"
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 9. Audit emission across the inbox lifecycle
# ---------------------------------------------------------------------------


def test_audit_kinds_emitted_across_inbox_flow(
    operations_user_p5b, conversation, template
) -> None:
    AuditEvent.objects.all().delete()
    client = _auth(APIClient(), operations_user_p5b)

    # Inbound webhook.
    client.post(
        "/api/webhooks/whatsapp/meta/",
        data=_inbound_body(conversation.customer, wamid="wamid.IN-AUDIT"),
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=anything",
    )
    # Mark read.
    client.post(
        f"/api/whatsapp/conversations/{conversation.id}/mark-read/",
        {},
        format="json",
    )
    # Add note.
    client.post(
        f"/api/whatsapp/conversations/{conversation.id}/notes/",
        {"body": "audit-test note"},
        format="json",
    )
    # Manual template send.
    client.post(
        f"/api/whatsapp/conversations/{conversation.id}/send-template/",
        {
            "actionKey": "whatsapp.payment_reminder",
            "variables": {"customer_name": "P5B", "context": "₹499"},
        },
        format="json",
    )
    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "whatsapp.inbound.received" in kinds
    assert "whatsapp.conversation.read" in kinds
    assert "whatsapp.internal_note.created" in kinds
    assert "whatsapp.template.manual_send_requested" in kinds
    assert "whatsapp.message.queued" in kinds
    assert "whatsapp.message.sent" in kinds
