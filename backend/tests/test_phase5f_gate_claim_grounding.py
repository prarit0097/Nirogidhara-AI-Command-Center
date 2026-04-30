"""Phase 5F-Gate Claim Vault Grounding Fix tests.

Covers:

1. ``category_to_claim_product`` mapping is deterministic, covers the
   eight live categories + common aliases, and returns ``""`` for
   unknown / empty input (fail-closed contract).
2. ``_claims_for_category`` resolves the slug ``weight-management`` to
   the live ``Claim(product="Weight Management")`` row via the new
   mapping — no longer produces an ``icontains`` mismatch.
3. The empty-string ``product_interest`` fallback no longer silently
   returns every Claim in the table (previous bug).
4. Unknown category fails closed (zero rows returned).
5. Disallowed phrases stay attached to the prompt context so the LLM
   continues to see them in the avoid list.
6. Controlled-test command output carries the new diagnostics block
   (``detectedCategory`` / ``normalizedClaimProduct`` / ``claimCount`` /
   ``confidence`` / ``replyPreview`` / ``safetyFlags`` /
   ``groundingStatus``).
7. ``whatsapp.ai.reply_blocked`` audit payload now carries the
   grounding context (``category`` / ``normalized_claim_product`` /
   ``claim_count`` / ``confidence``).
8. No tokens / verify token / app secret leak into the JSON output.
9. The final-send limited-mode guard still refuses non-allowed numbers
   under limited mode (defence-in-depth contract intact).
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
from apps.whatsapp.ai_orchestration import _claims_for_category
from apps.whatsapp.claim_mapping import (
    ALIASES,
    CATEGORY_SLUG_TO_PRODUCT,
    category_to_claim_product,
    known_category_slugs,
    known_claim_products,
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
    WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD=0.0,
    WHATSAPP_CALL_HANDOFF_ENABLED=False,
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=False,
    WHATSAPP_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_REORDER_DAY20_ENABLED=False,
    AI_PROVIDER="openai",
    AI_PROVIDER_FALLBACKS=["openai"],
)


# ---------------------------------------------------------------------------
# Section A — pure mapping helper tests (no DB required)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug, expected",
    [
        ("weight-management", "Weight Management"),
        ("blood-purification", "Blood Purification"),
        ("men-wellness", "Men Wellness"),
        ("women-wellness", "Women Wellness"),
        ("immunity", "Immunity"),
        ("lungs-detox", "Lungs Detox"),
        ("body-detox", "Body Detox"),
        ("joint-care", "Joint Care"),
    ],
)
def test_canonical_slugs_map_to_claim_product_label(slug, expected) -> None:
    assert category_to_claim_product(slug) == expected


@pytest.mark.parametrize(
    "alias, expected",
    [
        ("weight-loss", "Weight Management"),
        ("weight loss", "Weight Management"),
        ("WEIGHT MANAGEMENT", "Weight Management"),
        ("blood purify", "Blood Purification"),
        ("blood purification", "Blood Purification"),
        ("men wellness", "Men Wellness"),
        ("male wellness", "Men Wellness"),
        ("women wellness", "Women Wellness"),
        ("female wellness", "Women Wellness"),
        ("lungs detox", "Lungs Detox"),
        ("body detox", "Body Detox"),
        ("joint pain", "Joint Care"),
        ("joint care", "Joint Care"),
    ],
)
def test_aliases_map_to_claim_product_label(alias, expected) -> None:
    assert category_to_claim_product(alias) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        "unknown",
        "diabetes-cure",
        "magic-pill",
        "asdf",
    ],
)
def test_unknown_category_returns_empty_string_not_a_guess(value) -> None:
    assert category_to_claim_product(value) == ""


def test_known_helpers_match_table() -> None:
    assert set(known_category_slugs()) == set(CATEGORY_SLUG_TO_PRODUCT.keys())
    assert set(known_claim_products()) == set(CATEGORY_SLUG_TO_PRODUCT.values())


def test_aliases_table_contains_no_unknown_products() -> None:
    """Every alias must point at a known canonical product label —
    otherwise we risk routing the LLM to a non-existent product."""
    canonical = set(CATEGORY_SLUG_TO_PRODUCT.values())
    for alias_value, product in ALIASES.items():
        assert product in canonical, (
            f"alias {alias_value!r} points at unknown product {product!r}"
        )


# ---------------------------------------------------------------------------
# Section B — _claims_for_category resolves slug → Claim.product
# ---------------------------------------------------------------------------


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
def joint_care_claim(db):
    return Claim.objects.create(
        product="Joint Care",
        approved=["Supports joint comfort"],
        disallowed=["Guaranteed cure"],
        doctor="Approved",
        compliance="Approved",
        version="v1.0",
    )


@pytest.fixture
def customer_no_interest(db):
    customer = Customer.objects.create(
        id="NRG-CUST-CG-NOINT",
        name="No Product Interest",
        phone="+918949879990",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="",
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
def customer_with_interest(db):
    customer = Customer.objects.create(
        id="NRG-CUST-CG-INT",
        name="Has Product Interest",
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


def test_slug_resolves_to_claim_product_even_without_product_interest(
    weight_management_claim, customer_no_interest
) -> None:
    """The reported VPS bug: slug ``weight-management`` did not match
    ``Claim.product='Weight Management'`` and the customer had no
    ``product_interest`` set. With the fix the slug must resolve."""
    rows = _claims_for_category("weight-management", customer_no_interest)
    assert len(rows) == 1
    assert rows[0].product == "Weight Management"


def test_unknown_category_with_blank_product_interest_returns_empty(
    weight_management_claim, joint_care_claim, customer_no_interest
) -> None:
    """Previous bug: empty product_interest fell through to
    ``product__icontains=""`` and returned every Claim in the table.
    The fix replaces that with an exact-match-or-empty contract."""
    rows = _claims_for_category("unknown", customer_no_interest)
    assert rows == []


def test_unknown_category_falls_back_to_customer_product_interest(
    weight_management_claim, joint_care_claim, customer_with_interest
) -> None:
    rows = _claims_for_category("unknown", customer_with_interest)
    assert len(rows) == 1
    assert rows[0].product == "Weight Management"


def test_known_slug_overrides_product_interest_when_both_present(
    weight_management_claim, joint_care_claim, customer_with_interest
) -> None:
    """If the LLM emitted ``joint-care`` for a customer whose
    historical interest is Weight Management, the live category wins.
    """
    rows = _claims_for_category("joint-care", customer_with_interest)
    assert len(rows) == 1
    assert rows[0].product == "Joint Care"


def test_unknown_slug_with_no_known_alias_fails_closed(
    weight_management_claim, customer_no_interest
) -> None:
    """An unknown slug must NEVER smuggle through to a kitchen-sink
    return. The prior bug allowed ``product__icontains=""`` to leak
    every claim; ensure that path is gone."""
    rows = _claims_for_category("magic-pill", customer_no_interest)
    assert rows == []


# ---------------------------------------------------------------------------
# Section C — controlled-test command diagnostics + audit
# ---------------------------------------------------------------------------


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-CG-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Nirogidhara Claim-Grounding",
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


def _ai_decision_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "action": "send_reply",
        "language": "hinglish",
        "category": "weight-management",
        "confidence": 0.9,
        "replyText": (
            "Namaskar! Weight management ke liye humare paas Supports "
            "healthy metabolism wala Ayurvedic blend hai."
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
        raw={"id": "resp-claim-grounding"},
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


@override_settings(**META_CREDS)
def test_controlled_send_now_grounds_weight_management_claim(
    connection,
    greeting_template,
    weight_management_claim,
    customer_with_interest,
    monkeypatch,
) -> None:
    """End-to-end regression of the exact VPS bug: customer asks about
    weight-management, the LLM is supposed to ground in the Weight
    Management Claim Vault row, the controlled test command must now
    surface the grounding diagnostics + actually dispatch."""
    convo = whatsapp_services.get_or_open_conversation(
        customer_with_interest, connection=connection
    )
    WhatsAppMessage.objects.create(
        id="WAM-CG-PRESEED",
        conversation=convo,
        customer=customer_with_interest,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )

    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    fake_provider = mock.Mock()
    fake_provider.name = "meta_cloud"
    fake_provider.send_text_message.return_value = mock.Mock(
        provider="meta_cloud",
        provider_message_id="wamid.CG-LIVE-OK",
        status="sent",
        request_payload={"to": customer_with_interest.phone},
        response_payload={},
        response_status=200,
        latency_ms=1,
    )
    monkeypatch.setattr(
        "apps.whatsapp.services.get_provider", lambda: fake_provider
    )

    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_with_interest.phone,
            message=(
                "Namaste mujhe weight management product ke baare me "
                "approved safe jaankari chahiye"
            ),
            send=True,
        )

    assert result["passed"] is True
    assert result["replySent"] is True
    # New diagnostics block.
    assert result["detectedCategory"] == "weight-management"
    assert result["normalizedClaimProduct"] == "Weight Management"
    assert result["claimCount"] == 3
    assert result["confidence"] == pytest.approx(0.9)
    assert result["action"] == "send_reply"
    assert result["replyPreview"].startswith("Namaskar!")
    assert result["safetyFlags"]["claimVaultUsed"] is True
    assert result["groundingStatus"]["claimProductFound"] is True
    assert result["groundingStatus"]["approvedClaimCount"] == 3
    assert result["groundingStatus"]["disallowedPhraseCount"] == 2
    assert result["groundingStatus"]["promptGroundingInjected"] is True


@override_settings(**META_CREDS)
def test_controlled_send_blocks_when_llm_returns_claim_vault_used_false(
    connection,
    greeting_template,
    weight_management_claim,
    customer_with_interest,
    monkeypatch,
) -> None:
    """Even after grounding is fixed, the safety contract must still
    hold: if the LLM marks ``claimVaultUsed=false``, the orchestrator
    blocks via the existing ``claim_vault_not_used`` path."""
    convo = whatsapp_services.get_or_open_conversation(
        customer_with_interest, connection=connection
    )
    WhatsAppMessage.objects.create(
        id="WAM-CG-PRESEED-BLK",
        conversation=convo,
        customer=customer_with_interest,
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
                safety={
                    "claimVaultUsed": False,
                    "medicalEmergency": False,
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
            phone=customer_with_interest.phone,
            message="weight management batao",
            send=True,
        )

    assert result["passed"] is False
    assert result["replySent"] is False
    assert result["replyBlocked"] is True
    # Diagnostics still populated even on block — operator can see the
    # claim DOES exist; the reason is the LLM choosing not to use it.
    assert result["detectedCategory"] == "weight-management"
    assert result["normalizedClaimProduct"] == "Weight Management"
    assert result["claimCount"] == 3
    assert result["claimVaultUsed"] is False
    assert result["nextAction"] == "blocked_for_unapproved_claim"


@override_settings(**META_CREDS)
def test_reply_blocked_audit_payload_now_carries_grounding_context(
    connection,
    greeting_template,
    weight_management_claim,
    customer_with_interest,
    monkeypatch,
) -> None:
    """The orchestrator's `whatsapp.ai.reply_blocked` audit row must
    now include category + normalized_claim_product + claim_count +
    confidence so log readers can diagnose without re-running."""
    convo = whatsapp_services.get_or_open_conversation(
        customer_with_interest, connection=connection
    )
    WhatsAppMessage.objects.create(
        id="WAM-CG-PRESEED-AUDIT",
        conversation=convo,
        customer=customer_with_interest,
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
                safety={
                    "claimVaultUsed": False,
                    "medicalEmergency": False,
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
        _run_command(
            phone=customer_with_interest.phone,
            message="weight management batao",
            send=True,
        )

    # `claim_vault_not_used` routes through the handoff path, not the
    # plain reply_blocked path. Both carry the grounding diagnostics.
    audit = (
        AuditEvent.objects.filter(kind="whatsapp.ai.handoff_required")
        .order_by("-occurred_at")
        .first()
    )
    assert audit is not None
    payload = audit.payload
    assert payload.get("reason") == "claim_vault_not_used"
    assert payload.get("category") == "weight-management"
    assert payload.get("normalized_claim_product") == "Weight Management"
    # Phase 5F-Gate Controlled Reply Confidence Fix splits the
    # ambiguous claim_count into row vs approved-phrase counts. The
    # legacy claim_count alias now reflects the approved-phrase count
    # (3 phrases for Weight Management); claim_row_count is 1.
    assert payload.get("claim_row_count") == 1
    assert payload.get("approved_claim_count") == 3
    assert payload.get("disallowed_phrase_count") == 2
    assert payload.get("claim_count") == 3
    assert payload.get("confidence") == pytest.approx(0.9)
    # Audit payload must never carry secrets.
    for key in payload.keys():
        assert "token" not in key.lower()
        assert "secret" not in key.lower()


@override_settings(**META_CREDS)
def test_controlled_command_output_omits_secrets_after_diagnostics_added(
    connection, greeting_template, weight_management_claim, customer_with_interest
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer_with_interest.phone,
            message="hello",
        )
    blob = json.dumps(result).lower()
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob


# ---------------------------------------------------------------------------
# Section D — defence-in-depth contracts still hold
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_final_send_limited_mode_guard_still_blocks_non_allowed_number(
    connection,
) -> None:
    """The Phase 5F-Gate Controlled AI Auto-Reply contract still
    holds: any send to a phone outside the allow-list under limited
    mode is refused at the service layer."""
    customer = Customer.objects.create(
        id="NRG-CUST-CG-OUTSIDE",
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
        id="WCV-CG-OUTSIDE",
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


def test_disallowed_phrases_remain_in_orchestrator_prompt_context(
    weight_management_claim, customer_with_interest
) -> None:
    """Build the prompt context manually and confirm the disallowed
    list survives — the LLM continues to see the avoid list."""
    from apps.whatsapp.ai_orchestration import _build_prompt
    from apps.whatsapp.ai_schema import BLOCKED_CLAIM_PHRASES

    # The prompt builder reads claims from the context object — we
    # construct a minimal context that mimics what _build_context
    # produces.
    convo = WhatsAppConversation.objects.create(
        id="WCV-CG-PROMPT",
        customer=customer_with_interest,
        connection=WhatsAppConnection.objects.create(
            id="WAC-CG-PROMPT",
            provider=WhatsAppConnection.Provider.MOCK,
            display_name="prompt test",
            phone_number="+91 9000099001",
            status=WhatsAppConnection.Status.CONNECTED,
        ),
        status=WhatsAppConversation.Status.OPEN,
    )
    inbound = WhatsAppMessage.objects.create(
        id="WAM-CG-PROMPT-IN",
        conversation=convo,
        customer=customer_with_interest,
        direction=WhatsAppMessage.Direction.INBOUND,
        status=WhatsAppMessage.Status.DELIVERED,
        type=WhatsAppMessage.Type.TEXT,
        body="weight management batao",
        queued_at=timezone.now(),
    )
    context = {
        "customer": {
            "id": customer_with_interest.id,
            "name": customer_with_interest.name,
            "phone": customer_with_interest.phone,
            "city": customer_with_interest.city,
            "state": customer_with_interest.state,
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
            "advanceAmountInr": 499,
            "totalDiscountCapPct": 50,
        },
    }
    messages = _build_prompt(convo, inbound, context)
    user_block = messages[1]["content"]
    # Approved phrases injected.
    assert "Supports healthy metabolism" in user_block
    # Disallowed list visible too — the LLM has the avoid list.
    assert "Guaranteed cure" in user_block
    # Hard-coded blocked-phrase guard from the schema is still in the
    # system policy (defence in depth on the prompt side).
    assert any(
        phrase in messages[0]["content"].lower()
        for phrase in BLOCKED_CLAIM_PHRASES
    )
