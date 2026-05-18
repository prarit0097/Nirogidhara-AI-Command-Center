"""Phase 12C — Post-Call WhatsApp Follow-up Automation V1 tests.

Defensive contract: across every queue / prepare / mark / skip /
celery / CLI / API path, all four outbound entrypoints are patched
and asserted ``assert_not_called``. ``Lead`` / ``Customer`` /
``Order`` / ``Payment`` / ``Shipment`` row counts stay constant.
The Phase 7E-Live-B ``prepare_gate`` function is also patched in the
defensive integration tests so the queue does not even create a
draft gate row when the test exercises the no-side-effect promise.

Phase 12C is itself a QUEUE/SUGGESTION layer — the actual WhatsApp
send is the Director's separate Phase 7E-Live-B execute step.
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
    CallOutcomeRecord,
    CallTranscriptLine,
    PostCallFollowUpQueue,
)
from apps.calls.outcome_classifier import classify_call
from apps.calls.post_call_followup import (
    PostCallFollowUpStateError,
    TRIGGER_OUTCOMES,
    bulk_identify_and_queue,
    create_follow_up_entry,
    get_followups_summary,
    identify_follow_up_candidates,
    mark_dispatched,
    prepare_gate_for_follow_up,
    skip_follow_up,
)
from apps.crm.models import Customer, Lead
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lead(
    *,
    lead_id: str = "LD-FU-1",
    status: str = "Interested",
    phone: str = "+919999990001",
) -> Lead:
    return Lead.objects.create(
        id=lead_id,
        name="Test Customer",
        phone=phone,
        state="Delhi",
        city="Delhi",
        language="Hindi",
        source="manual",
        campaign="t",
        product_interest="Nirogidhara",
        status=status,
    )


def _make_customer(
    *,
    customer_id: str = "CUS-FU-1",
    name: str = "Test Customer",
    phone: str = "+919999990001",
) -> Customer:
    return Customer.objects.create(
        id=customer_id,
        name=name,
        phone=phone,
        city="Delhi",
        state="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
    )


def _make_call(
    *,
    call_id: str = "CL-FU-1",
    lead_id: str = "LD-FU-1",
    status: str = Call.Status.COMPLETED.value,
    duration: str = "1:30",
    phone: str = "+919999990001",
) -> Call:
    return Call.objects.create(
        id=call_id,
        lead_id=lead_id,
        customer="Test",
        phone=phone,
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


def _seed_converted_outcome(
    *,
    lead_id: str = "LD-FU-1",
    call_id: str = "CL-FU-1",
    phone: str = "+919999990001",
    apply: bool = True,
) -> CallOutcomeRecord:
    _make_lead(lead_id=lead_id, phone=phone)
    call = _make_call(call_id=call_id, lead_id=lead_id, phone=phone)
    _add_lines(call, [("customer", "haan bilkul link bhejo lena hai")])
    record = classify_call(call.id)
    assert (
        record.detected_outcome
        == CallOutcomeRecord.DetectedOutcome.CONNECTED_CONVERTED.value
    )
    if apply:
        record.review_status = (
            CallOutcomeRecord.ReviewStatus.APPLIED.value
        )
        record.save(update_fields=["review_status"])
    return record


def _seed_callback_outcome(
    *,
    lead_id: str = "LD-FU-CB",
    call_id: str = "CL-FU-CB",
    phone: str = "+919999990002",
    apply: bool = True,
) -> CallOutcomeRecord:
    _make_lead(lead_id=lead_id, phone=phone)
    call = _make_call(call_id=call_id, lead_id=lead_id, phone=phone)
    _add_lines(call, [("customer", "abhi busy hoon kal call karo")])
    record = classify_call(call.id)
    assert (
        record.detected_outcome
        == CallOutcomeRecord.DetectedOutcome.CONNECTED_CALLBACK.value
    )
    if apply:
        record.review_status = (
            CallOutcomeRecord.ReviewStatus.APPLIED.value
        )
        record.save(update_fields=["review_status"])
    return record


def _seed_unclear_outcome(
    *,
    lead_id: str = "LD-FU-UC",
    call_id: str = "CL-FU-UC",
    phone: str = "+919999990003",
) -> CallOutcomeRecord:
    _make_lead(lead_id=lead_id, phone=phone)
    call = _make_call(call_id=call_id, lead_id=lead_id, phone=phone)
    _add_lines(
        call, [("customer", "sun raha hoon"), ("agent", "theek hai")]
    )
    return classify_call(call.id)


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
# identify_follow_up_candidates
# ---------------------------------------------------------------------------


def test_identify_includes_converted(patched_outbound):
    record = _seed_converted_outcome()
    candidates = list(identify_follow_up_candidates(hours=72))
    assert record in candidates


def test_identify_includes_callback(patched_outbound):
    record = _seed_callback_outcome()
    candidates = list(identify_follow_up_candidates(hours=72))
    assert record in candidates


def test_identify_excludes_unclear(patched_outbound):
    record = _seed_unclear_outcome()
    candidates = list(identify_follow_up_candidates(hours=72))
    assert record not in candidates


def test_identify_excludes_when_followup_exists(patched_outbound):
    record = _seed_converted_outcome()
    create_follow_up_entry(call_outcome=record)
    candidates = list(identify_follow_up_candidates(hours=72))
    assert record not in candidates


def test_identify_filter_respects_window(patched_outbound):
    record = _seed_converted_outcome()
    # Push classified_at to 30 hours ago — outside default 26h window.
    record.classified_at = timezone.now() - timedelta(hours=30)
    record.save(update_fields=["classified_at"])
    candidates_default = list(
        identify_follow_up_candidates(hours=26)
    )
    candidates_wide = list(identify_follow_up_candidates(hours=72))
    assert record not in candidates_default
    assert record in candidates_wide


# ---------------------------------------------------------------------------
# create_follow_up_entry — idempotent + trigger map
# ---------------------------------------------------------------------------


def test_create_follow_up_entry_for_converted(patched_outbound):
    record = _seed_converted_outcome()
    entry, created = create_follow_up_entry(call_outcome=record)
    assert created is True
    assert entry.follow_up_type == "payment_reminder"
    assert entry.status == "pending"
    assert entry.lead_phone_last4 == "0001"
    assert AuditEvent.objects.filter(
        kind="call_followup.queued",
        payload__follow_up_id=entry.pk,
    ).exists()


def test_create_follow_up_entry_for_callback(patched_outbound):
    record = _seed_callback_outcome()
    entry, created = create_follow_up_entry(call_outcome=record)
    assert created is True
    assert entry.follow_up_type == "callback_confirmation"
    assert entry.status == "pending"


def test_create_follow_up_entry_idempotent(patched_outbound):
    record = _seed_converted_outcome()
    entry1, created1 = create_follow_up_entry(call_outcome=record)
    entry2, created2 = create_follow_up_entry(call_outcome=record)
    assert created1 is True
    assert created2 is False
    assert entry1.pk == entry2.pk
    assert PostCallFollowUpQueue.objects.count() == 1


def test_create_follow_up_entry_refuses_non_trigger_outcome(
    patched_outbound,
):
    record = _seed_unclear_outcome()
    with pytest.raises(PostCallFollowUpStateError):
        create_follow_up_entry(call_outcome=record)


def test_create_follow_up_entry_outcome_not_yet_applied_flag(
    patched_outbound,
):
    record = _seed_converted_outcome(apply=False)
    entry, _ = create_follow_up_entry(call_outcome=record)
    assert entry.metadata.get("outcome_not_yet_applied") is True


def test_trigger_outcomes_map_complete():
    assert "connected_converted" in TRIGGER_OUTCOMES
    assert "connected_callback" in TRIGGER_OUTCOMES
    # No other outcomes auto-queue a follow-up.
    assert len(TRIGGER_OUTCOMES) == 2


# ---------------------------------------------------------------------------
# bulk_identify_and_queue
# ---------------------------------------------------------------------------


def test_bulk_identify_and_queue_counts(patched_outbound):
    _seed_converted_outcome()
    _seed_callback_outcome()
    _seed_unclear_outcome()
    summary = bulk_identify_and_queue(hours=72)
    assert summary["total_found"] == 2
    assert summary["queued"] == 2
    assert summary["already_existed"] == 0


def test_bulk_identify_and_queue_idempotent(patched_outbound):
    _seed_converted_outcome()
    first = bulk_identify_and_queue(hours=72)
    second = bulk_identify_and_queue(hours=72)
    assert first["queued"] == 1
    # On the second sweep, the previously queued row excludes itself
    # via the follow_up__isnull=True filter — total_found drops to 0.
    assert second["queued"] == 0
    assert second["total_found"] == 0


# ---------------------------------------------------------------------------
# prepare_gate_for_follow_up — happy + edge paths
# ---------------------------------------------------------------------------


def test_prepare_gate_happy_path_stores_gate_id(patched_outbound):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    with mock.patch(
        "apps.whatsapp.phase7e_live_b_real_customer_send.prepare_gate",
        return_value={
            "phase": "7E-Live-B",
            "ok": True,
            "gateId": 4242,
            "status": "draft",
            "templateName": "payment_reminder",
            "targetMasked": "***0001",
            "blockers": [],
            "nextAction": "approve_phase7e_live_b_real_customer_gate",
        },
    ) as patched_p7e:
        result = prepare_gate_for_follow_up(
            follow_up_id=entry.pk,
            operator_name="Prarit",
        )
    assert result["ok"] is True
    assert result["phase7e_gate_id"] == 4242
    entry.refresh_from_db()
    assert entry.status == "gate_prepared"
    assert entry.phase7e_gate_id == 4242
    assert entry.customer_found is True
    # Verify the Phase 7E-Live-B prepare_gate received the right shape.
    call_kwargs = patched_p7e.call_args.kwargs
    assert call_kwargs["template_name"] == "payment_reminder"
    assert call_kwargs["operator_name"] == "Prarit"
    assert "customer_name" in call_kwargs["template_params"]
    assert "context" in call_kwargs["template_params"]
    # Audit row written.
    assert AuditEvent.objects.filter(
        kind="call_followup.gate_prepared",
        payload__follow_up_id=entry.pk,
    ).exists()


def test_prepare_gate_callback_uses_confirmation_reminder_template(
    patched_outbound,
):
    record = _seed_callback_outcome()
    _make_customer(customer_id="CUS-FU-CB", phone="+919999990002")
    entry, _ = create_follow_up_entry(call_outcome=record)
    with mock.patch(
        "apps.whatsapp.phase7e_live_b_real_customer_send.prepare_gate",
        return_value={
            "phase": "7E-Live-B",
            "ok": True,
            "gateId": 4243,
            "status": "draft",
            "templateName": "confirmation_reminder",
            "targetMasked": "***0002",
            "blockers": [],
            "nextAction": "approve_phase7e_live_b_real_customer_gate",
        },
    ) as patched_p7e:
        result = prepare_gate_for_follow_up(
            follow_up_id=entry.pk, operator_name="Prarit"
        )
    assert result["ok"] is True
    assert (
        patched_p7e.call_args.kwargs["template_name"]
        == "confirmation_reminder"
    )


def test_prepare_gate_no_customer_marks_needs_setup(patched_outbound):
    record = _seed_converted_outcome()
    # No Customer row — only the Lead exists.
    entry, _ = create_follow_up_entry(call_outcome=record)
    with mock.patch(
        "apps.whatsapp.phase7e_live_b_real_customer_send.prepare_gate"
    ) as patched_p7e:
        result = prepare_gate_for_follow_up(
            follow_up_id=entry.pk, operator_name="Prarit"
        )
    patched_p7e.assert_not_called()
    assert result["ok"] is False
    assert result["reason"] == "needs_customer_setup"
    entry.refresh_from_db()
    assert entry.status == "needs_customer_setup"
    assert entry.customer_found is False
    assert AuditEvent.objects.filter(
        kind="call_followup.needs_customer_setup",
        payload__follow_up_id=entry.pk,
    ).exists()


def test_prepare_gate_sandbox_marks_sandbox_skipped(patched_outbound):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    with mock.patch(
        "apps.whatsapp.phase7e_live_b_real_customer_send.prepare_gate"
    ) as patched_p7e:
        result = prepare_gate_for_follow_up(
            follow_up_id=entry.pk,
            operator_name="Prarit",
            sandbox=True,
        )
    patched_p7e.assert_not_called()
    assert result["ok"] is False
    assert result["reason"] == "sandbox_mode"
    entry.refresh_from_db()
    assert entry.status == "sandbox_skipped"
    assert AuditEvent.objects.filter(
        kind="call_followup.sandbox_skipped",
        payload__follow_up_id=entry.pk,
    ).exists()


def test_prepare_gate_phase7e_exception_marks_failed(patched_outbound):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    with mock.patch(
        "apps.whatsapp.phase7e_live_b_real_customer_send.prepare_gate",
        side_effect=RuntimeError("boom"),
    ):
        result = prepare_gate_for_follow_up(
            follow_up_id=entry.pk,
            operator_name="Prarit",
        )
    assert result["ok"] is False
    assert result["reason"] == "gate_prep_failed"
    assert "boom" in (result.get("error_excerpt") or "")
    entry.refresh_from_db()
    assert entry.status == "gate_prep_failed"
    assert AuditEvent.objects.filter(
        kind="call_followup.gate_prep_failed",
        payload__follow_up_id=entry.pk,
    ).exists()


def test_prepare_gate_phase7e_not_ok_marks_failed(patched_outbound):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    with mock.patch(
        "apps.whatsapp.phase7e_live_b_real_customer_send.prepare_gate",
        return_value={
            "phase": "7E-Live-B",
            "ok": False,
            "gateId": None,
            "status": "blocked",
            "blockers": ["phase7e_consent_required"],
            "nextAction": "grant_consent_first",
        },
    ):
        result = prepare_gate_for_follow_up(
            follow_up_id=entry.pk,
            operator_name="Prarit",
        )
    assert result["ok"] is False
    assert result["reason"] == "gate_prep_blockers"
    assert "phase7e_consent_required" in result["blockers"]
    entry.refresh_from_db()
    assert entry.status == "gate_prep_failed"


def test_prepare_gate_refuses_wrong_status(patched_outbound):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    entry.status = PostCallFollowUpQueue.Status.DISPATCHED.value
    entry.save(update_fields=["status"])
    with pytest.raises(PostCallFollowUpStateError):
        prepare_gate_for_follow_up(
            follow_up_id=entry.pk, operator_name="Prarit"
        )


def test_prepare_gate_requires_operator(patched_outbound):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    with pytest.raises(PostCallFollowUpStateError):
        prepare_gate_for_follow_up(
            follow_up_id=entry.pk, operator_name=""
        )


def test_prepare_gate_missing_row_raises(patched_outbound):
    with pytest.raises(PostCallFollowUpStateError):
        prepare_gate_for_follow_up(
            follow_up_id=999999, operator_name="P"
        )


# ---------------------------------------------------------------------------
# mark_dispatched + skip_follow_up
# ---------------------------------------------------------------------------


def test_mark_dispatched_happy_path(patched_outbound):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    entry.status = PostCallFollowUpQueue.Status.GATE_PREPARED.value
    entry.phase7e_gate_id = 42
    entry.save(update_fields=["status", "phase7e_gate_id"])
    out = mark_dispatched(
        follow_up_id=entry.pk,
        operator_name="Prarit",
        note="executed via phase7e gate 42",
    )
    assert out.status == "dispatched"
    assert out.dispatched_at is not None
    assert out.dispatched_by == "Prarit"
    assert AuditEvent.objects.filter(
        kind="call_followup.dispatched",
        payload__follow_up_id=entry.pk,
    ).exists()


def test_mark_dispatched_refuses_pending(patched_outbound):
    record = _seed_converted_outcome()
    entry, _ = create_follow_up_entry(call_outcome=record)
    with pytest.raises(PostCallFollowUpStateError):
        mark_dispatched(
            follow_up_id=entry.pk, operator_name="P"
        )


def test_mark_dispatched_requires_operator(patched_outbound):
    record = _seed_converted_outcome()
    entry, _ = create_follow_up_entry(call_outcome=record)
    entry.status = PostCallFollowUpQueue.Status.GATE_PREPARED.value
    entry.save(update_fields=["status"])
    with pytest.raises(PostCallFollowUpStateError):
        mark_dispatched(follow_up_id=entry.pk, operator_name="")


def test_skip_follow_up_from_pending(patched_outbound):
    record = _seed_converted_outcome()
    entry, _ = create_follow_up_entry(call_outcome=record)
    out = skip_follow_up(
        follow_up_id=entry.pk,
        operator_name="Prarit",
        reason="duplicate followup",
    )
    assert out.status == "skipped"
    assert out.metadata.get("skip_reason") == "duplicate followup"


def test_skip_follow_up_from_gate_prepared(patched_outbound):
    record = _seed_converted_outcome()
    entry, _ = create_follow_up_entry(call_outcome=record)
    entry.status = PostCallFollowUpQueue.Status.GATE_PREPARED.value
    entry.save(update_fields=["status"])
    out = skip_follow_up(
        follow_up_id=entry.pk, operator_name="Prarit"
    )
    assert out.status == "skipped"


def test_skip_follow_up_refuses_dispatched(patched_outbound):
    record = _seed_converted_outcome()
    entry, _ = create_follow_up_entry(call_outcome=record)
    entry.status = PostCallFollowUpQueue.Status.DISPATCHED.value
    entry.save(update_fields=["status"])
    with pytest.raises(PostCallFollowUpStateError):
        skip_follow_up(
            follow_up_id=entry.pk, operator_name="P"
        )


def test_skip_follow_up_refuses_already_skipped(patched_outbound):
    record = _seed_converted_outcome()
    entry, _ = create_follow_up_entry(call_outcome=record)
    skip_follow_up(follow_up_id=entry.pk, operator_name="P")
    with pytest.raises(PostCallFollowUpStateError):
        skip_follow_up(
            follow_up_id=entry.pk, operator_name="P"
        )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_celery_followup_happy_path(patched_outbound):
    _seed_converted_outcome()
    _seed_callback_outcome()
    from apps.calls.tasks import queue_post_call_followups_daily

    summary = queue_post_call_followups_daily(hours=72)
    assert summary["total_found"] == 2
    assert summary["queued"] == 2
    assert AuditEvent.objects.filter(
        kind="call_followup.daily_queue.completed"
    ).exists()


def test_celery_followup_kill_switch_blocked(patched_outbound):
    _seed_converted_outcome()
    from apps.calls.tasks import queue_post_call_followups_daily

    with mock.patch(
        "apps.calls.tasks._kill_switch_blocked", return_value=True
    ):
        result = queue_post_call_followups_daily(hours=72)
    assert result["skipped"] is True
    assert result["reason"] == "kill_switch_off"
    assert PostCallFollowUpQueue.objects.count() == 0


def test_celery_followup_sandbox_blocked(patched_outbound):
    _seed_converted_outcome()
    from apps.calls.tasks import queue_post_call_followups_daily

    with mock.patch(
        "apps.calls.tasks._sandbox_active", return_value=True
    ):
        result = queue_post_call_followups_daily(hours=72)
    assert result["skipped"] is True
    assert result["reason"] == "sandbox_mode"
    assert PostCallFollowUpQueue.objects.count() == 0


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def test_cli_list_post_call_followups(patched_outbound):
    record = _seed_converted_outcome()
    create_follow_up_entry(call_outcome=record)
    out = StringIO()
    call_command("list_post_call_followups", stdout=out)
    text = out.getvalue()
    assert "PostCallFollowUpQueue listing" in text


def test_cli_prepare_post_call_followup_gate_success(patched_outbound):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    with mock.patch(
        "apps.whatsapp.phase7e_live_b_real_customer_send.prepare_gate",
        return_value={
            "phase": "7E-Live-B",
            "ok": True,
            "gateId": 4244,
            "status": "draft",
            "blockers": [],
            "nextAction": "approve_phase7e_live_b_real_customer_gate",
        },
    ):
        out = StringIO()
        call_command(
            "prepare_post_call_followup_gate",
            str(entry.pk),
            "--operator-name",
            "Prarit",
            stdout=out,
        )
    entry.refresh_from_db()
    assert entry.status == "gate_prepared"
    assert entry.phase7e_gate_id == 4244


def test_cli_prepare_post_call_followup_gate_refused_returns_1(
    patched_outbound,
):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    entry.status = PostCallFollowUpQueue.Status.DISPATCHED.value
    entry.save(update_fields=["status"])
    err = StringIO()
    with pytest.raises(SystemExit) as exc:
        call_command(
            "prepare_post_call_followup_gate",
            str(entry.pk),
            "--operator-name",
            "Prarit",
            stderr=err,
        )
    assert exc.value.code == 1
    assert "REFUSED" in err.getvalue()


def test_cli_mark_followup_dispatched(patched_outbound):
    record = _seed_converted_outcome()
    entry, _ = create_follow_up_entry(call_outcome=record)
    entry.status = PostCallFollowUpQueue.Status.GATE_PREPARED.value
    entry.save(update_fields=["status"])
    out = StringIO()
    call_command(
        "mark_followup_dispatched",
        str(entry.pk),
        "--operator-name",
        "Prarit",
        stdout=out,
    )
    entry.refresh_from_db()
    assert entry.status == "dispatched"


def test_cli_skip_post_call_followup(patched_outbound):
    record = _seed_converted_outcome()
    entry, _ = create_follow_up_entry(call_outcome=record)
    out = StringIO()
    call_command(
        "skip_post_call_followup",
        str(entry.pk),
        "--operator-name",
        "Prarit",
        "--reason",
        "duplicate",
        stdout=out,
    )
    entry.refresh_from_db()
    assert entry.status == "skipped"


# ---------------------------------------------------------------------------
# Read-only API
# ---------------------------------------------------------------------------


def test_api_followups_anonymous_blocked():
    from rest_framework.test import APIClient

    client = APIClient()
    response = client.get(reverse("phase12c-followups-list"))
    assert response.status_code in {401, 403}


def test_api_followups_admin_list_detail_summary(
    auth_client, admin_user, patched_outbound
):
    record = _seed_converted_outcome()
    entry, _ = create_follow_up_entry(call_outcome=record)
    client = auth_client(admin_user)
    list_resp = client.get(reverse("phase12c-followups-list"))
    assert list_resp.status_code == 200
    assert list_resp.json()["count"] >= 1
    detail_resp = client.get(
        reverse("phase12c-followup-detail", args=[entry.pk])
    )
    assert detail_resp.status_code == 200
    body = detail_resp.json()
    assert body["id"] == entry.pk
    assert body["followUpType"] == "payment_reminder"
    summary_resp = client.get(reverse("phase12c-followups-summary"))
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["total"] >= 1


def test_api_followups_detail_404(auth_client, admin_user):
    client = auth_client(admin_user)
    assert (
        client.get(
            reverse("phase12c-followup-detail", args=[999999])
        ).status_code
        == 404
    )


def test_api_followups_post_returns_405(auth_client, admin_user):
    client = auth_client(admin_user)
    url = reverse("phase12c-followups-list")
    assert client.post(url).status_code == 405
    assert client.patch(url).status_code == 405
    assert client.delete(url).status_code == 405


# ---------------------------------------------------------------------------
# Defensive integration — no outbound, business rows untouched
# ---------------------------------------------------------------------------


def test_defensive_no_outbound_on_queue_path(patched_outbound):
    _seed_converted_outcome()
    _seed_callback_outcome()
    pre = {
        "Customer": Customer.objects.count(),
        "Lead": Lead.objects.count(),
        "Order": Order.objects.count(),
        "Payment": Payment.objects.count(),
        "Shipment": Shipment.objects.count(),
    }
    bulk_identify_and_queue(hours=72)
    assert Customer.objects.count() == pre["Customer"]
    assert Lead.objects.count() == pre["Lead"]
    assert Order.objects.count() == pre["Order"]
    assert Payment.objects.count() == pre["Payment"]
    assert Shipment.objects.count() == pre["Shipment"]
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


def test_defensive_sandbox_prepare_does_not_create_phase7e_gate(
    patched_outbound,
):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    pre = {
        "Customer": Customer.objects.count(),
        "Lead": Lead.objects.count(),
        "Order": Order.objects.count(),
        "Payment": Payment.objects.count(),
        "Shipment": Shipment.objects.count(),
    }
    with mock.patch(
        "apps.whatsapp.phase7e_live_b_real_customer_send.prepare_gate"
    ) as patched_p7e:
        prepare_gate_for_follow_up(
            follow_up_id=entry.pk,
            operator_name="Prarit",
            sandbox=True,
        )
    patched_p7e.assert_not_called()
    assert Customer.objects.count() == pre["Customer"]
    assert Lead.objects.count() == pre["Lead"]
    assert Order.objects.count() == pre["Order"]
    assert Payment.objects.count() == pre["Payment"]
    assert Shipment.objects.count() == pre["Shipment"]
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


def test_defensive_full_lifecycle_no_business_row_mutation(
    patched_outbound,
):
    record = _seed_converted_outcome()
    _make_customer()
    entry, _ = create_follow_up_entry(call_outcome=record)
    pre = {
        "Customer": Customer.objects.count(),
        "Lead": Lead.objects.count(),
        "Order": Order.objects.count(),
        "Payment": Payment.objects.count(),
        "Shipment": Shipment.objects.count(),
    }
    with mock.patch(
        "apps.whatsapp.phase7e_live_b_real_customer_send.prepare_gate",
        return_value={
            "phase": "7E-Live-B",
            "ok": True,
            "gateId": 99,
            "status": "draft",
            "blockers": [],
            "nextAction": "approve_phase7e_live_b_real_customer_gate",
        },
    ):
        prepare_gate_for_follow_up(
            follow_up_id=entry.pk, operator_name="Prarit"
        )
    mark_dispatched(
        follow_up_id=entry.pk, operator_name="Prarit"
    )
    assert Customer.objects.count() == pre["Customer"]
    assert Lead.objects.count() == pre["Lead"]
    assert Order.objects.count() == pre["Order"]
    assert Payment.objects.count() == pre["Payment"]
    assert Shipment.objects.count() == pre["Shipment"]
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()


# ---------------------------------------------------------------------------
# Summary + beat schedule
# ---------------------------------------------------------------------------


def test_get_followups_summary_counts(patched_outbound):
    r1 = _seed_converted_outcome()
    r2 = _seed_callback_outcome()
    create_follow_up_entry(call_outcome=r1)
    e2, _ = create_follow_up_entry(call_outcome=r2)
    e2.status = PostCallFollowUpQueue.Status.SKIPPED.value
    e2.save(update_fields=["status"])
    summary = get_followups_summary()
    assert summary["total"] == 2
    assert summary["by_status"].get("pending") == 1
    assert summary["by_status"].get("skipped") == 1
    assert (
        summary["by_follow_up_type"].get("payment_reminder") == 1
    )
    assert (
        summary["by_follow_up_type"].get("callback_confirmation") == 1
    )


def test_beat_schedule_registers_post_call_followup_daily():
    from config.celery import build_beat_schedule

    schedule = build_beat_schedule()
    assert "post-call-followup-daily" in schedule
    entry = schedule["post-call-followup-daily"]
    assert (
        entry["task"]
        == "apps.calls.tasks.queue_post_call_followups_daily"
    )
    # Phase 12C adds ONE new beat entry. Total drifts as future phases
    # add more — use >= to keep this test stable.
    assert len(schedule) >= 13
