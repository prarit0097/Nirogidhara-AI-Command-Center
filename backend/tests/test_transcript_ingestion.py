"""Phase 11A — Transcript Ingestion Pipeline V1 tests.

Defensive contract: across every test path that triggers the
ingestion service or its CLI / Celery wrappers, all outbound
entrypoints (`queue_template_message`, `send_freeform_text_message`,
`trigger_call_for_lead`, `create_shipment`) are patched and asserted
NOT called. Customer / Order / Payment / Shipment / Lead row counts
stay constant. The only mutations Phase 11A ever performs are
`CallTranscriptLine` row creation and `Call.transcript_*` field
updates.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.calls.models import Call, CallTranscriptLine


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_call(
    *,
    call_id: str,
    provider_call_id: str = "vapi_call_test_123",
    created_offset_hours: int = 48,
    transcript_ingested_at=None,
    transcript_line_count: int = 0,
) -> Call:
    call = Call.objects.create(
        id=call_id,
        lead_id=f"LD-{call_id}",
        customer="Test Customer",
        phone="+919999990000",
        agent="Calling AI · Vapi",
        language="Hindi",
        provider=Call.Provider.VAPI,
        provider_call_id=provider_call_id,
        status=Call.Status.COMPLETED,
        transcript_ingested_at=transcript_ingested_at,
        transcript_line_count=transcript_line_count,
    )
    # ``created_at`` is auto_now_add — override it after create.
    Call.objects.filter(pk=call.pk).update(
        created_at=timezone.now() - timedelta(hours=created_offset_hours)
    )
    call.refresh_from_db()
    return call


def _vapi_response(*utterances: tuple[str, str]) -> dict:
    """Build a Vapi-shaped response body from (role, message) pairs."""
    return {
        "id": "vapi_call_test_123",
        "status": "ended",
        "messages": [
            {"role": role, "message": message}
            for role, message in utterances
        ],
    }


@pytest.fixture
def patched_outbound():
    """Defensive contract — patch every outbound entrypoint."""
    with (
        mock.patch(
            "apps.whatsapp.services.queue_template_message"
        ) as wa_queue,
        mock.patch(
            "apps.whatsapp.services.send_freeform_text_message"
        ) as wa_freeform,
        mock.patch(
            "apps.calls.services.trigger_call_for_lead"
        ) as call_trigger,
        mock.patch(
            "apps.shipments.services.create_shipment"
        ) as ship_create,
    ):
        yield {
            "wa_queue": wa_queue,
            "wa_freeform": wa_freeform,
            "call_trigger": call_trigger,
            "ship_create": ship_create,
        }


# ---------------------------------------------------------------------------
# fetch_vapi_transcript
# ---------------------------------------------------------------------------


@override_settings(VAPI_API_KEY="rzp_test_dummy_key", VAPI_API_BASE_URL="https://api.vapi.example")
def test_fetch_vapi_transcript_happy_returns_normalized_utterances():
    from apps.calls.transcript_ingestion import fetch_vapi_transcript

    body = _vapi_response(
        ("assistant", "Namaste, Nirogidhara se baat kar rahe hain."),
        ("user", "Haan ji, batayein."),
        ("assistant", "Order confirm kar lein?"),
    )
    response = mock.MagicMock(status_code=200)
    response.json.return_value = body
    with mock.patch("requests.get", return_value=response) as get:
        utterances = fetch_vapi_transcript("vapi_call_test_123")
    assert get.called
    assert isinstance(utterances, list)
    assert len(utterances) == 3
    assert utterances[0]["who"] == "assistant"
    assert "Nirogidhara" in utterances[0]["text"]
    assert utterances[0]["order"] == 0
    assert utterances[2]["order"] == 2


@override_settings(VAPI_API_KEY="rzp_test_dummy_key")
def test_fetch_vapi_transcript_404_returns_none():
    from apps.calls.transcript_ingestion import fetch_vapi_transcript

    response = mock.MagicMock(status_code=404)
    with mock.patch("requests.get", return_value=response):
        assert fetch_vapi_transcript("vapi_404") is None


@override_settings(VAPI_API_KEY="rzp_test_dummy_key")
def test_fetch_vapi_transcript_network_error_returns_none():
    from apps.calls.transcript_ingestion import fetch_vapi_transcript

    with mock.patch(
        "requests.get",
        side_effect=Exception("network down"),
    ):
        assert fetch_vapi_transcript("vapi_oops") is None


@override_settings(VAPI_API_KEY="")
def test_fetch_vapi_transcript_missing_api_key_returns_none(patched_outbound):
    from apps.calls.transcript_ingestion import fetch_vapi_transcript

    with mock.patch("requests.get") as get:
        assert fetch_vapi_transcript("vapi_any") is None
    get.assert_not_called()


def test_fetch_vapi_transcript_empty_id_returns_none():
    from apps.calls.transcript_ingestion import fetch_vapi_transcript

    assert fetch_vapi_transcript("") is None
    assert fetch_vapi_transcript("   ") is None


@override_settings(VAPI_API_KEY="dummy")
def test_fetch_vapi_transcript_legacy_string_transcript_shape():
    from apps.calls.transcript_ingestion import fetch_vapi_transcript

    response = mock.MagicMock(status_code=200)
    response.json.return_value = {
        "id": "x",
        "transcript": "User: hi. Agent: hello.",
    }
    with mock.patch("requests.get", return_value=response):
        utterances = fetch_vapi_transcript("legacy")
    assert utterances and utterances[0]["text"].startswith("User:")


# ---------------------------------------------------------------------------
# ingest_call_transcript
# ---------------------------------------------------------------------------


@override_settings(VAPI_API_KEY="dummy")
def test_ingest_call_transcript_happy_path_creates_lines_and_audit(patched_outbound):
    from apps.calls.transcript_ingestion import ingest_call_transcript

    call = _make_call(call_id="CL-9001")
    response = mock.MagicMock(status_code=200)
    response.json.return_value = _vapi_response(
        ("assistant", "Line one."),
        ("user", "Line two."),
    )
    pre_audit = AuditEvent.objects.count()
    with mock.patch("requests.get", return_value=response):
        result = ingest_call_transcript("CL-9001")
    assert result == {
        **result,
        "ok": True,
        "skipped": False,
        "call_id": "CL-9001",
        "line_count": 2,
    }
    assert CallTranscriptLine.objects.filter(call=call).count() == 2
    call.refresh_from_db()
    assert call.transcript_ingested_at is not None
    assert call.transcript_line_count == 2
    # Audit row written, with vapi_call_id last-4 only (no full id).
    audit_rows = AuditEvent.objects.filter(kind="transcript.ingested")
    assert audit_rows.count() == pre_audit + 1 - pre_audit  # exactly 1 new
    payload = audit_rows.first().payload
    assert payload["call_id"] == "CL-9001"
    assert payload["line_count"] == 2
    assert payload["vapi_call_id_last4"] == "_123"
    # Full provider_call_id never appears in the payload.
    assert "vapi_call_test_123" not in str(payload)
    # Defensive contract — no outbound.
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


def test_ingest_call_transcript_no_vapi_id_returns_skipped(patched_outbound):
    from apps.calls.transcript_ingestion import ingest_call_transcript

    _make_call(call_id="CL-9002", provider_call_id="")
    with mock.patch("requests.get") as get:
        result = ingest_call_transcript("CL-9002")
    assert result["skipped"] is True
    assert result["reason"] == "no_vapi_id"
    get.assert_not_called()
    assert CallTranscriptLine.objects.count() == 0


@override_settings(VAPI_API_KEY="dummy")
def test_ingest_call_transcript_already_ingested_skips(patched_outbound):
    from apps.calls.transcript_ingestion import ingest_call_transcript

    _make_call(
        call_id="CL-9003",
        transcript_ingested_at=timezone.now(),
        transcript_line_count=3,
    )
    with mock.patch("requests.get") as get:
        result = ingest_call_transcript("CL-9003")
    assert result["skipped"] is True
    assert result["reason"] == "already_ingested"
    assert result["line_count"] == 3
    get.assert_not_called()


@override_settings(VAPI_API_KEY="dummy")
def test_ingest_call_transcript_vapi_returns_none_skips(patched_outbound):
    from apps.calls.transcript_ingestion import ingest_call_transcript

    _make_call(call_id="CL-9004")
    with mock.patch(
        "apps.calls.transcript_ingestion.fetch_vapi_transcript",
        return_value=None,
    ):
        result = ingest_call_transcript("CL-9004")
    assert result["skipped"] is True
    assert result["reason"] == "no_transcript_from_vapi"
    assert CallTranscriptLine.objects.count() == 0


@override_settings(VAPI_API_KEY="dummy")
def test_ingest_call_transcript_dry_run_creates_nothing(patched_outbound):
    from apps.calls.transcript_ingestion import ingest_call_transcript

    _make_call(call_id="CL-9005")
    response = mock.MagicMock(status_code=200)
    response.json.return_value = _vapi_response(("user", "X"), ("agent", "Y"))
    pre_audit = AuditEvent.objects.filter(kind="transcript.ingested").count()
    with mock.patch("requests.get", return_value=response):
        result = ingest_call_transcript("CL-9005", dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["line_count"] == 2
    assert CallTranscriptLine.objects.count() == 0
    assert (
        AuditEvent.objects.filter(kind="transcript.ingested").count()
        == pre_audit
    )


@override_settings(VAPI_API_KEY="dummy")
def test_ingest_call_transcript_db_error_rolls_back(patched_outbound):
    from apps.calls.transcript_ingestion import ingest_call_transcript

    _make_call(call_id="CL-9006")
    response = mock.MagicMock(status_code=200)
    response.json.return_value = _vapi_response(("user", "X"))
    with (
        mock.patch("requests.get", return_value=response),
        mock.patch.object(
            CallTranscriptLine.objects,
            "bulk_create",
            side_effect=RuntimeError("DB blew up"),
        ),
    ):
        result = ingest_call_transcript("CL-9006")
    assert result["ok"] is False
    assert result["reason"] == "ingest_error"
    # Atomic block rolled back — no transcript lines, no field update.
    assert CallTranscriptLine.objects.count() == 0
    call = Call.objects.get(pk="CL-9006")
    assert call.transcript_ingested_at is None
    assert call.transcript_line_count == 0


def test_ingest_call_transcript_missing_call_returns_skipped(patched_outbound):
    from apps.calls.transcript_ingestion import ingest_call_transcript

    result = ingest_call_transcript("CL-DOES-NOT-EXIST")
    assert result["skipped"] is True
    assert result["reason"] == "call_not_found"


# ---------------------------------------------------------------------------
# get_transcript_backlog
# ---------------------------------------------------------------------------


def test_backlog_excludes_calls_under_24h(patched_outbound):
    from apps.calls.transcript_ingestion import get_transcript_backlog

    # Eligible: 48h old, no transcript, has provider id.
    _make_call(call_id="CL-9010", created_offset_hours=48)
    # Excluded: 1h old.
    _make_call(call_id="CL-9011", created_offset_hours=1)
    # Excluded: 48h old but already ingested.
    _make_call(
        call_id="CL-9012",
        created_offset_hours=48,
        transcript_ingested_at=timezone.now(),
        transcript_line_count=5,
    )
    # Excluded: 48h old but no provider_call_id.
    _make_call(call_id="CL-9013", created_offset_hours=48, provider_call_id="")
    # Excluded: way too old (45 days).
    _make_call(call_id="CL-9014", created_offset_hours=24 * 45)
    backlog_ids = list(
        get_transcript_backlog().values_list("id", flat=True)
    )
    assert backlog_ids == ["CL-9010"]


# ---------------------------------------------------------------------------
# ingest_backlog
# ---------------------------------------------------------------------------


@override_settings(VAPI_API_KEY="dummy")
def test_ingest_backlog_summary_counts_all_outcomes(patched_outbound):
    from apps.calls.transcript_ingestion import ingest_backlog

    _make_call(call_id="CL-9020", provider_call_id="VAPI-AAA1")
    _make_call(call_id="CL-9021", provider_call_id="VAPI-BBB2")

    response_ok = mock.MagicMock(status_code=200)
    response_ok.json.return_value = _vapi_response(("user", "X"))
    response_404 = mock.MagicMock(status_code=404)

    def _route(url, headers=None, timeout=None):
        if "AAA1" in url:
            return response_ok
        return response_404

    with mock.patch("requests.get", side_effect=_route):
        summary = ingest_backlog(limit=10)
    assert summary["total"] == 2
    assert summary["ingested"] == 1
    assert summary["skipped_no_transcript"] == 1
    assert summary["errors"] == 0
    # Outbound stays silent.
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


@override_settings(VAPI_API_KEY="dummy")
def test_ingest_backlog_sandbox_short_circuits(patched_outbound):
    from apps.calls.transcript_ingestion import ingest_backlog

    _make_call(call_id="CL-9030")
    with mock.patch("requests.get") as get:
        summary = ingest_backlog(limit=10, sandbox=True)
    assert summary["total"] == 0
    assert summary["skipped_reason"] == "sandbox_mode"
    get.assert_not_called()


# ---------------------------------------------------------------------------
# Celery task — ingest_transcript_backlog_daily
# ---------------------------------------------------------------------------


@override_settings(VAPI_API_KEY="dummy")
def test_celery_happy_path(patched_outbound):
    from apps.calls.tasks import ingest_transcript_backlog_daily

    _make_call(call_id="CL-9100", provider_call_id="VAPI-OK01")
    response = mock.MagicMock(status_code=200)
    response.json.return_value = _vapi_response(("user", "Hello"))
    with mock.patch("requests.get", return_value=response):
        summary = ingest_transcript_backlog_daily(limit=5)
    assert summary["total"] == 1
    assert summary["ingested"] == 1
    assert AuditEvent.objects.filter(
        kind="transcript.daily_ingest.completed"
    ).exists()


def test_celery_blocked_when_vapi_key_missing(patched_outbound):
    from apps.calls.tasks import ingest_transcript_backlog_daily

    _make_call(call_id="CL-9101")
    with override_settings(VAPI_API_KEY=""):
        result = ingest_transcript_backlog_daily(limit=5)
    assert result["skipped"] is True
    assert result["reason"] == "vapi_api_key_missing"
    assert AuditEvent.objects.filter(
        kind="transcript.daily_ingest.blocked"
    ).exists()


@override_settings(VAPI_API_KEY="dummy")
def test_celery_blocked_by_kill_switch(patched_outbound):
    from apps.calls.tasks import ingest_transcript_backlog_daily

    _make_call(call_id="CL-9102")
    with mock.patch(
        "apps.calls.tasks._kill_switch_blocked",
        return_value=True,
    ):
        result = ingest_transcript_backlog_daily(limit=5)
    assert result["skipped"] is True
    assert result["reason"] == "kill_switch_off"
    # Audit blocked row written.
    rows = AuditEvent.objects.filter(kind="transcript.daily_ingest.blocked")
    assert any(r.payload.get("reason") == "kill_switch_off" for r in rows)


@override_settings(VAPI_API_KEY="dummy")
def test_celery_blocked_by_sandbox(patched_outbound):
    from apps.calls.tasks import ingest_transcript_backlog_daily

    _make_call(call_id="CL-9103")
    with mock.patch(
        "apps.calls.tasks._sandbox_active",
        return_value=True,
    ):
        result = ingest_transcript_backlog_daily(limit=5)
    assert result["skipped"] is True
    assert result["reason"] == "sandbox_mode"


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@override_settings(VAPI_API_KEY="dummy")
def test_cli_ingest_call_transcripts_dry_run_makes_no_db_changes(patched_outbound):
    _make_call(call_id="CL-9200", provider_call_id="VAPI-D1")
    response = mock.MagicMock(status_code=200)
    response.json.return_value = _vapi_response(("user", "Y"))
    with mock.patch("requests.get", return_value=response):
        out = StringIO()
        call_command(
            "ingest_call_transcripts", "--dry-run", "--limit", "5", stdout=out
        )
    assert CallTranscriptLine.objects.count() == 0
    assert "Phase 11A" in out.getvalue()


@override_settings(VAPI_API_KEY="dummy")
def test_cli_ingest_call_transcripts_single_call(patched_outbound):
    _make_call(call_id="CL-9201", provider_call_id="VAPI-D2")
    response = mock.MagicMock(status_code=200)
    response.json.return_value = _vapi_response(("user", "Z"))
    with mock.patch("requests.get", return_value=response):
        out = StringIO()
        call_command(
            "ingest_call_transcripts", "--call-id", "CL-9201", stdout=out
        )
    assert CallTranscriptLine.objects.filter(call_id="CL-9201").count() == 1
    text = out.getvalue()
    assert "ingest call CL-9201" in text


def test_cli_inspect_transcript_backlog_prints_summary(patched_outbound):
    _make_call(call_id="CL-9300", created_offset_hours=48)
    out = StringIO()
    call_command("inspect_transcript_backlog", "--window-days", "30", stdout=out)
    text = out.getvalue()
    assert "Transcript backlog overview" in text
    assert "backlog count" in text
    # Call CL-9300 should appear in the top-10 list.
    assert "CL-9300" in text


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


def test_api_anonymous_blocked():
    from rest_framework.test import APIClient

    client = APIClient()
    url = reverse("phase11a-transcript-backlog")
    response = client.get(url)
    assert response.status_code in {401, 403}


def test_api_admin_can_read_backlog(auth_client, admin_user, patched_outbound):
    _make_call(call_id="CL-9400", created_offset_hours=48)
    client = auth_client(admin_user)
    url = reverse("phase11a-transcript-backlog")
    response = client.get(url)
    assert response.status_code == 200
    body = response.json()
    assert "windowDays" in body or "window_days" in body
    assert body.get("backlog_count", body.get("backlogCount")) >= 1
    top = body.get("top_backlog") or body.get("topBacklog") or []
    assert any(row.get("callId") == "CL-9400" for row in top)


def test_api_admin_can_read_transcript_detail(auth_client, admin_user, patched_outbound):
    call = _make_call(
        call_id="CL-9401",
        transcript_ingested_at=timezone.now(),
        transcript_line_count=1,
    )
    CallTranscriptLine.objects.create(
        call=call, order=0, who="assistant", text="Hello"
    )
    client = auth_client(admin_user)
    url = reverse("phase11a-transcript-detail", args=["CL-9401"])
    response = client.get(url)
    assert response.status_code == 200
    body = response.json()
    assert body["callId"] == "CL-9401"
    assert body["transcriptLineCount"] == 1
    assert body["lines"][0]["text"] == "Hello"


def test_api_admin_can_read_transcript_detail_returns_404_for_missing(
    auth_client, admin_user
):
    client = auth_client(admin_user)
    url = reverse("phase11a-transcript-detail", args=["CL-NOPE"])
    response = client.get(url)
    assert response.status_code == 404


def test_api_post_returns_405(auth_client, admin_user):
    client = auth_client(admin_user)
    url = reverse("phase11a-transcript-backlog")
    assert client.post(url).status_code == 405
    assert client.patch(url).status_code == 405
    assert client.delete(url).status_code == 405


# ---------------------------------------------------------------------------
# Defensive integration — no outbound under any path
# ---------------------------------------------------------------------------


@override_settings(VAPI_API_KEY="dummy")
def test_no_outbound_or_business_mutation_under_full_run(patched_outbound):
    from apps.calls.transcript_ingestion import ingest_backlog
    from apps.crm.models import Customer, Lead
    from apps.orders.models import Order
    from apps.payments.models import Payment

    _make_call(call_id="CL-9500", provider_call_id="VAPI-X1")
    _make_call(call_id="CL-9501", provider_call_id="VAPI-X2")
    response = mock.MagicMock(status_code=200)
    response.json.return_value = _vapi_response(
        ("assistant", "A"), ("user", "B")
    )

    pre_customers = Customer.objects.count()
    pre_leads = Lead.objects.count()
    pre_orders = Order.objects.count()
    pre_payments = Payment.objects.count()

    with mock.patch("requests.get", return_value=response):
        summary = ingest_backlog(limit=10)

    assert summary["ingested"] == 2
    assert Customer.objects.count() == pre_customers
    assert Lead.objects.count() == pre_leads
    assert Order.objects.count() == pre_orders
    assert Payment.objects.count() == pre_payments
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


# ---------------------------------------------------------------------------
# Beat schedule sanity — Phase 11A entry registered
# ---------------------------------------------------------------------------


def test_beat_schedule_has_transcript_ingestion_daily():
    from config.celery import build_beat_schedule

    schedule = build_beat_schedule()
    assert "transcript-ingestion-daily" in schedule
    entry = schedule["transcript-ingestion-daily"]
    assert (
        entry["task"]
        == "apps.calls.tasks.ingest_transcript_backlog_daily"
    )
    # Phase 11A added the 9th entry; Phase 11B raised this to 10 with
    # ``call-quality-scoring-daily``. Assert ≥ 9 so adding future
    # daily entries doesn't break the Phase 11A regression suite.
    assert len(schedule) >= 9
    assert "call-quality-scoring-daily" in schedule
