from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.saas.models import RuntimeKillSwitch
from apps.whatsapp.models import Phase7ELiveBRealCustomerSendGate
from apps.whatsapp.phase7e_live_b_real_customer_send import (
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_CANCELLED,
    AUDIT_KIND_EXECUTED,
    ENV_FLAG,
)


pytestmark = pytest.mark.django_db


PHONE = "+919999991203"
SECOND_PHONE = "+919999994506"


def _json_call(command: str, *args: str) -> dict:
    out = StringIO()
    call_command(command, *args, "--json", stdout=out)
    return json.loads(out.getvalue())


def _prepare_gate(
    *,
    phone: str = PHONE,
    customer_name: str = "Real Customer",
    template_name: str = "payment_reminder",
    template_params: dict[str, str] | None = None,
) -> Phase7ELiveBRealCustomerSendGate:
    params = template_params or {
        "customer_name": customer_name,
        "payment_url": "https://rzp.io/test/p7e-live-b",
    }
    report = _json_call(
        "prepare_phase7e_live_b_real_customer_gate",
        "--target-phone",
        phone,
        "--target-customer-name",
        customer_name,
        "--template-name",
        template_name,
        "--template-params",
        json.dumps(params),
        "--operator-name",
        "Prarit Sidana",
    )
    assert report["ok"] is True
    return Phase7ELiveBRealCustomerSendGate.objects.get(pk=report["gateId"])


def _window(*, before_minutes: int = 1, after_minutes: int = 10) -> tuple[str, str]:
    start = (timezone.now() - timedelta(minutes=before_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end = (timezone.now() + timedelta(minutes=after_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return start, end


def _last4(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-4:]


def _signoff(gate: Phase7ELiveBRealCustomerSendGate, *, outside: bool = False) -> str:
    if outside:
        begin = (timezone.now() + timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        end = (timezone.now() + timedelta(minutes=20)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    else:
        begin, end = _window()
    return (
        f"phase7e_live_b_gate_id_{gate.pk} "
        f"target_phone_{_last4(gate.target_phone)} template_{gate.template_name} "
        f"phase7eLiveBApproval BEGIN_UTC={begin} END_UTC={end}"
    )


def _customer() -> Customer:
    return Customer.objects.create(
        id="CL-P7E-LIVE-B",
        name="Real Customer",
        phone=PHONE,
        state="Delhi",
        city="Delhi",
        language="Hindi",
        product_interest="Nirogidhara",
        disease_category="general",
        consent_whatsapp=True,
    )


def test_inspect_flag_off_vs_on():
    off = _json_call("inspect_phase7e_live_b_real_customer_gate", "--no-audit")
    assert off["status"] == "blocked"
    assert f"{ENV_FLAG}_must_be_true" in off["blockers"]

    with override_settings(PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=True):
        on = _json_call("inspect_phase7e_live_b_real_customer_gate", "--no-audit")

    assert on["flagEnabled"] is True
    assert on["killSwitch"]["enabled"] is True


def test_prepare_valid_template_and_invalid_template():
    valid = _json_call(
        "prepare_phase7e_live_b_real_customer_gate",
        "--target-phone",
        PHONE,
        "--target-customer-name",
        "Real Customer",
        "--template-name",
        "confirmation_reminder",
        "--operator-name",
        "Operator",
    )
    assert valid["ok"] is True
    assert valid["status"] == "draft"
    assert valid["targetMasked"].endswith("1203")

    invalid = _json_call(
        "prepare_phase7e_live_b_real_customer_gate",
        "--target-phone",
        PHONE,
        "--target-customer-name",
        "Real Customer",
        "--template-name",
        "freeform_pitch",
        "--operator-name",
        "Operator",
    )
    assert invalid["ok"] is False
    assert "phase7e_live_b_template_name_not_approved" in invalid["blockers"]


@override_settings(PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=True)
def test_approve_happy_path_writes_audit():
    gate = _prepare_gate()

    report = _json_call(
        "approve_phase7e_live_b_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7e-live-b-real-customer-send",
    )

    gate.refresh_from_db()
    assert report["ok"] is True
    assert gate.status == Phase7ELiveBRealCustomerSendGate.Status.APPROVED
    assert gate.recorded_signoff_window_start_utc is not None
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_APPROVED).exists()


@override_settings(PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=True)
def test_approve_bad_signoff_missing_window_and_wrong_status():
    gate = _prepare_gate()
    bad = _json_call(
        "approve_phase7e_live_b_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        "phase7eLiveBApproval",
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7e-live-b-real-customer-send",
    )
    assert bad["ok"] is False
    assert "phase7e_live_b_director_signoff_missing_structured_utc_window" in bad[
        "blockers"
    ]

    gate.status = Phase7ELiveBRealCustomerSendGate.Status.CANCELLED
    gate.save(update_fields=["status", "updated_at"])
    wrong_status = _json_call(
        "approve_phase7e_live_b_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7e-live-b-real-customer-send",
    )
    assert wrong_status["ok"] is False
    assert "phase7e_live_b_gate_status_cancelled_not_draft" in wrong_status["blockers"]


@override_settings(PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=True)
def test_execute_happy_path_sets_notification_and_keeps_locked_false_flags():
    _customer()
    gate = _prepare_gate()
    signoff = _signoff(gate)
    _json_call(
        "approve_phase7e_live_b_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        signoff,
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7e-live-b-real-customer-send",
    )

    with mock.patch(
        "apps.whatsapp.services.queue_template_message",
        return_value={"message_id": "wamid.test123"},
    ) as queued:
        report = _json_call(
            "execute_phase7e_live_b_real_customer_send",
            "--gate-id",
            str(gate.pk),
            "--director-signoff",
            signoff,
            "--operator-name",
            "Prarit Sidana",
            "--confirm-phase7e-live-b-real-customer-send",
        )

    gate.refresh_from_db()
    assert report["ok"] is True
    assert report["metaMessageId"] == "wamid.test123"
    assert gate.status == Phase7ELiveBRealCustomerSendGate.Status.EXECUTED
    assert gate.customer_notification_sent is True
    assert gate.payment_mutation_made is False
    assert gate.order_mutation_made is False
    assert gate.courier_called is False
    queued.assert_called_once()
    assert queued.call_args.kwargs["override_limited_test_mode"] is True
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_EXECUTED).exists()


@override_settings(PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=True)
def test_execute_outside_window_and_gate_not_approved_are_refused():
    _customer()
    gate = _prepare_gate()
    not_approved = _json_call(
        "execute_phase7e_live_b_real_customer_send",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7e-live-b-real-customer-send",
    )
    assert not_approved["ok"] is False
    assert "phase7e_live_b_gate_status_draft_not_approved" in not_approved[
        "blockers"
    ]

    gate.status = Phase7ELiveBRealCustomerSendGate.Status.APPROVED
    gate.save(update_fields=["status", "updated_at"])
    outside = _json_call(
        "execute_phase7e_live_b_real_customer_send",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate, outside=True),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7e-live-b-real-customer-send",
    )
    assert outside["ok"] is False
    assert "phase7e_live_b_now_outside_director_signoff_utc_window_before_start" in outside[
        "blockers"
    ]


def test_execute_flag_not_set_and_kill_switch_off_are_refused():
    _customer()
    gate = _prepare_gate()
    gate.status = Phase7ELiveBRealCustomerSendGate.Status.APPROVED
    gate.save(update_fields=["status", "updated_at"])
    no_flag = _json_call(
        "execute_phase7e_live_b_real_customer_send",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7e-live-b-real-customer-send",
    )
    assert no_flag["ok"] is False
    assert f"{ENV_FLAG}_must_be_true" in no_flag["blockers"]

    RuntimeKillSwitch.objects.create(scope="global", enabled=False)
    with override_settings(PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=True):
        kill_off = _json_call(
            "execute_phase7e_live_b_real_customer_send",
            "--gate-id",
            str(gate.pk),
            "--director-signoff",
            _signoff(gate),
            "--operator-name",
            "Prarit Sidana",
            "--confirm-phase7e-live-b-real-customer-send",
        )
    assert "runtime_kill_switch_disabled" in kill_off["blockers"]


def test_cancel_valid_and_after_executed_refused():
    gate = _prepare_gate()
    cancelled = _json_call(
        "cancel_phase7e_live_b_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--reason",
        "Director paused real customer send",
        "--operator-name",
        "Prarit Sidana",
    )
    assert cancelled["ok"] is True
    assert cancelled["status"] == "cancelled"
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_CANCELLED).exists()

    executed = _prepare_gate(template_name="delivery_reminder")
    executed.status = Phase7ELiveBRealCustomerSendGate.Status.EXECUTED
    executed.save(update_fields=["status", "updated_at"])
    refused = _json_call(
        "cancel_phase7e_live_b_real_customer_gate",
        "--gate-id",
        str(executed.pk),
        "--reason",
        "too late",
        "--operator-name",
        "Prarit Sidana",
    )
    assert refused["ok"] is False
    assert "phase7e_live_b_executed_gate_cannot_be_cancelled" in refused["blockers"]


@override_settings(PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=True)
def test_prior_executed_gate_for_different_phone_does_not_block_approval():
    executed = _prepare_gate()
    executed.status = Phase7ELiveBRealCustomerSendGate.Status.EXECUTED
    executed.save(update_fields=["status", "updated_at"])

    gate = _prepare_gate(
        phone=SECOND_PHONE,
        customer_name="Kavita Joshi",
        template_params={
            "customer_name": "Kavita Joshi",
            "payment_url": "https://rzp.io/test/kavita",
        },
    )
    report = _json_call(
        "approve_phase7e_live_b_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7e-live-b-real-customer-send",
    )

    assert report["ok"] is True
    assert "phase7e_live_b_duplicate_executed_gate_exists" not in report["blockers"]


@override_settings(PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=True)
def test_prior_executed_same_phone_and_payment_context_blocks_duplicate():
    executed = _prepare_gate(
        template_params={
            "customer_name": "Real Customer",
            "payment_url": "https://rzp.io/test/duplicate",
        }
    )
    executed.status = Phase7ELiveBRealCustomerSendGate.Status.EXECUTED
    executed.save(update_fields=["status", "updated_at"])

    gate = _prepare_gate(
        template_params={
            "customer_name": "Real Customer",
            "payment_url": "https://rzp.io/test/duplicate",
        }
    )
    report = _json_call(
        "approve_phase7e_live_b_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7e-live-b-real-customer-send",
    )

    assert report["ok"] is False
    assert "phase7e_live_b_duplicate_executed_gate_exists" in report["blockers"]


@override_settings(PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED=True)
def test_prior_executed_same_phone_different_payment_context_is_allowed():
    executed = _prepare_gate(
        template_params={
            "customer_name": "Real Customer",
            "payment_url": "https://rzp.io/test/old-link",
        }
    )
    executed.status = Phase7ELiveBRealCustomerSendGate.Status.EXECUTED
    executed.save(update_fields=["status", "updated_at"])

    gate = _prepare_gate(
        template_params={
            "customer_name": "Real Customer",
            "payment_url": "https://rzp.io/test/new-link",
        }
    )
    report = _json_call(
        "approve_phase7e_live_b_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7e-live-b-real-customer-send",
    )

    assert report["ok"] is True
