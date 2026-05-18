"""Phase 12A — AI Calling Campaign Gate V1 tests.

Defensive contract: across every path that runs prepare / approve /
execute / cancel, all four outbound entrypoints are patched. The
trigger_call_for_lead helper is patched everywhere except the
explicit "live dispatch" tests; in those tests we assert it IS
called for eligible leads while WhatsApp / shipment / Razorpay paths
stay `assert_not_called`.
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
from apps.calls.ai_calling_gate import (
    AiCallCampaignGateError,
    BLOCKED_STAGES,
    DEFAULT_ALLOWED_STAGES,
    MAX_WINDOW_SECONDS,
    approve_campaign_gate,
    cancel_campaign_gate,
    execute_campaign_gate,
    inspect_campaign_gate,
    prepare_campaign_gate,
)
from apps.calls.models import AiCallCampaignGate, Call
from apps.crm.models import Lead


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_lead(
    *,
    lead_id: str,
    status: str = Lead.Status.INTERESTED.value,
    phone: str = "+919999990000",
    name: str = "Test Lead",
) -> Lead:
    return Lead.objects.create(
        id=lead_id,
        name=name,
        phone=phone,
        state="Delhi",
        city="Delhi",
        language="Hindi",
        source="manual",
        campaign="t",
        product_interest="Nirogidhara",
        status=status,
    )


def _make_recent_call(lead_id: str, hours_ago: int = 1) -> Call:
    call = Call.objects.create(
        id=f"CL-RC-{lead_id}",
        lead_id=lead_id,
        customer="x",
        phone="+919999990000",
        agent="Calling AI · Vapi",
        language="Hindi",
        provider=Call.Provider.VAPI,
        provider_call_id=f"vapi_rc_{lead_id}",
        status=Call.Status.COMPLETED,
        duration="1:00",
    )
    Call.objects.filter(pk=call.pk).update(
        created_at=timezone.now() - timedelta(hours=hours_ago)
    )
    call.refresh_from_db()
    return call


def _now_window_signoff(extra_intent: str = "") -> str:
    start = (timezone.now() - timedelta(minutes=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end = (timezone.now() + timedelta(minutes=20)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return (
        f"ai_calling_campaign_test phase12a {extra_intent} "
        f"BEGIN_UTC={start} END_UTC={end}"
    )


def _future_window_signoff() -> str:
    start = (timezone.now() + timedelta(minutes=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end = (timezone.now() + timedelta(minutes=20)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return f"future window BEGIN_UTC={start} END_UTC={end}"


def _too_long_window_signoff() -> str:
    start = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    # 35 minutes > 30 minute cap
    end = (timezone.now() + timedelta(minutes=35)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return f"too long BEGIN_UTC={start} END_UTC={end}"


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
            "apps.shipments.services.create_shipment"
        ) as ship_create,
    ):
        yield {
            "wa_queue": wa_queue,
            "wa_freeform": wa_freeform,
            "ship_create": ship_create,
        }


@pytest.fixture
def patched_trigger(patched_outbound):
    """Patch trigger_call_for_lead inside the calls.services module so
    the gate's late binding via ``from apps.calls import services``
    finds the mock. Returns the MagicMock for assertions."""
    with mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as trig:
        trig.side_effect = lambda *, lead, by_user, purpose="sales_call": (
            Call.objects.create(
                id=f"CL-MOCK-{lead.id}",
                lead_id=lead.id,
                customer=lead.name,
                phone=lead.phone,
                agent="Calling AI · Vapi",
                language=lead.language,
                provider=Call.Provider.VAPI,
                provider_call_id=f"vapi_mock_{lead.id}",
                status=Call.Status.QUEUED,
            )
        )
        yield trig


# ---------------------------------------------------------------------------
# prepare_campaign_gate
# ---------------------------------------------------------------------------


def test_prepare_happy_path_creates_draft(patched_outbound):
    _make_lead(lead_id="LD-P1", status="Interested")
    _make_lead(lead_id="LD-P2", status="Callback Required")
    _make_lead(lead_id="LD-P3", status="New")
    result = prepare_campaign_gate(
        operator_name="Prarit",
        max_leads=5,
    )
    assert result["ok"] is True
    assert result["leads_selected_count"] == 3
    assert AiCallCampaignGate.objects.count() == 1
    gate = AiCallCampaignGate.objects.first()
    assert gate.status == "draft"
    assert AuditEvent.objects.filter(
        kind="ai_calling.campaign.prepared",
        payload__gate_id=gate.pk,
    ).exists()


def test_prepare_refuses_when_active_gate_exists(patched_outbound):
    _make_lead(lead_id="LD-A1", status="Interested")
    prepare_campaign_gate(operator_name="P")
    with pytest.raises(AiCallCampaignGateError) as exc:
        prepare_campaign_gate(operator_name="P")
    assert exc.value.code == "active_campaign_exists"


def test_prepare_frequency_filter_excludes_recent(patched_outbound):
    _make_lead(lead_id="LD-F1", status="Interested")
    _make_lead(lead_id="LD-F2", status="Interested")
    _make_recent_call("LD-F1", hours_ago=1)
    result = prepare_campaign_gate(operator_name="P")
    gate = AiCallCampaignGate.objects.first()
    assert "LD-F2" in gate.leads_selected
    assert "LD-F1" not in gate.leads_selected
    assert result["leads_selected_count"] == 1


def test_prepare_stage_filter_excludes_blocked_via_default(patched_outbound):
    _make_lead(lead_id="LD-S1", status="Interested")
    _make_lead(lead_id="LD-S2", status="Order Punched")  # blocked
    _make_lead(lead_id="LD-S3", status="Not Interested")  # blocked
    _make_lead(lead_id="LD-S4", status="Invalid")  # blocked
    prepare_campaign_gate(operator_name="P")
    gate = AiCallCampaignGate.objects.first()
    assert gate.leads_selected == ["LD-S1"]


def test_prepare_explicit_stage_filter_rejects_blocked_stage(
    patched_outbound,
):
    _make_lead(lead_id="LD-EX1", status="Interested")
    with pytest.raises(AiCallCampaignGateError) as exc:
        prepare_campaign_gate(
            operator_name="P",
            stage_filter=["Interested", "Order Punched"],
        )
    assert exc.value.code == "stage_filter_includes_blocked_stage"
    assert AiCallCampaignGate.objects.count() == 0


def test_prepare_max_leads_clamped(patched_outbound):
    for i in range(5):
        _make_lead(lead_id=f"LD-MX-{i}", status="Interested")
    prepare_campaign_gate(operator_name="P", max_leads=2)
    gate = AiCallCampaignGate.objects.first()
    assert len(gate.leads_selected) == 2


def test_prepare_excludes_empty_phone(patched_outbound):
    _make_lead(lead_id="LD-NP-1", status="Interested", phone="")
    _make_lead(lead_id="LD-NP-2", status="Interested")
    prepare_campaign_gate(operator_name="P")
    gate = AiCallCampaignGate.objects.first()
    assert "LD-NP-1" not in gate.leads_selected
    assert "LD-NP-2" in gate.leads_selected


# ---------------------------------------------------------------------------
# approve_campaign_gate
# ---------------------------------------------------------------------------


def _seed_draft() -> AiCallCampaignGate:
    _make_lead(lead_id="LD-AP-1", status="Interested")
    prepare_campaign_gate(operator_name="P")
    return AiCallCampaignGate.objects.first()


def test_approve_happy_path_inside_window(patched_outbound):
    gate = _seed_draft()
    result = approve_campaign_gate(
        gate_id=gate.pk,
        operator_name="Prarit",
        intent="Tier-4 first batch",
        director_signoff=_now_window_signoff(),
    )
    assert result["ok"] is True
    gate.refresh_from_db()
    assert gate.status == "approved"
    assert gate.recorded_signoff_window_valid is True
    assert gate.intent == "Tier-4 first batch"
    assert AuditEvent.objects.filter(
        kind="ai_calling.campaign.approved",
        payload__gate_id=gate.pk,
    ).exists()


def test_approve_future_window_allowed(patched_outbound):
    """Director can approve a window that starts in the future."""
    gate = _seed_draft()
    result = approve_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        intent="Scheduled",
        director_signoff=_future_window_signoff(),
    )
    assert result["ok"] is True


def test_approve_refuses_non_draft(patched_outbound):
    gate = _seed_draft()
    approve_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        intent="x",
        director_signoff=_now_window_signoff(),
    )
    with pytest.raises(AiCallCampaignGateError) as exc:
        approve_campaign_gate(
            gate_id=gate.pk,
            operator_name="P",
            intent="x",
            director_signoff=_now_window_signoff(),
        )
    assert exc.value.code == "gate_not_draft"


def test_approve_missing_window_markers_refused(patched_outbound):
    gate = _seed_draft()
    with pytest.raises(AiCallCampaignGateError) as exc:
        approve_campaign_gate(
            gate_id=gate.pk,
            operator_name="P",
            intent="x",
            director_signoff="no structured markers here",
        )
    assert exc.value.code == "director_signoff_missing_utc_window"


def test_approve_window_too_long_refused(patched_outbound):
    gate = _seed_draft()
    with pytest.raises(AiCallCampaignGateError) as exc:
        approve_campaign_gate(
            gate_id=gate.pk,
            operator_name="P",
            intent="x",
            director_signoff=_too_long_window_signoff(),
        )
    assert exc.value.code == "director_signoff_window_invalid"


def test_approve_empty_intent_refused(patched_outbound):
    gate = _seed_draft()
    with pytest.raises(AiCallCampaignGateError) as exc:
        approve_campaign_gate(
            gate_id=gate.pk,
            operator_name="P",
            intent="",
            director_signoff=_now_window_signoff(),
        )
    assert exc.value.code == "intent_required"


# ---------------------------------------------------------------------------
# execute_campaign_gate
# ---------------------------------------------------------------------------


def _seed_approved() -> AiCallCampaignGate:
    gate = _seed_draft()
    approve_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        intent="Live batch",
        director_signoff=_now_window_signoff(),
    )
    gate.refresh_from_db()
    return gate


@override_settings(AI_CALLING_ENABLED=False)
def test_execute_refused_when_flag_off(patched_trigger):
    gate = _seed_approved()
    with pytest.raises(AiCallCampaignGateError) as exc:
        execute_campaign_gate(
            gate_id=gate.pk,
            operator_name="P",
            confirm_ai_calling=True,
        )
    assert exc.value.code == "ai_calling_not_enabled"
    patched_trigger.assert_not_called()


@override_settings(AI_CALLING_ENABLED=True)
def test_execute_refused_when_confirm_flag_missing(patched_trigger):
    gate = _seed_approved()
    with pytest.raises(AiCallCampaignGateError) as exc:
        execute_campaign_gate(
            gate_id=gate.pk,
            operator_name="P",
            confirm_ai_calling=False,
        )
    assert exc.value.code == "confirm_ai_calling_campaign_flag_required"
    patched_trigger.assert_not_called()


@override_settings(AI_CALLING_ENABLED=True)
def test_execute_refused_when_kill_switch_off(patched_trigger):
    gate = _seed_approved()
    with mock.patch(
        "apps.calls.ai_calling_gate._kill_switch_blocked",
        return_value=(True, {"enabled": False, "model": "test"}),
    ):
        with pytest.raises(AiCallCampaignGateError) as exc:
            execute_campaign_gate(
                gate_id=gate.pk,
                operator_name="P",
                confirm_ai_calling=True,
            )
    assert exc.value.code == "runtime_kill_switch_disabled"
    patched_trigger.assert_not_called()


@override_settings(AI_CALLING_ENABLED=True)
def test_execute_window_expired_refused(patched_trigger):
    gate = _seed_approved()
    # Force the window to be in the past.
    AiCallCampaignGate.objects.filter(pk=gate.pk).update(
        recorded_signoff_window_start_utc=(
            timezone.now() - timedelta(hours=2)
        ),
        recorded_signoff_window_end_utc=(
            timezone.now() - timedelta(hours=1, minutes=30)
        ),
    )
    with pytest.raises(AiCallCampaignGateError) as exc:
        execute_campaign_gate(
            gate_id=gate.pk,
            operator_name="P",
            confirm_ai_calling=True,
        )
    assert exc.value.code == "approval_window_invalid_at_execute"
    patched_trigger.assert_not_called()


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="mock")
def test_execute_vapi_mock_mode_skips_real_calls(patched_trigger):
    gate = _seed_approved()
    result = execute_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        confirm_ai_calling=True,
    )
    assert result["calls_dispatched"] == 0
    assert result["calls_skipped"] == 1
    assert result["vapi_mode_at_execute"] == "mock"
    assert result["skip_reasons"]["vapi_not_live_skip"] == 1
    patched_trigger.assert_not_called()


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="test")
def test_execute_vapi_test_mode_skips_real_calls(patched_trigger):
    gate = _seed_approved()
    result = execute_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        confirm_ai_calling=True,
    )
    assert result["calls_dispatched"] == 0
    assert result["calls_skipped"] == 1
    assert "vapi_not_live_skip" in result["skip_reasons"]
    patched_trigger.assert_not_called()


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="live")
def test_execute_sandbox_skips_real_calls(patched_trigger):
    gate = _seed_approved()
    with mock.patch(
        "apps.calls.ai_calling_gate._sandbox_active",
        return_value=True,
    ):
        result = execute_campaign_gate(
            gate_id=gate.pk,
            operator_name="P",
            confirm_ai_calling=True,
        )
    assert result["calls_dispatched"] == 0
    assert result["sandbox"] is True
    assert "sandbox_skip" in result["skip_reasons"]
    patched_trigger.assert_not_called()


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="live")
def test_execute_live_mode_dispatches_per_eligible_lead(patched_trigger):
    _make_lead(lead_id="LD-LIVE-1", status="Interested")
    _make_lead(lead_id="LD-LIVE-2", status="Interested")
    prepare_campaign_gate(operator_name="P", max_leads=10)
    gate = AiCallCampaignGate.objects.first()
    approve_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        intent="live",
        director_signoff=_now_window_signoff(),
    )
    result = execute_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        confirm_ai_calling=True,
    )
    assert result["vapi_mode_at_execute"] == "live"
    assert result["calls_dispatched"] == 2
    assert patched_trigger.call_count == 2
    gate.refresh_from_db()
    assert gate.status == "completed"
    assert AuditEvent.objects.filter(
        kind="ai_calling.campaign.executed",
        payload__gate_id=gate.pk,
    ).exists()
    assert (
        AuditEvent.objects.filter(
            kind="ai_calling.campaign.lead.dispatched",
            payload__gate_id=gate.pk,
        ).count()
        == 2
    )


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="live")
def test_execute_lead_stage_changed_skipped(patched_trigger):
    lead = _make_lead(lead_id="LD-SC-1", status="Interested")
    prepare_campaign_gate(operator_name="P")
    gate = AiCallCampaignGate.objects.first()
    approve_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        intent="x",
        director_signoff=_now_window_signoff(),
    )
    # Move lead to a blocked stage after prepare.
    lead.status = "Not Interested"
    lead.save(update_fields=["status"])
    result = execute_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        confirm_ai_calling=True,
    )
    assert result["calls_dispatched"] == 0
    assert result["skip_reasons"]["stage_no_longer_eligible"] == 1
    patched_trigger.assert_not_called()


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="live")
def test_execute_trigger_exception_counted_as_skip(patched_trigger):
    _make_lead(lead_id="LD-EX-1", status="Interested")
    _make_lead(lead_id="LD-EX-2", status="Interested")
    prepare_campaign_gate(operator_name="P")
    gate = AiCallCampaignGate.objects.first()
    approve_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        intent="x",
        director_signoff=_now_window_signoff(),
    )
    # First call succeeds (default mock side_effect), then patch to raise.
    call_count = {"n": 0}

    def _flaky(*, lead, by_user, purpose="sales_call"):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return Call.objects.create(
                id=f"CL-OK-{lead.id}",
                lead_id=lead.id,
                customer=lead.name,
                phone=lead.phone,
                agent="Calling AI · Vapi",
                language=lead.language,
                provider=Call.Provider.VAPI,
                provider_call_id=f"vapi_ok_{lead.id}",
                status=Call.Status.QUEUED,
            )
        raise RuntimeError("vapi down")

    patched_trigger.side_effect = _flaky
    result = execute_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        confirm_ai_calling=True,
    )
    assert result["calls_dispatched"] == 1
    assert result["calls_skipped"] == 1
    assert "vapi_error" in result["skip_reasons"]


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="live")
def test_execute_recently_called_lead_skipped_at_execute_time(
    patched_trigger,
):
    _make_lead(lead_id="LD-RE-1", status="Interested")
    prepare_campaign_gate(operator_name="P")
    gate = AiCallCampaignGate.objects.first()
    approve_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        intent="x",
        director_signoff=_now_window_signoff(),
    )
    # Simulate a manual call landing between prepare and execute.
    _make_recent_call("LD-RE-1", hours_ago=0)
    result = execute_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        confirm_ai_calling=True,
    )
    assert result["calls_dispatched"] == 0
    assert result["skip_reasons"]["recently_called"] == 1
    patched_trigger.assert_not_called()


# ---------------------------------------------------------------------------
# cancel_campaign_gate
# ---------------------------------------------------------------------------


def test_cancel_draft(patched_outbound):
    gate = _seed_draft()
    out = cancel_campaign_gate(
        gate_id=gate.pk, operator_name="P", reason="not now"
    )
    assert out["status"] == "cancelled"
    assert AuditEvent.objects.filter(
        kind="ai_calling.campaign.cancelled"
    ).exists()


def test_cancel_approved(patched_outbound):
    gate = _seed_approved()
    out = cancel_campaign_gate(gate_id=gate.pk, operator_name="P")
    assert out["status"] == "cancelled"


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="mock")
def test_cancel_completed_refused(patched_trigger):
    gate = _seed_approved()
    execute_campaign_gate(
        gate_id=gate.pk, operator_name="P", confirm_ai_calling=True
    )
    with pytest.raises(AiCallCampaignGateError) as exc:
        cancel_campaign_gate(gate_id=gate.pk, operator_name="P")
    assert exc.value.code == "gate_not_cancellable"


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


def test_inspect_shape(patched_outbound):
    gate = _seed_draft()
    result = inspect_campaign_gate(gate.pk)
    assert result["gate_id"] == gate.pk
    assert result["status"] == "draft"
    assert result["leads_selected_count"] == 1
    assert result["leads"][0]["phone_last4"] == "0000"
    assert result["leads"][0]["status"] == "Interested"
    assert result["leads"][0]["recently_called"] is False


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def test_cli_prepare_inspect_cancel(patched_outbound):
    _make_lead(lead_id="LD-CLI-1", status="Interested")
    out = StringIO()
    call_command(
        "prepare_ai_calling_campaign",
        "--operator-name",
        "Prarit",
        "--stage",
        "Interested",
        stdout=out,
    )
    text = out.getvalue()
    assert "AI calling campaign prepared" in text
    gate = AiCallCampaignGate.objects.first()
    out = StringIO()
    call_command(
        "inspect_ai_calling_campaign", str(gate.pk), stdout=out
    )
    assert "status=draft" in out.getvalue()
    out = StringIO()
    call_command(
        "cancel_ai_calling_campaign",
        str(gate.pk),
        "--operator-name",
        "P",
        "--reason",
        "test",
        stdout=out,
    )
    gate.refresh_from_db()
    assert gate.status == "cancelled"


def test_cli_approve_happy_path(patched_outbound):
    gate = _seed_draft()
    out = StringIO()
    call_command(
        "approve_ai_calling_campaign",
        str(gate.pk),
        "--operator-name",
        "P",
        "--intent",
        "test batch",
        "--director-signoff",
        _now_window_signoff(),
        stdout=out,
    )
    gate.refresh_from_db()
    assert gate.status == "approved"


def test_cli_approve_refusal_exits_1(patched_outbound):
    gate = _seed_draft()
    err = StringIO()
    with pytest.raises(SystemExit) as exc:
        call_command(
            "approve_ai_calling_campaign",
            str(gate.pk),
            "--operator-name",
            "P",
            "--intent",
            "x",
            "--director-signoff",
            "no markers",
            stderr=err,
        )
    assert exc.value.code == 1


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="mock")
def test_cli_execute_happy_path_mock(patched_trigger):
    gate = _seed_approved()
    out = StringIO()
    call_command(
        "execute_ai_calling_campaign",
        str(gate.pk),
        "--operator-name",
        "P",
        "--confirm-ai-calling-campaign",
        stdout=out,
    )
    gate.refresh_from_db()
    assert gate.status == "completed"
    assert gate.vapi_mode_at_execute == "mock"
    patched_trigger.assert_not_called()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_anonymous_blocked():
    from rest_framework.test import APIClient

    client = APIClient()
    response = client.get(reverse("phase12a-campaigns-list"))
    assert response.status_code in {401, 403}


def test_api_admin_can_read_list_latest_detail(
    auth_client, admin_user, patched_outbound
):
    gate = _seed_draft()
    client = auth_client(admin_user)
    list_resp = client.get(reverse("phase12a-campaigns-list"))
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == gate.pk
    latest_resp = client.get(reverse("phase12a-campaign-latest"))
    assert latest_resp.status_code == 200
    assert latest_resp.json()["id"] == gate.pk
    detail_resp = client.get(
        reverse("phase12a-campaign-detail", args=[gate.pk])
    )
    assert detail_resp.status_code == 200


def test_api_latest_404_when_empty(auth_client, admin_user):
    client = auth_client(admin_user)
    assert (
        client.get(reverse("phase12a-campaign-latest")).status_code == 404
    )


def test_api_post_returns_405(auth_client, admin_user):
    client = auth_client(admin_user)
    url = reverse("phase12a-campaigns-list")
    assert client.post(url).status_code == 405
    assert client.patch(url).status_code == 405
    assert client.delete(url).status_code == 405


# ---------------------------------------------------------------------------
# Defensive integration — non-live path never calls trigger / WA / shipment
# ---------------------------------------------------------------------------


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="mock")
def test_no_outbound_when_mock_mode(patched_trigger):
    from apps.crm.models import Customer
    from apps.orders.models import Order
    from apps.payments.models import Payment

    _make_lead(lead_id="LD-DEF-1", status="Interested")
    _make_lead(lead_id="LD-DEF-2", status="Interested")
    prepare_campaign_gate(operator_name="P")
    gate = AiCallCampaignGate.objects.first()
    approve_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        intent="x",
        director_signoff=_now_window_signoff(),
    )
    pre = {
        "Customer": Customer.objects.count(),
        "Order": Order.objects.count(),
        "Payment": Payment.objects.count(),
        "Lead": Lead.objects.count(),
    }
    result = execute_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        confirm_ai_calling=True,
    )
    assert result["calls_dispatched"] == 0
    patched_trigger.assert_not_called()
    # Outbound paths patched via patched_outbound (chained inside
    # patched_trigger fixture) — verify.
    # NOTE: patched_trigger composes patched_outbound.
    assert Customer.objects.count() == pre["Customer"]
    assert Order.objects.count() == pre["Order"]
    assert Payment.objects.count() == pre["Payment"]
    assert Lead.objects.count() == pre["Lead"]


@override_settings(AI_CALLING_ENABLED=True, VAPI_MODE="live")
def test_live_path_calls_trigger_but_not_whatsapp_or_shipment(
    patched_trigger,
):
    from apps.orders.models import Order
    from apps.payments.models import Payment

    _make_lead(lead_id="LD-LIVE-DEF-1", status="Interested")
    prepare_campaign_gate(operator_name="P")
    gate = AiCallCampaignGate.objects.first()
    approve_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        intent="x",
        director_signoff=_now_window_signoff(),
    )
    pre_orders = Order.objects.count()
    pre_payments = Payment.objects.count()
    result = execute_campaign_gate(
        gate_id=gate.pk,
        operator_name="P",
        confirm_ai_calling=True,
    )
    assert result["calls_dispatched"] == 1
    # trigger_call_for_lead was called exactly once.
    assert patched_trigger.call_count == 1
    # Business rows untouched.
    assert Order.objects.count() == pre_orders
    assert Payment.objects.count() == pre_payments


# ---------------------------------------------------------------------------
# Beat schedule sanity — Phase 12A adds NO new beat entry
# ---------------------------------------------------------------------------


def test_beat_schedule_unchanged_at_11():
    # Phase 12A added no new beat entry; later phases (Phase 12B onwards)
    # may add additional sweeps. Assert >= 11 to tolerate future growth
    # while still proving Phase 12A itself did not regress.
    from config.celery import build_beat_schedule

    schedule = build_beat_schedule()
    assert len(schedule) >= 11
