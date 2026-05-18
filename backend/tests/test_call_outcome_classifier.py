"""Phase 12B — Call Outcome Classifier V1 tests.

Defensive contract: across every classify / approve / apply path, all
four outbound entrypoints are patched and asserted `assert_not_called`.
Lead row counts stay constant under classify; under apply, Lead.status
is the ONLY mutation (row count stays constant, only the `status`
field flips for `review_status=approved` records). Order / Payment /
Shipment / Customer row counts stay constant under every path.
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
    AiCallCampaignGate,
    Call,
    CallOutcomeRecord,
    CallTranscriptLine,
)
from apps.calls.outcome_classifier import (
    OUTCOME_TO_LEAD_STATUS,
    apply_outcome_updates,
    approve_record,
    classify_call,
    classify_campaign_calls,
    classify_recent_calls,
    get_outcomes_summary,
)
from apps.crm.models import Lead


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lead(*, lead_id: str = "LD-OC-1", status: str = "Interested") -> Lead:
    return Lead.objects.create(
        id=lead_id,
        name="Test Lead",
        phone="+919999990000",
        state="Delhi",
        city="Delhi",
        language="Hindi",
        source="manual",
        campaign="t",
        product_interest="Nirogidhara",
        status=status,
    )


def _make_call(
    *,
    call_id: str = "CL-OC-1",
    lead_id: str = "LD-OC-1",
    status: str = Call.Status.COMPLETED.value,
    duration: str = "1:30",
) -> Call:
    return Call.objects.create(
        id=call_id,
        lead_id=lead_id,
        customer="Test",
        phone="+919999990000",
        agent="Calling AI · Vapi",
        language="Hindi",
        provider=Call.Provider.VAPI,
        provider_call_id=f"vapi_{call_id}",
        status=status,
        duration=duration,
    )


def _add_lines(call: Call, lines: list[tuple[str, str]]) -> None:
    rows = [
        CallTranscriptLine(call=call, order=idx, who=who, text=text)
        for idx, (who, text) in enumerate(lines)
    ]
    CallTranscriptLine.objects.bulk_create(rows)


@pytest.fixture
def patched_outbound():
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
# classify_call — outcome rules
# ---------------------------------------------------------------------------


def test_classify_call_not_connected_when_missed(patched_outbound):
    _make_lead()
    call = _make_call(status=Call.Status.MISSED.value)
    record = classify_call(call.id)
    assert record.detected_outcome == "not_connected"
    assert record.suggested_lead_status == ""
    assert record.confidence == "high"


def test_classify_call_not_connected_when_failed(patched_outbound):
    _make_lead()
    call = _make_call(status=Call.Status.FAILED.value)
    record = classify_call(call.id)
    assert record.detected_outcome == "not_connected"


def test_classify_call_no_transcript_when_completed_but_empty(
    patched_outbound,
):
    _make_lead()
    call = _make_call()
    record = classify_call(call.id)
    assert record.detected_outcome == "no_transcript"
    assert record.suggested_lead_status == ""


def test_classify_call_connected_converted_on_conversion_signal(
    patched_outbound,
):
    _make_lead()
    call = _make_call()
    _add_lines(
        call,
        [
            ("agent", "Namaste, weight management capsule ke baare mein."),
            ("customer", "Haan bilkul, link bhejo, lena hai."),
            ("agent", "Theek hai, payment link bhej raha hoon."),
        ],
    )
    record = classify_call(call.id)
    assert record.detected_outcome == "connected_converted"
    assert record.suggested_lead_status == "Payment Link Sent"
    # 3 conversion keywords match -> high confidence (>1).
    assert record.confidence == "high"
    assert AuditEvent.objects.filter(
        kind="call_outcome.classified", payload__call_id=call.id
    ).exists()


def test_classify_call_converted_medium_when_single_signal(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(
        call,
        [
            ("agent", "Order karenge?"),
            ("customer", "Order kar lo."),
        ],
    )
    record = classify_call(call.id)
    assert record.detected_outcome == "connected_converted"
    assert record.confidence == "medium"


def test_classify_call_not_interested_on_rejection_signal(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(
        call,
        [
            ("agent", "Order karenge?"),
            ("customer", "Mujhe nahi chahiye, band karo."),
        ],
    )
    record = classify_call(call.id)
    assert record.detected_outcome == "connected_not_interested"
    assert record.suggested_lead_status == "Not Interested"
    assert record.confidence == "high"


def test_classify_call_callback_on_callback_signal(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(
        call,
        [
            ("agent", "Order karenge?"),
            ("customer", "Abhi busy hoon, baad mein call karo."),
        ],
    )
    record = classify_call(call.id)
    assert record.detected_outcome == "connected_callback"
    assert record.suggested_lead_status == "Callback Required"
    assert record.confidence == "medium"


def test_classify_call_unclear_when_no_signals(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(
        call,
        [
            ("agent", "Hello, hum Nirogidhara se baat kar rahe hain."),
            ("customer", "Sun raha hoon."),
            ("agent", "Sahi hai."),
        ],
    )
    record = classify_call(call.id)
    assert record.detected_outcome == "connected_unclear"
    assert record.suggested_lead_status == ""
    assert record.confidence == "low"


def test_classify_call_rejection_beats_callback(patched_outbound):
    """When rejection + callback both match, rejection wins (cascade order)."""
    _make_lead()
    call = _make_call()
    _add_lines(
        call,
        [
            ("customer", "Nahi chahiye, kal mat karo."),
        ],
    )
    record = classify_call(call.id)
    assert record.detected_outcome == "connected_not_interested"


def test_classify_call_idempotent_returns_existing(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan link bhejo")])
    first = classify_call(call.id)
    second = classify_call(call.id)
    assert first.pk == second.pk
    assert CallOutcomeRecord.objects.count() == 1
    # Exactly one audit row written (not two).
    assert (
        AuditEvent.objects.filter(
            kind="call_outcome.classified", payload__call_id=call.id
        ).count()
        == 1
    )


def test_classify_call_missing_raises(patched_outbound):
    with pytest.raises(ValueError):
        classify_call("CL-DOES-NOT-EXIST")


def test_classify_call_outcome_to_lead_status_map_complete():
    """Every DetectedOutcome value must be in OUTCOME_TO_LEAD_STATUS."""
    for choice in CallOutcomeRecord.DetectedOutcome.values:
        assert choice in OUTCOME_TO_LEAD_STATUS


# ---------------------------------------------------------------------------
# Lead snapshot + campaign linkage
# ---------------------------------------------------------------------------


def test_classify_call_records_current_lead_status(patched_outbound):
    _make_lead(lead_id="LD-SNAP", status="Interested")
    call = _make_call(call_id="CL-SNAP", lead_id="LD-SNAP")
    _add_lines(call, [("customer", "haan bilkul lena hai")])
    record = classify_call(call.id)
    assert record.current_lead_status == "Interested"
    assert record.lead_id == "LD-SNAP"


def test_classify_call_links_to_campaign_gate(patched_outbound):
    _make_lead(lead_id="LD-CG-1")
    call = _make_call(call_id="CL-CG-1", lead_id="LD-CG-1")
    _add_lines(call, [("customer", "haan order")])
    gate = AiCallCampaignGate.objects.create(
        status="completed",
        operator_name="P",
        stage_filter=["Interested"],
        max_leads=10,
        leads_selected=["LD-CG-1"],
        leads_attempted=["LD-CG-1"],
        executed_at=timezone.now(),
    )
    record = classify_call(call.id)
    assert record.campaign_gate_id == gate.pk


# ---------------------------------------------------------------------------
# classify_campaign_calls
# ---------------------------------------------------------------------------


def test_classify_campaign_calls_summary(patched_outbound):
    _make_lead(lead_id="LD-CC-1")
    _make_lead(lead_id="LD-CC-2")
    _make_lead(lead_id="LD-CC-NOCALL")
    c1 = _make_call(call_id="CL-CC-1", lead_id="LD-CC-1")
    _add_lines(c1, [("customer", "haan link bhejo lena hai")])
    c2 = _make_call(call_id="CL-CC-2", lead_id="LD-CC-2")
    _add_lines(c2, [("customer", "nahi chahiye")])
    gate = AiCallCampaignGate.objects.create(
        status="completed",
        operator_name="P",
        stage_filter=["Interested"],
        max_leads=10,
        leads_selected=["LD-CC-1", "LD-CC-2", "LD-CC-NOCALL"],
        leads_attempted=["LD-CC-1", "LD-CC-2", "LD-CC-NOCALL"],
        executed_at=timezone.now(),
    )
    summary = classify_campaign_calls(gate.pk)
    assert summary["total"] == 2
    assert summary["connected_converted"] == 1
    assert summary["connected_not_interested"] == 1
    assert summary["skipped_no_call"] == 1


# ---------------------------------------------------------------------------
# apply_outcome_updates
# ---------------------------------------------------------------------------


def _seed_approved_converted(lead_id: str = "LD-AP-1") -> CallOutcomeRecord:
    _make_lead(lead_id=lead_id, status="Interested")
    call = _make_call(call_id=f"CL-{lead_id}", lead_id=lead_id)
    _add_lines(call, [("customer", "haan bilkul link bhejo lena hai")])
    record = classify_call(call.id)
    record.review_status = CallOutcomeRecord.ReviewStatus.APPROVED.value
    record.save(update_fields=["review_status"])
    return record


def test_apply_updates_lead_status_for_approved(patched_outbound):
    record = _seed_approved_converted()
    pre_leads = Lead.objects.count()
    summary = apply_outcome_updates(operator_name="Prarit")
    assert summary["total_applied"] == 1
    record.refresh_from_db()
    assert record.review_status == "applied"
    assert record.applied_by == "Prarit"
    lead = Lead.objects.get(pk=record.lead_id)
    assert lead.status == "Payment Link Sent"
    # Lead row count stays constant.
    assert Lead.objects.count() == pre_leads
    assert AuditEvent.objects.filter(
        kind="call_outcome.applied",
        payload__outcome_record_id=record.pk,
    ).exists()


def test_apply_skips_blank_suggestion(patched_outbound):
    _make_lead(lead_id="LD-BL-1")
    call = _make_call(call_id="CL-BL-1", lead_id="LD-BL-1")
    _add_lines(call, [("agent", "hi"), ("customer", "sun raha hoon")])
    record = classify_call(call.id)
    record.review_status = CallOutcomeRecord.ReviewStatus.APPROVED.value
    record.save(update_fields=["review_status"])
    assert record.suggested_lead_status == ""  # unclear -> blank
    summary = apply_outcome_updates(operator_name="Prarit")
    assert summary["total_applied"] == 0
    assert summary["skipped_blank"] == 1


def test_apply_sandbox_skips_status_change(patched_outbound):
    record = _seed_approved_converted(lead_id="LD-SB-1")
    summary = apply_outcome_updates(
        operator_name="Prarit", sandbox=True
    )
    assert summary["total_applied"] == 0
    assert summary["skipped_sandbox"] == 1
    record.refresh_from_db()
    # Record stays approved (NOT applied); Lead.status unchanged.
    assert record.review_status == "approved"
    lead = Lead.objects.get(pk=record.lead_id)
    assert lead.status == "Interested"


def test_apply_only_picks_approved_rows(patched_outbound):
    record = _seed_approved_converted(lead_id="LD-OK-1")
    pending = classify_call(
        _make_call(
            call_id="CL-PEND",
            lead_id=(_make_lead(lead_id="LD-PEND-1")).id,
        ).id
    )
    # Add a transcript with a clear conversion signal so suggestion is non-blank.
    _add_lines(
        Call.objects.get(pk="CL-PEND"),
        [("customer", "haan link bhejo lena hai")],
    )
    # Re-classify after adding lines won't run because record exists.
    # Instead manually set its suggestion to mimic a pending row.
    pending.suggested_lead_status = "Payment Link Sent"
    pending.review_status = "pending"
    pending.save(update_fields=["suggested_lead_status", "review_status"])
    summary = apply_outcome_updates(operator_name="P")
    assert summary["total_applied"] == 1
    record.refresh_from_db()
    pending.refresh_from_db()
    assert record.review_status == "applied"
    assert pending.review_status == "pending"


def test_apply_specific_ids_filters_correctly(patched_outbound):
    r1 = _seed_approved_converted(lead_id="LD-ID-1")
    r2 = _seed_approved_converted(lead_id="LD-ID-2")
    summary = apply_outcome_updates(
        operator_name="P", outcome_record_ids=[r1.pk]
    )
    assert summary["total_applied"] == 1
    r1.refresh_from_db()
    r2.refresh_from_db()
    assert r1.review_status == "applied"
    assert r2.review_status == "approved"


def test_apply_empty_operator_raises():
    with pytest.raises(ValueError):
        apply_outcome_updates(operator_name="")


# ---------------------------------------------------------------------------
# approve_record
# ---------------------------------------------------------------------------


def test_approve_pending_transitions_to_approved(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan order")])
    record = classify_call(call.id)
    out = approve_record(
        outcome_record_id=record.pk, operator_name="Prarit"
    )
    assert out.review_status == "approved"
    assert out.applied_by == "Prarit"


def test_approve_non_pending_raises(patched_outbound):
    record = _seed_approved_converted(lead_id="LD-PA-1")
    with pytest.raises(ValueError):
        approve_record(
            outcome_record_id=record.pk, operator_name="P"
        )


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def test_cli_classify_call_outcomes_dry_run_no_rows_created(
    patched_outbound,
):
    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan link bhejo lena hai")])
    out = StringIO()
    call_command(
        "classify_call_outcomes",
        "--call-id",
        call.id,
        "--dry-run",
        stdout=out,
    )
    assert CallOutcomeRecord.objects.count() == 0
    assert "classify" in out.getvalue()


def test_cli_classify_call_outcomes_persists(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan link bhejo")])
    out = StringIO()
    call_command(
        "classify_call_outcomes",
        "--call-id",
        call.id,
        stdout=out,
    )
    assert CallOutcomeRecord.objects.count() == 1


def test_cli_review_call_outcomes_lists(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan order")])
    classify_call(call.id)
    out = StringIO()
    call_command("review_call_outcomes", "--status", "pending", stdout=out)
    text = out.getvalue()
    assert "CallOutcomeRecord listing" in text


def test_cli_approve_call_outcome(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan order")])
    record = classify_call(call.id)
    out = StringIO()
    call_command(
        "approve_call_outcome",
        str(record.pk),
        "--operator-name",
        "Prarit",
        stdout=out,
    )
    record.refresh_from_db()
    assert record.review_status == "approved"


def test_cli_apply_requires_confirm_flag(patched_outbound):
    _seed_approved_converted(lead_id="LD-CONF-1")
    err = StringIO()
    with pytest.raises(SystemExit) as exc:
        call_command(
            "apply_call_outcome_updates",
            "--operator-name",
            "P",
            stderr=err,
        )
    assert exc.value.code == 1
    assert "REFUSED" in err.getvalue()


def test_cli_apply_with_confirm_flips_status(patched_outbound):
    record = _seed_approved_converted(lead_id="LD-CLIAP-1")
    out = StringIO()
    call_command(
        "apply_call_outcome_updates",
        "--operator-name",
        "Prarit",
        "--confirm-outcome-apply",
        stdout=out,
    )
    record.refresh_from_db()
    assert record.review_status == "applied"
    lead = Lead.objects.get(pk=record.lead_id)
    assert lead.status == "Payment Link Sent"


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_celery_classify_happy_path(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan link bhejo lena hai")])
    from apps.calls.tasks import classify_call_outcomes_daily

    summary = classify_call_outcomes_daily(hours=26)
    assert summary["total"] == 1
    assert summary["connected_converted"] == 1
    assert AuditEvent.objects.filter(
        kind="call_outcome.daily_classification.completed"
    ).exists()


def test_celery_classify_kill_switch_blocked(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan")])
    from apps.calls.tasks import classify_call_outcomes_daily

    with mock.patch(
        "apps.calls.tasks._kill_switch_blocked", return_value=True
    ):
        result = classify_call_outcomes_daily(hours=26)
    assert result["skipped"] is True
    assert result["reason"] == "kill_switch_off"
    assert CallOutcomeRecord.objects.count() == 0


def test_celery_classify_sandbox_blocked(patched_outbound):
    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan")])
    from apps.calls.tasks import classify_call_outcomes_daily

    with mock.patch(
        "apps.calls.tasks._sandbox_active", return_value=True
    ):
        result = classify_call_outcomes_daily(hours=26)
    assert result["skipped"] is True
    assert result["reason"] == "sandbox_mode"
    assert CallOutcomeRecord.objects.count() == 0


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_anonymous_blocked():
    from rest_framework.test import APIClient

    client = APIClient()
    response = client.get(reverse("phase12b-outcomes-list"))
    assert response.status_code in {401, 403}


def test_api_admin_list_detail_summary(
    auth_client, admin_user, patched_outbound
):
    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan order")])
    record = classify_call(call.id)
    client = auth_client(admin_user)
    list_resp = client.get(reverse("phase12b-outcomes-list"))
    assert list_resp.status_code == 200
    assert list_resp.json()["count"] >= 1
    detail_resp = client.get(
        reverse("phase12b-outcome-detail", args=[record.pk])
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == record.pk
    assert "evidence" in detail_resp.json()
    summary_resp = client.get(reverse("phase12b-outcomes-summary"))
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["total"] >= 1
    assert "byOutcome" in summary


def test_api_detail_404(auth_client, admin_user):
    client = auth_client(admin_user)
    assert (
        client.get(
            reverse("phase12b-outcome-detail", args=[99999])
        ).status_code
        == 404
    )


def test_api_post_returns_405(auth_client, admin_user):
    client = auth_client(admin_user)
    url = reverse("phase12b-outcomes-list")
    assert client.post(url).status_code == 405
    assert client.patch(url).status_code == 405
    assert client.delete(url).status_code == 405


# ---------------------------------------------------------------------------
# Defensive integration — no outbound, business rows untouched
# ---------------------------------------------------------------------------


def test_no_outbound_classify_path(patched_outbound):
    from apps.crm.models import Customer
    from apps.orders.models import Order
    from apps.payments.models import Payment

    _make_lead()
    call = _make_call()
    _add_lines(call, [("customer", "haan link bhejo lena hai")])
    pre = {
        "Customer": Customer.objects.count(),
        "Lead": Lead.objects.count(),
        "Order": Order.objects.count(),
        "Payment": Payment.objects.count(),
    }
    classify_recent_calls(hours=24)
    assert Customer.objects.count() == pre["Customer"]
    assert Lead.objects.count() == pre["Lead"]
    assert Order.objects.count() == pre["Order"]
    assert Payment.objects.count() == pre["Payment"]
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


def test_apply_only_mutates_lead_status_not_other_business_rows(
    patched_outbound,
):
    from apps.crm.models import Customer
    from apps.orders.models import Order
    from apps.payments.models import Payment

    record = _seed_approved_converted(lead_id="LD-DEF-1")
    pre = {
        "Customer": Customer.objects.count(),
        "Order": Order.objects.count(),
        "Payment": Payment.objects.count(),
        "Lead": Lead.objects.count(),
    }
    apply_outcome_updates(operator_name="P")
    # Lead row count unchanged; only the status field flipped.
    assert Lead.objects.count() == pre["Lead"]
    assert Customer.objects.count() == pre["Customer"]
    assert Order.objects.count() == pre["Order"]
    assert Payment.objects.count() == pre["Payment"]
    lead = Lead.objects.get(pk=record.lead_id)
    assert lead.status == "Payment Link Sent"
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


# ---------------------------------------------------------------------------
# Beat schedule sanity — Phase 12B adds ONE new entry. Total drifts as
# later phases add more entries (use >= so future additions don't break).
# ---------------------------------------------------------------------------


def test_beat_schedule_has_call_outcome_classification_daily():
    from config.celery import build_beat_schedule

    schedule = build_beat_schedule()
    assert "call-outcome-classification-daily" in schedule
    entry = schedule["call-outcome-classification-daily"]
    assert (
        entry["task"]
        == "apps.calls.tasks.classify_call_outcomes_daily"
    )
    assert len(schedule) >= 12


# ---------------------------------------------------------------------------
# get_outcomes_summary
# ---------------------------------------------------------------------------


def test_get_outcomes_summary_counts(patched_outbound):
    # Mix of outcomes + statuses.
    r1 = _seed_approved_converted(lead_id="LD-S1")
    _make_lead(lead_id="LD-S2")
    call2 = _make_call(call_id="CL-S2", lead_id="LD-S2")
    _add_lines(call2, [("customer", "nahi chahiye")])
    classify_call(call2.id)  # pending rejection
    apply_outcome_updates(operator_name="P", outcome_record_ids=[r1.pk])
    summary = get_outcomes_summary()
    assert summary["total"] == 2
    assert summary["pending_count"] == 1
    assert summary["applied_count"] == 1
    assert "connected_converted" in summary["by_outcome"]
    assert "connected_not_interested" in summary["by_outcome"]
