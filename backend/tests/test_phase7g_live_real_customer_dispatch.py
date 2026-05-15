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
from apps.orders.models import Order
from apps.saas.models import RuntimeKillSwitch
from apps.shipments.models import (
    Phase7GLiveRealCustomerDispatchGate,
    Shipment,
)
from apps.shipments.phase7g_live_real_customer_dispatch import (
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_EXECUTED,
    AUDIT_KIND_ROLLED_BACK,
    ENV_FLAG,
)


pytestmark = pytest.mark.django_db


ORDER_ID = "NRG-PHASE7GL-001"
FAKE_AWB = "FAKEDLV123456"


def _json_call(command: str, *args: str) -> dict:
    out = StringIO()
    call_command(command, *args, "--json", stdout=out)
    return json.loads(out.getvalue())


def _seed_order(*, stage: str = Order.Stage.CONFIRMED.value) -> Order:
    return Order.objects.create(
        id=ORDER_ID,
        customer_name="Test Customer",
        phone="+919999990001",
        product="Nirogidhara",
        quantity=1,
        amount=3000,
        advance_paid=True,
        advance_amount=499,
        payment_status=Order.PaymentStatus.PAID.value,
        state="Delhi",
        city="Delhi",
        stage=stage,
    )


def _prepare_gate() -> Phase7GLiveRealCustomerDispatchGate:
    report = _json_call(
        "prepare_phase7g_live_real_customer_gate",
        "--order-id",
        ORDER_ID,
        "--operator-name",
        "Prarit Sidana",
    )
    assert report["ok"] is True, report
    return Phase7GLiveRealCustomerDispatchGate.objects.get(pk=report["gateId"])


def _window(*, before_minutes: int = 1, after_minutes: int = 10) -> tuple[str, str]:
    start = (timezone.now() - timedelta(minutes=before_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end = (timezone.now() + timedelta(minutes=after_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return start, end


def _signoff(
    gate: Phase7GLiveRealCustomerDispatchGate, *, outside: bool = False
) -> str:
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
        f"phase7g_live_gate_id_{gate.pk} "
        f"target_order_{gate.target_order_id} "
        f"phase7gLiveApproval BEGIN_UTC={begin} END_UTC={end}"
    )


def _fake_shipment_factory(*, status: str = "Pickup Scheduled") -> Shipment:
    return Shipment(
        awb=FAKE_AWB,
        order_id=ORDER_ID,
        customer="Test Customer",
        state="Delhi",
        city="Delhi",
        status=status,
        eta="3 days",
        courier="Delhivery",
        delhivery_status=status,
        tracking_url=f"https://delhivery.example/track/{FAKE_AWB}",
        raw_response={
            "mode": "live",
            "packages": [
                {
                    "waybill": FAKE_AWB,
                    "status": status,
                    "refnum": ORDER_ID,
                }
            ],
        },
    )


def test_inspect_flag_off_vs_on():
    off = _json_call("inspect_phase7g_live_real_customer_gate", "--no-audit")
    assert off["status"] == "blocked"
    assert f"{ENV_FLAG}_must_be_true" in off["blockers"]
    # delhivery mode defaults to mock in tests; execute requires live.
    assert "delhivery_mode_must_be_live_for_execute" in off["blockers"]

    with override_settings(
        PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=True,
        DELHIVERY_MODE="live",
    ):
        on = _json_call(
            "inspect_phase7g_live_real_customer_gate", "--no-audit"
        )
    assert on["flagEnabled"] is True
    assert on["delhiveryMode"] == "live"
    assert on["killSwitch"]["enabled"] is True


def test_prepare_valid_order_and_missing_order_and_wrong_state():
    _seed_order()
    valid = _json_call(
        "prepare_phase7g_live_real_customer_gate",
        "--order-id",
        ORDER_ID,
        "--operator-name",
        "Prarit Sidana",
    )
    assert valid["ok"] is True
    assert valid["status"] == "draft"
    assert valid["orderState"] == Order.Stage.CONFIRMED.value

    missing = _json_call(
        "prepare_phase7g_live_real_customer_gate",
        "--order-id",
        "NRG-DOES-NOT-EXIST",
        "--operator-name",
        "Prarit Sidana",
    )
    assert missing["ok"] is False
    assert "phase7g_live_target_order_not_found" in missing["blockers"]

    # Wrong stage refuses.
    Order.objects.filter(pk=ORDER_ID).update(stage=Order.Stage.NEW_LEAD.value)
    wrong = _json_call(
        "prepare_phase7g_live_real_customer_gate",
        "--order-id",
        ORDER_ID,
        "--operator-name",
        "Prarit Sidana",
    )
    assert wrong["ok"] is False
    assert any(
        b.startswith("phase7g_live_order_stage_") for b in wrong["blockers"]
    )


@override_settings(PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=True)
def test_approve_happy_path_writes_audit():
    _seed_order()
    gate = _prepare_gate()
    report = _json_call(
        "approve_phase7g_live_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7g-live-real-customer-dispatch",
    )
    gate.refresh_from_db()
    assert report["ok"] is True, report
    assert gate.status == Phase7GLiveRealCustomerDispatchGate.Status.APPROVED
    assert gate.recorded_signoff_window_start_utc is not None
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_APPROVED).exists()


@override_settings(PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=True)
def test_approve_bad_signoff_and_wrong_status_refused():
    _seed_order()
    gate = _prepare_gate()
    bad = _json_call(
        "approve_phase7g_live_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        "phase7gLiveApproval",
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7g-live-real-customer-dispatch",
    )
    assert bad["ok"] is False
    assert (
        "phase7g_live_director_signoff_missing_structured_utc_window"
        in bad["blockers"]
    )

    gate.status = Phase7GLiveRealCustomerDispatchGate.Status.CANCELLED
    gate.save(update_fields=["status", "updated_at"])
    wrong_status = _json_call(
        "approve_phase7g_live_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7g-live-real-customer-dispatch",
    )
    assert wrong_status["ok"] is False
    assert (
        "phase7g_live_gate_status_cancelled_not_draft"
        in wrong_status["blockers"]
    )


@override_settings(
    PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=True,
    DELHIVERY_MODE="live",
)
def test_execute_happy_path_creates_shipment_and_locked_flags_stay_false():
    _seed_order()
    gate = _prepare_gate()
    signoff = _signoff(gate)
    _json_call(
        "approve_phase7g_live_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        signoff,
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7g-live-real-customer-dispatch",
    )

    def _fake_create_shipment(*, order, by_user):
        ship = _fake_shipment_factory()
        ship.save()
        order.awb = FAKE_AWB
        order.save(update_fields=["awb"])
        return ship

    with mock.patch(
        "apps.shipments.services.create_shipment",
        side_effect=_fake_create_shipment,
    ) as create_mock:
        report = _json_call(
            "execute_phase7g_live_real_customer_dispatch",
            "--gate-id",
            str(gate.pk),
            "--director-signoff",
            signoff,
            "--operator-name",
            "Prarit Sidana",
            "--confirm-phase7g-live-real-customer-dispatch",
        )

    gate.refresh_from_db()
    assert report["ok"] is True, report
    assert report["awbNumber"] == FAKE_AWB
    assert gate.status == Phase7GLiveRealCustomerDispatchGate.Status.EXECUTED
    assert gate.awb_number == FAKE_AWB
    # Locked-False flags stay False.
    assert gate.payment_mutation_made is False
    assert gate.order_payment_status_changed is False
    assert gate.whatsapp_sent is False
    assert gate.razorpay_called is False
    create_mock.assert_called_once()
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_EXECUTED).exists()


@override_settings(
    PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=True,
    DELHIVERY_MODE="live",
)
def test_execute_outside_window_and_not_approved_are_refused():
    _seed_order()
    gate = _prepare_gate()
    not_approved = _json_call(
        "execute_phase7g_live_real_customer_dispatch",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7g-live-real-customer-dispatch",
    )
    assert not_approved["ok"] is False
    assert (
        "phase7g_live_gate_status_draft_not_approved"
        in not_approved["blockers"]
    )

    gate.status = Phase7GLiveRealCustomerDispatchGate.Status.APPROVED
    gate.save(update_fields=["status", "updated_at"])
    outside = _json_call(
        "execute_phase7g_live_real_customer_dispatch",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate, outside=True),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7g-live-real-customer-dispatch",
    )
    assert outside["ok"] is False
    assert (
        "phase7g_live_now_outside_director_signoff_utc_window_before_start"
        in outside["blockers"]
    )


def test_execute_flag_not_set_and_mode_not_live_and_kill_switch_off():
    _seed_order()
    gate = _prepare_gate()
    gate.status = Phase7GLiveRealCustomerDispatchGate.Status.APPROVED
    gate.save(update_fields=["status", "updated_at"])

    # Flag off.
    no_flag = _json_call(
        "execute_phase7g_live_real_customer_dispatch",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        _signoff(gate),
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7g-live-real-customer-dispatch",
    )
    assert no_flag["ok"] is False
    assert f"{ENV_FLAG}_must_be_true" in no_flag["blockers"]

    # Flag on but mode not live.
    with override_settings(PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=True):
        mode_off = _json_call(
            "execute_phase7g_live_real_customer_dispatch",
            "--gate-id",
            str(gate.pk),
            "--director-signoff",
            _signoff(gate),
            "--operator-name",
            "Prarit Sidana",
            "--confirm-phase7g-live-real-customer-dispatch",
        )
    assert mode_off["ok"] is False
    assert "delhivery_mode_must_be_live_for_execute" in mode_off["blockers"]

    # Phase 7E-Live-B Hotfix-1 pattern: a SECOND RuntimeKillSwitch row with
    # enabled=False must be detected even when the seeded enabled=True row
    # already exists.
    RuntimeKillSwitch.objects.create(scope="global", enabled=False)
    with override_settings(
        PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=True,
        DELHIVERY_MODE="live",
    ):
        kill_off = _json_call(
            "execute_phase7g_live_real_customer_dispatch",
            "--gate-id",
            str(gate.pk),
            "--director-signoff",
            _signoff(gate),
            "--operator-name",
            "Prarit Sidana",
            "--confirm-phase7g-live-real-customer-dispatch",
        )
    assert "runtime_kill_switch_disabled" in kill_off["blockers"]


@override_settings(
    PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=True,
    DELHIVERY_MODE="live",
)
def test_rollback_happy_path_and_refuses_when_not_executed():
    _seed_order()
    gate = _prepare_gate()
    signoff = _signoff(gate)
    _json_call(
        "approve_phase7g_live_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        signoff,
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7g-live-real-customer-dispatch",
    )

    def _fake_create_shipment(*, order, by_user):
        ship = _fake_shipment_factory()
        ship.save()
        return ship

    with mock.patch(
        "apps.shipments.services.create_shipment",
        side_effect=_fake_create_shipment,
    ):
        _json_call(
            "execute_phase7g_live_real_customer_dispatch",
            "--gate-id",
            str(gate.pk),
            "--director-signoff",
            signoff,
            "--operator-name",
            "Prarit Sidana",
            "--confirm-phase7g-live-real-customer-dispatch",
        )

    # Happy rollback (mock mode short-circuits the cancel API).
    with mock.patch(
        "apps.shipments.integrations.delhivery_client.cancel_awb",
        return_value={
            "status": "cancelled",
            "raw": {"awb": FAKE_AWB, "ok": True},
        },
    ) as cancel_mock:
        rolled = _json_call(
            "rollback_phase7g_live_real_customer_dispatch",
            "--gate-id",
            str(gate.pk),
            "--reason",
            "Test cancellation",
            "--operator-name",
            "Prarit Sidana",
        )

    gate.refresh_from_db()
    assert rolled["ok"] is True, rolled
    assert (
        gate.status
        == Phase7GLiveRealCustomerDispatchGate.Status.ROLLBACK_RECORDED
    )
    assert gate.cancellation_result.get("status") == "cancelled"
    cancel_mock.assert_called_once_with(awb=FAKE_AWB)
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_ROLLED_BACK).exists()

    # Rollback on a non-executed gate is refused.
    other = _prepare_gate()
    refused = _json_call(
        "rollback_phase7g_live_real_customer_dispatch",
        "--gate-id",
        str(other.pk),
        "--reason",
        "too early",
        "--operator-name",
        "Prarit Sidana",
    )
    assert refused["ok"] is False
    assert any(
        b.startswith("phase7g_live_gate_status_") for b in refused["blockers"]
    )


@override_settings(
    PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED=True,
    DELHIVERY_MODE="live",
)
def test_rollback_when_delhivery_refuses_still_records():
    _seed_order()
    gate = _prepare_gate()
    signoff = _signoff(gate)
    _json_call(
        "approve_phase7g_live_real_customer_gate",
        "--gate-id",
        str(gate.pk),
        "--director-signoff",
        signoff,
        "--operator-name",
        "Prarit Sidana",
        "--confirm-phase7g-live-real-customer-dispatch",
    )

    def _fake_create_shipment(*, order, by_user):
        ship = _fake_shipment_factory()
        ship.save()
        return ship

    with mock.patch(
        "apps.shipments.services.create_shipment",
        side_effect=_fake_create_shipment,
    ):
        _json_call(
            "execute_phase7g_live_real_customer_dispatch",
            "--gate-id",
            str(gate.pk),
            "--director-signoff",
            signoff,
            "--operator-name",
            "Prarit Sidana",
            "--confirm-phase7g-live-real-customer-dispatch",
        )

    with mock.patch(
        "apps.shipments.integrations.delhivery_client.cancel_awb",
        return_value={
            "status": "rejected",
            "http_status": 400,
            "raw": {"error": "already_in_transit"},
        },
    ):
        rolled = _json_call(
            "rollback_phase7g_live_real_customer_dispatch",
            "--gate-id",
            str(gate.pk),
            "--reason",
            "Delhivery refuses",
            "--operator-name",
            "Prarit Sidana",
        )

    gate.refresh_from_db()
    assert rolled["ok"] is True
    assert (
        gate.status
        == Phase7GLiveRealCustomerDispatchGate.Status.ROLLBACK_RECORDED
    )
    assert gate.cancellation_result.get("status") == "rejected"
    assert rolled["note"]
