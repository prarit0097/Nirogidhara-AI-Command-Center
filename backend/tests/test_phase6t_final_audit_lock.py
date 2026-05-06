"""Phase 6T final Phase 6 audit-lock tests."""
from __future__ import annotations

import io
import json
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import (
    Payment,
    RazorpayPaymentDispatchPilotPlan,
    RazorpayPhase6FinalAuditLock,
)
from apps.payments.razorpay_payment_dispatch_pilot_plan import (
    approve_phase6s_payment_dispatch_pilot_plan,
    prepare_phase6s_payment_dispatch_pilot_plan,
)
from apps.payments.razorpay_phase6_final_audit_lock import (
    AUDIT_KIND_ARCHIVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_INVARIANT_VIOLATION,
    AUDIT_KIND_LOCKED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    assert_phase6t_no_live_execution_or_provider_call,
    archive_phase6t_final_audit_lock,
    build_phase6t_final_audit_contract,
    inspect_phase6t_final_audit_lock_readiness,
    lock_phase6t_final_audit_record,
    prepare_phase6t_final_audit_lock,
    preview_phase6t_final_audit_lock,
    reject_phase6t_final_audit_lock,
)
from apps.shipments.models import Shipment
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from tests.test_phase6s_payment_dispatch_pilot_plan import (
    _make_approved_phase6r_readiness,
)


def _row_counts() -> dict[str, int]:
    return {
        "order": Order.objects.count(),
        "payment": Payment.objects.count(),
        "shipment": Shipment.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "customer": Customer.objects.count(),
        "lead": Lead.objects.count(),
        "whatsapp_message": WhatsAppMessage.objects.count(),
        "whatsapp_lifecycle_event": WhatsAppLifecycleEvent.objects.count(),
        "whatsapp_handoff": WhatsAppHandoffToCall.objects.count(),
        "phase6t_final_audit_lock": RazorpayPhase6FinalAuditLock.objects.count(),
    }


def _make_approved_phase6s_plan(
    *, source_event_id: str = "evt_phase6t_full"
) -> RazorpayPaymentDispatchPilotPlan:
    readiness = _make_approved_phase6r_readiness(
        source_event_id=source_event_id
    )
    with override_settings(RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED=True):
        prepared = prepare_phase6s_payment_dispatch_pilot_plan(readiness.pk)
        approve_phase6s_payment_dispatch_pilot_plan(
            prepared["plan"]["id"],
            reason="Phase 6S approved for Phase 6T final audit.",
        )
    return RazorpayPaymentDispatchPilotPlan.objects.get(
        pk=prepared["plan"]["id"]
    )


def test_contract_includes_phase_6n_through_6s_and_locks_effects_off() -> None:
    rows = build_phase6t_final_audit_contract()
    assert [row["phase"] for row in rows] == ["6N", "6O", "6P", "6Q", "6R", "6S"]
    for row in rows:
        assert row["mutationAllowedInPhase"] is False
        assert row["providerCallAllowedInPhase"] is False
        assert row["customerNotificationAllowedInPhase"] is False
        assert row["frontendExecutionAllowed"] is False
        assert row["apiExecutionAllowed"] is False
        assert row["cliOnlyReview"] is True


def test_phase6t_audit_kinds_fit_audit_event_kind_column() -> None:
    audit_kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_LOCKED,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_ARCHIVED,
        AUDIT_KIND_BLOCKED,
        AUDIT_KIND_INVARIANT_VIOLATION,
    ]
    assert all(kind.startswith("razorpay.phase6_final_audit.") for kind in audit_kinds)
    assert all(len(kind) <= 64 for kind in audit_kinds)


@pytest.mark.django_db
def test_readiness_command_returns_phase6t_shape() -> None:
    out = io.StringIO()
    call_command(
        "inspect_razorpay_phase6_final_audit_lock_readiness",
        "--json",
        "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "6T"
    assert body["status"] == "final_audit_lock_only"
    assert body["futureControlledPilotAllowedByPhase6T"] is False
    assert body["controlledPilotExecutionAllowedInPhase6T"] is False
    assert body["safeToStartPhase7A"] is False


@pytest.mark.django_db
def test_readiness_endpoint_admin_returns_phase6t_shape(
    admin_user, auth_client
) -> None:
    url = reverse("saas-razorpay-phase6-final-audit-lock-readiness")
    res = auth_client(admin_user).get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "6T"
    assert body["status"] == "final_audit_lock_only"
    assert body["frontendCanExecute"] is False
    assert body["apiEndpointCanExecute"] is False
    assert body["futureControlledPilotAllowedByPhase6T"] is False
    assert body["realOrderMutation"] is False
    assert body["providerCall"] is False


@pytest.mark.django_db
def test_prepare_fails_when_phase6t_flag_false() -> None:
    plan = _make_approved_phase6s_plan(source_event_id="evt_phase6t_flag")
    result = prepare_phase6t_final_audit_lock(plan.pk)
    assert result["created"] is False
    assert "RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED_must_be_true" in result["blockers"]


@pytest.mark.django_db
@override_settings(RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED=True)
def test_prepare_succeeds_only_with_eligible_approved_phase6s_plan() -> None:
    plan = _make_approved_phase6s_plan(source_event_id="evt_phase6t_prepare")
    counts_before = _row_counts()
    result = prepare_phase6t_final_audit_lock(plan.pk)
    counts_after = _row_counts()
    assert result["created"] is True
    row = RazorpayPhase6FinalAuditLock.objects.get(
        pk=result["auditLock"]["id"]
    )
    assert row.status == RazorpayPhase6FinalAuditLock.Status.PENDING_MANUAL_REVIEW
    assert row.full_chain_verified is True
    assert row.final_audit_passed is True
    assert row.future_execution_allowed_by_phase6t is False
    assert row.controlled_pilot_execution_allowed_in_phase6t is False
    assert counts_after["phase6t_final_audit_lock"] == counts_before["phase6t_final_audit_lock"] + 1
    for key in counts_before:
        if key != "phase6t_final_audit_lock":
            assert counts_after[key] == counts_before[key], key


@pytest.mark.django_db
@override_settings(RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED=True)
@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("status", RazorpayPaymentDispatchPilotPlan.Status.DRAFT, "status_must_be_approved"),
        ("pilot_execution_allowed_in_phase6s", True, "pilot_execution_allowed"),
        ("whatsapp_message_queued", True, "whatsapp_message_queued"),
        ("shipment_created", True, "shipment_created"),
        ("provider_call_attempted", True, "provider_call_attempted"),
    ],
)
def test_prepare_blocks_ineligible_phase6s_plan(field, value, blocker) -> None:
    plan = _make_approved_phase6s_plan(
        source_event_id=f"evt_phase6t_block_{field}"
    )
    setattr(plan, field, value)
    plan.save(update_fields=[field])
    result = prepare_phase6t_final_audit_lock(plan.pk)
    assert result["created"] is False
    assert any(blocker in item for item in result["blockers"])


@pytest.mark.django_db
@override_settings(RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED=True)
def test_lock_reject_archive_change_final_audit_status_only() -> None:
    plan = _make_approved_phase6s_plan(source_event_id="evt_phase6t_trans")
    prepared = prepare_phase6t_final_audit_lock(plan.pk)
    row_id = prepared["auditLock"]["id"]
    counts_before = _row_counts()
    locked = lock_phase6t_final_audit_record(
        row_id, reason="Director reviewed Phase 6 final audit chain."
    )
    assert locked["ok"] is True
    assert locked["auditLock"]["status"] == (
        RazorpayPhase6FinalAuditLock.Status.LOCKED_FOR_FUTURE_CONTROLLED_PILOT_REVIEW
    )
    counts_after = _row_counts()
    assert counts_after == counts_before

    plan2 = _make_approved_phase6s_plan(source_event_id="evt_phase6t_reject")
    row2 = prepare_phase6t_final_audit_lock(plan2.pk)["auditLock"]["id"]
    assert reject_phase6t_final_audit_lock(row2)["ok"] is True

    plan3 = _make_approved_phase6s_plan(source_event_id="evt_phase6t_archive")
    row3 = prepare_phase6t_final_audit_lock(plan3.pk)["auditLock"]["id"]
    assert archive_phase6t_final_audit_lock(row3)["ok"] is True


@pytest.mark.django_db
@override_settings(RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED=True)
def test_no_provider_or_notification_call_paths_invoked() -> None:
    plan = _make_approved_phase6s_plan(source_event_id="evt_phase6t_provider")
    with mock.patch(
        "apps.payments.integrations.razorpay_client.create_payment_link"
    ) as razorpay_client, mock.patch(
        "apps.whatsapp.integrations.whatsapp.meta_cloud_client.MetaCloudProvider"
    ) as meta_client, mock.patch(
        "apps.shipments.integrations.delhivery_client.create_awb"
    ) as delhivery_client:
        prepared = prepare_phase6t_final_audit_lock(plan.pk)
        lock_phase6t_final_audit_record(
            prepared["auditLock"]["id"], reason="lock only"
        )
    assert not razorpay_client.called
    assert not meta_client.called
    assert not delhivery_client.called


@pytest.mark.django_db
def test_outputs_do_not_leak_secret_or_planted_pii() -> None:
    Customer.objects.create(
        name="Phase6T Planted Customer",
        phone="+919999555777",
        product_interest="weight-management",
    )
    report = inspect_phase6t_final_audit_lock_readiness()
    blob = json.dumps(report, default=str)
    for planted in (
        "PHASE6T_FAKE_SECRET_xxxxxxxxxxxxxxxxxxxx",
        "+919999555777",
        "Phase6T Planted Customer",
    ):
        assert planted not in blob


_READ_ENDPOINT_NAMES = (
    "saas-razorpay-phase6-final-audit-lock-readiness",
    "saas-razorpay-phase6-final-audit-locks",
    "saas-razorpay-phase6-final-audit-lock-preview",
)


@pytest.mark.django_db
def test_phase6t_endpoints_require_admin_auth(
    client, viewer_user, auth_client
) -> None:
    url = reverse("saas-razorpay-phase6-final-audit-lock-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("name", _READ_ENDPOINT_NAMES)
def test_phase6t_endpoints_reject_non_get_methods(
    name, admin_user, auth_client
) -> None:
    client = auth_client(admin_user)
    url = reverse(name)
    for method in ("post", "patch", "put", "delete"):
        res = getattr(client, method)(url, {})
        assert res.status_code == 405, f"{method} {name} -> {res.status_code}"


@pytest.mark.django_db
@override_settings(RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED=True)
def test_audit_events_are_safe() -> None:
    plan = _make_approved_phase6s_plan(source_event_id="evt_phase6t_audit")
    prepared = prepare_phase6t_final_audit_lock(plan.pk)
    lock_phase6t_final_audit_record(
        prepared["auditLock"]["id"], reason="Director reviewed."
    )
    events = AuditEvent.objects.filter(
        kind__in=[AUDIT_KIND_PREPARED, AUDIT_KIND_LOCKED]
    )
    assert events.count() >= 2
    forbidden = {
        "raw_payload",
        "raw_signature",
        "raw_secret",
        "phone",
        "email",
        "address",
        "card",
        "vpa",
        "upi",
        "bank_account",
        "wallet",
    }
    for event in events:
        payload = event.payload or {}
        assert not (forbidden & set(payload))
        assert payload["future_execution_allowed_by_phase6t"] is False
        assert payload["controlled_pilot_execution_allowed_in_phase6t"] is False
        assert payload["provider_call_attempted"] is False


@pytest.mark.django_db
@override_settings(RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED=True)
def test_readiness_safe_future_consideration_only_after_lock() -> None:
    assert inspect_phase6t_final_audit_lock_readiness()[
        "safeToStartFutureControlledPilot"
    ] is False
    plan = _make_approved_phase6s_plan(source_event_id="evt_phase6t_safe")
    prepared = prepare_phase6t_final_audit_lock(plan.pk)
    assert inspect_phase6t_final_audit_lock_readiness()[
        "safeToStartFutureControlledPilot"
    ] is False
    lock_phase6t_final_audit_record(
        prepared["auditLock"]["id"], reason="Director reviewed."
    )
    report = inspect_phase6t_final_audit_lock_readiness()
    assert report["safeToStartFutureControlledPilot"] is True
    assert report["futureControlledPilotAllowedByPhase6T"] is False
    assert report["safeToStartPhase7A"] is False


@pytest.mark.django_db
def test_preview_is_read_only_and_assertion_blocks_flipped_boolean() -> None:
    before = RazorpayPhase6FinalAuditLock.objects.count()
    preview = preview_phase6t_final_audit_lock()
    assert preview["phase"] == "6T"
    assert RazorpayPhase6FinalAuditLock.objects.count() == before

    row = RazorpayPhase6FinalAuditLock(
        event_name="payment.captured",
        idempotency_key="phase6t::bad::row",
        provider_call_attempted=True,
    )
    with pytest.raises(ValueError):
        assert_phase6t_no_live_execution_or_provider_call(row)


@pytest.mark.django_db
def test_phase7a_or_live_execution_is_not_implemented() -> None:
    report = inspect_phase6t_final_audit_lock_readiness()
    blob = json.dumps(report, default=str).lower()
    assert report["safeToStartPhase7A"] is False
    assert "start pilot" not in blob
    assert "execute pilot" not in blob
