"""Phase 5C — WhatsApp AI Chat Sales Agent tests.

Coverage groups (mirrors the brief):

- Language detection (Hindi / Hinglish / English)
- Greeting fast-path (template present / missing / per-language)
- Inbound webhook → AI task trigger (Celery eager mode)
- AI provider disabled → no auto-send, suggestion stored
- Claim Vault gate (product context demands a Claim row)
- Blocked claim phrase blocks the auto-send
- Auto-reply gate: low confidence / disabled flag → no send
- Medical emergency / side-effect / legal threat → handoff
- CAIO actor blocked at the freeform send entry
- Discount discipline (no upfront / cap / rescue)
- Order booking happy path + incomplete address + no shipment mutation
- Payment-link ₹499 created via service after booking
- Idempotency on inbound message id
- Audit kinds emitted
- API: ai/status / ai-mode toggle / run-ai / ai-runs / handoff / resume-ai
- Permissions: viewer cannot toggle / run; operations can; anonymous blocked
"""
from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.compliance.models import Claim
from apps.crm.models import Customer
from apps.integrations.ai.base import AdapterResult, AdapterStatus
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.whatsapp import services
from apps.whatsapp.ai_orchestration import run_whatsapp_ai_agent
from apps.whatsapp.ai_schema import (
    BLOCKED_CLAIM_PHRASES,
    parse_decision,
    reply_contains_blocked_phrase,
)
from apps.whatsapp.discount_policy import (
    TOTAL_DISCOUNT_HARD_CAP_PCT,
    evaluate_whatsapp_discount,
    validate_total_discount_cap,
)
from apps.whatsapp.language import (
    LANG_ENGLISH,
    LANG_HINDI,
    LANG_HINGLISH,
    detect_language,
)
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppTemplate,
)
from apps.whatsapp.template_registry import upsert_template


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def operations_user_p5c(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="ops_p5c", password="ops12345", email="ops_p5c@nirogidhara.test"
    )
    user.role = User.Role.OPERATIONS
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def admin_user_p5c(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="admin_p5c", password="admin12345", email="admin_p5c@nirogidhara.test"
    )
    user.role = User.Role.ADMIN
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def viewer_user_p5c(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="viewer_p5c",
        password="viewer12345",
        email="viewer_p5c@nirogidhara.test",
    )
    user.role = User.Role.VIEWER
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-5C-001",
        provider=WhatsAppConnection.Provider.MOCK,
        display_name="Nirogidhara 5C",
        phone_number="+91 9000099991",
        status=WhatsAppConnection.Status.CONNECTED,
    )


@pytest.fixture
def customer(db):
    customer = Customer.objects.create(
        id="NRG-CUST-5C-001",
        name="Phase5C Customer",
        phone="+919999955001",
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
        id="WCV-5C-001",
        customer=customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
        ai_status=WhatsAppConversation.AiStatus.AUTO_AFTER_APPROVAL,
        unread_count=1,
    )


@pytest.fixture
def greeting_templates(connection):
    upsert_template(
        connection=connection,
        name="nrg_greeting_intro",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[
            {
                "type": "BODY",
                "text": (
                    "Namaskar, Nirogidhara Ayurvedic Sanstha mein aapka "
                    "swagat hai. Batayein, main aapki kya help kar sakta/sakti hoon?"
                ),
            }
        ],
        action_key="whatsapp.greeting",
        claim_vault_required=False,
    )
    upsert_template(
        connection=connection,
        name="nrg_greeting_intro",
        language="en",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[
            {
                "type": "BODY",
                "text": "Welcome to Nirogidhara Ayurvedic Sanstha.",
            }
        ],
        action_key="whatsapp.greeting",
        claim_vault_required=False,
    )


@pytest.fixture
def approved_claim(db):
    return Claim.objects.create(
        product="Weight Management",
        approved=["Helpful Ayurvedic blend"],
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


def _create_inbound(
    conversation: WhatsAppConversation,
    *,
    body: str,
    wamid_suffix: str = "AUTO",
) -> WhatsAppMessage:
    return WhatsAppMessage.objects.create(
        id=f"WAM-IN-{wamid_suffix}",
        conversation=conversation,
        customer=conversation.customer,
        provider_message_id=f"wamid.IN-{wamid_suffix}",
        direction=WhatsAppMessage.Direction.INBOUND,
        status=WhatsAppMessage.Status.DELIVERED,
        type=WhatsAppMessage.Type.TEXT,
        body=body,
        queued_at=timezone.now(),
        sent_at=timezone.now(),
        delivered_at=timezone.now(),
    )


def _ai_decision_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "action": "send_reply",
        "language": "hinglish",
        "category": "weight-management",
        "confidence": 0.9,
        "replyText": "Hi! Weight management ke liye humare paas options hain.",
        "needsTemplate": False,
        "handoffReason": "",
        "orderDraft": {
            "customerName": "",
            "phone": "",
            "product": "",
            "skuId": "",
            "quantity": 1,
            "address": "",
            "pincode": "",
            "city": "",
            "state": "",
            "landmark": "",
            "discountPct": 0,
            "amount": 3000,
        },
        "payment": {"shouldCreateAdvanceLink": False, "amount": 499},
        "safety": {
            "claimVaultUsed": True,
            "medicalEmergency": False,
            "sideEffectComplaint": False,
            "legalThreat": False,
            "angryCustomer": False,
        },
    }
    base.update(overrides)
    return base


def _adapter_success(payload: dict[str, Any]) -> AdapterResult:
    return AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model="gpt-test",
        output={"text": json.dumps(payload), "finish_reason": "stop"},
        raw={"id": "resp-test"},
        latency_ms=1,
        cost_usd=0.0,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )


# ---------------------------------------------------------------------------
# 1. Language detection
# ---------------------------------------------------------------------------


def test_language_detect_hindi() -> None:
    detection = detect_language("नमस्ते, मुझे वजन कम करना है।")
    assert detection.language == LANG_HINDI


def test_language_detect_english() -> None:
    detection = detect_language("Hello, I want to lose weight.")
    assert detection.language == LANG_ENGLISH


def test_language_detect_hinglish() -> None:
    detection = detect_language("Hi bhai, weight loss ke liye kya milega?")
    assert detection.language == LANG_HINGLISH


def test_language_detect_empty_defaults_to_unknown() -> None:
    detection = detect_language("")
    assert detection.language == "unknown"


# ---------------------------------------------------------------------------
# 2. Discount policy
# ---------------------------------------------------------------------------


def test_discount_blocked_before_required_pushes() -> None:
    result = evaluate_whatsapp_discount(
        proposed_pct=10,
        current_total_pct=0,
        discount_ask_count=1,
    )
    assert result.allowed is False
    assert "discipline_too_early" in result.notes


def test_discount_unlocked_after_repeated_asks() -> None:
    result = evaluate_whatsapp_discount(
        proposed_pct=10,
        current_total_pct=0,
        discount_ask_count=3,
    )
    assert result.allowed is True


def test_discount_total_cap_blocks_above_50() -> None:
    cap_passed, total = validate_total_discount_cap(
        current_total_pct=40, additional_pct=15
    )
    assert cap_passed is False
    assert total == 55
    result = evaluate_whatsapp_discount(
        proposed_pct=15,
        current_total_pct=40,
        discount_ask_count=3,
    )
    assert result.allowed is False
    assert result.handoff_required is True
    assert "over_total_cap_50" in result.notes
    assert TOTAL_DISCOUNT_HARD_CAP_PCT == 50


def test_discount_rescue_unlocks_proactive_offer() -> None:
    result = evaluate_whatsapp_discount(
        proposed_pct=10,
        current_total_pct=0,
        discount_ask_count=0,
        refusal_trigger="refused_order",
    )
    assert result.allowed is True
    assert "rescue_unlock" in result.notes


# ---------------------------------------------------------------------------
# 3. Schema validator
# ---------------------------------------------------------------------------


def test_schema_parses_decision_dict() -> None:
    decision = parse_decision(_ai_decision_payload())
    assert decision.action == "send_reply"
    assert decision.language == "hinglish"
    assert decision.confidence == pytest.approx(0.9)


def test_schema_invalid_action_falls_back_to_handoff() -> None:
    decision = parse_decision(_ai_decision_payload(action="send_email"))
    assert decision.action == "handoff"


def test_schema_blocked_phrase_detector() -> None:
    assert reply_contains_blocked_phrase(
        "We offer a 100% cure for diabetes."
    ) == "100% cure"
    assert reply_contains_blocked_phrase("Helpful Ayurvedic blend") == ""


# ---------------------------------------------------------------------------
# 4. Greeting fast-path
# ---------------------------------------------------------------------------


def test_greeting_sent_when_template_available(
    conversation, greeting_templates
):
    inbound = _create_inbound(conversation, body="Hi", wamid_suffix="GREET-OK")
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.action == "send_reply"
    assert outcome.sent is True
    assert outcome.stage == "discovery"
    assert AuditEvent.objects.filter(kind="whatsapp.ai.greeting_sent").exists()


def test_greeting_blocked_when_template_missing(conversation):
    # No greeting templates seeded.
    inbound = _create_inbound(conversation, body="Hi", wamid_suffix="GREET-MISS")
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.sent is False
    assert outcome.handoff_required is True
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.greeting_blocked"
    ).exists()


def test_greeting_only_first_outbound(conversation, greeting_templates):
    # Pre-seed an outbound so the greeting fast-path is skipped on the
    # next inbound — orchestration falls into the LLM dispatch path.
    WhatsAppMessage.objects.create(
        id="WAM-OUT-PRESEED",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed outbound",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    inbound = _create_inbound(conversation, body="hi", wamid_suffix="GREET-2ND")
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    # Provider is disabled by default in tests → blocked, not greeted.
    assert outcome.blocked_reason in {"ai_provider_disabled", "ai_disabled"}


# ---------------------------------------------------------------------------
# 5. AI provider disabled / Claim Vault gate
# ---------------------------------------------------------------------------


def test_ai_provider_disabled_blocks_send(conversation, greeting_templates):
    # Pre-seed outbound to skip greeting fast-path.
    WhatsAppMessage.objects.create(
        id="WAM-OUT-PRESEED-PROV",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    inbound = _create_inbound(
        conversation, body="weight loss?", wamid_suffix="PROV"
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.sent is False
    assert outcome.blocked_reason == "ai_provider_disabled"
    assert outcome.handoff_required is True


# ---------------------------------------------------------------------------
# 6. Auto-send gates with mocked LLM dispatch
# ---------------------------------------------------------------------------


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.5,
)
def test_auto_send_happy_path(
    conversation, greeting_templates, approved_claim, monkeypatch
):
    # Pre-seed outbound to skip greeting.
    WhatsAppMessage.objects.create(
        id="WAM-OUT-PRESEED-AUTO",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    inbound = _create_inbound(
        conversation, body="Weight loss ke liye batao", wamid_suffix="AUTO-OK"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.sent is True
    assert outcome.action == "send_reply"
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.reply_auto_sent",
        payload__conversation_id=conversation.id,
    ).exists()


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=False,
)
def test_auto_send_disabled_stores_suggestion(
    conversation, greeting_templates, approved_claim, monkeypatch
):
    WhatsAppMessage.objects.create(
        id="WAM-OUT-PRESEED-OFF",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    inbound = _create_inbound(
        conversation, body="Weight loss ke liye batao", wamid_suffix="AUTO-OFF"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.sent is False
    assert outcome.blocked_reason == "auto_reply_disabled"
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.suggestion_stored"
    ).exists()


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.95,
)
def test_low_confidence_blocks_send(
    conversation, greeting_templates, approved_claim, monkeypatch
):
    WhatsAppMessage.objects.create(
        id="WAM-OUT-PRESEED-LOW",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    inbound = _create_inbound(
        conversation, body="weight?", wamid_suffix="LOW"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(confidence=0.4)
        ),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.sent is False
    assert outcome.blocked_reason == "low_confidence"


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.0,
)
def test_blocked_phrase_blocks_send(
    conversation, greeting_templates, approved_claim, monkeypatch
):
    WhatsAppMessage.objects.create(
        id="WAM-OUT-PRESEED-BLK",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    inbound = _create_inbound(
        conversation, body="Will it cure my disease?", wamid_suffix="BLK"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(replyText="Yes, 100% cure guaranteed.")
        ),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.sent is False
    assert outcome.blocked_reason.startswith("blocked_phrase:")
    assert outcome.handoff_required is True


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.0,
)
def test_medical_emergency_triggers_handoff(
    conversation, greeting_templates, approved_claim, monkeypatch
):
    WhatsAppMessage.objects.create(
        id="WAM-OUT-PRESEED-MED",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    inbound = _create_inbound(
        conversation, body="I am bleeding!", wamid_suffix="MED"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(
                action="handoff",
                handoffReason="medical emergency",
                safety={
                    "claimVaultUsed": True,
                    "medicalEmergency": True,
                    "sideEffectComplaint": False,
                    "legalThreat": False,
                    "angryCustomer": False,
                },
            )
        ),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.sent is False
    assert outcome.handoff_required is True
    assert outcome.blocked_reason == "medical_emergency"
    conversation.refresh_from_db()
    assert conversation.status == WhatsAppConversation.Status.ESCALATED
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.handoff_required"
    ).exists()


# ---------------------------------------------------------------------------
# 7. CAIO blocked at freeform send entry
# ---------------------------------------------------------------------------


def test_caio_actor_blocked_at_freeform_send(conversation):
    with pytest.raises(services.WhatsAppServiceError) as excinfo:
        services.send_freeform_text_message(
            customer=conversation.customer,
            conversation=conversation,
            body="hello",
            actor_role="director",
            actor_agent="caio",
        )
    assert excinfo.value.block_reason == "caio_no_send"
    assert AuditEvent.objects.filter(
        kind="whatsapp.send.blocked",
        payload__block_reason="caio_no_send",
    ).exists()


def test_freeform_send_requires_consent(customer, conversation):
    customer.consent_whatsapp = False
    customer.save(update_fields=["consent_whatsapp"])
    WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={"consent_state": WhatsAppConsent.State.REVOKED},
    )
    with pytest.raises(services.WhatsAppServiceError) as excinfo:
        services.send_freeform_text_message(
            customer=customer,
            conversation=conversation,
            body="hi there",
        )
    assert excinfo.value.block_reason == "consent_missing"


# ---------------------------------------------------------------------------
# 8. Order booking from AI decision
# ---------------------------------------------------------------------------


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.0,
    RAZORPAY_MODE="mock",
)
def test_order_booking_happy_path(
    conversation, greeting_templates, approved_claim, monkeypatch
):
    WhatsAppMessage.objects.create(
        id="WAM-OUT-PRESEED-BOOK",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    inbound = _create_inbound(
        conversation,
        body="Yes, please book it. Confirm karo.",
        wamid_suffix="BOOK",
    )
    decision = _ai_decision_payload(
        action="book_order",
        replyText="Confirming your order.",
        orderDraft={
            "customerName": "Phase5C Customer",
            "phone": "+919999955001",
            "product": "Weight Management",
            "skuId": "",
            "quantity": 1,
            "address": "Flat 4, Plot 22, Aundh",
            "pincode": "411007",
            "city": "Pune",
            "state": "MH",
            "landmark": "near park",
            "discountPct": 0,
            "amount": 3000,
        },
        payment={"shouldCreateAdvanceLink": True, "amount": 499},
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(decision),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.action == "book_order"
    assert outcome.order_id
    assert outcome.payment_id
    order = Order.objects.get(pk=outcome.order_id)
    assert order.stage == Order.Stage.ORDER_PUNCHED
    assert order.amount == 3000
    payment = Payment.objects.get(pk=outcome.payment_id)
    assert payment.amount == 499
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.order_booked"
    ).exists()
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.payment_link_created"
    ).exists()
    # No shipment row created.
    from apps.shipments.models import Shipment

    assert not Shipment.objects.filter(order_id=order.id).exists()


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.0,
)
def test_order_blocked_without_explicit_confirmation(
    conversation, greeting_templates, approved_claim, monkeypatch
):
    WhatsAppMessage.objects.create(
        id="WAM-OUT-PRESEED-NOCFM",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    inbound = _create_inbound(
        conversation, body="bata do prices", wamid_suffix="NOCFM"
    )
    decision = _ai_decision_payload(
        action="book_order",
        orderDraft={
            "customerName": "X",
            "phone": "+919999955001",
            "product": "Weight Management",
            "skuId": "",
            "quantity": 1,
            "address": "Flat 4, Aundh",
            "pincode": "411007",
            "city": "Pune",
            "state": "MH",
            "landmark": "",
            "discountPct": 0,
            "amount": 3000,
        },
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(decision),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.order_id == ""
    assert outcome.blocked_reason == "missing_explicit_confirmation"
    assert Order.objects.filter(phone="+919999955001").count() == 0


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.0,
)
def test_order_blocked_with_incomplete_address(
    conversation, greeting_templates, approved_claim, monkeypatch
):
    WhatsAppMessage.objects.create(
        id="WAM-OUT-PRESEED-INC",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    inbound = _create_inbound(
        conversation, body="haan book karo", wamid_suffix="INC"
    )
    decision = _ai_decision_payload(
        action="book_order",
        orderDraft={
            "customerName": "X",
            "phone": "+919999955001",
            "product": "Weight Management",
            "skuId": "",
            "quantity": 1,
            "address": "",  # missing!
            "pincode": "411007",
            "city": "Pune",
            "state": "MH",
            "landmark": "",
            "discountPct": 0,
            "amount": 3000,
        },
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(decision),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome.order_id == ""
    assert outcome.blocked_reason == "order_booking_blocked:incomplete_address"
    assert outcome.handoff_required is True


# ---------------------------------------------------------------------------
# 9. Idempotency
# ---------------------------------------------------------------------------


def test_idempotent_skip_for_processed_inbound(
    conversation, greeting_templates
):
    inbound = _create_inbound(conversation, body="hi", wamid_suffix="IDEM")
    outcome1 = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome1.sent is True
    outcome2 = run_whatsapp_ai_agent(
        conversation_id=conversation.id, inbound_message_id=inbound.id
    )
    assert outcome2.sent is False
    assert "idempotent_skip" in outcome2.notes


# ---------------------------------------------------------------------------
# 10. API endpoints + permissions
# ---------------------------------------------------------------------------


def test_ai_status_endpoint_returns_state(operations_user_p5c, conversation):
    res = _auth(APIClient(), operations_user_p5c).get("/api/whatsapp/ai/status/")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in {"provider_disabled", "auto_reply_off", "auto"}
    assert "rateLimits" in body


def test_ai_mode_patch_operations(operations_user_p5c, conversation):
    res = _auth(APIClient(), operations_user_p5c).patch(
        f"/api/whatsapp/conversations/{conversation.id}/ai-mode/",
        {"aiEnabled": False, "aiMode": "suggest"},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["ai"]["aiEnabled"] is False
    assert res.json()["ai"]["aiMode"] == "suggest"


def test_ai_mode_patch_viewer_blocked(viewer_user_p5c, conversation):
    res = _auth(APIClient(), viewer_user_p5c).patch(
        f"/api/whatsapp/conversations/{conversation.id}/ai-mode/",
        {"aiEnabled": False},
        format="json",
    )
    assert res.status_code == 403


def test_ai_mode_patch_anonymous_blocked(conversation):
    res = APIClient().patch(
        f"/api/whatsapp/conversations/{conversation.id}/ai-mode/",
        {"aiEnabled": False},
        format="json",
    )
    assert res.status_code == 401


def test_run_ai_endpoint_operations(operations_user_p5c, conversation):
    # No greeting template seeded → expected blocked outcome.
    _create_inbound(conversation, body="hi", wamid_suffix="RUN")
    res = _auth(APIClient(), operations_user_p5c).post(
        f"/api/whatsapp/conversations/{conversation.id}/run-ai/",
        {},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["conversationId"] == conversation.id


def test_handoff_endpoint_flips_status(operations_user_p5c, conversation):
    res = _auth(APIClient(), operations_user_p5c).post(
        f"/api/whatsapp/conversations/{conversation.id}/handoff/",
        {"reason": "manual review"},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["ai"]["handoffRequired"] is True
    conversation.refresh_from_db()
    assert conversation.status == WhatsAppConversation.Status.ESCALATED


def test_resume_ai_re_enables_state(operations_user_p5c, conversation):
    # Seed handoff state.
    metadata = dict(conversation.metadata or {})
    metadata["ai"] = {"aiEnabled": False, "handoffRequired": True}
    conversation.metadata = metadata
    conversation.status = WhatsAppConversation.Status.ESCALATED
    conversation.save(update_fields=["metadata", "status"])

    res = _auth(APIClient(), operations_user_p5c).post(
        f"/api/whatsapp/conversations/{conversation.id}/resume-ai/",
        {},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ai"]["aiEnabled"] is True
    assert body["ai"]["handoffRequired"] is False
    conversation.refresh_from_db()
    assert conversation.status == WhatsAppConversation.Status.OPEN


def test_ai_runs_endpoint_returns_state(operations_user_p5c, conversation):
    res = _auth(APIClient(), operations_user_p5c).get(
        f"/api/whatsapp/conversations/{conversation.id}/ai-runs/"
    )
    assert res.status_code == 200
    body = res.json()
    assert "ai" in body
    assert "events" in body
    assert isinstance(body["events"], list)


# ---------------------------------------------------------------------------
# 11. Inbound webhook → AI task trigger (Celery eager mode)
# ---------------------------------------------------------------------------


def test_inbound_webhook_triggers_ai_task(customer, connection, greeting_templates):
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "ENTRY-AI",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "PNID"},
                                "messages": [
                                    {
                                        "id": "wamid.IN-AI-TRIGGER",
                                        "from": customer.phone.replace("+", ""),
                                        "type": "text",
                                        "text": {"body": "Hi"},
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
    assert AuditEvent.objects.filter(kind="whatsapp.ai.run_started").exists()
    # Greeting template available → greeting sent.
    assert AuditEvent.objects.filter(kind="whatsapp.ai.greeting_sent").exists()
