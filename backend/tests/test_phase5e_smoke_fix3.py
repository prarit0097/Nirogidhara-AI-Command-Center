"""Phase 5E-Smoke-Fix-3 — false-positive safety classification tests.

The OpenAI smoke run on the VPS reported ``overallPassed=false`` because
the orchestrator wrongly classified
"Hi mujhe weight loss product ke baare me batana" as a
``side_effect_complaint``. This module proves:

1. The new :func:`validate_safety_flags` deterministically downgrades
   safety flags whose vocabulary is absent from the inbound text.
2. Real side-effect / medical-emergency / legal vocabulary is still
   honoured — the validator never weakens an actual safety signal.
3. Wired end-to-end through ``run_whatsapp_ai_agent``: an LLM that
   over-flags a normal product inquiry no longer blocks the reply, an
   audit row ``whatsapp.ai.safety_downgraded`` is emitted, and a real
   side-effect inbound still routes to handoff.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.compliance.models import Claim
from apps.crm.models import Customer
from apps.integrations.ai.base import AdapterResult, AdapterStatus
from apps.whatsapp.ai_orchestration import run_whatsapp_ai_agent
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppTemplate,
)
from apps.whatsapp.safety_validation import (
    LEGAL_THREAT_KEYWORDS,
    MEDICAL_EMERGENCY_KEYWORDS,
    SIDE_EFFECT_KEYWORDS,
    validate_safety_flags,
)
from apps.whatsapp.template_registry import upsert_template


# ---------------------------------------------------------------------------
# Section 1 — Pure validator unit tests (no DB required)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "inbound",
    [
        # English product inquiry
        "Hi I want to know about your weight loss product",
        # Hinglish product inquiry — the exact VPS smoke false-positive
        "Hi mujhe weight loss product ke baare me batana",
        # Hindi product inquiry
        "Namaste mujhe vajan kam karne ki dawai chahiye",
        # Generic discount ask
        "Discount do please",
        # Pricing question
        "Kitne ka aata hai?",
    ],
)
def test_normal_inquiry_downgrades_side_effect_false_positive(
    inbound: str,
) -> None:
    flags_in = {
        "claimVaultUsed": True,
        "medicalEmergency": False,
        "sideEffectComplaint": True,  # LLM mistakenly set this
        "legalThreat": False,
        "angryCustomer": False,
    }
    corrected, downgraded = validate_safety_flags(inbound, flags_in)
    assert corrected["sideEffectComplaint"] is False
    assert "sideEffectComplaint" in downgraded


@pytest.mark.parametrize(
    "inbound",
    [
        # English
        "I had a side effect after taking the tablet",
        "Capsules ke baad allergic reaction ho gayi",
        # Hinglish
        "medicine khane ke baad ulta asar ho gaya",
        "tablet lene ke baad problem ho gayi",
        "capsules lene ke baad rash and swelling ho rahi hai",
        # Hindi-style
        "khane ke baad ulta asar mehsoos ho raha hai",
    ],
)
def test_real_side_effect_phrase_stays_flagged(inbound: str) -> None:
    flags_in = {
        "claimVaultUsed": True,
        "medicalEmergency": False,
        "sideEffectComplaint": True,
        "legalThreat": False,
        "angryCustomer": False,
    }
    corrected, downgraded = validate_safety_flags(inbound, flags_in)
    assert corrected["sideEffectComplaint"] is True
    assert "sideEffectComplaint" not in downgraded


def test_medical_emergency_false_positive_downgraded() -> None:
    flags_in = {
        "claimVaultUsed": True,
        "medicalEmergency": True,
        "sideEffectComplaint": False,
        "legalThreat": False,
        "angryCustomer": False,
    }
    corrected, downgraded = validate_safety_flags(
        "Mujhe weight loss ke baare me batao", flags_in
    )
    assert corrected["medicalEmergency"] is False
    assert "medicalEmergency" in downgraded


@pytest.mark.parametrize(
    "inbound",
    [
        "I have chest pain please send ambulance",
        "Saans nahi aa rahi, hospital le jao",
        "behosh ho gayi, ambulance chahiye",
    ],
)
def test_real_medical_emergency_stays_flagged(inbound: str) -> None:
    flags_in = {
        "claimVaultUsed": True,
        "medicalEmergency": True,
        "sideEffectComplaint": False,
        "legalThreat": False,
        "angryCustomer": False,
    }
    corrected, downgraded = validate_safety_flags(inbound, flags_in)
    assert corrected["medicalEmergency"] is True
    assert "medicalEmergency" not in downgraded


def test_legal_threat_false_positive_downgraded() -> None:
    flags_in = {
        "claimVaultUsed": True,
        "medicalEmergency": False,
        "sideEffectComplaint": False,
        "legalThreat": True,
        "angryCustomer": False,
    }
    corrected, downgraded = validate_safety_flags(
        "Aapka product accha hai kya?", flags_in
    )
    assert corrected["legalThreat"] is False
    assert "legalThreat" in downgraded


@pytest.mark.parametrize(
    "inbound",
    [
        "I will sue your company",
        "Consumer forum me complaint karunga",
        "Police me FIR karwau ga",
    ],
)
def test_real_legal_threat_stays_flagged(inbound: str) -> None:
    flags_in = {
        "claimVaultUsed": True,
        "medicalEmergency": False,
        "sideEffectComplaint": False,
        "legalThreat": True,
        "angryCustomer": False,
    }
    corrected, downgraded = validate_safety_flags(inbound, flags_in)
    assert corrected["legalThreat"] is True
    assert "legalThreat" not in downgraded


def test_angry_customer_flag_never_touched() -> None:
    """Anger is a tone signal — keyword matching is too unreliable, so
    the validator must always trust the LLM's ``angryCustomer`` flag."""
    flags_in = {
        "claimVaultUsed": True,
        "medicalEmergency": False,
        "sideEffectComplaint": False,
        "legalThreat": False,
        "angryCustomer": True,
    }
    corrected, downgraded = validate_safety_flags("Just a polite hi", flags_in)
    assert corrected["angryCustomer"] is True
    assert "angryCustomer" not in downgraded


def test_claim_vault_used_flag_never_touched() -> None:
    """``claimVaultUsed`` describes the AI reply, not the inbound."""
    flags_in = {
        "claimVaultUsed": False,
        "medicalEmergency": False,
        "sideEffectComplaint": False,
        "legalThreat": False,
        "angryCustomer": False,
    }
    corrected, downgraded = validate_safety_flags("hello", flags_in)
    assert corrected["claimVaultUsed"] is False
    assert "claimVaultUsed" not in downgraded


def test_validator_never_promotes_false_to_true() -> None:
    flags_in = {
        "claimVaultUsed": True,
        "medicalEmergency": False,
        "sideEffectComplaint": False,
        "legalThreat": False,
        "angryCustomer": False,
    }
    # Even with strong vocabulary in the inbound, a false flag stays false.
    corrected, downgraded = validate_safety_flags(
        "I had a side effect after taking the tablet", flags_in
    )
    assert corrected["sideEffectComplaint"] is False
    assert downgraded == []


def test_validator_handles_empty_inbound_text() -> None:
    flags_in = {
        "claimVaultUsed": True,
        "medicalEmergency": True,
        "sideEffectComplaint": True,
        "legalThreat": True,
        "angryCustomer": True,
    }
    corrected, downgraded = validate_safety_flags("", flags_in)
    # Empty inbound → trust LLM as-is.
    assert corrected == flags_in
    assert downgraded == []


def test_validator_handles_none_safety_dict() -> None:
    corrected, downgraded = validate_safety_flags("hello", None)
    assert corrected["claimVaultUsed"] is True
    assert corrected["medicalEmergency"] is False
    assert corrected["sideEffectComplaint"] is False
    assert corrected["legalThreat"] is False
    assert corrected["angryCustomer"] is False
    assert downgraded == []


def test_keyword_vocab_is_lowercase() -> None:
    """All vocabulary must be lowercase; the validator lowercases the
    inbound before matching."""
    for vocab in (
        SIDE_EFFECT_KEYWORDS,
        MEDICAL_EMERGENCY_KEYWORDS,
        LEGAL_THREAT_KEYWORDS,
    ):
        for word in vocab:
            assert word == word.lower(), f"{word!r} must be lowercase"


# ---------------------------------------------------------------------------
# Section 2 — End-to-end integration through run_whatsapp_ai_agent
# ---------------------------------------------------------------------------


@pytest.fixture
def connection_fix3(db):
    return WhatsAppConnection.objects.create(
        id="WAC-FIX3-001",
        provider=WhatsAppConnection.Provider.MOCK,
        display_name="Nirogidhara Fix3",
        phone_number="+91 9000099992",
        status=WhatsAppConnection.Status.CONNECTED,
    )


@pytest.fixture
def customer_fix3(db):
    customer = Customer.objects.create(
        id="NRG-CUST-FIX3-001",
        name="Fix3 Customer",
        phone="+919999933001",
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
def conversation_fix3(db, customer_fix3, connection_fix3):
    return WhatsAppConversation.objects.create(
        id="WCV-FIX3-001",
        customer=customer_fix3,
        connection=connection_fix3,
        status=WhatsAppConversation.Status.OPEN,
        ai_status=WhatsAppConversation.AiStatus.AUTO_AFTER_APPROVAL,
        unread_count=1,
    )


@pytest.fixture
def greeting_template_fix3(connection_fix3):
    upsert_template(
        connection=connection_fix3,
        name="nrg_greeting_intro",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[
            {"type": "BODY", "text": "Namaskar, Nirogidhara."},
        ],
        action_key="whatsapp.greeting",
        claim_vault_required=False,
    )


@pytest.fixture
def claim_fix3(db):
    return Claim.objects.create(
        product="Weight Management",
        approved=["Helpful Ayurvedic blend"],
        disallowed=["Guaranteed cure"],
        doctor="Dr Test",
        compliance="Compliance Test",
        version="v1.0",
    )


def _seed_outbound(conversation: WhatsAppConversation, suffix: str) -> None:
    WhatsAppMessage.objects.create(
        id=f"WAM-OUT-FIX3-{suffix}",
        conversation=conversation,
        customer=conversation.customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )


def _create_inbound_fix3(
    conversation: WhatsAppConversation, *, body: str, suffix: str
) -> WhatsAppMessage:
    return WhatsAppMessage.objects.create(
        id=f"WAM-IN-FIX3-{suffix}",
        conversation=conversation,
        customer=conversation.customer,
        provider_message_id=f"wamid.IN-FIX3-{suffix}",
        direction=WhatsAppMessage.Direction.INBOUND,
        status=WhatsAppMessage.Status.DELIVERED,
        type=WhatsAppMessage.Type.TEXT,
        body=body,
        queued_at=timezone.now(),
        sent_at=timezone.now(),
        delivered_at=timezone.now(),
    )


def _decision_payload_with_false_side_effect() -> dict[str, Any]:
    return {
        "action": "send_reply",
        "language": "hinglish",
        "category": "weight-management",
        "confidence": 0.9,
        "replyText": (
            "Hi! Weight management ke liye humare paas Helpful "
            "Ayurvedic blend hai. Price ₹3000 / 30 capsules."
        ),
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
        # The bug we are fixing: LLM mis-flags a product inquiry as a
        # side-effect complaint.
        "safety": {
            "claimVaultUsed": True,
            "medicalEmergency": False,
            "sideEffectComplaint": True,
            "legalThreat": False,
            "angryCustomer": False,
        },
    }


def _decision_payload_with_real_side_effect_handoff() -> dict[str, Any]:
    payload = _decision_payload_with_false_side_effect()
    payload["action"] = "handoff"
    payload["handoffReason"] = "side effect complaint"
    payload["replyText"] = "Operator se baat karwati hu."
    return payload


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


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.0,
)
def test_false_positive_side_effect_does_not_block_normal_inquiry(
    conversation_fix3,
    greeting_template_fix3,
    claim_fix3,
    monkeypatch,
):
    _seed_outbound(conversation_fix3, "FALSEPOS")
    inbound = _create_inbound_fix3(
        conversation_fix3,
        body="Hi mujhe weight loss product ke baare me batana",
        suffix="FALSEPOS",
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _decision_payload_with_false_side_effect()
        ),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation_fix3.id,
        inbound_message_id=inbound.id,
    )
    assert outcome.sent is True, (
        "Normal product inquiry should auto-send after the safety "
        f"validator downgrades the false positive (blocked={outcome.blocked_reason})"
    )
    assert outcome.action == "send_reply"
    assert outcome.handoff_required is False
    # Audit row proves the corrector ran observably.
    downgrade_events = AuditEvent.objects.filter(
        kind="whatsapp.ai.safety_downgraded",
        payload__conversation_id=conversation_fix3.id,
    )
    assert downgrade_events.exists()
    payload = downgrade_events.first().payload
    assert "sideEffectComplaint" in payload["downgraded_flags"]


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.0,
)
def test_real_side_effect_complaint_still_blocks_send(
    conversation_fix3,
    greeting_template_fix3,
    claim_fix3,
    monkeypatch,
):
    _seed_outbound(conversation_fix3, "REALSE")
    inbound = _create_inbound_fix3(
        conversation_fix3,
        body="medicine khane ke baad ulta asar ho gaya, vomiting bhi hui",
        suffix="REALSE",
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _decision_payload_with_real_side_effect_handoff()
        ),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation_fix3.id,
        inbound_message_id=inbound.id,
    )
    assert outcome.sent is False
    assert outcome.blocked_reason == "side_effect_complaint"
    assert outcome.handoff_required is True
    # No downgrade audit row should be present — the keyword matched.
    assert not AuditEvent.objects.filter(
        kind="whatsapp.ai.safety_downgraded",
        payload__conversation_id=conversation_fix3.id,
    ).exists()


@override_settings(
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.0,
)
def test_real_medical_emergency_still_blocks_send(
    conversation_fix3,
    greeting_template_fix3,
    claim_fix3,
    monkeypatch,
):
    _seed_outbound(conversation_fix3, "REALMED")
    inbound = _create_inbound_fix3(
        conversation_fix3,
        body="seene me dard ho raha hai, ambulance chahiye",
        suffix="REALMED",
    )
    payload = _decision_payload_with_false_side_effect()
    payload["action"] = "handoff"
    payload["handoffReason"] = "medical emergency"
    payload["safety"] = {
        "claimVaultUsed": True,
        "medicalEmergency": True,
        "sideEffectComplaint": False,
        "legalThreat": False,
        "angryCustomer": False,
    }
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(payload),
    )
    outcome = run_whatsapp_ai_agent(
        conversation_id=conversation_fix3.id,
        inbound_message_id=inbound.id,
    )
    assert outcome.sent is False
    assert outcome.blocked_reason == "medical_emergency"
    assert outcome.handoff_required is True
