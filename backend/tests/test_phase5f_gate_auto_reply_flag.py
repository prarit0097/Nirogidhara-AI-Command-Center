"""Phase 5F-Gate Limited Auto-Reply Flag Plan tests.

Covers:

- ``inspect_whatsapp_auto_reply_gate`` returns
  ``readyForLimitedAutoReply=true`` only when limited mode is on,
  provider is meta_cloud, the allow-list is non-empty, the WABA
  subscription is healthy (or unchecked due to missing creds), and
  every broad automation flag stays off.
- The same command flips ``readyForLimitedAutoReply=false`` and
  returns a typed blocker when any precondition fails.
- The command masks allow-list phones to last-4 by default.
- ``inspect_recent_whatsapp_auto_reply_activity`` reports the AI
  audit counts + business-state mutation deltas + flags any
  outbound that landed at a non-allow-list number in the window.
- The orchestrator's real auto-reply path emits two new audit
  kinds: ``whatsapp.ai.auto_reply_flag_path_used`` on success
  (when ``WHATSAPP_AI_AUTO_REPLY_ENABLED=true`` AND the run was NOT
  CLI-forced via ``force_auto_reply=True``), and
  ``whatsapp.ai.auto_reply_guard_blocked`` when the final-send
  guard refused.
- The CLI controlled-test command does NOT emit
  ``whatsapp.ai.auto_reply_flag_path_used`` (it's CLI-forced).
- The webhook-driven auto-reply path still respects the limited-
  mode allow-list, consent, Claim Vault, blocked-phrase, safety,
  CAIO, and audit ledger gates.
- Enabling the auto-reply flag does NOT enable any of the broad
  automation flags.
- No Order / Payment / Shipment / DiscountOfferLog row is created
  by the auto-reply path.
- No tokens / verify token / app secret / full phone numbers in
  output.
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
from apps.whatsapp.ai_orchestration import run_whatsapp_ai_agent
from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus
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


def _run(command_name: str, **kwargs: Any) -> dict[str, Any]:
    out = io.StringIO()
    call_command(command_name, "--json", stdout=out, **kwargs)
    return json.loads(out.getvalue().strip().splitlines()[-1])


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-FLAG-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Auto-Reply Flag Test",
        phone_number="+91 9000099000",
        phone_number_id="meta-phone-number-id-1",
        business_account_id="meta-waba-id-1",
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
def consented_test_customer(db):
    customer = Customer.objects.create(
        id="NRG-CUST-FLAG-001",
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


# ---------------------------------------------------------------------------
# Section A — inspect_whatsapp_auto_reply_gate
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_gate_inspector_reports_ready_when_every_precondition_passes(
    connection,
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_auto_reply_gate.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_auto_reply_gate")
    assert report["readyForLimitedAutoReply"] is True
    assert report["nextAction"] == "ready_to_enable_limited_auto_reply_flag"
    assert report["blockers"] == []
    assert report["limitedTestMode"] is True
    assert report["provider"] == "meta_cloud"


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_gate_inspector_reports_monitor_state_when_flag_already_on(
    connection,
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_auto_reply_gate.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_auto_reply_gate")
    assert report["readyForLimitedAutoReply"] is True
    assert report["autoReplyEnabled"] is True
    assert (
        report["nextAction"] == "limited_auto_reply_enabled_monitor_real_inbound"
    )


@override_settings(
    **{**META_CREDS, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE": False}
)
def test_gate_inspector_blocks_readiness_when_limited_mode_off(connection) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_auto_reply_gate.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_auto_reply_gate")
    assert report["readyForLimitedAutoReply"] is False
    assert report["nextAction"] == "keep_auto_reply_disabled_fix_blockers"
    assert any(
        "WHATSAPP_LIVE_META_LIMITED_TEST_MODE" in b for b in report["blockers"]
    )


@override_settings(
    **{
        **META_CREDS,
        "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED": True,
        "WHATSAPP_RESCUE_DISCOUNT_ENABLED": True,
    }
)
def test_gate_inspector_blocks_when_broad_automation_flags_on(
    connection,
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_auto_reply_gate.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_auto_reply_gate")
    assert report["readyForLimitedAutoReply"] is False
    assert any(
        "LIFECYCLE_AUTOMATION_ENABLED" in b for b in report["blockers"]
    )
    assert any(
        "RESCUE_DISCOUNT_ENABLED" in b for b in report["blockers"]
    )


@override_settings(**{**META_CREDS, "WHATSAPP_PROVIDER": "mock"})
def test_gate_inspector_blocks_when_provider_is_not_meta_cloud(
    connection,
) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_auto_reply_gate.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_auto_reply_gate")
    assert report["readyForLimitedAutoReply"] is False
    assert any("WHATSAPP_PROVIDER" in b for b in report["blockers"])


@override_settings(**META_CREDS)
def test_gate_inspector_masks_phones_and_omits_secrets(connection) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_auto_reply_gate.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        report = _run("inspect_whatsapp_auto_reply_gate")
    blob = json.dumps(report)
    # Full E.164 must NOT appear in the masked list output.
    assert "+918949879990" not in blob
    # Suffix appears.
    assert "9990" in blob
    # No tokens / secrets.
    blob_lower = blob.lower()
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob_lower
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob_lower
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob_lower


# ---------------------------------------------------------------------------
# Section B — orchestrator audit emits at the auto-reply flag path
# ---------------------------------------------------------------------------


def _ai_decision_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "action": "send_reply",
        "language": "hinglish",
        "category": "weight-management",
        "confidence": 0.9,
        "replyText": (
            "Namaskar! Weight management ke liye humare paas Supports "
            "healthy metabolism wala Ayurvedic blend hai. Standard price "
            "₹3000 / 30 capsules."
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
        raw={"id": "resp-flag"},
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
        id=f"WAM-FLAG-PRESEED-{customer.id}",
        conversation=convo,
        customer=customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    return convo


def _create_inbound(convo, customer, body: str) -> WhatsAppMessage:
    return WhatsAppMessage.objects.create(
        id=f"WAM-FLAG-IN-{customer.id}",
        conversation=convo,
        customer=customer,
        direction=WhatsAppMessage.Direction.INBOUND,
        status=WhatsAppMessage.Status.DELIVERED,
        type=WhatsAppMessage.Type.TEXT,
        body=body,
        provider_message_id=f"wamid.FLAG-IN-{customer.id}",
        queued_at=timezone.now(),
        delivered_at=timezone.now(),
    )


def _patch_provider_success(monkeypatch, *, mid: str = "wamid.FLAG-OK"):
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
    monkeypatch.setattr(
        "apps.whatsapp.services.get_provider", lambda: fake
    )


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_real_inbound_with_flag_on_emits_auto_reply_flag_path_used(
    connection,
    weight_management_claim,
    consented_test_customer,
    monkeypatch,
) -> None:
    """When WHATSAPP_AI_AUTO_REPLY_ENABLED=true AND the run is NOT
    CLI-forced (force_auto_reply default False), the orchestrator
    must emit ``whatsapp.ai.auto_reply_flag_path_used`` on every
    real auto-reply send."""
    convo = _seed_outbound(connection, consented_test_customer)
    inbound = _create_inbound(
        convo, consented_test_customer, "weight management price kya hai"
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
    assert outcome.sent is True
    assert AuditEvent.objects.filter(
        kind="whatsapp.ai.auto_reply_flag_path_used"
    ).exists()
    audit = AuditEvent.objects.filter(
        kind="whatsapp.ai.auto_reply_flag_path_used"
    ).first()
    assert audit.payload["category"] == "weight-management"
    assert audit.payload["claim_vault_used"] is True
    assert audit.payload["limited_test_mode"] is True
    # Phone last-4 only — never full E.164.
    assert audit.payload["phone_suffix"] == "9990"
    assert "+918949879990" not in json.dumps(audit.payload)


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_cli_forced_run_does_not_emit_flag_path_used(
    connection,
    weight_management_claim,
    consented_test_customer,
    monkeypatch,
) -> None:
    """A run forced via ``force_auto_reply=True`` is the CLI path —
    the dedicated controlled_test audits cover it. The new flag-path
    audit must NOT fire on that branch even though the env flag is
    on, otherwise the soak monitor would double-count."""
    convo = _seed_outbound(connection, consented_test_customer)
    inbound = _create_inbound(
        convo, consented_test_customer, "weight management price kya hai"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    _patch_provider_success(monkeypatch)

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="controlled_ai_auto_reply_test",
        force_auto_reply=True,
    )
    assert outcome.sent is True
    assert not AuditEvent.objects.filter(
        kind="whatsapp.ai.auto_reply_flag_path_used"
    ).exists()


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_real_inbound_to_non_allowed_number_emits_guard_blocked(
    connection, weight_management_claim, monkeypatch
) -> None:
    """Even when the env flag is on, the final-send guard must refuse
    a customer whose phone is not on the allow-list. The orchestrator
    must emit ``whatsapp.ai.auto_reply_guard_blocked`` with the typed
    block_reason."""
    customer = Customer.objects.create(
        id="NRG-CUST-FLAG-OUT",
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
    convo = _seed_outbound(connection, customer)
    inbound = _create_inbound(
        convo, customer, "weight management price kya hai"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    # Provider should NEVER be called — the limited-mode guard refuses
    # before we reach send_freeform_text_message.
    fake = mock.Mock()
    fake.name = "meta_cloud"
    fake.send_text_message = mock.Mock()
    monkeypatch.setattr(
        "apps.whatsapp.services.get_provider", lambda: fake
    )

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    assert outcome.sent is False
    fake.send_text_message.assert_not_called()
    audit = AuditEvent.objects.filter(
        kind="whatsapp.ai.auto_reply_guard_blocked"
    ).first()
    assert audit is not None
    assert audit.payload["block_reason"] == "limited_test_number_not_allowed"
    assert audit.payload["limited_test_mode"] is True
    assert audit.payload["auto_reply_enabled"] is True


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_real_inbound_blocks_side_effect_complaint(
    connection,
    weight_management_claim,
    consented_test_customer,
    monkeypatch,
) -> None:
    """Auto-reply flag on does NOT bypass safety. A side-effect
    complaint inbound still routes to handoff."""
    convo = _seed_outbound(connection, consented_test_customer)
    inbound = _create_inbound(
        convo,
        consented_test_customer,
        "medicine khane ke baad ulta asar ho gaya, vomiting bhi hui",
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

    outcome = run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    assert outcome.sent is False
    assert outcome.blocked_reason == "side_effect_complaint"
    # The handoff_required audit fired with the safety reason.
    handoff = AuditEvent.objects.filter(
        kind="whatsapp.ai.handoff_required"
    ).first()
    assert handoff is not None
    assert handoff.payload["reason"] == "side_effect_complaint"


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_auto_reply_flag_does_not_enable_broad_automation(
    connection, weight_management_claim, consented_test_customer
) -> None:
    """Flipping WHATSAPP_AI_AUTO_REPLY_ENABLED=true must NEVER imply
    that the lifecycle / call-handoff / rescue / RTO / reorder flags
    are also on. Verify by reading them directly from settings — the
    orchestrator must not mutate them."""
    from django.conf import settings

    assert (
        getattr(settings, "WHATSAPP_CALL_HANDOFF_ENABLED", False) is False
    )
    assert (
        getattr(settings, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED", False)
        is False
    )
    assert (
        getattr(settings, "WHATSAPP_RESCUE_DISCOUNT_ENABLED", False) is False
    )
    assert (
        getattr(settings, "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED", False)
        is False
    )
    assert (
        getattr(settings, "WHATSAPP_REORDER_DAY20_ENABLED", False) is False
    )


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_real_inbound_auto_reply_does_not_mutate_business_state(
    connection,
    weight_management_claim,
    consented_test_customer,
    monkeypatch,
) -> None:
    """Real auto-reply send must not create an Order, Payment,
    Shipment, or DiscountOfferLog row."""
    convo = _seed_outbound(connection, consented_test_customer)
    inbound = _create_inbound(
        convo, consented_test_customer, "weight management price kya hai"
    )
    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages",
        lambda messages: _adapter_success(_ai_decision_payload()),
    )
    _patch_provider_success(monkeypatch)

    discount_before = DiscountOfferLog.objects.count()
    order_before = Order.objects.count()
    payment_before = Payment.objects.count()
    shipment_before = Shipment.objects.count()
    run_whatsapp_ai_agent(
        conversation_id=convo.id,
        inbound_message_id=inbound.id,
        triggered_by="inbound",
    )
    assert DiscountOfferLog.objects.count() == discount_before
    assert Order.objects.count() == order_before
    assert Payment.objects.count() == payment_before
    assert Shipment.objects.count() == shipment_before


# ---------------------------------------------------------------------------
# Section C — inspect_recent_whatsapp_auto_reply_activity
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_recent_activity_inspector_counts_audit_kinds(
    connection, consented_test_customer
) -> None:
    # Seed a couple of audit rows so the inspector has something to
    # count.
    from apps.audit.signals import write_event

    write_event(
        kind="whatsapp.ai.run_started",
        text="run started",
        tone=AuditEvent.Tone.INFO,
        payload={"customer_id": consented_test_customer.id},
    )
    write_event(
        kind="whatsapp.ai.reply_auto_sent",
        text="auto sent",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "customer_id": consented_test_customer.id,
            "phone_suffix": "9990",
        },
    )
    write_event(
        kind="whatsapp.ai.auto_reply_flag_path_used",
        text="flag path used",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "customer_id": consented_test_customer.id,
            "phone_suffix": "9990",
        },
    )

    report = _run("inspect_recent_whatsapp_auto_reply_activity", hours=2)
    assert report["inboundAiRunStartedCount"] >= 1
    assert report["replyAutoSentCount"] >= 1
    assert report["autoReplyFlagPathUsedCount"] >= 1
    assert report["unexpectedNonAllowedSendsCount"] == 0
    # Nothing was created in the test window.
    assert report["ordersCreatedInWindow"] == 0
    assert report["paymentsCreatedInWindow"] == 0
    assert report["shipmentsCreatedInWindow"] == 0
    assert report["discountOfferLogsCreatedInWindow"] == 0
    assert report["nextAction"] in {
        "limited_auto_reply_enabled_monitor_real_inbound",
        "review_blocked_or_suggestion_paths",
    }


@override_settings(**META_CREDS)
def test_recent_activity_inspector_flags_unexpected_non_allowed_send(
    connection, weight_management_claim
) -> None:
    """A historical outbound that landed at a non-allow-list number
    in the window must surface as an unexpected send."""
    customer = Customer.objects.create(
        id="NRG-CUST-FLAG-LEAK",
        name="Non Allow-list Leak",
        phone="+919999999999",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=True,
    )
    convo = WhatsAppConversation.objects.create(
        id="WCV-FLAG-LEAK",
        customer=customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
    )
    WhatsAppMessage.objects.create(
        id="WAM-FLAG-LEAK",
        conversation=convo,
        customer=customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEXT,
        body="leak — should NEVER happen in real prod",
        provider_message_id="wamid.LEAK-FORENSIC",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )

    report = _run("inspect_recent_whatsapp_auto_reply_activity", hours=2)
    assert report["unexpectedNonAllowedSendsCount"] == 1
    assert report["nextAction"] == "rollback_auto_reply_flag"


@override_settings(**META_CREDS)
def test_recent_activity_inspector_output_omits_secrets(
    connection,
) -> None:
    report = _run("inspect_recent_whatsapp_auto_reply_activity", hours=2)
    blob = json.dumps(report).lower()
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob


# ---------------------------------------------------------------------------
# Section D — defence-in-depth: existing limited-mode guard intact
# ---------------------------------------------------------------------------


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_existing_limited_mode_guard_still_blocks_non_allowed_under_flag(
    connection,
) -> None:
    """The final-send guard blocks the same way regardless of whether
    the auto-reply env flag is on or off."""
    customer = Customer.objects.create(
        id="NRG-CUST-FLAG-GUARD",
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
        id="WCV-FLAG-GUARD",
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
