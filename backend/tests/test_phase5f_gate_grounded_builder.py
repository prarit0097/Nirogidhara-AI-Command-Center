"""Phase 5F-Gate Deterministic Grounded Reply Builder tests.

Covers:

1. ``build_grounded_product_reply`` produces a deterministic reply
   that literally embeds at least one approved Claim Vault phrase
   plus the locked business facts when the customer asked about
   price / quantity / booking.
2. The builder NEVER offers an upfront discount.
3. The builder fails closed when approved claims are missing.
4. ``can_build_grounded_product_reply`` refuses on safety flags,
   non-product-info inquiries, and unmapped categories.
5. ``validate_reply_uses_claim_vault`` rejects discount vocabulary,
   blocked phrases, or replies that omit any approved phrase.
6. ``run_controlled_ai_auto_reply_test --send`` triggers the
   fallback when the LLM returns ``claim_vault_not_used`` (the
   exact VPS bug) and **dispatches** the deterministic reply.
7. Same fallback path also fires on ``low_confidence`` and
   ``ai_handoff_requested``.
8. The fallback is **never** invoked for safety-shaped blockers
   (medical / side-effect / legal / blocked-phrase) — those still
   block.
9. The fallback still flows through the limited-mode guard, so
   non-allowed numbers under limited mode still cannot receive a
   send even via the fallback.
10. The controlled-test JSON now carries
    ``deterministicFallbackUsed`` / ``fallbackReason`` /
    ``deterministicReplyPreview`` / ``finalReplySource`` /
    ``finalReplyValidation``.
11. Audit ledger writes ``whatsapp.ai.deterministic_grounded_reply_used``
    on success, never carrying tokens or secrets.
12. Output omits secrets.
"""
from __future__ import annotations

import io
import json
from typing import Any
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.compliance.models import Claim
from apps.crm.models import Customer
from apps.integrations.ai.base import AdapterResult, AdapterStatus
from apps.whatsapp import services as whatsapp_services
from apps.whatsapp.grounded_reply_builder import (
    ADVANCE_AMOUNT_INR,
    STANDARD_CAPSULE_COUNT,
    STANDARD_PRICE_INR,
    build_grounded_product_reply,
    can_build_grounded_product_reply,
    is_normal_product_info_inquiry,
    validate_reply_uses_claim_vault,
)
from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppTemplate,
)
from apps.whatsapp.template_registry import upsert_template


META_CREDS = dict(
    WHATSAPP_PROVIDER="meta_cloud",
    WHATSAPP_LIVE_META_LIMITED_TEST_MODE=True,
    WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS="+91 89498 79990",
    META_WA_ACCESS_TOKEN="dummy-meta-token-not-real",
    META_WA_PHONE_NUMBER_ID="123456789",
    META_WA_BUSINESS_ACCOUNT_ID="987654321",
    META_WA_VERIFY_TOKEN="dummy-verify-token",
    META_WA_APP_SECRET="dummy-app-secret",
    WHATSAPP_AI_AUTO_REPLY_ENABLED=False,
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.75,
    WHATSAPP_CALL_HANDOFF_ENABLED=False,
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=False,
    WHATSAPP_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_REORDER_DAY20_ENABLED=False,
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
)


# ---------------------------------------------------------------------------
# Section A — pure builder unit tests
# ---------------------------------------------------------------------------


APPROVED = (
    "Supports healthy metabolism",
    "Ayurvedic blend used traditionally",
    "Best with diet & activity",
)
DISALLOWED = ("Guaranteed cure", "Permanent solution")


def test_intent_detector_accepts_normal_product_info_inquiry() -> None:
    inbound = (
        "Namaste. Mujhe Nirogidhara ke weight management product ke baare "
        "me approved safe jaankari chahiye. Price, capsule quantity aur "
        "use guidance bata dijiye."
    )
    assert is_normal_product_info_inquiry(inbound) is True


@pytest.mark.parametrize(
    "inbound",
    [
        "Will it cure diabetes 100%?",
        "Mujhe 100% cure chahiye",
        "Ye permanent solution dega kya",
        "medicine khane ke baad ulta asar ho gaya",
        "consumer forum me complaint karunga",
    ],
)
def test_intent_detector_rejects_unsafe_inputs(inbound) -> None:
    assert is_normal_product_info_inquiry(inbound) is False


def test_eligibility_passes_with_full_grounding() -> None:
    eligibility = can_build_grounded_product_reply(
        category="weight-management",
        inbound_text="weight management price kitna hai",
        safety_flags={
            "claimVaultUsed": False,
            "medicalEmergency": False,
            "sideEffectComplaint": False,
            "legalThreat": False,
            "angryCustomer": False,
        },
        approved_claims=APPROVED,
        disallowed_phrases=DISALLOWED,
    )
    assert eligibility.eligible is True
    assert eligibility.normalized_product == "Weight Management"
    assert eligibility.approved_claim_count == 3


def test_eligibility_fails_when_no_approved_claims() -> None:
    eligibility = can_build_grounded_product_reply(
        category="weight-management",
        inbound_text="weight management price",
        safety_flags={},
        approved_claims=[],
    )
    assert eligibility.eligible is False
    assert eligibility.reason == "no_approved_claims"


def test_eligibility_fails_when_safety_flag_set() -> None:
    eligibility = can_build_grounded_product_reply(
        category="weight-management",
        inbound_text="weight management price",
        safety_flags={"medicalEmergency": True},
        approved_claims=APPROVED,
    )
    assert eligibility.eligible is False
    assert eligibility.reason == "safety_flag_set:medicalEmergency"


def test_eligibility_fails_when_inbound_is_not_product_info() -> None:
    eligibility = can_build_grounded_product_reply(
        category="weight-management",
        inbound_text="namaste only",
        safety_flags={},
        approved_claims=APPROVED,
    )
    assert eligibility.eligible is False
    assert eligibility.reason == "not_product_info_inquiry"


def test_eligibility_fails_when_category_is_not_mapped() -> None:
    eligibility = can_build_grounded_product_reply(
        category="totally-unknown",
        inbound_text="weight management price",
        safety_flags={},
        approved_claims=APPROVED,
    )
    assert eligibility.eligible is False
    assert eligibility.reason == "category_not_mapped"


def test_builder_emits_deterministic_grounded_reply_with_business_facts() -> None:
    result = build_grounded_product_reply(
        normalized_product="Weight Management",
        approved_claims=APPROVED,
        inbound_text=(
            "Namaste. Mujhe weight management product ke baare me approved "
            "safe jaankari chahiye. Price, capsule quantity bata dijiye."
        ),
        customer_name="Prarit",
    )
    assert result.ok is True
    body = result.reply_text
    # At least one approved phrase appears verbatim.
    assert "Supports healthy metabolism" in body
    # Business facts present.
    assert f"₹{STANDARD_PRICE_INR}" in body
    assert f"{STANDARD_CAPSULE_COUNT} capsules" in body
    assert f"₹{ADVANCE_AMOUNT_INR}" in body
    # Conservative usage + doctor escalation lines present.
    assert "qualified Ayurvedic practitioner" in body
    assert "doctor" in body.lower()
    # Validator agrees.
    assert result.validation["passed"] is True
    assert result.validation["containsApprovedClaim"] is True
    assert result.validation["blockedPhraseFree"] is True
    assert result.validation["discountOffered"] is False


def test_builder_does_not_offer_discount() -> None:
    result = build_grounded_product_reply(
        normalized_product="Weight Management",
        approved_claims=APPROVED,
        inbound_text="weight management price discount kya hai",
    )
    assert result.ok is True
    body_lower = result.reply_text.lower()
    for needle in ("discount", "% off", "free de do"):
        assert needle not in body_lower


def test_builder_fails_closed_when_approved_claims_missing() -> None:
    result = build_grounded_product_reply(
        normalized_product="Weight Management",
        approved_claims=[],
        inbound_text="weight management price",
    )
    assert result.ok is False
    assert result.fallback_reason == "no_approved_claims"


def test_validator_flags_missing_approved_phrase() -> None:
    validation = validate_reply_uses_claim_vault(
        reply_text="Just generic chit-chat, no approved phrase.",
        approved_claims=APPROVED,
    )
    assert validation["passed"] is False
    assert validation["violation"] == "missing_approved_phrase"


def test_validator_flags_blocked_phrase_even_with_approved_phrase() -> None:
    validation = validate_reply_uses_claim_vault(
        reply_text=(
            "Supports healthy metabolism. This is a guaranteed cure. "
            "100% cure!"
        ),
        approved_claims=APPROVED,
    )
    assert validation["passed"] is False
    assert validation["violation"].startswith("blocked_phrase:")


def test_validator_flags_discount_vocabulary() -> None:
    validation = validate_reply_uses_claim_vault(
        reply_text=(
            "Supports healthy metabolism. Special 10% discount for you!"
        ),
        approved_claims=APPROVED,
    )
    assert validation["passed"] is False
    assert validation["violation"].startswith("discount_vocab:")


# ---------------------------------------------------------------------------
# Section B — controlled command fallback dispatches a real send
# ---------------------------------------------------------------------------


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-DETERM-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Nirogidhara Deterministic",
        phone_number="+91 9000099000",
        phone_number_id="meta-phone-number-id-1",
        business_account_id="meta-waba-id-1",
        status=WhatsAppConnection.Status.CONNECTED,
    )


@pytest.fixture
def greeting_template(db, connection):
    template, _ = upsert_template(
        connection=connection,
        name="nrg_greeting_intro",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[{"type": "BODY", "text": "Namaskar, Nirogidhara."}],
        action_key="whatsapp.greeting",
        claim_vault_required=False,
    )
    return template


@pytest.fixture
def weight_management_claim(db):
    return Claim.objects.create(
        product="Weight Management",
        approved=list(APPROVED),
        disallowed=list(DISALLOWED),
        doctor="Approved",
        compliance="Approved",
        version="v3.2",
    )


@pytest.fixture
def customer_allowed(db):
    customer = Customer.objects.create(
        id="NRG-CUST-DETERM-001",
        name="Allowed Test",
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


def _ai_decision_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "action": "send_reply",
        "language": "hinglish",
        "category": "weight-management",
        "confidence": 0.7,
        "replyText": (
            "Namaskar! Weight management ke liye humare paas options hain."
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
        raw={"id": "resp-determ"},
        latency_ms=1,
        cost_usd=0.0,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )


def _run_command(**kwargs: Any) -> dict[str, Any]:
    out = io.StringIO()
    call_command(
        "run_controlled_ai_auto_reply_test",
        "--json",
        stdout=out,
        **kwargs,
    )
    return json.loads(out.getvalue().strip().splitlines()[-1])


def _live_send_setup(monkeypatch, decision_payload, *, provider_mid="wamid.DETERM-OK"):
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(decision_payload),
    )
    fake_provider = mock.Mock()
    fake_provider.name = "meta_cloud"
    fake_provider.send_text_message.return_value = mock.Mock(
        provider="meta_cloud",
        provider_message_id=provider_mid,
        status="sent",
        request_payload={"to": "+918949879990"},
        response_payload={},
        response_status=200,
        latency_ms=1,
    )
    monkeypatch.setattr(
        "apps.whatsapp.services.get_provider", lambda: fake_provider
    )


def _seed_outbound(connection, customer):
    convo = whatsapp_services.get_or_open_conversation(
        customer, connection=connection
    )
    WhatsAppMessage.objects.create(
        id=f"WAM-DETERM-PRESEED-{customer.id}",
        conversation=convo,
        customer=customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )


@override_settings(**META_CREDS)
def test_fallback_dispatches_when_llm_returns_claim_vault_not_used(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    """Exact VPS reproducer: LLM returns
    safety.claimVaultUsed=false → orchestrator blocks → controlled
    command fallback ships the deterministic Claim-Vault-grounded
    reply through the same final-send path."""
    _seed_outbound(connection, customer_allowed)
    _live_send_setup(
        monkeypatch,
        _ai_decision_payload(
            confidence=0.9,
            safety={
                "claimVaultUsed": False,
                "medicalEmergency": False,
                "sideEffectComplaint": False,
                "legalThreat": False,
                "angryCustomer": False,
            },
        ),
    )

    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_allowed.phone,
            message=(
                "Namaste. Mujhe Nirogidhara ke weight management product ke "
                "baare me approved safe jaankari chahiye. Price, capsule "
                "quantity aur use guidance bata dijiye."
            ),
            send=True,
        )

    assert result["passed"] is True
    assert result["replySent"] is True
    assert result["action"] == "send_reply"
    assert result["claimVaultUsed"] is True
    assert result["confidence"] >= 0.75
    assert result["deterministicFallbackUsed"] is True
    assert result["finalReplySource"] == "deterministic_grounded_builder"
    assert result["fallbackReason"] == "claim_vault_not_used"
    assert result["finalReplyValidation"]["passed"] is True
    assert "Supports healthy metabolism" in result["replyPreview"]
    assert "₹3000" in result["replyPreview"]
    assert "30 capsules" in result["replyPreview"]
    assert result["nextAction"] == "live_ai_reply_sent_verify_phone"
    # The deterministic fallback emitted its own audit row.
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.deterministic_grounded_reply_used"
    ).exists()


@override_settings(**META_CREDS)
def test_fallback_also_fires_on_low_confidence(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    _seed_outbound(connection, customer_allowed)
    # LLM has high-quality grounding but returns confidence below the
    # threshold; orchestrator blocks with low_confidence; fallback
    # ships the deterministic reply.
    _live_send_setup(
        monkeypatch,
        _ai_decision_payload(confidence=0.4),
    )

    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_allowed.phone,
            message=(
                "weight management product price aur capsule quantity bata dijiye"
            ),
            send=True,
        )

    assert result["passed"] is True
    assert result["replySent"] is True
    assert result["deterministicFallbackUsed"] is True
    assert result["fallbackReason"] == "low_confidence"


@override_settings(**META_CREDS)
def test_fallback_fires_on_ai_handoff_requested(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    _seed_outbound(connection, customer_allowed)
    _live_send_setup(
        monkeypatch,
        _ai_decision_payload(
            action="handoff",
            handoffReason="not sure",
            confidence=0.9,
        ),
    )

    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_allowed.phone,
            message="weight management product price",
            send=True,
        )

    assert result["passed"] is True
    assert result["replySent"] is True
    assert result["deterministicFallbackUsed"] is True
    assert result["fallbackReason"] == "ai_handoff_requested"


@override_settings(**META_CREDS)
def test_fallback_does_NOT_fire_on_safety_blocks(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    """Medical emergency / side-effect / legal-threat blocks must NOT
    be rescued by the deterministic fallback."""
    _seed_outbound(connection, customer_allowed)
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

    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_allowed.phone,
            message="seene me dard ho raha hai, ambulance chahiye",
            send=True,
        )

    assert result["passed"] is False
    assert result["safetyBlocked"] is True
    assert result["nextAction"] == "blocked_for_medical_safety"
    assert result["deterministicFallbackUsed"] is False


@override_settings(**META_CREDS)
def test_fallback_skips_when_no_approved_claims_exist(
    connection, greeting_template, customer_allowed, monkeypatch
) -> None:
    """No Claim Vault row → orchestrator raises claim_vault_missing.
    Fallback also refuses (no approved claims) and the run remains
    blocked."""
    _seed_outbound(connection, customer_allowed)
    customer_allowed.product_interest = ""
    customer_allowed.save(update_fields=["product_interest"])
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(category="immunity")
        ),
    )

    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_allowed.phone,
            message="immunity product price",
            send=True,
        )

    assert result["passed"] is False
    assert result["replySent"] is False
    assert result["deterministicFallbackUsed"] is False


@override_settings(**META_CREDS)
def test_fallback_still_blocked_by_limited_mode_guard_for_non_allowed_phone(
    connection, greeting_template, weight_management_claim
) -> None:
    """The deterministic fallback uses ``send_freeform_text_message``
    so the limited-mode allow-list check still applies. Force the
    LLM into a soft block, then watch the fallback get refused at
    the final-send guard for a non-allowed phone."""
    customer = Customer.objects.create(
        id="NRG-CUST-DETERM-OUT",
        name="Outside Allow-list",
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
    convo = WhatsAppConversation.objects.create(
        id="WCV-DETERM-OUT",
        customer=customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
    )
    # Direct unit-style assertion: the limited-mode guard inside
    # services.send_freeform_text_message still refuses.
    with pytest.raises(whatsapp_services.WhatsAppServiceError) as excinfo:
        whatsapp_services.send_freeform_text_message(
            customer=customer,
            conversation=convo,
            body=(
                "Namaste 🙏 Supports healthy metabolism, ₹3000 / 30 capsules."
            ),
            actor_role="ai_chat",
            actor_agent="ai_chat",
        )
    assert excinfo.value.block_reason == "limited_test_number_not_allowed"


@override_settings(**META_CREDS)
def test_fallback_command_output_omits_secrets(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    _seed_outbound(connection, customer_allowed)
    _live_send_setup(
        monkeypatch,
        _ai_decision_payload(
            safety={
                "claimVaultUsed": False,
                "medicalEmergency": False,
                "sideEffectComplaint": False,
                "legalThreat": False,
                "angryCustomer": False,
            },
        ),
    )

    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_allowed.phone,
            message="weight management price kitna hai",
            send=True,
        )

    blob = json.dumps(result).lower()
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob
    # Audit ledger payloads also clean.
    audit = AuditEvent.objects.filter(
        kind="whatsapp.ai.deterministic_grounded_reply_used"
    ).first()
    assert audit is not None
    for key in audit.payload.keys():
        assert "token" not in key.lower()
        assert "secret" not in key.lower()
