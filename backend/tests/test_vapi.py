"""Phase 2D tests — Vapi voice trigger + webhook receiver.

Mirrors the structure of ``test_razorpay.py`` / ``test_delhivery.py``:

1. Mock-mode trigger creates a Call row with provider=vapi.
2. Test-mode trigger routes through the SDK adapter (we patch
   ``_create_via_sdk`` so no real network call is made).
3. Auth: anonymous → 401, viewer → 403, operations → 201.
4. Lead lookup: missing lead → 404.
5. Webhook ``call.started`` flips Call to Live.
6. Webhook ``transcript.final`` persists transcript lines under the Call.
7. Webhook ``call.failed`` flips Call to Failed and writes danger AuditEvent.
8. Webhook ``analysis.completed`` records handoff_flags + danger AuditEvent.
9. Keyword fallback flags ``side_effect_complaint`` even when Vapi omits it.
10. Webhook duplicate event is idempotent.
11. Webhook with invalid signature returns 400 when secret is configured.
12. Signature verification helper round-trip.
13. Audit ledger captures call.triggered + call.completed + call.transcript.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.calls.integrations.vapi_client import CallResult
from apps.calls.models import Call, CallTranscriptLine, WebhookEvent
from apps.crm.models import Lead

WEBHOOK_SECRET = "test-vapi-secret"


# ---------- helpers ----------


def _make_lead(**overrides) -> Lead:
    defaults = dict(
        id="LD-VAPI-001",
        name="Vapi Demo",
        phone="+91 9000000111",
        state="Maharashtra",
        city="Pune",
        language="Hinglish",
        source="Meta Ads",
        campaign="Monsoon Detox '25",
        product_interest="Weight Management",
    )
    defaults.update(overrides)
    return Lead.objects.create(**defaults)


def _make_call(lead: Lead, **overrides) -> Call:
    defaults = dict(
        id="CL-VAPI-001",
        lead_id=lead.id,
        customer=lead.name,
        phone=lead.phone,
        agent="Calling AI · Vapi",
        language=lead.language,
        status=Call.Status.QUEUED,
        provider=Call.Provider.VAPI,
        provider_call_id="call_test_xyz",
    )
    defaults.update(overrides)
    return Call.objects.create(**defaults)


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _post_webhook(
    client: APIClient,
    event: dict,
    *,
    secret: str | None = None,
):
    body = json.dumps(event).encode("utf-8")
    headers: dict = {}
    if secret:
        headers["HTTP_X_VAPI_SIGNATURE"] = _sign(body, secret)
    return client.post(
        "/api/webhooks/vapi/",
        data=body,
        content_type="application/json",
        **headers,
    )


# ---------- 1. Mock mode ----------


def test_trigger_mock_creates_call_row(operations_user, auth_client, settings) -> None:
    settings.VAPI_MODE = "mock"
    lead = _make_lead()
    client = auth_client(operations_user)
    res = client.post(
        "/api/calls/trigger/",
        {"leadId": lead.id, "purpose": "sales_call"},
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["leadId"] == lead.id
    assert body["provider"] == "vapi"
    assert body["status"] == "queued"
    assert body["providerCallId"].startswith("call_mock_")
    assert body["callId"].startswith("CL-")
    call = Call.objects.get(pk=body["callId"])
    assert call.provider == Call.Provider.VAPI
    assert call.provider_call_id == body["providerCallId"]
    assert call.raw_response.get("mode") == "mock"


# ---------- 2. Test-mode adapter mocked ----------


def test_trigger_test_mode_uses_sdk(operations_user, auth_client, settings) -> None:
    settings.VAPI_MODE = "test"
    settings.VAPI_API_BASE_URL = "https://staging.vapi.ai"
    settings.VAPI_API_KEY = "key_xxx"
    settings.VAPI_ASSISTANT_ID = "assistant_xxx"
    settings.VAPI_PHONE_NUMBER_ID = "phone_xxx"
    lead = _make_lead(id="LD-VAPI-TEST")
    client = auth_client(operations_user)

    fake = CallResult(
        provider_call_id="call_staging_42",
        status="queued",
        raw={"id": "call_staging_42", "status": "queued"},
    )

    with patch(
        "apps.calls.integrations.vapi_client._create_via_sdk",
        return_value=fake,
    ) as mock_sdk:
        res = client.post(
            "/api/calls/trigger/",
            {"leadId": lead.id},
            format="json",
        )

    assert res.status_code == 201
    assert mock_sdk.called
    assert res.json()["providerCallId"] == "call_staging_42"


# ---------- 3. Auth + role gating ----------


def test_trigger_requires_authentication(settings) -> None:
    settings.VAPI_MODE = "mock"
    lead = _make_lead(id="LD-VAPI-AUTH")
    res = APIClient().post(
        "/api/calls/trigger/",
        {"leadId": lead.id},
        format="json",
    )
    assert res.status_code == 401


def test_viewer_cannot_trigger_call(viewer_user, auth_client, settings) -> None:
    settings.VAPI_MODE = "mock"
    lead = _make_lead(id="LD-VAPI-VIEW")
    client = auth_client(viewer_user)
    res = client.post(
        "/api/calls/trigger/",
        {"leadId": lead.id},
        format="json",
    )
    assert res.status_code == 403


# ---------- 4. Missing lead ----------


def test_trigger_missing_lead_returns_404(operations_user, auth_client, settings) -> None:
    settings.VAPI_MODE = "mock"
    client = auth_client(operations_user)
    res = client.post(
        "/api/calls/trigger/",
        {"leadId": "LD-DOES-NOT-EXIST"},
        format="json",
    )
    assert res.status_code == 404


# ---------- 5. Webhook: call.started ----------


def test_webhook_call_started_flips_status(settings) -> None:
    settings.VAPI_MODE = "mock"
    lead = _make_lead(id="LD-VAPI-START")
    call = _make_call(lead, id="CL-VAPI-START", provider_call_id="call_start_demo")
    event = {
        "id": "evt_start_demo",
        "type": "call.started",
        "call": {"id": "call_start_demo"},
    }
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    call.refresh_from_db()
    assert call.status == Call.Status.LIVE
    assert WebhookEvent.objects.filter(event_id="evt_start_demo").exists()


# ---------- 6. Webhook: transcript.final ----------


def test_webhook_transcript_final_persists_lines(settings) -> None:
    settings.VAPI_MODE = "mock"
    lead = _make_lead(id="LD-VAPI-TXT")
    call = _make_call(lead, id="CL-VAPI-TXT", provider_call_id="call_txt_demo")
    event = {
        "id": "evt_txt_demo",
        "type": "transcript.final",
        "call": {"id": "call_txt_demo"},
        "transcript": [
            {"who": "AI", "text": "Namaste, main Vaani bol rahi hoon."},
            {"who": "Customer", "text": "Haan bolo."},
            {"who": "AI", "text": "Aap ne weight management ke liye enquiry ki thi?"},
        ],
    }
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    lines = list(CallTranscriptLine.objects.filter(call=call).order_by("order"))
    assert len(lines) == 3
    assert lines[0].who == "AI"
    assert lines[1].text == "Haan bolo."


# ---------- 7. Webhook: call.failed ----------


def test_webhook_call_failed_writes_danger_audit(settings) -> None:
    settings.VAPI_MODE = "mock"
    lead = _make_lead(id="LD-VAPI-FAIL")
    call = _make_call(lead, id="CL-VAPI-FAIL", provider_call_id="call_fail_demo")
    AuditEvent.objects.all().delete()
    event = {
        "id": "evt_fail_demo",
        "type": "call.failed",
        "call": {"id": "call_fail_demo"},
        "error": "Customer hung up before connect",
    }
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    call.refresh_from_db()
    assert call.status == Call.Status.FAILED
    assert call.error_message == "Customer hung up before connect"
    failed_audit = AuditEvent.objects.filter(kind="call.failed").first()
    assert failed_audit is not None
    assert failed_audit.tone == AuditEvent.Tone.DANGER


# ---------- 8. Webhook: analysis flags handoff ----------


def test_webhook_analysis_records_handoff_flags(settings) -> None:
    settings.VAPI_MODE = "mock"
    lead = _make_lead(id="LD-VAPI-FLAG")
    call = _make_call(lead, id="CL-VAPI-FLAG", provider_call_id="call_flag_demo")
    event = {
        "id": "evt_flag_demo",
        "type": "analysis.completed",
        "call": {"id": "call_flag_demo"},
        "summary": "Customer requested human after pricing discussion.",
        "handoff_flags": ["human_requested", "low_confidence"],
    }
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    call.refresh_from_db()
    assert "human_requested" in call.handoff_flags
    assert "low_confidence" in call.handoff_flags
    assert "Customer requested human" in call.summary
    audit = AuditEvent.objects.filter(kind="call.handoff_flagged").first()
    assert audit is not None


# ---------- 9. Keyword fallback for handoff ----------


def test_keyword_fallback_flags_side_effect(settings) -> None:
    settings.VAPI_MODE = "mock"
    lead = _make_lead(id="LD-VAPI-KW")
    call = _make_call(lead, id="CL-VAPI-KW", provider_call_id="call_kw_demo")
    # Seed transcript with a side-effect phrase, then run analysis without
    # explicit flags — the keyword fallback should still catch it.
    CallTranscriptLine.objects.create(
        call=call, order=0, who="Customer", text="I had a bad rash and vomiting after taking it."
    )
    event = {
        "id": "evt_kw_demo",
        "type": "analysis.completed",
        "call": {"id": "call_kw_demo"},
        "summary": "Post-purchase side-effect complaint.",
    }
    res = _post_webhook(APIClient(), event)
    assert res.status_code == 200
    call.refresh_from_db()
    assert "side_effect_complaint" in call.handoff_flags


# ---------- 10. Webhook duplicate idempotent ----------


def test_webhook_duplicate_event_idempotent(settings) -> None:
    settings.VAPI_MODE = "mock"
    lead = _make_lead(id="LD-VAPI-DUP")
    call = _make_call(lead, id="CL-VAPI-DUP", provider_call_id="call_dup_demo")
    event = {
        "id": "evt_dup_demo",
        "type": "call.started",
        "call": {"id": "call_dup_demo"},
    }
    client = APIClient()
    first = _post_webhook(client, event)
    second = _post_webhook(client, event)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["detail"] == "duplicate"
    assert WebhookEvent.objects.filter(event_id="evt_dup_demo").count() == 1


# ---------- 11. Invalid signature when secret configured ----------


def test_webhook_invalid_signature_returns_400(settings) -> None:
    settings.VAPI_MODE = "mock"
    settings.VAPI_WEBHOOK_SECRET = WEBHOOK_SECRET
    event = {
        "id": "evt_bad_sig",
        "type": "call.started",
        "call": {"id": "call_anything"},
    }
    body = json.dumps(event).encode("utf-8")
    res = APIClient().post(
        "/api/webhooks/vapi/",
        data=body,
        content_type="application/json",
        HTTP_X_VAPI_SIGNATURE="deadbeef",
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "invalid signature"
    assert not WebhookEvent.objects.exists()


def test_webhook_skips_signature_when_secret_empty(settings) -> None:
    """No secret configured → signature header is not required (dev default)."""
    settings.VAPI_MODE = "mock"
    settings.VAPI_WEBHOOK_SECRET = ""
    lead = _make_lead(id="LD-VAPI-NOSIG")
    _make_call(lead, id="CL-VAPI-NOSIG", provider_call_id="call_nosig_demo")
    event = {
        "id": "evt_nosig_demo",
        "type": "call.started",
        "call": {"id": "call_nosig_demo"},
    }
    body = json.dumps(event).encode("utf-8")
    res = APIClient().post(
        "/api/webhooks/vapi/",
        data=body,
        content_type="application/json",
    )
    assert res.status_code == 200


# ---------- 12. Signature helper unit test ----------


def test_signature_helper_round_trip() -> None:
    from apps.calls.integrations.vapi_client import verify_webhook_signature

    body = b'{"type":"call.started"}'
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig, secret="secret") is True
    assert verify_webhook_signature(body, sig, secret="wrong") is False
    assert verify_webhook_signature(body, "", secret="secret") is False
    assert verify_webhook_signature(body, sig, secret="") is False


# ---------- 13. Audit ledger captures full flow ----------


def test_audit_ledger_captures_trigger_and_completion(
    operations_user, auth_client, settings
) -> None:
    settings.VAPI_MODE = "mock"
    settings.VAPI_WEBHOOK_SECRET = ""  # let the webhook through unsigned for this test
    lead = _make_lead(id="LD-VAPI-AUD")
    client = auth_client(operations_user)
    AuditEvent.objects.all().delete()

    trigger_res = client.post(
        "/api/calls/trigger/",
        {"leadId": lead.id, "purpose": "sales_call"},
        format="json",
    )
    assert trigger_res.status_code == 201
    provider_id = trigger_res.json()["providerCallId"]

    transcript_event = {
        "id": "evt_aud_txt",
        "type": "transcript.final",
        "call": {"id": provider_id},
        "transcript": [
            {"who": "AI", "text": "Namaste."},
            {"who": "Customer", "text": "Haan."},
        ],
    }
    end_event = {
        "id": "evt_aud_end",
        "type": "call.ended",
        "call": {"id": provider_id},
        "duration": 245,
    }
    assert _post_webhook(APIClient(), transcript_event).status_code == 200
    assert _post_webhook(APIClient(), end_event).status_code == 200

    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "call.triggered" in kinds
    assert "call.transcript" in kinds
    assert "call.completed" in kinds


# ---------- 14. Vapi adapter mock unit test ----------


def test_client_mock_mode_returns_deterministic_call_id(settings) -> None:
    settings.VAPI_MODE = "mock"
    from apps.calls.integrations import vapi_client

    a = vapi_client.trigger_call(
        lead_id="LD-12345",
        customer_phone="+91 9000000000",
        customer_name="A",
        purpose="sales_call",
    )
    b = vapi_client.trigger_call(
        lead_id="LD-12345",
        customer_phone="+91 9000000000",
        customer_name="A",
        purpose="sales_call",
    )
    assert a.provider_call_id == b.provider_call_id == "call_mock_LD_12345_sales_call"
    assert a.status == "queued"
