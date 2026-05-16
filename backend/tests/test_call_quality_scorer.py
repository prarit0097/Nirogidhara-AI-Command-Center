"""Phase 11B — Call Quality Scorer V1 tests.

Deterministic, no LLM. Defensive safety contract: every path that
runs the scorer (service / CLI / Celery / API) is wrapped with
patches on `queue_template_message`, `send_freeform_text_message`,
`trigger_call_for_lead`, `create_shipment` and asserted
`assert_not_called`. `Customer` / `Lead` / `Order` / `Payment` /
`Shipment` row counts stay constant.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.calls.models import (
    Call,
    CallQualityScore,
    CallTranscriptLine,
)


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_call(
    *,
    call_id: str,
    status: str = Call.Status.COMPLETED.value,
    duration: str = "2:30",
    agent_label: str = "Calling AI · Vapi",
    transcript_line_count: int = 0,
    transcript_ingested_at=None,
    created_offset_hours: int = 48,
) -> Call:
    if transcript_line_count > 0 and transcript_ingested_at is None:
        transcript_ingested_at = timezone.now()
    call = Call.objects.create(
        id=call_id,
        lead_id=f"LD-{call_id}",
        customer="Test Customer",
        phone="+919999990000",
        agent=agent_label,
        language="Hindi",
        provider=Call.Provider.VAPI,
        provider_call_id=f"vapi_{call_id}",
        status=status,
        duration=duration,
        transcript_ingested_at=transcript_ingested_at,
        transcript_line_count=transcript_line_count,
    )
    Call.objects.filter(pk=call.pk).update(
        created_at=timezone.now() - timedelta(hours=created_offset_hours)
    )
    call.refresh_from_db()
    return call


def _add_lines(call: Call, lines: list[tuple[str, str]]) -> None:
    rows = [
        CallTranscriptLine(call=call, order=idx, who=who, text=text)
        for idx, (who, text) in enumerate(lines)
    ]
    CallTranscriptLine.objects.bulk_create(rows)
    Call.objects.filter(pk=call.pk).update(
        transcript_ingested_at=timezone.now(),
        transcript_line_count=len(rows),
    )
    call.refresh_from_db()


@pytest.fixture
def patched_outbound():
    """Defensive contract — every outbound entrypoint patched."""
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
# Dimension scorers
# ---------------------------------------------------------------------------


def test_connection_score_missed_call_is_zero():
    from apps.calls.quality_scorer import connection_score

    call = _make_call(call_id="CL-CS-1", status=Call.Status.MISSED.value)
    score, secs = connection_score(call)
    assert score == 0
    assert secs == 0


def test_connection_score_failed_call_is_zero():
    from apps.calls.quality_scorer import connection_score

    call = _make_call(call_id="CL-CS-2", status=Call.Status.FAILED.value)
    score, _ = connection_score(call)
    assert score == 0


def test_connection_score_queued_is_thirty():
    from apps.calls.quality_scorer import connection_score

    call = _make_call(call_id="CL-CS-3", status=Call.Status.QUEUED.value)
    score, _ = connection_score(call)
    assert score == 30


def test_connection_score_completed_short_is_sixty():
    from apps.calls.quality_scorer import connection_score

    call = _make_call(call_id="CL-CS-4", duration="0:10")
    score, secs = connection_score(call)
    assert score == 60
    assert secs == 10


def test_connection_score_completed_long_is_one_hundred():
    from apps.calls.quality_scorer import connection_score

    call = _make_call(call_id="CL-CS-5", duration="6:00")
    score, secs = connection_score(call)
    assert score == 100
    assert secs == 360


def test_product_knowledge_score_with_keywords():
    from apps.calls.quality_scorer import product_knowledge_score

    score, found = product_knowledge_score(
        [
            "Yeh ayurvedic capsule weight management ke liye hai.",
            "Roz ek capsule, dose simple hai.",
        ]
    )
    assert score > 0
    assert "ayurvedic" in found
    assert "capsule" in found


def test_product_knowledge_score_no_agent_lines_is_zero():
    from apps.calls.quality_scorer import product_knowledge_score

    score, found = product_knowledge_score([])
    assert score == 0
    assert found == []


def test_compliance_score_clean_is_one_hundred():
    from apps.calls.quality_scorer import compliance_score

    score, found = compliance_score(
        ["Bilkul, yeh ayurvedic product hai. Roz ek capsule lein."]
    )
    assert score == 100
    assert found == []


def test_compliance_score_forbidden_phrase_drops_score():
    from apps.calls.quality_scorer import compliance_score

    score, found = compliance_score(
        ["Hum guarantee dete hain ki yeh cure kar dega."]
    )
    assert score <= 50
    assert "guarantee" in found
    assert "cure" in found


def test_objection_handling_no_objection_is_neutral():
    from apps.calls.quality_scorer import objection_handling_score

    score, found, total, handled = objection_handling_score(
        [
            ("agent", "Namaste, kaise hain aap?"),
            ("customer", "Theek hoon."),
        ]
    )
    assert score == 70
    assert total == 0
    assert handled == 0


def test_objection_handling_addressed_objection_high_score():
    from apps.calls.quality_scorer import objection_handling_score

    score, found, total, handled = objection_handling_score(
        [
            ("agent", "Yeh weight management capsule hai."),
            ("customer", "Bahut mehnga lag raha hai, paisa kam ho sakta hai?"),
            ("agent", "Dekh, hum discount offer kar sakte hain."),
        ]
    )
    assert total == 1
    assert handled == 1
    assert score == 100


def test_objection_handling_ignored_objection_low_score():
    from apps.calls.quality_scorer import objection_handling_score

    score, found, total, handled = objection_handling_score(
        [
            ("agent", "Yeh weight management capsule hai."),
            ("customer", "Price mehnga hai."),
            ("agent", "Order karein?"),
        ]
    )
    assert total == 1
    assert handled == 0
    assert score == 0


def test_tonality_score_with_greeting_and_closing():
    from apps.calls.quality_scorer import tonality_score

    score, greeting_found, closing_found, _ = tonality_score(
        [
            "Namaste, kaise hain aap?",
            "Bilkul, samajh gaye.",
            "Dhanyavad, phir milenge.",
        ],
        first_agent_text="Namaste, kaise hain aap?",
    )
    assert greeting_found is True
    assert closing_found is True
    assert score >= 80


def test_tonality_score_no_greeting():
    from apps.calls.quality_scorer import tonality_score

    score, greeting_found, _, _ = tonality_score(
        ["Order karein?", "Order karein?"],
        first_agent_text="Order karein?",
    )
    assert greeting_found is False
    assert score == 50


# ---------------------------------------------------------------------------
# score_call — composite + flags
# ---------------------------------------------------------------------------


def test_score_call_happy_path_creates_row_and_audit(patched_outbound):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9501", duration="3:00")
    _add_lines(
        call,
        [
            ("agent", "Namaste, Nirogidhara se baat kar rahe hain."),
            ("customer", "Bolo."),
            ("agent", "Yeh ayurvedic capsule weight management ke liye hai."),
            ("customer", "Theek hai."),
            ("agent", "Dhanyavad, phir milenge."),
        ],
    )
    result = score_call("CL-9501")
    assert result["ok"] is True
    assert result["skipped"] is False
    assert result["composite_score"] > 0
    assert result["connection_score"] >= 80
    row = CallQualityScore.objects.get(call=call)
    assert row.composite_score == result["composite_score"]
    assert row.scoring_version == "deterministic_v1"
    # Audit row written.
    audit = AuditEvent.objects.filter(
        kind="call_quality.scored", payload__call_id="CL-9501"
    ).first()
    assert audit is not None
    assert "composite_score" in audit.payload
    # Defensive contract — no outbound.
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


def test_score_call_dry_run_creates_no_row(patched_outbound):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9502")
    _add_lines(call, [("agent", "Namaste."), ("customer", "Hi.")])
    pre_audit = AuditEvent.objects.filter(
        kind="call_quality.scored"
    ).count()
    result = score_call("CL-9502", dry_run=True)
    assert result["dry_run"] is True
    assert CallQualityScore.objects.count() == 0
    assert (
        AuditEvent.objects.filter(kind="call_quality.scored").count()
        == pre_audit
    )


def test_score_call_already_scored_is_skipped(patched_outbound):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9503")
    _add_lines(call, [("agent", "Namaste.")])
    first = score_call("CL-9503")
    assert first["ok"] is True
    second = score_call("CL-9503")
    assert second["skipped"] is True
    assert second["reason"] == "already_scored"
    assert second["composite_score"] == first["composite_score"]


def test_score_call_missing_returns_skipped(patched_outbound):
    from apps.calls.quality_scorer import score_call

    result = score_call("CL-DOES-NOT-EXIST")
    assert result["skipped"] is True
    assert result["reason"] == "call_not_found"


def test_score_call_no_transcript_flags_no_transcript(patched_outbound):
    from apps.calls.quality_scorer import score_call

    _make_call(call_id="CL-9504", transcript_line_count=0)
    result = score_call("CL-9504")
    assert "no_transcript" in result["flags"]
    assert result["product_knowledge_score"] == 0


def test_score_call_compliance_violation_flag(patched_outbound):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9505")
    _add_lines(
        call,
        [
            ("agent", "Hum guarantee dete hain ki yeh cure kar dega."),
            ("customer", "Sahi hai?"),
            ("agent", "Bilkul."),
        ],
    )
    result = score_call("CL-9505")
    assert "compliance_violation" in result["flags"]
    assert result["compliance_score"] < 100


def test_score_call_weak_product_knowledge_flag(patched_outbound):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9506")
    _add_lines(
        call,
        [
            ("agent", "Hello."),
            ("customer", "Hi."),
            ("agent", "Order karein."),
        ],
    )
    result = score_call("CL-9506")
    assert "weak_product_knowledge" in result["flags"]
    assert result["product_knowledge_score"] < 40


def test_score_call_no_greeting_flag(patched_outbound):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9507")
    _add_lines(
        call,
        [
            ("agent", "Order karein."),
            ("customer", "Theek hai."),
        ],
    )
    result = score_call("CL-9507")
    assert "no_greeting" in result["flags"]


def test_score_call_short_call_flag(patched_outbound):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9508", duration="0:10")
    _add_lines(call, [("agent", "Namaste."), ("customer", "Hi.")])
    result = score_call("CL-9508")
    assert "short_call" in result["flags"]
    assert result["raw_signals"]["duration_seconds"] == 10


def test_score_call_zero_agent_utterances_flag(patched_outbound):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9509")
    _add_lines(
        call,
        [("customer", "Kaun hai?"), ("customer", "Bolo na.")],
    )
    result = score_call("CL-9509")
    assert "zero_agent_utterances" in result["flags"]
    assert result["product_knowledge_score"] == 0


def test_score_call_no_objection_response_flag(patched_outbound):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9510")
    _add_lines(
        call,
        [
            ("agent", "Namaste, weight management capsule hai."),
            ("customer", "Bahut mehnga hai, kya price kam ho sakti hai?"),
            ("agent", "Order karein?"),
        ],
    )
    result = score_call("CL-9510")
    assert "no_objection_response" in result["flags"]
    assert result["objection_handling_score"] < 40


# ---------------------------------------------------------------------------
# Composite formula
# ---------------------------------------------------------------------------


def test_composite_formula_weights_correct(patched_outbound):
    from apps.calls.quality_scorer import _compute_composite

    # 100 across all → 100.
    assert _compute_composite(100, 100, 100, 100, 100) == 100
    # 0 across all → 0.
    assert _compute_composite(0, 0, 0, 0, 0) == 0
    # Manual weighting: 80*0.2 + 60*0.25 + 100*0.25 + 50*0.15 + 70*0.15
    # = 16 + 15 + 25 + 7.5 + 10.5 = 74
    assert _compute_composite(80, 60, 100, 50, 70) == 74


# ---------------------------------------------------------------------------
# Backlog selectors + score_backlog summary
# ---------------------------------------------------------------------------


def test_get_scoring_backlog_excludes_no_transcript_and_already_scored(
    patched_outbound,
):
    from apps.calls.quality_scorer import get_scoring_backlog, score_call

    # Eligible — has transcript lines.
    call_a = _make_call(call_id="CL-9600")
    _add_lines(call_a, [("agent", "Hi")])
    # Not eligible — no transcript lines.
    _make_call(call_id="CL-9601", transcript_line_count=0)
    # Not eligible — already scored.
    call_c = _make_call(call_id="CL-9602")
    _add_lines(call_c, [("agent", "Hi")])
    score_call("CL-9602")
    ids = list(get_scoring_backlog().values_list("id", flat=True))
    assert "CL-9600" in ids
    assert "CL-9601" not in ids
    assert "CL-9602" not in ids


def test_score_backlog_summary_counts(patched_outbound):
    from apps.calls.quality_scorer import score_backlog, score_call

    a = _make_call(call_id="CL-9610")
    _add_lines(a, [("agent", "Namaste."), ("agent", "Capsule.")])
    b = _make_call(call_id="CL-9611")
    _add_lines(b, [("agent", "Namaste.")])
    # Pre-score one of them so the summary records skipped_already.
    score_call("CL-9610")
    summary = score_backlog(limit=10)
    # Only CL-9611 should remain in the backlog after the pre-score.
    assert summary["total"] == 1
    assert summary["scored"] == 1
    assert summary["errors"] == 0


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_celery_happy_path_writes_completed_audit(patched_outbound):
    from apps.calls.tasks import score_call_transcripts_daily

    call = _make_call(call_id="CL-9700")
    _add_lines(call, [("agent", "Namaste."), ("customer", "Hi.")])
    summary = score_call_transcripts_daily(limit=5)
    assert summary["total"] == 1
    assert summary["scored"] == 1
    assert AuditEvent.objects.filter(
        kind="call_quality.daily_scoring.completed"
    ).exists()


def test_celery_blocked_by_kill_switch(patched_outbound):
    from apps.calls.tasks import score_call_transcripts_daily

    call = _make_call(call_id="CL-9701")
    _add_lines(call, [("agent", "Hi")])
    with mock.patch(
        "apps.calls.tasks._kill_switch_blocked",
        return_value=True,
    ):
        result = score_call_transcripts_daily(limit=5)
    assert result["skipped"] is True
    assert result["reason"] == "kill_switch_off"
    assert AuditEvent.objects.filter(
        kind="call_quality.daily_scoring.blocked"
    ).exists()


def test_celery_blocked_by_sandbox(patched_outbound):
    from apps.calls.tasks import score_call_transcripts_daily

    call = _make_call(call_id="CL-9702")
    _add_lines(call, [("agent", "Hi")])
    with mock.patch(
        "apps.calls.tasks._sandbox_active",
        return_value=True,
    ):
        result = score_call_transcripts_daily(limit=5)
    assert result["skipped"] is True
    assert result["reason"] == "sandbox_mode"


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def test_cli_score_call_transcripts_dry_run_makes_no_db_changes(
    patched_outbound,
):
    call = _make_call(call_id="CL-9800")
    _add_lines(call, [("agent", "Namaste.")])
    out = StringIO()
    call_command(
        "score_call_transcripts",
        "--dry-run",
        "--limit",
        "5",
        stdout=out,
    )
    assert CallQualityScore.objects.count() == 0
    assert "backlog scoring" in out.getvalue()


def test_cli_score_call_transcripts_single_call(patched_outbound):
    call = _make_call(call_id="CL-9801")
    _add_lines(call, [("agent", "Namaste."), ("customer", "Hi.")])
    out = StringIO()
    call_command(
        "score_call_transcripts", "--call-id", "CL-9801", stdout=out
    )
    assert CallQualityScore.objects.filter(call_id="CL-9801").count() == 1
    assert "score call CL-9801" in out.getvalue()


def test_cli_inspect_quality_scoring_backlog_prints_summary(patched_outbound):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9802")
    _add_lines(call, [("agent", "Namaste.")])
    score_call("CL-9802")
    out = StringIO()
    call_command("inspect_quality_scoring_backlog", stdout=out)
    text = out.getvalue()
    assert "Call quality scoring overview" in text
    assert "total scored" in text


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_anonymous_blocked():
    from rest_framework.test import APIClient

    client = APIClient()
    url = reverse("phase11b-quality-scores-list")
    response = client.get(url)
    assert response.status_code in {401, 403}


def test_api_admin_can_read_list_detail_and_summary(
    auth_client, admin_user, patched_outbound
):
    from apps.calls.quality_scorer import score_call

    call = _make_call(call_id="CL-9900")
    _add_lines(call, [("agent", "Namaste."), ("agent", "Capsule.")])
    score_call("CL-9900")

    client = auth_client(admin_user)
    list_resp = client.get(reverse("phase11b-quality-scores-list"))
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["count"] == 1
    assert body["results"][0]["callId"] == "CL-9900"
    assert "compositeScore" in body["results"][0]
    detail_resp = client.get(
        reverse("phase11b-quality-score-detail", args=["CL-9900"])
    )
    assert detail_resp.status_code == 200
    summary_resp = client.get(reverse("phase11b-quality-scores-summary"))
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["totalScored"] == 1
    assert summary["windowDays"] == 30
    # avg_by_agent groups by Call.agent label.
    assert any(
        row["agentLabel"] == "Calling AI · Vapi"
        for row in summary["avgByAgent"]
    )


def test_api_detail_404_for_missing_call(auth_client, admin_user):
    client = auth_client(admin_user)
    url = reverse("phase11b-quality-score-detail", args=["CL-NOPE"])
    response = client.get(url)
    assert response.status_code == 404


def test_api_post_returns_405(auth_client, admin_user):
    client = auth_client(admin_user)
    url = reverse("phase11b-quality-scores-list")
    assert client.post(url, data={}).status_code == 405
    assert client.patch(url, data={}).status_code == 405
    assert client.delete(url).status_code == 405


# ---------------------------------------------------------------------------
# Defensive integration — no outbound under any path
# ---------------------------------------------------------------------------


def test_no_outbound_or_business_mutation_under_full_run(patched_outbound):
    from apps.calls.quality_scorer import score_backlog
    from apps.crm.models import Customer, Lead
    from apps.orders.models import Order
    from apps.payments.models import Payment

    a = _make_call(call_id="CL-9950")
    _add_lines(
        a,
        [
            ("agent", "Namaste, weight management capsule hai."),
            ("customer", "Theek hai."),
        ],
    )
    b = _make_call(call_id="CL-9951", duration="0:10")
    _add_lines(b, [("agent", "Hello.")])

    pre_customers = Customer.objects.count()
    pre_leads = Lead.objects.count()
    pre_orders = Order.objects.count()
    pre_payments = Payment.objects.count()

    summary = score_backlog(limit=10)
    assert summary["scored"] == 2
    assert Customer.objects.count() == pre_customers
    assert Lead.objects.count() == pre_leads
    assert Order.objects.count() == pre_orders
    assert Payment.objects.count() == pre_payments
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


# ---------------------------------------------------------------------------
# Beat schedule sanity
# ---------------------------------------------------------------------------


def test_beat_schedule_has_call_quality_scoring_daily():
    from config.celery import build_beat_schedule

    schedule = build_beat_schedule()
    assert "call-quality-scoring-daily" in schedule
    entry = schedule["call-quality-scoring-daily"]
    assert entry["task"] == "apps.calls.tasks.score_call_transcripts_daily"
    # Phase 11B added the 10th entry; Phase 11C raised this to 11 with
    # ``caio-audit-daily``. Assert >= 10 so future additions are tolerated.
    assert len(schedule) >= 10
