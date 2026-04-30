"""Phase 5F-Gate Controlled Reply Confidence Fix tests.

Covers:

1. Prompt now carries the BUSINESS FACTS section, the ACTION
   SELECTION DECISION TREE, and the ``settings`` block has
   ``standardCapsuleCount`` + ``businessFactsAllowed`` + the
   ``discountDiscipline`` description.
2. End-to-end controlled --send with a normal grounded
   weight-management inquiry produces ``action=send_reply`` with
   ``claimVaultUsed=true`` (mocked LLM honours the action discipline).
3. The reply preview literally includes one of the approved Claim
   Vault phrases.
4. The reply may freely state the ₹3000 / 30 capsules / ₹499 advance
   business facts when the customer asks.
5. The harness does NOT offer a discount upfront.
6. A "guarantee" / "100% cure" inbound is blocked even if Claim
   Vault grounding exists.
7. A side-effect-complaint inbound is blocked / handed off.
8. Unknown category still fails closed (zero claims, action=handoff
   path).
9. Missing Claim Vault still blocks via the existing
   ``claim_vault_not_used`` path.
10. Final-send limited-mode guard still refuses non-allowed numbers.
11. Controlled-test JSON now carries ``claimRowCount`` +
    ``approvedClaimCount`` + ``disallowedPhraseCount`` distinctly,
    plus ``confidenceThreshold``, ``actionReason``,
    ``sendEligibilitySummary``, ``businessFactsInjected``.
12. Controlled-test output omits secrets.
13. ``whatsapp.ai.controlled_test.blocked`` audit payload carries the
    cleaner counts.
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
from apps.whatsapp.ai_orchestration import _build_prompt, _claim_grounding_counts
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-CONF-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Nirogidhara Confidence Fix",
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
        approved=[
            "Supports healthy metabolism",
            "Ayurvedic blend used traditionally",
            "Best with diet & activity",
        ],
        disallowed=[
            "Guaranteed cure",
            "Permanent solution",
        ],
        doctor="Approved",
        compliance="Approved",
        version="v3.2",
    )


@pytest.fixture
def customer_allowed(db):
    customer = Customer.objects.create(
        id="NRG-CUST-CONF-001",
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
        "confidence": 0.9,
        "replyText": (
            "Namaskar! Weight management ke liye humare paas Supports "
            "healthy metabolism wala Ayurvedic blend hai. Standard price "
            "₹3000 / 30 capsules. Order book karne par ₹499 advance lagega."
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
        raw={"id": "resp-conf-fix"},
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


def _live_send_setup(monkeypatch, decision_payload):
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(decision_payload),
    )
    fake_provider = mock.Mock()
    fake_provider.name = "meta_cloud"
    fake_provider.send_text_message.return_value = mock.Mock(
        provider="meta_cloud",
        provider_message_id="wamid.CONF-LIVE-OK",
        status="sent",
        request_payload={"to": "+918949879990"},
        response_payload={},
        response_status=200,
        latency_ms=1,
    )
    monkeypatch.setattr(
        "apps.whatsapp.services.get_provider", lambda: fake_provider
    )


# ---------------------------------------------------------------------------
# Section A — prompt content
# ---------------------------------------------------------------------------


def test_prompt_carries_business_facts_section(
    weight_management_claim, customer_allowed, connection
) -> None:
    convo = WhatsAppConversation.objects.create(
        id="WCV-CONF-PROMPT-A",
        customer=customer_allowed,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
    )
    inbound = WhatsAppMessage.objects.create(
        id="WAM-CONF-PROMPT-IN-A",
        conversation=convo,
        customer=customer_allowed,
        direction=WhatsAppMessage.Direction.INBOUND,
        status=WhatsAppMessage.Status.DELIVERED,
        type=WhatsAppMessage.Type.TEXT,
        body="weight management price?",
        queued_at=timezone.now(),
    )
    context = {
        "customer": {
            "id": customer_allowed.id,
            "name": customer_allowed.name,
            "phone": customer_allowed.phone,
            "city": customer_allowed.city,
            "state": customer_allowed.state,
            "language": "hinglish",
            "product_interest": "Weight Management",
            "consent_whatsapp": True,
        },
        "conversation": {
            "id": convo.id,
            "status": "open",
            "stage": "discovery",
            "discountAskCount": 0,
            "totalDiscountPct": 0,
            "language": "hinglish",
            "addressCollection": {},
        },
        "history": [],
        "inbound": {"id": inbound.id, "body": inbound.body},
        "lastOrder": None,
        "claims": [
            {
                "product": "Weight Management",
                "approved": list(weight_management_claim.approved),
                "disallowed": list(weight_management_claim.disallowed),
            }
        ],
        "settings": {
            "standardPriceInr": 3000,
            "standardCapsuleCount": 30,
            "advanceAmountInr": 499,
            "totalDiscountCapPct": 50,
            "currency": "INR",
            "discountDiscipline": "no upfront discount",
            "businessFactsAllowed": ["Standard price ₹3000 / 30 capsules"],
        },
    }
    messages = _build_prompt(convo, inbound, context)
    system_block = messages[0]["content"]
    user_block = messages[1]["content"]

    # Business facts section is present in the system policy.
    assert "BUSINESS FACTS YOU MAY STATE FREELY" in system_block
    assert "Standard price: ₹3000 for one bottle of 30 capsules" in system_block
    assert "Fixed advance amount on order booking: ₹499" in system_block

    # ACTION SELECTION DECISION TREE is present and explains the
    # grounded-inquiry → send_reply mapping.
    assert "ACTION SELECTION DECISION TREE" in system_block
    assert "action='send_reply'" in system_block
    assert "confidence ≥ 0.85" in system_block

    # Settings block in user message carries the new fields.
    assert '"standardCapsuleCount": 30' in user_block
    assert '"businessFactsAllowed"' in user_block
    assert '"discountDiscipline"' in user_block

    # Claim Vault grounding still flows through (avoid + approved).
    assert "Supports healthy metabolism" in user_block
    assert "Guaranteed cure" in user_block

    # Final-check sentence appears so the LLM knows defaulting to
    # handoff on a grounded inquiry is a defect.
    assert "FINAL CHECK" in user_block
    assert "Defaulting to action='handoff' on a grounded inquiry is a defect" in user_block


# ---------------------------------------------------------------------------
# Section B — happy path: grounded inquiry produces send_reply
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_grounded_weight_management_send_succeeds_with_business_facts(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    convo = whatsapp_services.get_or_open_conversation(
        customer_allowed, connection=connection
    )
    WhatsAppMessage.objects.create(
        id="WAM-CONF-PRESEED-OK",
        conversation=convo,
        customer=customer_allowed,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    _live_send_setup(monkeypatch, _ai_decision_payload())

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
                "approved safe jaankari chahiye. Price aur capsule "
                "quantity bata dijiye."
            ),
            send=True,
        )

    assert result["passed"] is True
    assert result["replySent"] is True
    assert result["action"] == "send_reply"
    assert result["claimVaultUsed"] is True
    assert result["confidence"] >= 0.75
    # Reply uses an approved Claim Vault phrase verbatim.
    assert "Supports healthy metabolism" in result["replyPreview"]
    # Business facts present.
    assert "₹3000" in result["replyPreview"]
    assert "30 capsules" in result["replyPreview"]
    # Confidence threshold + diagnostics cleanup landed.
    assert result["confidenceThreshold"] == pytest.approx(0.75)
    assert result["claimRowCount"] == 1
    assert result["approvedClaimCount"] == 3
    assert result["disallowedPhraseCount"] == 2
    assert result["claimCount"] == 3  # backward-compat alias
    assert result["groundingStatus"]["claimRowCount"] == 1
    assert result["groundingStatus"]["approvedClaimCount"] == 3
    assert result["groundingStatus"]["promptGroundingInjected"] is True
    assert result["groundingStatus"]["businessFactsInjected"] is True
    assert "Live AI reply sent" in result["sendEligibilitySummary"]


@override_settings(**META_CREDS)
def test_send_does_not_offer_discount_upfront(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    convo = whatsapp_services.get_or_open_conversation(
        customer_allowed, connection=connection
    )
    WhatsAppMessage.objects.create(
        id="WAM-CONF-PRESEED-DISC",
        conversation=convo,
        customer=customer_allowed,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    _live_send_setup(monkeypatch, _ai_decision_payload())

    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_allowed.phone,
            message="weight management batao",
            send=True,
        )

    preview = (result.get("replyPreview") or "").lower()
    # Never mentions a percent discount or an offer phrase.
    forbidden = ["discount", "%", "offer", "off"]
    for needle in forbidden:
        assert needle not in preview, (
            f"reply preview unexpectedly contained {needle!r}: {preview}"
        )


# ---------------------------------------------------------------------------
# Section C — safety contract still in force
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_cure_request_is_blocked_even_with_grounding(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    """An LLM that returns a 'guaranteed cure' phrase must still be
    blocked by the blocked-phrase filter, even with grounding."""
    convo = whatsapp_services.get_or_open_conversation(
        customer_allowed, connection=connection
    )
    WhatsAppMessage.objects.create(
        id="WAM-CONF-PRESEED-CURE",
        conversation=convo,
        customer=customer_allowed,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(
                replyText=(
                    "Sure! Our product is a guaranteed cure and 100% cure "
                    "for weight management."
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
            message="will it cure me?",
            send=True,
        )
    assert result["passed"] is False
    assert result["replySent"] is False
    assert result["replyBlocked"] is True
    assert result["blockedReason"].startswith("blocked_phrase:")


@override_settings(**META_CREDS)
def test_side_effect_complaint_routes_to_safety_handoff(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    convo = whatsapp_services.get_or_open_conversation(
        customer_allowed, connection=connection
    )
    WhatsAppMessage.objects.create(
        id="WAM-CONF-PRESEED-SE",
        conversation=convo,
        customer=customer_allowed,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
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


@override_settings(**META_CREDS)
def test_unknown_category_fails_closed(
    connection, greeting_template, customer_allowed, monkeypatch
) -> None:
    """No Claim Vault row for the inferred category → orchestrator
    raises _ClaimVaultMissingError → blocked."""
    convo = whatsapp_services.get_or_open_conversation(
        customer_allowed, connection=connection
    )
    WhatsAppMessage.objects.create(
        id="WAM-CONF-PRESEED-UNK",
        conversation=convo,
        customer=customer_allowed,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    # Customer has product_interest=Weight Management but the LLM
    # detects an unsupported category. Drop the customer's interest so
    # _claims_for_category truly fails closed.
    customer_allowed.product_interest = ""
    customer_allowed.save(update_fields=["product_interest"])
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(
                category="immunity",  # supported, but no Claim row
                replyText="Some text",
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
            message="immunity ke baare me batao",
            send=True,
        )
    assert result["passed"] is False
    assert result["replySent"] is False


# ---------------------------------------------------------------------------
# Section D — diagnostics + audit + safety wiring
# ---------------------------------------------------------------------------


def test_claim_grounding_counts_helper_separates_rows_and_phrases(
    weight_management_claim,
) -> None:
    counts = _claim_grounding_counts("weight-management")
    assert counts == {
        "claim_row_count": 1,
        "approved_claim_count": 3,
        "disallowed_phrase_count": 2,
    }


def test_claim_grounding_counts_helper_returns_zeros_for_unknown() -> None:
    counts = _claim_grounding_counts("unknown")
    assert counts == {
        "claim_row_count": 0,
        "approved_claim_count": 0,
        "disallowed_phrase_count": 0,
    }


@override_settings(**META_CREDS)
def test_controlled_blocked_audit_payload_carries_split_counts(
    connection,
    greeting_template,
    weight_management_claim,
    customer_allowed,
    monkeypatch,
) -> None:
    convo = whatsapp_services.get_or_open_conversation(
        customer_allowed, connection=connection
    )
    WhatsAppMessage.objects.create(
        id="WAM-CONF-PRESEED-AUDIT",
        conversation=convo,
        customer=customer_allowed,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    # Force a block via low confidence so the controlled_test.blocked
    # audit fires.
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(
            _ai_decision_payload(confidence=0.1)
        ),
    )

    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        _run_command(
            phone=customer_allowed.phone,
            message="weight management batao",
            send=True,
        )

    audit = (
        AuditEvent.objects.filter(kind="whatsapp.ai.controlled_test.blocked")
        .order_by("-occurred_at")
        .first()
    )
    assert audit is not None
    payload = audit.payload
    assert payload.get("claim_row_count") == 1
    assert payload.get("approved_claim_count") == 3
    assert payload.get("disallowed_phrase_count") == 2
    assert payload.get("claim_count") == 3  # backward-compat alias
    assert payload.get("confidence_threshold") == pytest.approx(0.75)
    # No tokens / secrets in payload.
    for key in payload.keys():
        assert "token" not in key.lower()
        assert "secret" not in key.lower()


@override_settings(**META_CREDS)
def test_controlled_command_output_omits_secrets_after_confidence_diagnostics(
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
            message="hello",
        )
    blob = json.dumps(result).lower()
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob


@override_settings(**META_CREDS)
def test_dry_run_send_eligibility_summary_explains_ready_state(
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
            message="weight management batao",
        )
    assert result["passed"] is True
    assert result["dryRun"] is True
    assert "Dry-run gates passed" in result["sendEligibilitySummary"]


# ---------------------------------------------------------------------------
# Section E — defence-in-depth contracts unchanged
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_final_send_limited_mode_guard_still_blocks_non_allowed_number_after_confidence_fix(
    connection,
) -> None:
    customer = Customer.objects.create(
        id="NRG-CUST-CONF-OUT",
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
        id="WCV-CONF-OUT",
        customer=customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
    )
    with pytest.raises(whatsapp_services.WhatsAppServiceError) as excinfo:
        whatsapp_services.send_freeform_text_message(
            customer=customer,
            conversation=convo,
            body="grounded reply",
            actor_role="ai_chat",
            actor_agent="ai_chat",
        )
    assert excinfo.value.block_reason == "limited_test_number_not_allowed"
