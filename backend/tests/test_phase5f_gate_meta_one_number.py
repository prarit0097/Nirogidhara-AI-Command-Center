"""Phase 5F-Gate — Limited Live Meta WhatsApp One-Number Test harness tests.

Verifies that the new ``run_meta_one_number_test`` management command +
:mod:`apps.whatsapp.meta_one_number_test` helpers fail closed on every
unsafe combination and only proceed when every gate is green.

Hard rules under test:

1. ``is_number_allowed_for_live_meta_test`` — empty allow-list, missing
   number, allowed digits all collapse correctly.
2. ``--verify-only`` returns ``passed=true`` only when provider is
   ``meta_cloud`` AND limited-test-mode is on AND credentials exist
   AND every automation flag is OFF AND template is approved.
3. ``--send`` is refused when:
   - Provider is not ``meta_cloud``.
   - Limited test mode is off.
   - Allow-list is empty.
   - Destination number is not on the allow-list.
   - Template is missing / not approved / inactive.
   - Any automation flag (auto-reply / lifecycle / handoff / rescue /
     RTO / Day-20) is ON.
4. Dry-run never calls the provider.
5. Real send path with mocked provider succeeds and emits the
   expected ledger rows.
6. ``--check-webhook-config`` prints the expected callback URL.
7. No real Meta token is required for any test (mocking covers it).
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
from apps.crm.models import Customer
from apps.whatsapp.integrations.whatsapp.base import ProviderSendResult
from apps.whatsapp.meta_one_number_test import (
    get_allowed_test_numbers,
    is_number_allowed_for_live_meta_test,
    resolve_test_template,
    verify_provider_and_credentials,
    webhook_url_summary,
)
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
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
    WHATSAPP_CALL_HANDOFF_ENABLED=False,
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=False,
    WHATSAPP_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_REORDER_DAY20_ENABLED=False,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-META-TEST-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Nirogidhara Meta Test",
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
        id="NRG-CUST-META-TEST-001",
        name="Meta Test Number",
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


def _run_command(**kwargs: Any) -> dict[str, Any]:
    """Invoke ``run_meta_one_number_test`` and return the JSON output."""
    out = io.StringIO()
    call_command("run_meta_one_number_test", "--json", stdout=out, **kwargs)
    raw = out.getvalue().strip().splitlines()[-1]
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


@override_settings(WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS="")
def test_allow_list_empty_blocks_every_number() -> None:
    assert get_allowed_test_numbers() == []
    assert is_number_allowed_for_live_meta_test("+919000099001") is False


@override_settings(WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS="+91 90000 99001, 919000099002")
def test_allow_list_normalizes_and_matches() -> None:
    allow = get_allowed_test_numbers()
    assert "919000099001" in allow
    assert "919000099002" in allow
    assert is_number_allowed_for_live_meta_test("+919000099001") is True
    assert is_number_allowed_for_live_meta_test("91-9000099002") is True
    assert is_number_allowed_for_live_meta_test("9000099003") is False


@override_settings(WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS="+919000099001")
def test_empty_phone_is_blocked() -> None:
    assert is_number_allowed_for_live_meta_test("") is False
    assert is_number_allowed_for_live_meta_test(None) is False


# ---------------------------------------------------------------------------
# verify_provider_and_credentials
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_verification_passes_when_all_gates_green(connection, greeting_template) -> None:
    outcome = verify_provider_and_credentials()
    assert outcome.ok is True
    assert outcome.provider == "meta_cloud"
    assert outcome.limited_test_mode is True
    assert outcome.missing_keys == []
    assert outcome.automation_off is True


@override_settings(**{**META_CREDS, "WHATSAPP_PROVIDER": "mock"})
def test_verification_fails_when_provider_is_mock() -> None:
    outcome = verify_provider_and_credentials()
    assert outcome.ok is False
    assert outcome.provider == "mock"
    assert "WHATSAPP_PROVIDER" in outcome.missing_keys


@override_settings(**{**META_CREDS, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE": False})
def test_verification_fails_when_limited_test_mode_off() -> None:
    outcome = verify_provider_and_credentials()
    assert outcome.ok is False
    assert outcome.limited_test_mode is False


@override_settings(**{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True})
def test_verification_warns_when_automation_flag_on() -> None:
    outcome = verify_provider_and_credentials()
    assert outcome.ok is False
    assert outcome.automation_off is False
    assert "WHATSAPP_AI_AUTO_REPLY_ENABLED" in outcome.automation_warnings


@override_settings(
    **{**META_CREDS, "META_WA_ACCESS_TOKEN": "", "META_WA_PHONE_NUMBER_ID": ""}
)
def test_verification_lists_missing_credentials() -> None:
    outcome = verify_provider_and_credentials()
    assert outcome.ok is False
    assert "META_WA_ACCESS_TOKEN" in outcome.missing_keys
    assert "META_WA_PHONE_NUMBER_ID" in outcome.missing_keys


# ---------------------------------------------------------------------------
# Template resolver
# ---------------------------------------------------------------------------


def test_resolve_template_falls_back_to_greeting(connection, greeting_template) -> None:
    template, reason = resolve_test_template(connection=connection, language="hi")
    assert template is not None
    assert template.name == "nrg_greeting_intro"
    assert reason == ""


def test_resolve_template_refuses_marketing_tier(db, connection) -> None:
    upsert_template(
        connection=connection,
        name="nrg_promo",
        language="hi",
        category=WhatsAppTemplate.Category.MARKETING,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[{"type": "BODY", "text": "Big sale!"}],
        action_key="whatsapp.broadcast_promo",
    )
    template, reason = resolve_test_template(
        template_name="nrg_promo", connection=connection, language="hi"
    )
    assert template is None
    assert reason == "template_is_marketing_tier"


def test_resolve_template_refuses_pending_status(db, connection) -> None:
    upsert_template(
        connection=connection,
        name="nrg_pending",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.PENDING,
        body_components=[{"type": "BODY", "text": "pending"}],
        action_key="whatsapp.pending",
    )
    template, reason = resolve_test_template(
        template_name="nrg_pending", connection=connection, language="hi"
    )
    assert template is None
    assert reason.startswith("template_not_approved")


def test_resolve_template_refuses_inactive(db, connection, greeting_template) -> None:
    greeting_template.is_active = False
    greeting_template.save(update_fields=["is_active"])
    template, reason = resolve_test_template(connection=connection, language="hi")
    assert template is None
    assert reason == "template_inactive"


# ---------------------------------------------------------------------------
# Webhook config printer
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_webhook_summary_reports_callback_url() -> None:
    summary = webhook_url_summary()
    assert summary["callbackUrl"] == "https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/"
    assert summary["verifyTokenSet"] is True
    assert summary["appSecretSet"] is True
    assert "messages" in summary["subscribedFields"]


# ---------------------------------------------------------------------------
# Management command — verify-only / dry-run
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_verify_only_passes_with_valid_config(connection, greeting_template) -> None:
    result = _run_command(to="+919000099001", template="nrg_greeting_intro", verify_only=True)
    assert result["passed"] is True
    assert result["dryRun"] is True
    assert result["sendAttempted"] is False
    assert result["toAllowed"] is True
    assert result["templateApproved"] is True
    kinds = set(result["auditEvents"])
    assert "whatsapp.meta_test.started" in kinds
    assert "whatsapp.meta_test.config_ok" in kinds
    assert "whatsapp.meta_test.completed" in kinds
    assert "whatsapp.meta_test.failed" not in kinds


@override_settings(**{**META_CREDS, "WHATSAPP_PROVIDER": "mock"})
def test_send_blocks_when_provider_not_meta_cloud(connection, greeting_template) -> None:
    result = _run_command(to="+919000099001", template="nrg_greeting_intro", send=True)
    assert result["passed"] is False
    assert result["sendAttempted"] is False
    assert "fix_provider_credentials" == result["nextAction"]
    assert "whatsapp.meta_test.config_failed" in result["auditEvents"]


@override_settings(**{**META_CREDS, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE": False})
def test_send_blocks_when_limited_test_mode_false(connection, greeting_template) -> None:
    result = _run_command(to="+919000099001", template="nrg_greeting_intro", send=True)
    assert result["passed"] is False
    assert result["nextAction"] == "enable_limited_test_mode"
    assert "whatsapp.meta_test.config_failed" in result["auditEvents"]


@override_settings(**{**META_CREDS, "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS": ""})
def test_send_blocks_when_allow_list_empty(connection, greeting_template) -> None:
    result = _run_command(to="+919000099001", template="nrg_greeting_intro", send=True)
    assert result["passed"] is False
    assert result["toAllowed"] is False
    assert "whatsapp.meta_test.blocked_number" in result["auditEvents"]


@override_settings(**META_CREDS)
def test_send_blocks_when_number_not_in_allow_list(connection, greeting_template) -> None:
    result = _run_command(to="+919999999999", template="nrg_greeting_intro", send=True)
    assert result["passed"] is False
    assert result["toAllowed"] is False
    assert result["nextAction"] == "add_number_to_allowed_list"
    assert "whatsapp.meta_test.blocked_number" in result["auditEvents"]


@override_settings(**META_CREDS)
def test_send_blocks_when_template_missing(connection) -> None:
    # No template seeded → resolver returns template_not_found.
    result = _run_command(to="+919000099001", template="nrg_does_not_exist", send=True)
    assert result["passed"] is False
    assert "whatsapp.meta_test.template_missing" in result["auditEvents"]
    assert result["nextAction"] == "sync_or_approve_template"


@override_settings(**META_CREDS)
def test_send_blocks_when_template_not_approved(db, connection) -> None:
    upsert_template(
        connection=connection,
        name="nrg_pending_only",
        language="hi",
        category=WhatsAppTemplate.Category.UTILITY,
        status=WhatsAppTemplate.Status.PENDING,
        body_components=[{"type": "BODY", "text": "not approved"}],
        action_key="whatsapp.pending_only",
    )
    result = _run_command(to="+919000099001", template="nrg_pending_only", send=True)
    assert result["passed"] is False
    assert "whatsapp.meta_test.template_missing" in result["auditEvents"]


@override_settings(**{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True})
def test_send_blocks_when_automation_flag_on(connection, greeting_template) -> None:
    result = _run_command(to="+919000099001", template="nrg_greeting_intro", send=True)
    assert result["passed"] is False
    assert result["nextAction"] == "disable_automation_flags"
    assert "whatsapp.meta_test.config_failed" in result["auditEvents"]


@override_settings(**META_CREDS)
def test_dry_run_default_does_not_call_provider(connection, greeting_template) -> None:
    """No `--send` flag means dry-run regardless. Provider must not be invoked."""
    with mock.patch(
        "apps.whatsapp.services.send_queued_message"
    ) as mocked_send:
        result = _run_command(to="+919000099001", template="nrg_greeting_intro")
    mocked_send.assert_not_called()
    assert result["passed"] is True
    assert result["sendAttempted"] is False
    assert result["dryRun"] is True


@override_settings(**META_CREDS)
def test_check_webhook_config_prints_callback_url(connection) -> None:
    out = io.StringIO()
    call_command("run_meta_one_number_test", "--check-webhook-config", "--json", stdout=out)
    raw = out.getvalue().strip().splitlines()[-1]
    payload = json.loads(raw)
    assert payload["nextAction"] == "webhook_config_summary"
    assert payload["webhook"]["callbackUrl"] == (
        "https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/"
    )


# ---------------------------------------------------------------------------
# Real send (with mocked provider)
# ---------------------------------------------------------------------------


def _fake_provider_send_result() -> ProviderSendResult:
    return ProviderSendResult(
        provider="meta_cloud",
        provider_message_id="wamid.MOCK-META-TEST-PROVIDER-MSGID",
        status="sent",
        request_payload={"to": "+919000099001", "type": "template"},
        response_payload={"messages": [{"id": "wamid.MOCK-META-TEST-PROVIDER-MSGID"}]},
        response_status=200,
        latency_ms=42,
    )


@override_settings(**META_CREDS)
def test_send_succeeds_with_allowed_number_and_approved_template(
    connection,
    greeting_template,
    consented_test_customer,
) -> None:
    with mock.patch(
        "apps.whatsapp.services.get_provider"
    ) as mocked_factory:
        provider = mock.Mock()
        provider.name = "meta_cloud"
        provider.send_template_message.return_value = _fake_provider_send_result()
        mocked_factory.return_value = provider

        result = _run_command(
            to="+919000099001", template="nrg_greeting_intro", send=True
        )

    assert result["passed"] is True
    assert result["sendAttempted"] is True
    assert result["toAllowed"] is True
    assert result["templateApproved"] is True
    assert result["providerMessageId"] == "wamid.MOCK-META-TEST-PROVIDER-MSGID"
    assert "whatsapp.meta_test.sent" in result["auditEvents"]
    assert result["nextAction"] == "verify_inbound_webhook_callback"

    # Audit ledger has the expected sequence.
    kinds = AuditEvent.objects.values_list("kind", flat=True)
    assert "whatsapp.meta_test.started" in kinds
    assert "whatsapp.meta_test.config_ok" in kinds
    assert "whatsapp.meta_test.sent" in kinds
    assert "whatsapp.meta_test.completed" in kinds
    # Audit payloads must never carry tokens.
    for ev in AuditEvent.objects.filter(kind__startswith="whatsapp.meta_test."):
        for key in ev.payload.keys():
            assert "token" not in key.lower()

    # And the WhatsAppMessage row exists in SENT state.
    sent_msgs = WhatsAppMessage.objects.filter(
        provider_message_id="wamid.MOCK-META-TEST-PROVIDER-MSGID"
    )
    assert sent_msgs.exists()
    assert sent_msgs.first().status == WhatsAppMessage.Status.SENT
