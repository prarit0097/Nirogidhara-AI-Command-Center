"""Phase 5F-Gate Controlled AI Auto-Reply Test Harness — pytest cases.

Covers:

- Final-send limited-mode guard inside ``services.send_freeform_text_message``
  + ``services.queue_template_message`` refuses sends to phones not on
  ``WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`` when limited mode is on.
- The new ``run_controlled_ai_auto_reply_test`` command refuses on
  every amber gate (provider, limited mode, automation flag on,
  number not allowed, customer missing, consent missing, WABA empty).
- Dry-run path passes without persisting a synthetic inbound or
  invoking the orchestrator.
- Real ``--send`` path drives the orchestrator with
  ``force_auto_reply=True`` so the AI reply is dispatched without
  needing to flip the global ``WHATSAPP_AI_AUTO_REPLY_ENABLED`` env.
- Medical-emergency / safety-flag inbounds are blocked.
- Output never carries tokens / verify token / app secret.
- No campaigns / broadcasts behaviour is introduced (audit ledger
  contains zero ``whatsapp.campaign.*`` rows).
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
    WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS="+91 90000 99001",
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-CTRL-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Nirogidhara Controlled Test",
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
def consented_test_customer(db):
    customer = Customer.objects.create(
        id="NRG-CUST-CTRL-001",
        name="Allowed Test Number",
        phone="+919000099001",
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
def disallowed_customer(db):
    customer = Customer.objects.create(
        id="NRG-CUST-CTRL-OUTSIDE",
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
    return customer


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


# ---------------------------------------------------------------------------
# Final-send limited-mode guard
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_freeform_send_refuses_phone_outside_allow_list_in_limited_mode(
    connection, disallowed_customer
) -> None:
    """The new guard inside services.send_freeform_text_message must
    block freeform AI replies to phones that are not on the allow-list
    when WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true."""
    convo = WhatsAppConversation.objects.create(
        id="WCV-CTRL-GUARD-001",
        customer=disallowed_customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
    )
    with pytest.raises(whatsapp_services.WhatsAppServiceError) as excinfo:
        whatsapp_services.send_freeform_text_message(
            customer=disallowed_customer,
            conversation=convo,
            body="Hello from AI",
            actor_role="ai_chat",
            actor_agent="ai_chat",
        )
    assert excinfo.value.block_reason == "limited_test_number_not_allowed"
    assert AuditEvent.objects.filter(
        kind="whatsapp.send.blocked",
        payload__block_reason="limited_test_number_not_allowed",
    ).exists()


@override_settings(**META_CREDS)
def test_template_send_refuses_phone_outside_allow_list_in_limited_mode(
    connection, greeting_template, disallowed_customer
) -> None:
    """The same guard must apply to template sends — limited mode is a
    blanket rule for every customer-facing send under meta_cloud."""
    with pytest.raises(whatsapp_services.WhatsAppServiceError) as excinfo:
        whatsapp_services.queue_template_message(
            customer=disallowed_customer,
            action_key="whatsapp.greeting",
            template=greeting_template,
            triggered_by="test",
            actor_role="director",
            actor_agent="cli",
        )
    assert excinfo.value.block_reason == "limited_test_number_not_allowed"


@override_settings(
    **{**META_CREDS, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE": False}
)
def test_freeform_send_passes_when_limited_mode_off(
    connection, disallowed_customer, monkeypatch
) -> None:
    """Limited mode off — the guard must not interfere even with a
    phone outside the allow-list (other gates still apply, but this
    specific guard is a no-op)."""
    convo = WhatsAppConversation.objects.create(
        id="WCV-CTRL-GUARD-OFF",
        customer=disallowed_customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
    )
    # We don't want to hit a real provider; mock the provider singleton.
    fake_provider = mock.Mock()
    fake_provider.name = "meta_cloud"
    fake_provider.send_text_message.return_value = mock.Mock(
        provider="meta_cloud",
        provider_message_id="wamid.OFF-MODE-OK",
        status="sent",
        request_payload={"to": disallowed_customer.phone},
        response_payload={},
        response_status=200,
        latency_ms=1,
    )
    monkeypatch.setattr(
        "apps.whatsapp.services.get_provider", lambda: fake_provider
    )

    sent = whatsapp_services.send_freeform_text_message(
        customer=disallowed_customer,
        conversation=convo,
        body="Hello from AI",
        actor_role="ai_chat",
        actor_agent="ai_chat",
    )
    assert sent.status == WhatsAppMessage.Status.SENT


# ---------------------------------------------------------------------------
# run_controlled_ai_auto_reply_test — refusals
# ---------------------------------------------------------------------------


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
def test_controlled_ai_dry_run_passes_for_allowed_consented_number(
    connection, greeting_template, consented_test_customer
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone="+919000099001",
            message="Namaste mujhe weight loss product ke baare me bataye",
        )
    assert result["passed"] is True
    assert result["dryRun"] is True
    assert result["sendAttempted"] is False
    assert result["toAllowed"] is True
    assert result["nextAction"] == "dry_run_passed_ready_for_send"
    assert "whatsapp.ai.controlled_test.dry_run_passed" in result["auditEvents"]
    # Dry-run must NOT persist a synthetic inbound.
    assert not WhatsAppMessage.objects.filter(
        customer=consented_test_customer,
        direction=WhatsAppMessage.Direction.INBOUND,
    ).exists()


@override_settings(**META_CREDS)
def test_controlled_ai_refuses_non_allowed_number(
    connection, greeting_template, disallowed_customer
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=disallowed_customer.phone,
            message="hello",
        )
    assert result["passed"] is False
    assert result["toAllowed"] is False
    assert result["nextAction"] == "add_number_to_allowed_list"
    assert "whatsapp.ai.controlled_test.blocked" in result["auditEvents"]


@override_settings(**META_CREDS)
def test_controlled_ai_refuses_missing_consent(connection, db) -> None:
    customer = Customer.objects.create(
        id="NRG-CUST-CTRL-NOCONSENT",
        name="No Consent",
        phone="+919000099001",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=False,
    )
    WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={"consent_state": WhatsAppConsent.State.UNKNOWN},
    )
    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=customer.phone, message="hello"
        )
    assert result["passed"] is False
    assert result["nextAction"] == "grant_consent_on_test_number"


@override_settings(**{**META_CREDS, "WHATSAPP_PROVIDER": "mock"})
def test_controlled_ai_refuses_when_provider_not_meta_cloud(
    connection, consented_test_customer
) -> None:
    result = _run_command(
        phone=consented_test_customer.phone, message="hello"
    )
    assert result["passed"] is False
    assert result["nextAction"] == "enable_meta_cloud_provider"


@override_settings(
    **{**META_CREDS, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE": False}
)
def test_controlled_ai_refuses_when_limited_mode_off(
    connection, consented_test_customer
) -> None:
    result = _run_command(
        phone=consented_test_customer.phone, message="hello"
    )
    assert result["passed"] is False
    assert result["nextAction"] == "enable_limited_test_mode"


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_controlled_ai_refuses_when_auto_reply_already_globally_enabled(
    connection, consented_test_customer
) -> None:
    """The harness exists so Director can run a one-off test WITHOUT
    flipping the global flag. If the global flag is already on, refuse
    — the operator should be using the regular pipeline + soak."""
    result = _run_command(
        phone=consented_test_customer.phone, message="hello"
    )
    assert result["passed"] is False
    assert result["nextAction"] == "disable_automation_flags"


@override_settings(
    **{**META_CREDS, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED": True}
)
def test_controlled_ai_refuses_when_lifecycle_automation_on(
    connection, consented_test_customer
) -> None:
    result = _run_command(
        phone=consented_test_customer.phone, message="hello"
    )
    assert result["passed"] is False
    assert result["nextAction"] == "disable_automation_flags"


@override_settings(**META_CREDS)
def test_controlled_ai_refuses_when_waba_subscription_inactive(
    connection, consented_test_customer
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True,
            active=False,
            subscribed_app_count=0,
            warning="subscribed_apps is empty.",
        ),
    ):
        result = _run_command(
            phone=consented_test_customer.phone, message="hello"
        )
    assert result["passed"] is False
    assert result["nextAction"] == "fix_waba_subscription"


# ---------------------------------------------------------------------------
# Real --send path with mocked LLM
# ---------------------------------------------------------------------------


def _ai_decision_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "action": "send_reply",
        "language": "hinglish",
        "category": "weight-management",
        "confidence": 0.9,
        "replyText": (
            "Hi! Weight management ke liye humare paas Helpful Ayurvedic "
            "blend hai. Standard price ₹3000 / 30 capsules."
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
        raw={"id": "resp-controlled-test"},
        latency_ms=1,
        cost_usd=0.0,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )


@override_settings(**META_CREDS)
def test_controlled_ai_send_drives_orchestrator_with_force_auto_reply(
    connection, greeting_template, consented_test_customer, approved_claim, monkeypatch
) -> None:
    """End-to-end: --send must produce a real AI freeform reply through
    services.send_freeform_text_message even though
    WHATSAPP_AI_AUTO_REPLY_ENABLED stays false in env. The provider
    layer is mocked so no real Meta call fires."""
    # Pre-seed an outbound so the orchestrator does not take the
    # greeting fast-path.
    convo = whatsapp_services.get_or_open_conversation(
        consented_test_customer,
        connection=connection,
    )
    WhatsAppMessage.objects.create(
        id="WAM-CTRL-PRESEED-001",
        conversation=convo,
        customer=consented_test_customer,
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
        provider_message_id="wamid.CTRL-LIVE-OK",
        status="sent",
        request_payload={"to": consented_test_customer.phone},
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
            phone=consented_test_customer.phone,
            message="Namaste mujhe weight loss product ke baare me bataye",
            send=True,
        )

    assert result["passed"] is True, result
    assert result["dryRun"] is False
    assert result["sendAttempted"] is True
    assert result["replySent"] is True
    assert result["replyBlocked"] is False
    assert result["claimVaultUsed"] is True
    assert result["providerMessageId"] == "wamid.CTRL-LIVE-OK"
    assert result["nextAction"] == "live_ai_reply_sent_verify_phone"
    assert "whatsapp.ai.controlled_test.sent" in result["auditEvents"]


@override_settings(**META_CREDS)
def test_controlled_ai_send_blocks_medical_emergency(
    connection, greeting_template, consented_test_customer, approved_claim, monkeypatch
) -> None:
    """Safety flags from the LLM must still block the send even when
    --send is forced. The harness is not a safety bypass."""
    convo = whatsapp_services.get_or_open_conversation(
        consented_test_customer,
        connection=connection,
    )
    WhatsAppMessage.objects.create(
        id="WAM-CTRL-PRESEED-MED",
        conversation=convo,
        customer=consented_test_customer,
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
            phone=consented_test_customer.phone,
            message="Mujhe seene me dard ho raha hai, ambulance chahiye",
            send=True,
        )

    assert result["passed"] is False
    assert result["replySent"] is False
    assert result["safetyBlocked"] is True
    assert result["nextAction"] == "blocked_for_medical_safety"
    assert "whatsapp.ai.controlled_test.blocked" in result["auditEvents"]


# ---------------------------------------------------------------------------
# Misc safety
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_controlled_ai_output_omits_secrets(
    connection, greeting_template, consented_test_customer
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_command(
            phone=consented_test_customer.phone,
            message="hello",
        )
    blob = json.dumps(result).lower()
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob


@override_settings(**META_CREDS)
def test_controlled_ai_does_not_introduce_campaign_audit_kinds(
    connection, greeting_template, consented_test_customer
) -> None:
    """The harness must NOT introduce campaign / broadcast behaviour —
    no ``whatsapp.campaign.*`` audit row should ever land."""
    with mock.patch(
        "apps.whatsapp.management.commands.run_controlled_ai_auto_reply_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        _run_command(
            phone=consented_test_customer.phone,
            message="hello",
        )
    assert not AuditEvent.objects.filter(kind__startswith="whatsapp.campaign.").exists()
    assert not AuditEvent.objects.filter(kind__startswith="whatsapp.broadcast.").exists()
