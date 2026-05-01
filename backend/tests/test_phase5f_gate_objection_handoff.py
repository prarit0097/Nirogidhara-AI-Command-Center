"""Phase 5F-Gate Objection & Handoff Reason Refinement tests.

Covers:

- ``classify_inbound_intent`` returns the correct primary for unsafe
  / human-request / discount-objection / price-objection /
  product-info / unknown inputs.
- ``build_objection_aware_reply`` produces a deterministic reply
  that literally embeds an approved phrase, the locked business
  facts, AND an objection acknowledgement, but NEVER promises a
  discount.
- ``validate_objection_reply`` rejects "discount confirmed",
  "guaranteed discount", "50% discount" framing.
- Controlled-test command live ``--send`` with a discount-objection
  inbound dispatches the objection-aware reply (no upfront
  discount, no business-state mutation).
- Controlled-test command live ``--send`` with a human-request
  inbound returns `human_advisor_requested` handoff (NOT
  `claim_vault_not_used`) and does not trigger Vapi.
- Side-effect / legal / cure-guarantee / unknown-category paths
  remain blocked exactly as before.
- Final-send limited-mode guard still blocks non-allowed numbers.
- No DiscountOfferLog / Order / Payment / Shipment is created on
  any controlled-test path.
- No tokens / verify token / app secret in command output.
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
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment
from apps.whatsapp import services as whatsapp_services
from apps.whatsapp.grounded_reply_builder import (
    build_objection_aware_reply,
    can_build_objection_reply,
    classify_inbound_intent,
    detect_discount_objection,
    detect_human_request,
    detect_purchase_intent,
    detect_unsafe_signal,
    validate_objection_reply,
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


APPROVED = (
    "Supports healthy metabolism",
    "Ayurvedic blend used traditionally",
    "Best with diet & activity",
)
DISALLOWED = ("Guaranteed cure", "Permanent solution")


# ---------------------------------------------------------------------------
# Section A — pure detector unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "inbound, expected_type",
    [
        ("discount milega kya", "discount"),
        ("kya discount milega", "discount"),
        ("kuch kam ho sakta hai", "discount"),
        ("offer chal raha hai kya", "discount"),
        ("best price bata do", "discount"),
        ("thoda mehenga lag raha hai", "price"),
        ("price zyada hai", "price"),
        ("budget thoda kam hai", "price"),
        ("ye costly hai", "price"),
    ],
)
def test_detect_discount_objection_classifies_type(inbound, expected_type) -> None:
    detected, kind = detect_discount_objection(inbound)
    assert detected is True
    assert kind == expected_type


@pytest.mark.parametrize(
    "inbound",
    [
        "weight management product price kya hai",
        "30 capsules price",
        "namaste",
        "advance kitna hai",
    ],
)
def test_detect_discount_objection_negatives(inbound) -> None:
    detected, _ = detect_discount_objection(inbound)
    assert detected is False


@pytest.mark.parametrize(
    "inbound",
    [
        "mujhe call karwa do",
        "AI se baat nahi karni, advisor se baat",
        "callback please",
        "human se baat karna hai",
        "talk to a human",
        "agent se baat karwa do",
        "doctor se baat karwa do",
    ],
)
def test_detect_human_request_positives(inbound) -> None:
    assert detect_human_request(inbound) is True


@pytest.mark.parametrize(
    "inbound",
    [
        "weight management product price",
        "discount milega kya",
        "namaste",
    ],
)
def test_detect_human_request_negatives(inbound) -> None:
    assert detect_human_request(inbound) is False


@pytest.mark.parametrize(
    "inbound",
    [
        "abhi order karna hai",
        "ready to buy",
        "let me order",
        "abhi book karna hai",
        "confirm order karwa do",
    ],
)
def test_detect_purchase_intent(inbound) -> None:
    assert detect_purchase_intent(inbound) is True


@pytest.mark.parametrize(
    "inbound, primary",
    [
        ("100% cure guarantee chahiye", "unsafe"),
        ("permanent solution chahiye", "unsafe"),
        ("medicine khane ke baad ulta asar ho gaya", "unsafe"),
        ("consumer forum me complaint karunga", "unsafe"),
        ("mujhe call karwa do", "human_request"),
        ("AI se baat nahi", "human_request"),
        ("discount milega kya", "discount_objection"),
        ("thoda mehenga lag raha hai", "discount_objection"),
        ("weight management product price kya hai", "product_info"),
        ("namaste only", "unknown"),
    ],
)
def test_classify_inbound_intent_priority_order(inbound, primary) -> None:
    result = classify_inbound_intent(inbound)
    assert result.primary == primary


def test_classify_unsafe_signal_wins_over_human_request() -> None:
    """Cure / 100% / guarantee inside a "call me" message must
    classify as unsafe — safety wins."""
    result = classify_inbound_intent(
        "callback please, mujhe 100% cure chahiye"
    )
    assert result.primary == "unsafe"
    assert result.unsafe is True


def test_detect_unsafe_signal_helpers() -> None:
    assert detect_unsafe_signal("100% cure guarantee") is True
    assert detect_unsafe_signal("medicine khane ke baad ulta asar") is True
    assert detect_unsafe_signal("weight management price") is False


# ---------------------------------------------------------------------------
# Section B — objection-aware builder
# ---------------------------------------------------------------------------


def test_build_objection_aware_reply_includes_approved_phrase_and_facts() -> None:
    result = build_objection_aware_reply(
        normalized_product="Weight Management",
        approved_claims=APPROVED,
        inbound_text="discount milega kya",
        purchase_intent=False,
    )
    assert result.ok is True
    body = result.reply_text
    assert "Supports healthy metabolism" in body
    assert "₹3000" in body
    assert "30 capsules" in body
    assert "₹499" in body
    # Acknowledgement of the price concern present.
    assert "Price concern samajh sakta/sakti hoon" in body
    assert result.validation["passed"] is True


def test_build_objection_aware_reply_does_not_promise_discount() -> None:
    result = build_objection_aware_reply(
        normalized_product="Weight Management",
        approved_claims=APPROVED,
        inbound_text="discount milega kya",
    )
    body_lower = (result.reply_text or "").lower()
    forbidden = (
        "discount confirmed",
        "guaranteed discount",
        "50% discount",
        "50 percent discount",
        "100% discount",
        "% off",
        "free de do",
    )
    for needle in forbidden:
        assert needle not in body_lower


def test_validate_objection_reply_rejects_promised_discount() -> None:
    validation = validate_objection_reply(
        reply_text=(
            "Supports healthy metabolism. ₹3000 / 30 capsules. "
            "Aapko 50% discount confirmed milega."
        ),
        approved_claims=APPROVED,
    )
    assert validation["passed"] is False
    assert validation["objectionPromisedDiscount"] is True


def test_can_build_objection_reply_refuses_unsafe_inbound() -> None:
    eligibility = can_build_objection_reply(
        category="weight-management",
        inbound_text="discount chahiye aur 100% cure bhi",
        safety_flags={},
        approved_claims=APPROVED,
    )
    assert eligibility.eligible is False
    assert eligibility.reason == "unsafe_signal_in_inbound"


def test_can_build_objection_reply_refuses_non_objection_inbound() -> None:
    eligibility = can_build_objection_reply(
        category="weight-management",
        inbound_text="weight management product price",
        safety_flags={},
        approved_claims=APPROVED,
    )
    assert eligibility.eligible is False
    assert eligibility.reason == "not_discount_objection"


# ---------------------------------------------------------------------------
# Section C — controlled-test command end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-OBJ-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Nirogidhara Objection",
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
        id="NRG-CUST-OBJ-001",
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
        raw={"id": "resp-obj"},
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


def _live_send_setup(monkeypatch, decision_payload, *, provider_mid="wamid.OBJ-OK"):
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
        id=f"WAM-OBJ-PRESEED-{customer.id}",
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
def test_discount_objection_dispatches_objection_aware_reply(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    _seed_outbound(connection, customer_allowed)
    # LLM blocks (claimVaultUsed=false) — the controlled-test command
    # routes through the objection-aware fallback.
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

    discount_offers_before = DiscountOfferLog.objects.count()
    orders_before = Order.objects.count()
    payments_before = Payment.objects.count()
    shipments_before = Shipment.objects.count()

    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_allowed.phone,
            message=(
                "weight management product accha hai lekin thoda mehenga "
                "lag raha hai. Kuch kam ho sakta hai?"
            ),
            send=True,
        )

    assert result["passed"] is True
    assert result["replySent"] is True
    assert result["finalReplySource"] == "deterministic_objection_reply"
    assert result["detectedIntent"] == "discount_objection"
    assert result["objectionDetected"] is True
    assert result["objectionType"] in {"discount", "price"}
    assert result["fallbackReason"].startswith("objection")
    # Reply embeds approved phrase + business facts.
    preview = result["replyPreview"]
    assert "Supports healthy metabolism" in preview or "Ayurvedic blend" in preview
    assert "₹3000" in preview
    # Reply policy explicitly states no business-state mutation.
    assert result["replyPolicy"]["upfrontDiscountOffered"] is False
    assert result["replyPolicy"]["discountMutationCreated"] is False
    assert result["replyPolicy"]["businessMutationCreated"] is False
    # No Order / Payment / Shipment / DiscountOfferLog created.
    assert DiscountOfferLog.objects.count() == discount_offers_before
    assert Order.objects.count() == orders_before
    assert Payment.objects.count() == payments_before
    assert Shipment.objects.count() == shipments_before
    # Audit trail: objection_detected + objection_reply_used both fired.
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.objection_detected"
    ).exists()
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.objection_reply_used"
    ).exists()


@override_settings(**META_CREDS)
def test_discount_objection_with_unsafe_claim_demand_is_blocked(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    """Cure demand inside a discount sentence must lose to safety."""
    _seed_outbound(connection, customer_allowed)
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(
                action="handoff",
                handoffReason="blocked phrase",
                replyText=(
                    "Sure! Our product is a guaranteed cure. 100% cure."
                ),
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
            message="discount chahiye aur 100% cure bhi",
            send=True,
        )

    assert result["passed"] is False
    assert result["replySent"] is False
    # The intent classifier surfaces unsafe ahead of objection.
    assert result["detectedIntent"] == "unsafe"


@override_settings(**META_CREDS)
def test_human_request_returns_typed_handoff_not_claim_vault_not_used(
    connection, greeting_template, customer_allowed, monkeypatch
) -> None:
    """Customer asks to talk to a human → controlled command returns
    `human_advisor_requested` handoff. The orchestrator is NEVER
    invoked (intent short-circuit). No Vapi call (handoff flag off).
    """
    # Trigger Vapi mock to make sure it does NOT fire.
    fake_trigger_call = mock.Mock()
    monkeypatch.setattr(
        "apps.whatsapp.call_handoff.trigger_vapi_call_from_whatsapp",
        fake_trigger_call,
    )
    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_allowed.phone,
            message="AI se baat nahi karni, mujhe call karwa do",
            send=True,
        )

    assert result["passed"] is False
    assert result["replySent"] is False
    assert result["replyBlocked"] is True
    assert result["detectedIntent"] == "human_request"
    assert result["humanRequestDetected"] is True
    assert result["blockedReason"] == "human_advisor_requested"
    assert result["handoffReason"] == "human_advisor_requested"
    assert result["nextAction"] == "human_handoff_requested"
    assert result["finalReplySource"] == "blocked_handoff"
    assert result["safetyBlocked"] is False
    # No Vapi trigger fired.
    assert fake_trigger_call.called is False
    # Audit trail.
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.human_request_detected"
    ).exists()
    handoff = (
        AuditEvent.objects.filter(kind="whatsapp.ai.handoff_required")
        .order_by("-occurred_at")
        .first()
    )
    assert handoff is not None
    assert handoff.payload["reason"] == "human_advisor_requested"
    # Specifically NOT claim_vault_not_used.
    assert handoff.payload.get("reason") != "claim_vault_not_used"


@override_settings(**META_CREDS)
def test_normal_product_info_unchanged_by_classifier(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    """Normal product-info inquiry still routes to the existing
    grounded reply path (not the objection path)."""
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
            }
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
                "Namaste mujhe weight management product ke baare me "
                "approved safe jaankari chahiye"
            ),
            send=True,
        )

    assert result["passed"] is True
    assert result["replySent"] is True
    assert result["detectedIntent"] == "product_info"
    assert result["objectionDetected"] is False
    assert result["humanRequestDetected"] is False
    assert result["finalReplySource"] == "deterministic_grounded_builder"


@override_settings(**META_CREDS)
def test_side_effect_complaint_still_blocks_with_safety_reason(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    _seed_outbound(connection, customer_allowed)
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(
                action="handoff",
                handoffReason="side effect complaint",
                safety={
                    "claimVaultUsed": True,
                    "medicalEmergency": False,
                    "sideEffectComplaint": True,
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
            message=(
                "medicine khane ke baad ulta asar ho gaya, vomiting bhi hui"
            ),
            send=True,
        )

    assert result["passed"] is False
    assert result["safetyBlocked"] is True
    assert result["nextAction"] == "blocked_for_medical_safety"
    # Intent classifier surfaces unsafe (side-effect vocabulary is in
    # the disqualifier list).
    assert result["detectedIntent"] == "unsafe"


@override_settings(**META_CREDS)
def test_command_output_omits_secrets_after_objection_diagnostics(
    connection, greeting_template, weight_management_claim, customer_allowed
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_allowed.phone,
            message="discount milega kya",
        )
    blob = json.dumps(result).lower()
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob


# ---------------------------------------------------------------------------
# Section D — defence-in-depth contracts intact
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_final_send_limited_mode_guard_still_blocks_objection_reply_to_non_allowed(
    connection,
) -> None:
    """The objection-aware fallback uses ``send_freeform_text_message``
    so the limited-mode allow-list check still applies."""
    customer = Customer.objects.create(
        id="NRG-CUST-OBJ-OUT",
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
        id="WCV-OBJ-OUT",
        customer=customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
    )
    with pytest.raises(whatsapp_services.WhatsAppServiceError) as excinfo:
        whatsapp_services.send_freeform_text_message(
            customer=customer,
            conversation=convo,
            body=(
                "Namaste 🙏 Supports healthy metabolism. ₹3000 / 30 capsules."
            ),
            actor_role="ai_chat",
            actor_agent="ai_chat",
        )
    assert excinfo.value.block_reason == "limited_test_number_not_allowed"
