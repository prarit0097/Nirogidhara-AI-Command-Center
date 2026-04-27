"""Phase 2E tests — Meta Lead Ads webhook (verification + delivery).

Mirrors the structure of ``test_razorpay.py`` / ``test_delhivery.py`` /
``test_vapi.py``:

1. GET verification challenge succeeds with the correct token.
2. GET verification fails with a wrong token.
3. GET verification fails when token is empty (env not configured).
4. POST mock webhook creates a Lead with Meta provenance fields.
5. POST mock webhook is idempotent on leadgen_id.
6. POST signature verification rejects bad signatures when secret is set.
7. POST without signature is allowed when no secret is configured.
8. AuditEvent ``lead.meta_ingested`` is written for new leads.
9. Test-mode adapter routes through ``_fetch_lead_via_graph`` (patched).
10. Existing leads with the same leadgen_id are refreshed, not duplicated.
11. Signature helper round-trip.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.crm.models import Lead, MetaLeadEvent

VERIFY_TOKEN = "phase2e-verify-token"
WEBHOOK_SECRET = "phase2e-webhook-secret"


# ---------- helpers ----------


def _meta_payload(*, leadgen_id: str, **overrides) -> dict:
    """Build a realistic Meta webhook payload (one entry, one change)."""
    field_data = overrides.pop(
        "field_data",
        [
            {"name": "full_name", "values": ["Suresh Patel"]},
            {"name": "phone_number", "values": ["+91 9000000777"]},
            {"name": "city", "values": ["Pune"]},
            {"name": "state", "values": ["Maharashtra"]},
            {"name": "product_interest", "values": ["Weight Management"]},
            {"name": "language", "values": ["Hinglish"]},
        ],
    )
    value: dict = {
        "leadgen_id": leadgen_id,
        "page_id": overrides.pop("page_id", "page_42"),
        "form_id": overrides.pop("form_id", "form_99"),
        "ad_id": overrides.pop("ad_id", "ad_1234"),
        "campaign_id": overrides.pop("campaign_id", "camp_777"),
        "field_data": field_data,
    }
    value.update(overrides)
    return {
        "object": "page",
        "entry": [
            {
                "id": value["page_id"],
                "time": 1714200000,
                "changes": [{"field": "leadgen", "value": value}],
            }
        ],
    }


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _post(client: APIClient, payload: dict, *, secret: str | None = None):
    body = json.dumps(payload).encode("utf-8")
    headers: dict = {}
    if secret:
        headers["HTTP_X_HUB_SIGNATURE_256"] = _sign(body, secret)
    return client.post(
        "/api/webhooks/meta/leads/",
        data=body,
        content_type="application/json",
        **headers,
    )


# ---------- 1-3. GET verification handshake ----------


def test_get_verify_succeeds_with_correct_token(settings) -> None:
    settings.META_VERIFY_TOKEN = VERIFY_TOKEN
    res = APIClient().get(
        "/api/webhooks/meta/leads/",
        {
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "challenge_42",
        },
    )
    assert res.status_code == 200
    assert res.data == "challenge_42"


def test_get_verify_fails_with_wrong_token(settings) -> None:
    settings.META_VERIFY_TOKEN = VERIFY_TOKEN
    res = APIClient().get(
        "/api/webhooks/meta/leads/",
        {
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge_42",
        },
    )
    assert res.status_code == 403


def test_get_verify_fails_when_token_unset(settings) -> None:
    settings.META_VERIFY_TOKEN = ""
    res = APIClient().get(
        "/api/webhooks/meta/leads/",
        {
            "hub.mode": "subscribe",
            "hub.verify_token": "anything",
            "hub.challenge": "challenge_42",
        },
    )
    assert res.status_code == 403


# ---------- 4. POST mock webhook creates Lead ----------


def test_post_mock_creates_lead(settings) -> None:
    settings.META_MODE = "mock"
    settings.META_WEBHOOK_SECRET = ""
    settings.META_APP_SECRET = ""
    payload = _meta_payload(leadgen_id="meta_lead_001")
    res = _post(APIClient(), payload)
    assert res.status_code == 200
    body = res.json()
    assert body["ingested"] == 1
    assert body["leads"][0]["leadgenId"] == "meta_lead_001"
    assert body["leads"][0]["action"] == "created"

    lead = Lead.objects.get(meta_leadgen_id="meta_lead_001")
    assert lead.name == "Suresh Patel"
    assert lead.phone == "+91 9000000777"
    assert lead.city == "Pune"
    assert lead.state == "Maharashtra"
    assert lead.product_interest == "Weight Management"
    assert lead.source == "Meta Ads"
    assert lead.meta_page_id == "page_42"
    assert lead.meta_form_id == "form_99"
    assert lead.meta_ad_id == "ad_1234"
    assert lead.meta_campaign_id == "camp_777"
    # Idempotency row written.
    assert MetaLeadEvent.objects.filter(leadgen_id="meta_lead_001").exists()


# ---------- 5. POST is idempotent on leadgen_id ----------


def test_post_duplicate_leadgen_is_idempotent(settings) -> None:
    settings.META_MODE = "mock"
    settings.META_WEBHOOK_SECRET = ""
    settings.META_APP_SECRET = ""
    payload = _meta_payload(leadgen_id="meta_lead_dup")
    client = APIClient()
    first = _post(client, payload)
    second = _post(client, payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["leads"][0]["action"] == "duplicate"
    assert Lead.objects.filter(meta_leadgen_id="meta_lead_dup").count() == 1
    assert MetaLeadEvent.objects.filter(leadgen_id="meta_lead_dup").count() == 1


# ---------- 6. Bad signature rejected when secret set ----------


def test_post_rejects_bad_signature(settings) -> None:
    settings.META_MODE = "mock"
    settings.META_WEBHOOK_SECRET = WEBHOOK_SECRET
    payload = _meta_payload(leadgen_id="meta_lead_badsig")
    body = json.dumps(payload).encode("utf-8")
    res = APIClient().post(
        "/api/webhooks/meta/leads/",
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=deadbeef",
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "invalid signature"
    assert not Lead.objects.filter(meta_leadgen_id="meta_lead_badsig").exists()
    assert not MetaLeadEvent.objects.exists()


def test_post_accepts_correct_signature(settings) -> None:
    settings.META_MODE = "mock"
    settings.META_WEBHOOK_SECRET = WEBHOOK_SECRET
    payload = _meta_payload(leadgen_id="meta_lead_sig_ok")
    res = _post(APIClient(), payload, secret=WEBHOOK_SECRET)
    assert res.status_code == 200
    assert Lead.objects.filter(meta_leadgen_id="meta_lead_sig_ok").exists()


def test_post_falls_back_to_app_secret(settings) -> None:
    """When META_WEBHOOK_SECRET is empty, META_APP_SECRET signs the body."""
    settings.META_MODE = "mock"
    settings.META_WEBHOOK_SECRET = ""
    settings.META_APP_SECRET = "fallback-app-secret"
    payload = _meta_payload(leadgen_id="meta_lead_app_secret")
    res = _post(APIClient(), payload, secret="fallback-app-secret")
    assert res.status_code == 200
    assert Lead.objects.filter(meta_leadgen_id="meta_lead_app_secret").exists()


# ---------- 7. No signature allowed when secret is empty ----------


def test_post_no_signature_when_secret_empty(settings) -> None:
    settings.META_MODE = "mock"
    settings.META_WEBHOOK_SECRET = ""
    settings.META_APP_SECRET = ""
    payload = _meta_payload(leadgen_id="meta_lead_nosig")
    res = APIClient().post(
        "/api/webhooks/meta/leads/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert res.status_code == 200
    assert Lead.objects.filter(meta_leadgen_id="meta_lead_nosig").exists()


# ---------- 8. Audit event written ----------


def test_audit_event_written_for_meta_ingest(settings) -> None:
    settings.META_MODE = "mock"
    settings.META_WEBHOOK_SECRET = ""
    settings.META_APP_SECRET = ""
    AuditEvent.objects.all().delete()
    payload = _meta_payload(leadgen_id="meta_lead_audit")
    res = _post(APIClient(), payload)
    assert res.status_code == 200
    audit = AuditEvent.objects.filter(kind="lead.meta_ingested").first()
    assert audit is not None
    assert "Meta Ads" in audit.text
    assert audit.payload["leadgen_id"] == "meta_lead_audit"


# ---------- 9. Test-mode adapter expansion ----------


def test_test_mode_routes_through_graph_api(settings) -> None:
    settings.META_MODE = "test"
    settings.META_WEBHOOK_SECRET = ""
    settings.META_APP_SECRET = ""
    settings.META_PAGE_ACCESS_TOKEN = "page_access_xxx"
    payload = _meta_payload(leadgen_id="meta_lead_graph")

    fake_graph_response = {
        "id": "meta_lead_graph",
        "field_data": [
            {"name": "full_name", "values": ["From Graph API"]},
            {"name": "phone_number", "values": ["+91 9111111111"]},
            {"name": "city", "values": ["Mumbai"]},
            {"name": "state", "values": ["Maharashtra"]},
            {"name": "product_interest", "values": ["Immunity Booster"]},
        ],
    }

    with patch(
        "apps.crm.integrations.meta_client._fetch_lead_via_graph",
        return_value=fake_graph_response,
    ) as mock_graph:
        res = _post(APIClient(), payload)

    assert res.status_code == 200
    assert mock_graph.called
    lead = Lead.objects.get(meta_leadgen_id="meta_lead_graph")
    # Graph data wins over webhook field_data.
    assert lead.name == "From Graph API"
    assert lead.product_interest == "Immunity Booster"
    assert lead.phone == "+91 9111111111"


# ---------- 10. Re-delivery refreshes existing lead, no duplicate ----------


def test_existing_meta_lead_is_refreshed_not_duplicated(settings) -> None:
    settings.META_MODE = "mock"
    settings.META_WEBHOOK_SECRET = ""
    settings.META_APP_SECRET = ""
    # Pre-existing lead from a prior delivery (idempotency table cleared).
    Lead.objects.create(
        id="LD-META-PRE",
        name="Old Name",
        phone="+91 9000000000",
        state="Maharashtra",
        city="Pune",
        language="Hinglish",
        source="Meta Ads",
        campaign="",
        product_interest="Weight Management",
        meta_leadgen_id="meta_lead_refresh",
    )
    payload = _meta_payload(leadgen_id="meta_lead_refresh", page_id="page_new")
    res = _post(APIClient(), payload)
    assert res.status_code == 200
    assert res.json()["leads"][0]["action"] == "updated"
    assert Lead.objects.filter(meta_leadgen_id="meta_lead_refresh").count() == 1
    refreshed = Lead.objects.get(meta_leadgen_id="meta_lead_refresh")
    assert refreshed.meta_page_id == "page_new"
    # Existing name field gets refreshed by webhook payload.
    assert refreshed.name == "Suresh Patel"


# ---------- 11. Signature helper unit test ----------


def test_signature_helper_round_trip() -> None:
    from apps.crm.integrations.meta_client import verify_webhook_signature

    body = b'{"object":"page"}'
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    sig = f"sha256={digest}"
    assert verify_webhook_signature(body, sig, secret="secret") is True
    # Hex-only form (no sha256= prefix) also accepted.
    assert verify_webhook_signature(body, digest, secret="secret") is True
    assert verify_webhook_signature(body, sig, secret="wrong") is False
    assert verify_webhook_signature(body, "", secret="secret") is False
    assert verify_webhook_signature(body, sig, secret="") is False


# ---------- 12. Empty payload returns 200 / no leads ----------


def test_post_empty_payload_returns_no_leads(settings) -> None:
    settings.META_MODE = "mock"
    settings.META_WEBHOOK_SECRET = ""
    settings.META_APP_SECRET = ""
    res = APIClient().post(
        "/api/webhooks/meta/leads/",
        data=b"{}",
        content_type="application/json",
    )
    assert res.status_code == 200
    assert res.json()["ingested"] == 0
