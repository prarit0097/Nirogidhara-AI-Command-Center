"""Phase 5F-Gate Hardening Hotfix tests.

Covers:

- ``run_meta_one_number_test`` returns clean JSON instead of a
  traceback when the unique idempotency-key constraint fires.
- ``run_meta_one_number_test --check-webhook-config`` warns when the
  WABA's ``subscribed_apps`` list is empty, reports active when it
  contains rows, and survives Graph failures.
- ``inspect_whatsapp_live_test`` is strictly read-only, returns the
  expected JSON shape, handles "no data" cleanly, never prints
  secrets, and never adds new audit / message / status / webhook
  rows during a run.
"""
from __future__ import annotations

import io
import json
from typing import Any
from unittest import mock

import pytest
from django.core.management import call_command
from django.db import IntegrityError
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppMessageStatusEvent,
    WhatsAppTemplate,
    WhatsAppWebhookEvent,
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
        id="WAC-HARDEN-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Nirogidhara Meta Hardening",
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
        body_components=[
            {"type": "BODY", "text": "Namaskar, Nirogidhara."},
        ],
        action_key="whatsapp.greeting",
        claim_vault_required=False,
    )
    return template


@pytest.fixture
def consented_test_customer(db):
    customer = Customer.objects.create(
        id="NRG-CUST-HARDEN-001",
        name="Hardening Test Number",
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


def _run_one_number(**kwargs: Any) -> dict[str, Any]:
    out = io.StringIO()
    call_command("run_meta_one_number_test", "--json", stdout=out, **kwargs)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def _run_inspector(phone: str) -> dict[str, Any]:
    out = io.StringIO()
    call_command(
        "inspect_whatsapp_live_test",
        "--phone",
        phone,
        "--json",
        stdout=out,
    )
    return json.loads(out.getvalue().strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# Phase 2 — duplicate idempotency
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_duplicate_idempotency_returns_clean_json_no_traceback(
    connection, greeting_template, consented_test_customer
) -> None:
    """The IntegrityError used to crash the CLI with a traceback. The
    Hardening Hotfix wraps the create + reports the existing message
    cleanly so operators can see what already happened."""
    from apps.whatsapp import services as whatsapp_services
    from apps.whatsapp.models import WhatsAppMessage

    # Simulate the prior outbound row that owns the unique idempotency
    # key for today. The CLI's queue_template_message call should
    # collide on it.
    fake_key = whatsapp_services._build_idempotency_key(
        customer=consented_test_customer,
        template=greeting_template,
        variables={},
        action_key="whatsapp.greeting",
    )
    existing = WhatsAppMessage.objects.create(
        id="WAM-EXISTING-DUP-001",
        conversation=WhatsAppConversation.objects.create(
            id="WCV-EXISTING-DUP-001",
            customer=consented_test_customer,
            connection=connection,
            status=WhatsAppConversation.Status.OPEN,
        ),
        customer=consented_test_customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        template=greeting_template,
        provider_message_id="wamid.PRIOR-DUP-PROVIDER-MSGID",
        idempotency_key=fake_key,
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )

    result = _run_one_number(
        to="+919000099001",
        template="nrg_greeting_intro",
        send=True,
    )
    assert result["passed"] is False
    assert result["duplicateIdempotencyKey"] is True
    assert result["existingMessageId"] == existing.id
    assert result["alreadySent"] is True
    assert result["nextAction"] == "inspect_existing_message"
    assert "whatsapp.meta_test.duplicate_idempotency" in result["auditEvents"]


@override_settings(**META_CREDS)
def test_duplicate_idempotency_audit_payload_omits_secrets(
    connection, greeting_template, consented_test_customer
) -> None:
    """The duplicate-idempotency audit row must never carry the raw key
    or any secret-shaped value."""
    from apps.whatsapp import services as whatsapp_services
    from apps.whatsapp.models import WhatsAppMessage

    fake_key = whatsapp_services._build_idempotency_key(
        customer=consented_test_customer,
        template=greeting_template,
        variables={},
        action_key="whatsapp.greeting",
    )
    WhatsAppMessage.objects.create(
        id="WAM-EXISTING-DUP-002",
        conversation=WhatsAppConversation.objects.create(
            id="WCV-EXISTING-DUP-002",
            customer=consented_test_customer,
            connection=connection,
            status=WhatsAppConversation.Status.OPEN,
        ),
        customer=consented_test_customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.QUEUED,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        template=greeting_template,
        idempotency_key=fake_key,
        queued_at=timezone.now(),
    )

    _run_one_number(
        to="+919000099001",
        template="nrg_greeting_intro",
        send=True,
    )
    audit = AuditEvent.objects.filter(
        kind="whatsapp.meta_test.duplicate_idempotency"
    ).order_by("-occurred_at").first()
    assert audit is not None
    payload = audit.payload
    # Only the suffix is allowed, never the raw key, and no token-shaped key.
    assert "idempotency_key_suffix" in payload
    assert "idempotency_key" not in payload
    for key in payload.keys():
        assert "token" not in key.lower()
        assert "secret" not in key.lower()


# ---------------------------------------------------------------------------
# Phase 4 — webhook config WABA diagnostics
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_check_webhook_config_warns_when_subscribed_apps_empty(db) -> None:
    """When ``GET /{WABA}/subscribed_apps`` returns ``data=[]``, the
    command must surface the warning + emit a webhook_subscription
    audit row + flip nextAction so the operator sees what to do."""
    from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus

    with mock.patch(
        "apps.whatsapp.management.commands.run_meta_one_number_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True,
            active=False,
            subscribed_app_count=0,
            warning="subscribed_apps is empty — Meta will NOT deliver inbound webhooks.",
        ),
    ):
        result = _run_one_number(check_webhook_config=True)

    assert result["nextAction"] == "subscribe_waba_to_app_webhooks"
    assert any("subscribed_apps" in w for w in result["warnings"])
    assert "whatsapp.meta_test.webhook_subscription_checked" in result["auditEvents"]
    audit = AuditEvent.objects.filter(
        kind="whatsapp.meta_test.webhook_subscription_checked"
    ).first()
    assert audit is not None
    assert audit.payload["active"] is False
    assert audit.payload["subscribed_app_count"] == 0


@override_settings(**META_CREDS)
def test_check_webhook_config_reports_active_when_subscribed_apps_populated(db) -> None:
    from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus

    with mock.patch(
        "apps.whatsapp.management.commands.run_meta_one_number_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        ),
    ):
        result = _run_one_number(check_webhook_config=True)

    assert result["nextAction"] == "webhook_config_summary"
    audit = AuditEvent.objects.filter(
        kind="whatsapp.meta_test.webhook_subscription_checked"
    ).first()
    assert audit is not None
    assert audit.payload["active"] is True
    assert audit.payload["subscribed_app_count"] == 1


@override_settings(**META_CREDS)
def test_check_webhook_config_handles_graph_failure_gracefully(db) -> None:
    from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus

    with mock.patch(
        "apps.whatsapp.management.commands.run_meta_one_number_test.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=False,
            active=None,
            subscribed_app_count=0,
            error="Graph subscribed_apps GET failed: ConnectionError",
        ),
    ):
        result = _run_one_number(check_webhook_config=True)

    # Command still produced JSON, did not crash, and surfaced an error.
    assert result["nextAction"] == "webhook_config_summary"
    assert any("Graph subscribed_apps GET failed" in w for w in result["warnings"])
    audit = AuditEvent.objects.filter(
        kind="whatsapp.meta_test.webhook_subscription_checked"
    ).first()
    assert audit is not None
    assert audit.payload["error"]


@override_settings(
    **{**META_CREDS, "META_WA_ACCESS_TOKEN": "", "META_WA_BUSINESS_ACCOUNT_ID": ""}
)
def test_check_webhook_config_skips_graph_check_without_creds() -> None:
    """Missing credentials → skip the Graph call, flag the warning, do
    NOT change nextAction (the user is fixing config first)."""
    result = _run_one_number(check_webhook_config=True)
    assert result["nextAction"] == "webhook_config_summary"
    audit = AuditEvent.objects.filter(
        kind="whatsapp.meta_test.webhook_subscription_checked"
    ).first()
    assert audit is not None
    assert audit.payload["checked"] is False


# ---------------------------------------------------------------------------
# Phase 3 — inspect_whatsapp_live_test
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_inspector_reports_customer_consent_conversation_messages(
    connection, greeting_template, consented_test_customer
) -> None:
    """End-to-end: a customer with consent + a conversation + an
    outbound message should all show up in the inspector report."""
    convo = WhatsAppConversation.objects.create(
        id="WCV-INSPECT-001",
        customer=consented_test_customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
        unread_count=2,
    )
    WhatsAppMessage.objects.create(
        id="WAM-INSPECT-OUT-001",
        conversation=convo,
        customer=consented_test_customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="Namaskar, Nirogidhara.",
        template=greeting_template,
        provider_message_id="wamid.INSPECT-PROVIDER-001",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )

    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_live_test.check_waba_subscription",
    ) as mocked:
        from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus

        mocked.return_value = WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        )
        report = _run_inspector("+919000099001")

    assert report["isAllowedTestNumber"] is True
    assert report["customer"]["found"] is True
    assert report["customer"]["id"] == consented_test_customer.id
    assert report["whatsappConsent"]["found"] is True
    assert report["whatsappConsent"]["consent_state"] == "granted"
    assert report["conversation"]["found"] is True
    assert report["conversation"]["id"] == convo.id
    assert report["messages"]["latestOutbound"]
    assert (
        report["messages"]["latestOutbound"][0]["provider_message_id"]
        == "wamid.INSPECT-PROVIDER-001"
    )
    assert report["latestProviderMessageId"] == "wamid.INSPECT-PROVIDER-001"


@override_settings(**META_CREDS)
def test_inspector_handles_empty_state_gracefully(db) -> None:
    """No customer, no messages, no webhooks, no status events — the
    inspector must still produce a complete JSON report and recommend a
    sane next action without crashing."""
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_live_test.check_waba_subscription",
    ) as mocked:
        from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus

        mocked.return_value = WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        )
        report = _run_inspector("+919000099001")

    assert report["customer"]["found"] is False
    assert report["whatsappConsent"]["found"] is False
    assert report["conversation"]["found"] is False
    assert report["messages"]["latestOutbound"] == []
    assert report["messages"]["latestInbound"] == []
    assert report["webhookEvents"]["count"] == 0
    assert report["statusEvents"]["count"] == 0
    assert report["nextAction"] == "run_one_number_send"


@override_settings(**META_CREDS)
def test_inspector_reports_subscribe_when_waba_inactive(db) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_live_test.check_waba_subscription",
    ) as mocked:
        from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus

        mocked.return_value = WabaSubscriptionStatus(
            checked=True,
            active=False,
            subscribed_app_count=0,
            warning="subscribed_apps is empty.",
        )
        report = _run_inspector("+919000099001")

    assert report["nextAction"] == "subscribe_waba_to_app_webhooks"
    assert any("subscribed_apps" in w for w in report["warnings"])


@override_settings(**META_CREDS)
def test_inspector_recommends_observe_status_when_inbound_exists_but_no_status_events(
    connection, greeting_template, consented_test_customer
) -> None:
    convo = WhatsAppConversation.objects.create(
        id="WCV-INSPECT-002",
        customer=consented_test_customer,
        connection=connection,
        status=WhatsAppConversation.Status.OPEN,
    )
    WhatsAppMessage.objects.create(
        id="WAM-INSPECT-OUT-002",
        conversation=convo,
        customer=consented_test_customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEMPLATE,
        body="seed",
        template=greeting_template,
        provider_message_id="wamid.INSPECT-PROVIDER-002",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    WhatsAppMessage.objects.create(
        id="WAM-INSPECT-IN-002",
        conversation=convo,
        customer=consented_test_customer,
        direction=WhatsAppMessage.Direction.INBOUND,
        status=WhatsAppMessage.Status.DELIVERED,
        type=WhatsAppMessage.Type.TEXT,
        body="Namaste webhook test",
        provider_message_id="wamid.INBOUND-WEBHOOK-TEST",
        queued_at=timezone.now(),
        delivered_at=timezone.now(),
    )

    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_live_test.check_waba_subscription",
    ) as mocked:
        from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus

        mocked.return_value = WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        )
        report = _run_inspector("+919000099001")

    assert report["nextAction"] == "observe_status_events_optional"
    # The 0 status_events is a soft signal — no warning yet.
    assert report["statusEvents"]["count"] == 0


@override_settings(**META_CREDS)
def test_inspector_does_not_mutate_database(connection, greeting_template, consented_test_customer) -> None:
    """Strict read-only contract — running the inspector must not add a
    single row anywhere (no audit row, no message, no status event,
    no webhook envelope)."""
    audit_before = AuditEvent.objects.count()
    msg_before = WhatsAppMessage.objects.count()
    status_before = WhatsAppMessageStatusEvent.objects.count()
    webhook_before = WhatsAppWebhookEvent.objects.count()

    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_live_test.check_waba_subscription",
    ) as mocked:
        from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus

        mocked.return_value = WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        )
        _run_inspector("+919000099001")

    assert AuditEvent.objects.count() == audit_before
    assert WhatsAppMessage.objects.count() == msg_before
    assert WhatsAppMessageStatusEvent.objects.count() == status_before
    assert WhatsAppWebhookEvent.objects.count() == webhook_before


@override_settings(**META_CREDS)
def test_inspector_output_omits_secrets_and_tokens(connection, greeting_template, consented_test_customer) -> None:
    with mock.patch(
        "apps.whatsapp.management.commands.inspect_whatsapp_live_test.check_waba_subscription",
    ) as mocked:
        from apps.whatsapp.meta_one_number_test import WabaSubscriptionStatus

        mocked.return_value = WabaSubscriptionStatus(
            checked=True, active=True, subscribed_app_count=1
        )
        report = _run_inspector("+919000099001")

    blob = json.dumps(report).lower()
    # Hard-coded tokens used in META_CREDS — must never appear in the report.
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob


@override_settings(
    **{**META_CREDS, "META_WA_ACCESS_TOKEN": "", "META_WA_BUSINESS_ACCOUNT_ID": ""}
)
def test_inspector_runs_when_meta_credentials_are_missing(db) -> None:
    """Operator may run the inspector before configuring Meta — the
    Graph check is skipped, but every other pane still renders."""
    report = _run_inspector("+919000099001")
    assert "wabaSubscription" in report
    assert report["wabaSubscription"]["wabaSubscriptionChecked"] is False
    assert report["isAllowedTestNumber"] is True
