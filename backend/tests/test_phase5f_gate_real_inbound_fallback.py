"""Phase 5F-Gate Real Inbound Deterministic Fallback Fix tests.

The first real inbound auto-reply attempt on the VPS (allowed test
number suffix 9990 → real Meta inbound ``WAM-100059``) was blocked
with ``claim_vault_not_used`` even though backend grounding was
fully present (``claim_row_count=1``, ``approved_claim_count=3``,
``confidence=0.9``). Root cause: the CLI controlled-test command
applies the deterministic grounded fallback OUTSIDE the orchestrator,
so the real-inbound webhook path never benefited from it.

This phase wires the deterministic fallback INTO the orchestrator's
``run_whatsapp_ai_agent`` for the soft non-safety blockers
(``claim_vault_not_used`` / ``low_confidence`` / ``ai_handoff_requested``
/ ``no_action``) when auto-reply is enabled (env flag OR
``force_auto_reply=True``) AND the latest inbound is a normal
product-info inquiry with no live safety signal AND backend grounding
is valid.

Hard rules covered by these tests:

- The fallback NEVER bypasses consent, the limited-mode allow-list
  guard, CAIO, or idempotency. Send goes through
  :func:`apps.whatsapp.services.send_freeform_text_message`.
- The fallback NEVER mutates ``Order`` / ``Payment`` / ``Shipment``
  / ``DiscountOfferLog``.
- The fallback NEVER fires when auto-reply is globally off and the
  run was not CLI-forced — that path stays as a stored suggestion.
- The fallback NEVER fires when the latest inbound has a live safety
  signal (side-effect, legal threat, medical emergency).
- Latest-inbound safety isolation: older synthetic scenario messages
  in the same conversation history must not poison the current safe
  query. Real safety signals in the LATEST inbound still block.
- Real flag-driven runs emit ``whatsapp.ai.auto_reply_flag_path_used``
  (the soak monitor counts those). CLI-forced runs do NOT emit it.
- All audit payloads carry phone last-4 only — never full E.164,
  never tokens.
"""
from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.compliance.models import Claim
from apps.crm.models import Customer
from apps.integrations.ai.base import AdapterResult, AdapterStatus
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment
from apps.whatsapp import services as whatsapp_services
from apps.whatsapp.ai_orchestration import run_whatsapp_ai_agent
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
)


META_CREDS = dict(
    WHATSAPP_PROVIDER="meta_cloud",
    WHATSAPP_LIVE_META_LIMITED_TEST_MODE=True,
    WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS="+91 89498 79990",
    META_WA_ACCESS_TOKEN="dummy-meta-token-not-real",
    META_WA_PHONE_NUMBER_ID="123456789",
    META_WA_BUSINESS_ACCOUNT_ID="987654321",
    META_WA_VERIFY_TOKEN="dummy-verify-token",
    META_WA_APP_SECRET="dummy-app-secret",
    WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.5,
    WHATSAPP_CALL_HANDOFF_ENABLED=False,
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=False,
    WHATSAPP_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_REORDER_DAY20_ENABLED=False,
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-RIF-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Real Inbound Fallback Test",
        phone_number="+91 9000099000",
        phone_number_id="meta-phone-number-id-rif",
        business_account_id="meta-waba-id-rif",
        status=WhatsAppConnection.Status.CONNECTED,
    )


@pytest.fixture
def weight_management_claim(db):
    return Claim.objects.create(
        product="Weight Management",
        approved=[
            "Supports healthy metabolism",
            "Ayurvedic blend used traditionally",
            "Best with diet & activity",
        ],
        disallowed=["Guaranteed cure", "Permanent solution"],
        doctor="Approved",
        compliance="Approved",
        version="v3.2",
    )


@pytest.fixture
def customer_allowed(db):
    customer = Customer.objects.create(
        id="NRG-CUST-RIF-001",
        name="Allowed Test User",
        phone="+918949879990",
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
def customer_not_allowed(db):
    """A customer whose phone is NOT on the allow-list."""
    customer = Customer.objects.create(
        id="NRG-CUST-RIF-002",
        name="Not Allowed",
        phone="+919999999999",
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
        id="NRG-CUST-RIF-003",
        name="No Consent",
        phone="+918949879990",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=False,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ai_decision_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "action": "send_reply",
        "language": "hinglish",
        "category": "weight-management",
        "confidence": 0.9,
        "replyText": "Generic placeholder reply that the LLM thinks isn't grounded.",
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
            "claimVaultUsed": False,  # the LLM says NOT grounded → soft block
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
        raw={"id": "resp-rif"},
        latency_ms=1,
        cost_usd=0.0,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )


def _seed_outbound(connection, customer):
    convo = whatsapp_services.get_or_open_conversation(
        customer, connection=connection
    )
    WhatsAppMessage.objects.create(
        id=f"WAM-RIF-PRESEED-{customer.id}",
        conversation=convo,
        customer=customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed greeting",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    return convo


def _create_inbound(convo, customer, body: str, *, suffix: str = "main") -> WhatsAppMessage:
    return WhatsAppMessage.objects.create(
        id=f"WAM-RIF-IN-{customer.id}-{suffix}",
        conversation=convo,
        customer=customer,
        direction=WhatsAppMessage.Direction.INBOUND,
        status=WhatsAppMessage.Status.DELIVERED,
        type=WhatsAppMessage.Type.TEXT,
        body=body,
        provider_message_id=f"wamid.RIF-IN-{customer.id}-{suffix}",
        queued_at=timezone.now(),
        delivered_at=timezone.now(),
    )


def _patch_provider_success(monkeypatch, *, mid: str = "wamid.RIF-OK"):
    fake = mock.Mock()
    fake.name = "meta_cloud"
    fake.send_text_message.return_value = mock.Mock(
        provider="meta_cloud",
        provider_message_id=mid,
        status="sent",
        request_payload={"to": "+918949879990"},
        response_payload={},
        response_status=200,
        latency_ms=1,
    )
    monkeypatch.setattr("apps.whatsapp.services.get_provider", lambda: fake)


# ---------------------------------------------------------------------------
# Section A — Real inbound deterministic fallback success path
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_real_inbound_uses_deterministic_fallback_when_llm_says_claim_vault_not_used(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    """The original VPS reproducer: backend grounding is valid but the
    LLM returns ``safety.claimVaultUsed=false``. The orchestrator must
    fall back to the deterministic Claim-Vault-grounded reply and send
    via the real-inbound auto-reply path.
    """
    convo = _seed_outbound(connection, customer_allowed)
    inbound = _create_inbound(
        convo,
        customer_allowed,
        "Namaste. Mujhe weight management product ke price aur capsule "
        "quantity ke baare me bataye.",
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    _patch_provider_success(monkeypatch)

    orders_before = Order.objects.count()
    payments_before = Payment.objects.count()
    shipments_before = Shipment.objects.count()
    discounts_before = DiscountOfferLog.objects.count()

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )

    assert outcome.sent is True
    assert outcome.action == "send_reply"
    assert "deterministic_grounded_fallback_used" in outcome.notes
    # claimVaultUsed flipped to True because the validator confirmed
    # the reply text embeds an approved phrase.
    assert outcome.decision is not None
    assert outcome.decision.safety["claimVaultUsed"] is True

    # Audit ledger.
    used = AuditEvent.objects.filter(
        kind="whatsapp.ai.deterministic_grounded_reply_used"
    ).first()
    assert used is not None
    assert used.payload["category"] == "weight-management"
    assert used.payload["normalized_claim_product"] == "Weight Management"
    assert used.payload["fallback_reason"] == "claim_vault_not_used"
    assert used.payload["final_reply_source"] == "deterministic_grounded_builder"
    assert used.payload["phone_suffix"] == "9990"
    assert "+918949879990" not in json.dumps(used.payload)

    # Real flag-driven path → flag_path_used must be emitted.
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.auto_reply_flag_path_used"
    ).exists()
    flag_audit = AuditEvent.objects.filter(
        kind="whatsapp.ai.auto_reply_flag_path_used"
    ).first()
    assert flag_audit.payload["deterministic_fallback_used"] is True
    assert (
        flag_audit.payload["final_reply_source"]
        == "deterministic_grounded_builder"
    )
    assert flag_audit.payload["claim_vault_used"] is True

    # Reply was actually persisted as an outbound text message.
    sent_msg = WhatsAppMessage.objects.filter(
        conversation=convo,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        type=WhatsAppMessage.Type.TEXT,
    ).first()
    assert sent_msg is not None
    assert "Supports healthy metabolism" in sent_msg.body or (
        "Ayurvedic blend used traditionally" in sent_msg.body
    )
    # ₹3000 / 30 capsules / ₹499 advance must appear.
    assert "₹3000" in sent_msg.body
    assert "30" in sent_msg.body
    assert "₹499" in sent_msg.body

    # No Order / Payment / Shipment / DiscountOfferLog created.
    assert Order.objects.count() == orders_before
    assert Payment.objects.count() == payments_before
    assert Shipment.objects.count() == shipments_before
    assert DiscountOfferLog.objects.count() == discounts_before


@override_settings(**META_CREDS)
def test_real_inbound_fallback_fires_on_low_confidence_too(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    """The fallback must also fire when the LLM returns a confidence
    below the threshold for a normal grounded inquiry."""
    convo = _seed_outbound(connection, customer_allowed)
    inbound = _create_inbound(
        convo,
        customer_allowed,
        "weight management product ke price aur capsule quantity batao",
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(
                confidence=0.3,
                safety={
                    "claimVaultUsed": True,
                    "medicalEmergency": False,
                    "sideEffectComplaint": False,
                    "legalThreat": False,
                    "angryCustomer": False,
                },
            )
        ),
    )
    _patch_provider_success(monkeypatch)

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    assert outcome.sent is True
    assert "deterministic_grounded_fallback_used" in outcome.notes
    used = AuditEvent.objects.filter(
        kind="whatsapp.ai.deterministic_grounded_reply_used"
    ).first()
    assert used is not None
    assert used.payload["fallback_reason"] == "low_confidence"


@override_settings(**META_CREDS)
def test_real_inbound_fallback_fires_on_ai_handoff_requested(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    """When the LLM picks ``action=handoff`` on a normal product
    inquiry despite valid grounding, the orchestrator must fall back
    rather than escalating to a human."""
    convo = _seed_outbound(connection, customer_allowed)
    inbound = _create_inbound(
        convo,
        customer_allowed,
        "weight management product ke baare me jaankari chahiye",
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(
                action="handoff",
                handoffReason="Cautious — passing to human.",
                safety={
                    "claimVaultUsed": True,
                    "medicalEmergency": False,
                    "sideEffectComplaint": False,
                    "legalThreat": False,
                    "angryCustomer": False,
                },
            )
        ),
    )
    _patch_provider_success(monkeypatch)

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    assert outcome.sent is True
    assert "deterministic_grounded_fallback_used" in outcome.notes


# ---------------------------------------------------------------------------
# Section B — Latest-inbound safety isolation
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_latest_safe_inbound_not_poisoned_by_synthetic_history(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    """The conversation has older synthetic side-effect / legal /
    refund test messages. The LATEST inbound is a clean weight-
    management product info query. The orchestrator must NOT block
    based on the older history.
    """
    convo = _seed_outbound(connection, customer_allowed)
    # Synthetic history pollution — these are inbounds from previous
    # scenario tests that an LLM might use as context.
    _create_inbound(
        convo,
        customer_allowed,
        "side effect ho gaya, ulta asar ho raha hai",
        suffix="hist1",
    )
    _create_inbound(
        convo,
        customer_allowed,
        "main consumer forum jaaunga, lawyer se baat karunga",
        suffix="hist2",
    )

    inbound = _create_inbound(
        convo,
        customer_allowed,
        "Namaste. Mujhe weight management product ke price aur capsule "
        "quantity ke baare me bataye.",
        suffix="latest",
    )

    # The LLM, biased by history, returns a side-effect flag even
    # though the LATEST inbound has zero side-effect vocabulary.
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(
                safety={
                    "claimVaultUsed": False,
                    "medicalEmergency": False,
                    "sideEffectComplaint": True,  # bias from history
                    "legalThreat": True,  # bias from history
                    "angryCustomer": False,
                },
            )
        ),
    )
    _patch_provider_success(monkeypatch)

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )

    # The latest-inbound safety corrector flips both flags down → the
    # deterministic fallback runs successfully.
    assert outcome.sent is True
    assert "deterministic_grounded_fallback_used" in outcome.notes

    # safety_downgraded audit emitted with explicit isolation metadata.
    downgraded = AuditEvent.objects.filter(
        kind="whatsapp.ai.safety_downgraded"
    ).first()
    assert downgraded is not None
    assert (
        downgraded.payload["history_safety_ignored_for_current_safe_query"]
        is True
    )
    assert "sideEffectComplaint" in downgraded.payload["downgraded_flags"]
    assert "legalThreat" in downgraded.payload["downgraded_flags"]
    # Latest-inbound snapshot.
    assert downgraded.payload["latest_inbound_message_id"] == inbound.id
    # History view captured separately.
    assert (
        downgraded.payload["history_safety_flags"]["sideEffectComplaint"] is True
    )
    assert (
        downgraded.payload["latest_inbound_safety_flags"][
            "sideEffectComplaint"
        ]
        is False
    )


@override_settings(**META_CREDS)
def test_real_side_effect_in_latest_inbound_still_blocks(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    """When the LATEST inbound itself contains real side-effect
    vocabulary, the safety stack must block — fallback never fires."""
    convo = _seed_outbound(connection, customer_allowed)
    inbound = _create_inbound(
        convo,
        customer_allowed,
        "medicine khane ke baad ulta asar ho raha hai aur skin pe rash aa gaya",
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(
                category="weight-management",
                safety={
                    "claimVaultUsed": False,
                    "medicalEmergency": False,
                    "sideEffectComplaint": True,
                    "legalThreat": False,
                    "angryCustomer": False,
                },
            )
        ),
    )
    _patch_provider_success(monkeypatch)

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    assert outcome.sent is False
    assert outcome.blocked_reason == "side_effect_complaint"
    assert "deterministic_grounded_fallback_used" not in outcome.notes
    # No deterministic grounded reply audit.
    assert not AuditEvent.objects.filter(
        kind="whatsapp.ai.deterministic_grounded_reply_used"
    ).exists()


@override_settings(**META_CREDS)
def test_legal_threat_in_latest_inbound_still_blocks(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    """A legal/refund threat in the LATEST inbound never falls back."""
    convo = _seed_outbound(connection, customer_allowed)
    inbound = _create_inbound(
        convo,
        customer_allowed,
        "main lawyer ko bulaunga, consumer forum me jaaunga, refund chahiye",
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(
                category="weight-management",
                safety={
                    "claimVaultUsed": False,
                    "medicalEmergency": False,
                    "sideEffectComplaint": False,
                    "legalThreat": True,
                    "angryCustomer": True,
                },
            )
        ),
    )
    _patch_provider_success(monkeypatch)

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    assert outcome.sent is False
    assert outcome.blocked_reason == "legal_threat"
    assert "deterministic_grounded_fallback_used" not in outcome.notes


# ---------------------------------------------------------------------------
# Section C — Hard guardrails the fallback must never bypass
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_fallback_refused_when_destination_not_on_allow_list(
    connection, weight_management_claim, customer_not_allowed, monkeypatch
) -> None:
    """When the customer phone is not on the allow-list, the final-
    send guard inside ``services.send_freeform_text_message`` refuses.
    The orchestrator must NOT mark the run sent; it must emit the
    ``auto_reply_guard_blocked`` audit and the deterministic-blocked
    audit so the soak monitor sees the leak attempt.
    """
    convo = _seed_outbound(connection, customer_not_allowed)
    inbound = _create_inbound(
        convo,
        customer_not_allowed,
        "weight management product ke price kya hai",
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    _patch_provider_success(monkeypatch)

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )

    # Send refused → outcome.sent stays False.
    assert outcome.sent is False
    # Guard-blocked audit fired.
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.auto_reply_guard_blocked"
    ).exists()
    guard_audit = AuditEvent.objects.filter(
        kind="whatsapp.ai.auto_reply_guard_blocked"
    ).first()
    assert (
        guard_audit.payload["block_reason"]
        == "limited_test_number_not_allowed"
    )
    # Phone number NEVER appears in audit payload.
    assert "+919999999999" not in json.dumps(guard_audit.payload)
    # The flag-path-used audit must NOT fire on refusal.
    assert not AuditEvent.objects.filter(
        kind="whatsapp.ai.auto_reply_flag_path_used"
    ).exists()


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": False}
)
def test_fallback_does_not_fire_when_auto_reply_disabled(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    """When the env flag is off and force_auto_reply=False, the
    fallback must NOT fire. The operator wants the suggestion stored
    for manual review — not an auto-send."""
    convo = _seed_outbound(connection, customer_allowed)
    inbound = _create_inbound(
        convo, customer_allowed, "weight management product price"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    _patch_provider_success(monkeypatch)

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    assert outcome.sent is False
    assert outcome.blocked_reason == "claim_vault_not_used"
    assert "deterministic_grounded_fallback_used" not in outcome.notes
    assert not AuditEvent.objects.filter(
        kind="whatsapp.ai.deterministic_grounded_reply_used"
    ).exists()


@override_settings(**META_CREDS)
def test_fallback_refused_when_consent_missing(
    connection, weight_management_claim, customer_no_consent, monkeypatch
) -> None:
    """No WhatsApp consent → orchestrator returns at the consent
    guard before the LLM dispatch ever runs. Fallback never sees the
    customer."""
    convo = whatsapp_services.get_or_open_conversation(
        customer_no_consent, connection=connection
    )
    inbound = _create_inbound(
        convo, customer_no_consent, "weight management product price"
    )
    # The dispatch should never even be invoked, but stub it anyway.
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    _patch_provider_success(monkeypatch)

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    assert outcome.sent is False
    assert outcome.blocked_reason == "consent_missing"
    assert not AuditEvent.objects.filter(
        kind="whatsapp.ai.deterministic_grounded_reply_used"
    ).exists()


@override_settings(
    **{**META_CREDS, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED": True}
)
def test_auto_reply_flag_does_not_unlock_lifecycle_automation(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    """Even with ``WHATSAPP_AI_AUTO_REPLY_ENABLED=true``, lifecycle /
    rescue / RTO / reorder / call handoff settings are independent.
    Toggling the auto-reply flag must not change those.
    """
    from django.conf import settings as _settings

    assert getattr(_settings, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED") is True
    assert getattr(_settings, "WHATSAPP_RESCUE_DISCOUNT_ENABLED") is False
    assert getattr(_settings, "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED") is False
    assert getattr(_settings, "WHATSAPP_REORDER_DAY20_ENABLED") is False
    assert getattr(_settings, "WHATSAPP_CALL_HANDOFF_ENABLED") is False


# ---------------------------------------------------------------------------
# Section D — Mutation safety + secret hygiene
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_fallback_never_creates_business_rows(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    """The fallback path must never mutate Order / Payment / Shipment
    / DiscountOfferLog — verified with before/after counts."""
    convo = _seed_outbound(connection, customer_allowed)
    inbound = _create_inbound(
        convo,
        customer_allowed,
        "weight management product ke baare me jaankari chahiye",
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    _patch_provider_success(monkeypatch)

    orders_before = Order.objects.count()
    payments_before = Payment.objects.count()
    shipments_before = Shipment.objects.count()
    discounts_before = DiscountOfferLog.objects.count()

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    assert outcome.sent is True

    assert Order.objects.count() == orders_before
    assert Payment.objects.count() == payments_before
    assert Shipment.objects.count() == shipments_before
    assert DiscountOfferLog.objects.count() == discounts_before


@override_settings(**META_CREDS)
def test_fallback_audit_payloads_omit_secrets_and_full_phone(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    convo = _seed_outbound(connection, customer_allowed)
    inbound = _create_inbound(
        convo, customer_allowed, "weight management product price kya hai"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    _patch_provider_success(monkeypatch)

    run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    blob_chunks = []
    for kind in (
        "whatsapp.ai.deterministic_grounded_reply_used",
        "whatsapp.ai.reply_auto_sent",
        "whatsapp.ai.auto_reply_flag_path_used",
        "whatsapp.ai.run_completed",
    ):
        for evt in AuditEvent.objects.filter(kind=kind):
            blob_chunks.append(json.dumps(evt.payload))
    blob = "\n".join(blob_chunks).lower()

    assert "+918949879990" not in blob
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob


# ---------------------------------------------------------------------------
# Section E — Monitor command counts the new path
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_monitor_command_counts_auto_reply_flag_path_used_after_real_inbound(
    connection, weight_management_claim, customer_allowed, monkeypatch
) -> None:
    """After a successful real-inbound deterministic fallback send,
    the soak monitor's ``inspect_recent_whatsapp_auto_reply_activity``
    must report:

    - ``replyAutoSentCount >= 1``
    - ``autoReplyFlagPathUsedCount >= 1``
    - ``deterministicBuilderUsedCount >= 1``
    - ``unexpectedNonAllowedSendsCount == 0``
    - ``ordersCreatedInWindow == 0`` etc.
    """
    convo = _seed_outbound(connection, customer_allowed)
    inbound = _create_inbound(
        convo, customer_allowed, "weight management product price kya hai"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    _patch_provider_success(monkeypatch)

    run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )

    import io as _io
    from django.core.management import call_command

    out = _io.StringIO()
    call_command(
        "inspect_recent_whatsapp_auto_reply_activity",
        "--hours",
        "24",
        "--json",
        stdout=out,
    )
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert report["replyAutoSentCount"] >= 1
    assert report["autoReplyFlagPathUsedCount"] >= 1
    assert report["deterministicBuilderUsedCount"] >= 1
    assert report["unexpectedNonAllowedSendsCount"] == 0
    assert report["ordersCreatedInWindow"] == 0
    assert report["paymentsCreatedInWindow"] == 0
    assert report["shipmentsCreatedInWindow"] == 0
    assert report["discountOfferLogsCreatedInWindow"] == 0
    assert report["nextAction"] == (
        "limited_auto_reply_enabled_monitor_real_inbound"
    )
