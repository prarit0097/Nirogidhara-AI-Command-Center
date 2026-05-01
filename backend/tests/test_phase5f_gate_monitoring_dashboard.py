"""Phase 5F-Gate Auto-Reply Monitoring Dashboard tests.

Covers the read-only dashboard surface:

- Selectors return JSON-ready dictionaries with masked phones and no
  secrets.
- API endpoints under ``/api/whatsapp/monitoring/`` require admin
  auth and never mutate state.
- The combined overview derives a top-level ``status`` ∈ {``safe_off``,
  ``limited_auto_reply_on``, ``danger``, ``needs_attention``} the
  frontend renders directly.
- Mutation safety summary returns zero when the auto-reply path
  hasn't created any business-state rows.
- Unexpected outbound summary surfaces leaks (mocked).
- Audit endpoint scrubs sensitive payload keys.
- Unauthenticated and viewer-role access blocked.
"""
from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.compliance.models import Claim
from apps.crm.models import Customer
from apps.whatsapp import dashboard
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
    WHATSAPP_CALL_HANDOFF_ENABLED=False,
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=False,
    WHATSAPP_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=False,
    WHATSAPP_REORDER_DAY20_ENABLED=False,
)


def _patch_waba(active: bool = True, count: int = 1):
    return mock.patch(
        "apps.whatsapp.dashboard.check_waba_subscription",
        return_value=WabaSubscriptionStatus(
            checked=True, active=active, subscribed_app_count=count
        ),
    )


@pytest.fixture
def connection(db):
    return WhatsAppConnection.objects.create(
        id="WAC-MON-001",
        provider=WhatsAppConnection.Provider.META_CLOUD,
        display_name="Monitoring Test",
        phone_number="+91 9000099000",
        phone_number_id="meta-phone-mon",
        business_account_id="meta-waba-mon",
        status=WhatsAppConnection.Status.CONNECTED,
    )


@pytest.fixture
def weight_management_claim(db):
    return Claim.objects.create(
        product="Weight Management",
        approved=["Supports healthy metabolism"],
        disallowed=["Guaranteed cure"],
        doctor="Approved",
        compliance="Approved",
        version="v3.2",
    )


@pytest.fixture
def customer_allowed(db):
    customer = Customer.objects.create(
        id="NRG-CUST-MON-001",
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
# Section A — Selector unit tests
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_get_auto_reply_gate_summary_reports_ready_when_clean(
    connection,
) -> None:
    with _patch_waba():
        report = dashboard.get_auto_reply_gate_summary()
    assert report["readyForLimitedAutoReply"] is True
    assert report["nextAction"] == "ready_to_enable_limited_auto_reply_flag"
    assert report["blockers"] == []
    assert report["provider"] == "meta_cloud"
    assert report["limitedTestMode"] is True
    assert report["campaignsLocked"] is True
    # Phones masked.
    blob = json.dumps(report)
    assert "+918949879990" not in blob
    assert "9990" in blob
    # Secrets never present.
    blob_lower = blob.lower()
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob_lower
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob_lower
    assert META_CREDS["META_WA_APP_SECRET"].lower() not in blob_lower


@override_settings(
    **{**META_CREDS, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED": True}
)
def test_get_auto_reply_gate_summary_blocks_when_broad_flag_on(
    connection,
) -> None:
    with _patch_waba():
        report = dashboard.get_auto_reply_gate_summary()
    assert report["readyForLimitedAutoReply"] is False
    assert any(
        "LIFECYCLE_AUTOMATION_ENABLED" in b for b in report["blockers"]
    )


@override_settings(**META_CREDS)
def test_get_recent_auto_reply_activity_returns_zero_for_quiet_window(
    connection,
) -> None:
    activity = dashboard.get_recent_auto_reply_activity(hours=1)
    assert activity["replyAutoSentCount"] == 0
    assert activity["autoReplyFlagPathUsedCount"] == 0
    assert activity["unexpectedNonAllowedSendsCount"] == 0
    assert activity["ordersCreatedInWindow"] == 0
    assert activity["paymentsCreatedInWindow"] == 0
    assert activity["shipmentsCreatedInWindow"] == 0
    assert activity["discountOfferLogsCreatedInWindow"] == 0
    assert activity["nextAction"] == "no_recent_ai_activity_in_window"


@override_settings(**META_CREDS)
def test_get_recent_auto_reply_activity_counts_audit_kinds(
    connection, customer_allowed
) -> None:
    write_event(
        kind="whatsapp.ai.reply_auto_sent",
        text="auto reply",
        payload={"phone_suffix": "9990"},
    )
    write_event(
        kind="whatsapp.ai.auto_reply_flag_path_used",
        text="flag path",
        payload={"phone_suffix": "9990"},
    )
    write_event(
        kind="whatsapp.ai.deterministic_grounded_reply_used",
        text="deterministic",
        payload={"phone_suffix": "9990"},
    )
    activity = dashboard.get_recent_auto_reply_activity(hours=1)
    assert activity["replyAutoSentCount"] == 1
    assert activity["autoReplyFlagPathUsedCount"] == 1
    assert activity["deterministicBuilderUsedCount"] == 1


@override_settings(**META_CREDS)
def test_get_internal_cohort_summary_masks_phone_and_reports_ready(
    connection, customer_allowed
) -> None:
    with _patch_waba():
        report = dashboard.get_internal_cohort_summary()
    assert report["allowedListSize"] == 1
    assert report["cohort"][0]["customerFound"] is True
    assert report["cohort"][0]["consentState"] == "granted"
    assert report["cohort"][0]["readyForControlledTest"] is True
    blob = json.dumps(report)
    assert "+918949879990" not in blob
    assert "9990" in blob
    # operator-only --show-full-numbers flag should NEVER influence
    # the API surface.
    assert "fullPhone" not in blob


@override_settings(**META_CREDS)
def test_get_recent_audit_events_scrubs_sensitive_keys(
    connection, customer_allowed
) -> None:
    write_event(
        kind="whatsapp.ai.reply_auto_sent",
        text="dangerous payload",
        payload={
            "phone_suffix": "9990",
            "category": "weight-management",
            "token": "must-not-leak",
            "verify_token": "must-not-leak",
            "app_secret": "must-not-leak",
        },
    )
    report = dashboard.get_recent_whatsapp_audit_events(hours=1, limit=10)
    assert report["count"] >= 1
    blob = json.dumps(report).lower()
    assert "must-not-leak" not in blob
    assert "verify_token" not in blob
    assert "app_secret" not in blob


@override_settings(**META_CREDS)
def test_get_mutation_safety_summary_zero_for_clean_window() -> None:
    report = dashboard.get_whatsapp_mutation_safety_summary(hours=1)
    assert report["totalMutations"] == 0
    assert report["allClean"] is True
    assert report["ordersCreatedInWindow"] == 0
    assert report["paymentsCreatedInWindow"] == 0
    assert report["shipmentsCreatedInWindow"] == 0
    assert report["discountOfferLogsCreatedInWindow"] == 0


@override_settings(**META_CREDS)
def test_get_unexpected_outbound_summary_clean_returns_zero() -> None:
    report = dashboard.get_unexpected_outbound_summary(hours=1)
    assert report["unexpectedSendsCount"] == 0
    assert report["rollbackRecommended"] is False
    assert report["breakdown"] == []


@override_settings(**META_CREDS)
def test_get_unexpected_outbound_summary_detects_non_allowed_send(
    connection,
) -> None:
    """A real outbound sent to a phone outside the allow-list must
    appear in the breakdown."""
    leaky_customer = Customer.objects.create(
        id="NRG-CUST-MON-LEAK",
        name="Leak",
        phone="+919999999999",  # NOT on allow-list
        state="MH",
        city="Pune",
        consent_whatsapp=True,
    )
    convo = WhatsAppConversation.objects.create(
        id="WCV-MON-LEAK",
        connection=connection,
        customer=leaky_customer,
        status=WhatsAppConversation.Status.OPEN,
    )
    WhatsAppMessage.objects.create(
        id="WAM-MON-LEAK-1",
        conversation=convo,
        customer=leaky_customer,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        status=WhatsAppMessage.Status.SENT,
        type=WhatsAppMessage.Type.TEXT,
        body="leaked",
        provider_message_id="wamid.LEAK.1",
        queued_at=timezone.now(),
        sent_at=timezone.now(),
    )
    report = dashboard.get_unexpected_outbound_summary(hours=1)
    assert report["unexpectedSendsCount"] == 1
    assert report["rollbackRecommended"] is True
    blob = json.dumps(report)
    assert "+919999999999" not in blob
    assert "9999" in blob


@override_settings(**META_CREDS)
def test_get_whatsapp_monitoring_dashboard_combines_sections(
    connection, customer_allowed
) -> None:
    with _patch_waba():
        report = dashboard.get_whatsapp_monitoring_dashboard(hours=1)
    assert "gate" in report
    assert "activity" in report
    assert "cohort" in report
    assert "mutationSafety" in report
    assert "unexpectedOutbound" in report
    assert report["status"] == "safe_off"
    assert report["nextAction"]
    assert report["rollbackReady"] is True


@override_settings(
    **{**META_CREDS, "WHATSAPP_AI_AUTO_REPLY_ENABLED": True}
)
def test_dashboard_status_flips_to_limited_auto_reply_on(
    connection, customer_allowed
) -> None:
    with _patch_waba():
        report = dashboard.get_whatsapp_monitoring_dashboard(hours=1)
    assert report["status"] == "limited_auto_reply_on"


# ---------------------------------------------------------------------------
# Section B — API endpoint tests
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_overview_endpoint_returns_200_for_admin(
    admin_user, auth_client, connection, customer_allowed
) -> None:
    client = auth_client(admin_user)
    with _patch_waba():
        url = reverse("whatsapp-monitoring-overview")
        res = client.get(url)
    assert res.status_code == 200
    body = res.json()
    assert "gate" in body
    assert "activity" in body
    assert "status" in body


@override_settings(**META_CREDS)
def test_overview_endpoint_blocks_unauthenticated(
    auth_client, connection
) -> None:
    client = auth_client(None)
    url = reverse("whatsapp-monitoring-overview")
    res = client.get(url)
    assert res.status_code in (401, 403)


@override_settings(**META_CREDS)
def test_overview_endpoint_blocks_viewer(
    viewer_user, auth_client, connection
) -> None:
    client = auth_client(viewer_user)
    url = reverse("whatsapp-monitoring-overview")
    res = client.get(url)
    assert res.status_code in (401, 403)


@override_settings(**META_CREDS)
def test_overview_endpoint_blocks_operations(
    operations_user, auth_client, connection
) -> None:
    """Admin-only by design — operations is too broad for monitoring."""
    client = auth_client(operations_user)
    url = reverse("whatsapp-monitoring-overview")
    res = client.get(url)
    assert res.status_code in (401, 403)


@override_settings(**META_CREDS)
def test_gate_endpoint_masks_phones_and_secrets(
    admin_user, auth_client, connection
) -> None:
    client = auth_client(admin_user)
    with _patch_waba():
        url = reverse("whatsapp-monitoring-gate")
        res = client.get(url)
    assert res.status_code == 200
    body = res.json()
    blob = json.dumps(body)
    assert "+918949879990" not in blob
    assert "9990" in blob
    blob_lower = blob.lower()
    assert META_CREDS["META_WA_ACCESS_TOKEN"].lower() not in blob_lower
    assert META_CREDS["META_WA_VERIFY_TOKEN"].lower() not in blob_lower


@override_settings(**META_CREDS)
def test_activity_endpoint_returns_counts(
    admin_user, auth_client, connection, customer_allowed
) -> None:
    write_event(
        kind="whatsapp.ai.reply_auto_sent",
        text="auto reply",
        payload={"phone_suffix": "9990"},
    )
    client = auth_client(admin_user)
    url = reverse("whatsapp-monitoring-activity")
    res = client.get(url + "?hours=1")
    assert res.status_code == 200
    body = res.json()
    assert body["replyAutoSentCount"] >= 1
    assert body["unexpectedNonAllowedSendsCount"] == 0


@override_settings(**META_CREDS)
def test_cohort_endpoint_returns_masked_cohort(
    admin_user, auth_client, connection, customer_allowed
) -> None:
    client = auth_client(admin_user)
    with _patch_waba():
        url = reverse("whatsapp-monitoring-cohort")
        res = client.get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["allowedListSize"] == 1
    blob = json.dumps(body)
    assert "+918949879990" not in blob
    assert "9990" in blob


@override_settings(**META_CREDS)
def test_audit_endpoint_scrubs_secrets(
    admin_user, auth_client, connection
) -> None:
    write_event(
        kind="whatsapp.ai.reply_auto_sent",
        text="auto reply",
        payload={
            "phone_suffix": "9990",
            "token": "leak-token",
            "verify_token": "leak-verify",
            "app_secret": "leak-app-secret",
        },
    )
    client = auth_client(admin_user)
    url = reverse("whatsapp-monitoring-audit")
    res = client.get(url + "?hours=1&limit=10")
    assert res.status_code == 200
    body = res.json()
    blob = json.dumps(body).lower()
    assert "leak-token" not in blob
    assert "leak-verify" not in blob
    assert "leak-app-secret" not in blob


@override_settings(**META_CREDS)
def test_mutation_safety_endpoint_returns_clean(
    admin_user, auth_client, connection
) -> None:
    client = auth_client(admin_user)
    url = reverse("whatsapp-monitoring-mutation-safety")
    res = client.get(url + "?hours=1")
    assert res.status_code == 200
    body = res.json()
    assert body["totalMutations"] == 0
    assert body["allClean"] is True


@override_settings(**META_CREDS)
def test_unexpected_outbound_endpoint_returns_clean(
    admin_user, auth_client, connection
) -> None:
    client = auth_client(admin_user)
    url = reverse("whatsapp-monitoring-unexpected-outbound")
    res = client.get(url + "?hours=1")
    assert res.status_code == 200
    body = res.json()
    assert body["unexpectedSendsCount"] == 0
    assert body["rollbackRecommended"] is False


# ---------------------------------------------------------------------------
# Section C — Dashboard endpoints are read-only
# ---------------------------------------------------------------------------


@override_settings(**META_CREDS)
def test_dashboard_endpoints_reject_post(
    admin_user, auth_client, connection
) -> None:
    """Every monitoring endpoint must reject POST/PATCH/DELETE."""
    client = auth_client(admin_user)
    for name in (
        "whatsapp-monitoring-overview",
        "whatsapp-monitoring-gate",
        "whatsapp-monitoring-activity",
        "whatsapp-monitoring-cohort",
        "whatsapp-monitoring-audit",
        "whatsapp-monitoring-mutation-safety",
        "whatsapp-monitoring-unexpected-outbound",
    ):
        url = reverse(name)
        # POST is not implemented on these views — DRF returns 405.
        res = client.post(url, {})
        assert res.status_code == 405, f"{name} accepted POST: {res.status_code}"
