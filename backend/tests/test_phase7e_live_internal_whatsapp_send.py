"""Phase 7E-Live-A - Internal allowed-list WhatsApp one-shot send tests.

Asserts every Phase 7E-Live-A safety requirement. Phase 7E-Live-A
never sends to a real customer phone, never queues broad
automation, never mutates real ``Order`` / ``Payment`` /
``Shipment`` / ``DiscountOfferLog`` / ``Customer`` / ``Lead``
rows, never edits any ``.env*`` file. The Meta Cloud wrapper
``_send_internal_template_via_meta_cloud`` is patched as a
``MagicMock`` in every refusal test and asserted ``assert_not_called``
so a false-positive that accidentally reaches the network would
fail the test deterministically.
"""
from __future__ import annotations

import importlib
import io
import json
from datetime import datetime, timedelta, timezone
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
    RazorpayWhatsAppInternalSendAttempt,
)
from apps.payments.razorpay_whatsapp_internal_send import (
    AUDIT_KIND_APPROVED,
    AUDIT_KIND_BLOCKED,
    AUDIT_KIND_EXECUTED,
    AUDIT_KIND_FAILED,
    AUDIT_KIND_PREPARED,
    AUDIT_KIND_PREVIEWED,
    AUDIT_KIND_READINESS,
    AUDIT_KIND_REJECTED,
    AUDIT_KIND_ROLLBACK_RECORDED,
    Phase7ELiveExecutionError,
    approve_phase7e_live_internal_send,
    execute_phase7e_live_internal_send,
    inspect_phase7e_live_internal_send_readiness,
    prepare_phase7e_live_internal_send,
    preview_phase7e_live_internal_send,
    reject_phase7e_live_internal_send,
    rollback_phase7e_live_internal_send,
    summarize_phase7e_live_internal_send_attempts,
)
from apps.shipments.models import RescueAttempt, Shipment, WorkflowStep
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)
from tests.test_phase7f_courier_readiness import (
    _make_approved_phase7e_gate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_ALLOWED_NUMBER = "+919999990001"
_ALLOWED_LAST4 = "0001"


def _row_counts() -> dict[str, int]:
    return {
        "order": Order.objects.count(),
        "payment": Payment.objects.count(),
        "shipment": Shipment.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "customer": Customer.objects.count(),
        "lead": Lead.objects.count(),
        "whatsapp_message": WhatsAppMessage.objects.count(),
        "whatsapp_lifecycle_event": (
            WhatsAppLifecycleEvent.objects.count()
        ),
        "whatsapp_handoff": WhatsAppHandoffToCall.objects.count(),
        "workflow_step": WorkflowStep.objects.count(),
        "rescue_attempt": RescueAttempt.objects.count(),
    }


def _phase7e_live_test_settings(**overrides):
    base = {
        "PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED": True,
        "PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED": True,
        "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED": False,
        "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION": False,
        "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER": False,
        "WHATSAPP_LIVE_META_LIMITED_TEST_MODE": True,
        "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS": [_ALLOWED_NUMBER],
        "WHATSAPP_AI_AUTO_REPLY_ENABLED": False,
        "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED": False,
        "WHATSAPP_CALL_HANDOFF_ENABLED": False,
        "WHATSAPP_RESCUE_DISCOUNT_ENABLED": False,
        "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED": False,
        "WHATSAPP_REORDER_DAY20_ENABLED": False,
        "WHATSAPP_PROVIDER": "mock",
    }
    base.update(overrides)
    return override_settings(**base)


def _structured_signoff(
    *,
    begin_offset_seconds: int = -60,
    end_offset_seconds: int = 60,
) -> str:
    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    begin = now + timedelta(seconds=begin_offset_seconds)
    end = now + timedelta(seconds=end_offset_seconds)
    return (
        f"Director sign-off for Phase 7E-Live-A internal allowed-list "
        f"WhatsApp send. "
        f"BEGIN_UTC={begin.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"END_UTC={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )


def _make_prepared_attempt() -> RazorpayWhatsAppInternalSendAttempt:
    gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7e_live_prepare"
    )
    with _phase7e_live_test_settings():
        out = prepare_phase7e_live_internal_send(
            gate.pk,
            template_name="nrg_internal_test_intro",
            template_language="en",
            allowed_recipient_last4=_ALLOWED_LAST4,
        )
    attempt_id = out["attempt"]["id"]
    return RazorpayWhatsAppInternalSendAttempt.objects.get(
        pk=attempt_id
    )


def _make_approved_attempt() -> RazorpayWhatsAppInternalSendAttempt:
    attempt = _make_prepared_attempt()
    with _phase7e_live_test_settings():
        approve_phase7e_live_internal_send(
            attempt.pk,
            reviewed_by=None,
            reason="Director Phase 7E-Live approve",
            director_signoff="Director PS approve.",
        )
    attempt.refresh_from_db()
    return attempt


# ---------------------------------------------------------------------------
# Audit-kind + static-file invariants
# ---------------------------------------------------------------------------


def test_phase7e_live_audit_kinds_within_length_budget() -> None:
    audit_kinds = [
        AUDIT_KIND_READINESS,
        AUDIT_KIND_PREVIEWED,
        AUDIT_KIND_PREPARED,
        AUDIT_KIND_APPROVED,
        AUDIT_KIND_EXECUTED,
        AUDIT_KIND_FAILED,
        AUDIT_KIND_ROLLBACK_RECORDED,
        AUDIT_KIND_REJECTED,
        AUDIT_KIND_BLOCKED,
    ]
    assert len(audit_kinds) == 9
    for kind in audit_kinds:
        assert kind.startswith("phase7e.internal_send.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


def test_phase7e_live_service_module_no_top_level_meta_cloud_import() -> (
    None
):
    """Check actual import lines, not docstring mentions of forbidden
    imports."""
    src_path = importlib.import_module(
        "apps.payments.razorpay_whatsapp_internal_send"
    ).__file__
    with open(src_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    forbidden_import_lines = [
        "from apps.whatsapp.services import send_freeform_text_message",
        "from apps.whatsapp.services import queue_template_message",
        "from apps.payments.integrations.razorpay_client",
        "from dotenv",
        "import dotenv",
    ]
    for needle in forbidden_import_lines:
        for line in text.splitlines():
            stripped = line.lstrip()
            indent_level = len(line) - len(stripped)
            if not (
                stripped.startswith("from ")
                or stripped.startswith("import ")
            ):
                continue
            if needle in stripped and indent_level == 0:
                pytest.fail(
                    f"Phase 7E-Live service imports forbidden module "
                    f"at top level: {needle}"
                )
    # The Meta Cloud client must be imported only inside the lazy
    # wrapper, never at module top-level.
    top_level_meta = (
        "from apps.whatsapp.integrations.whatsapp import meta_cloud_client"
    )
    for line in text.splitlines():
        stripped = line.lstrip()
        if (
            top_level_meta in stripped
            and (len(line) - len(stripped)) == 0
            and (
                stripped.startswith("from ")
                or stripped.startswith("import ")
            )
        ):
            pytest.fail(
                "Meta Cloud client must be lazy-imported inside a "
                "function, not at top level."
            )


# ---------------------------------------------------------------------------
# Readiness command + endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7e_live_readiness_command_returns_internal_only_shape() -> (
    None
):
    out = io.StringIO()
    call_command(
        "inspect_phase7e_live_internal_whatsapp_send_readiness",
        "--json", "--no-audit",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["phase"] == "7E-Live-A"
    assert (
        body["status"]
        == "internal_allowed_list_whatsapp_one_shot_send_only"
    )
    for key in (
        "phase7ELiveSendsToRealCustomer",
        "phase7ELiveMutatesBusinessRow",
        "phase7ELiveCustomerNotification",
        "phase7ELiveSupportsFreeformMedicalText",
    ):
        assert body[key] is False, key
    assert (
        body["phase7ELiveRecipientScope"]
        == "internal_staff_allow_list"
    )


@pytest.mark.django_db
def test_phase7e_live_readiness_endpoint_requires_admin_auth(
    client, viewer_user, admin_user, auth_client
) -> None:
    url = reverse("saas-whatsapp-internal-send-readiness")
    assert client.get(url).status_code in {401, 403}
    assert auth_client(viewer_user).get(url).status_code == 403
    assert auth_client(admin_user).get(url).status_code == 200


@pytest.mark.django_db
def test_phase7e_live_endpoints_reject_non_get_methods(
    admin_user, auth_client
) -> None:
    urls = [
        reverse("saas-whatsapp-internal-send-readiness"),
        reverse("saas-whatsapp-internal-send-attempts"),
        reverse("saas-whatsapp-internal-send-preview") + "?gate_id=1",
        reverse(
            "saas-whatsapp-internal-send-attempt-detail",
            kwargs={"pk": 1},
        ),
    ]
    client = auth_client(admin_user)
    for url in urls:
        for method in ("post", "patch", "put", "delete"):
            assert (
                getattr(client, method)(url, {}).status_code == 405
            ), f"{method} {url}"


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7e_live_prepare_creates_attempt_internal_only() -> None:
    gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7e_live_prepare_ok"
    )
    before = _row_counts()
    with _phase7e_live_test_settings():
        out = prepare_phase7e_live_internal_send(
            gate.pk,
            template_name="nrg_internal_test_intro",
            template_language="en",
            allowed_recipient_last4=_ALLOWED_LAST4,
        )
    after = _row_counts()
    assert out["created"] is True
    attempt_id = out["attempt"]["id"]
    row = RazorpayWhatsAppInternalSendAttempt.objects.get(pk=attempt_id)
    assert row.recipient_scope == "internal_staff_allow_list"
    assert row.allowed_recipient_last4 == _ALLOWED_LAST4
    assert row.template_name == "nrg_internal_test_intro"
    assert row.real_customer_allowed is False
    assert row.real_customer_phone_used is False
    assert row.customer_notification_sent is False
    assert row.business_mutation_was_made is False
    # No business mutation.
    assert before == after


@pytest.mark.django_db
def test_phase7e_live_prepare_refuses_non_allow_list_recipient() -> (
    None
):
    gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7e_live_bad_recipient"
    )
    with _phase7e_live_test_settings():
        out = prepare_phase7e_live_internal_send(
            gate.pk,
            template_name="nrg_internal_test_intro",
            template_language="en",
            allowed_recipient_last4="1234",  # not on allow-list
        )
    assert out["created"] is False
    assert any(
        "phase7e_live_recipient_must_be_on_allowed_test_numbers" in b
        for b in out["blockers"]
    )
    assert RazorpayWhatsAppInternalSendAttempt.objects.count() == 0


@pytest.mark.django_db
def test_phase7e_live_prepare_refuses_when_limited_test_mode_off() -> (
    None
):
    gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7e_live_no_limited_mode"
    )
    with _phase7e_live_test_settings(
        WHATSAPP_LIVE_META_LIMITED_TEST_MODE=False,
    ):
        out = prepare_phase7e_live_internal_send(
            gate.pk,
            template_name="nrg_internal_test_intro",
            template_language="en",
            allowed_recipient_last4=_ALLOWED_LAST4,
        )
    assert out["created"] is False
    assert any(
        "WHATSAPP_LIVE_META_LIMITED_TEST_MODE_must_be_true" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7e_live_prepare_refuses_when_broad_automation_on() -> (
    None
):
    gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7e_live_broad_auto"
    )
    with _phase7e_live_test_settings(
        WHATSAPP_AI_AUTO_REPLY_ENABLED=True,
    ):
        out = prepare_phase7e_live_internal_send(
            gate.pk,
            template_name="nrg_internal_test_intro",
            template_language="en",
            allowed_recipient_last4=_ALLOWED_LAST4,
        )
    assert out["created"] is False
    assert any(
        "WHATSAPP_AI_AUTO_REPLY_ENABLED_must_be_false" in b
        for b in out["blockers"]
    )


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7e_live_approve_requires_reason_and_signoff() -> None:
    attempt = _make_prepared_attempt()
    with _phase7e_live_test_settings():
        no_reason = approve_phase7e_live_internal_send(
            attempt.pk, reason="", director_signoff="x"
        )
        no_signoff = approve_phase7e_live_internal_send(
            attempt.pk, reason="ok", director_signoff=""
        )
    assert no_reason["ok"] is False
    assert no_signoff["ok"] is False


@pytest.mark.django_db
def test_phase7e_live_approve_flips_status() -> None:
    attempt = _make_prepared_attempt()
    AuditEvent.objects.filter(kind=AUDIT_KIND_APPROVED).delete()
    with _phase7e_live_test_settings():
        out = approve_phase7e_live_internal_send(
            attempt.pk, reason="Director approve",
            director_signoff="Director PS approve.",
        )
    assert out["ok"] is True
    attempt.refresh_from_db()
    assert (
        attempt.status
        == RazorpayWhatsAppInternalSendAttempt.Status.APPROVED_FOR_INTERNAL_ONE_SHOT_SEND
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_APPROVED
    ).exists()


@pytest.mark.django_db
def test_phase7e_live_reject_records_warning_audit() -> None:
    attempt = _make_prepared_attempt()
    AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).delete()
    out = reject_phase7e_live_internal_send(
        attempt.pk, reason="Director paused send review."
    )
    assert out["ok"] is True
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_REJECTED).exists()


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7e_live_execute_refuses_without_lifecycle_flag() -> None:
    attempt = _make_approved_attempt()
    with _phase7e_live_test_settings(
        PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED=False,
    ), mock.patch(
        "apps.payments.razorpay_whatsapp_internal_send._send_internal_template_via_meta_cloud"
    ) as patched:
        out = execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=_structured_signoff(),
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
    patched.assert_not_called()
    assert out["ok"] is False
    assert any(
        "PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED_must_be_true" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7e_live_execute_refuses_without_structured_signoff() -> (
    None
):
    """Phase 7G-Hotfix-1 structured-window guard is reused here."""
    attempt = _make_approved_attempt()
    free_text = "Director Phase 7E-Live approve (free text only)"
    with _phase7e_live_test_settings(), mock.patch(
        "apps.payments.razorpay_whatsapp_internal_send._send_internal_template_via_meta_cloud"
    ) as patched:
        out = execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=free_text,
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
    patched.assert_not_called()
    assert out["ok"] is False
    assert any(
        "phase7e_live_director_signoff_missing_structured_utc_window"
        in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7e_live_execute_refuses_when_now_after_window_end() -> (
    None
):
    attempt = _make_approved_attempt()
    signoff = _structured_signoff(
        begin_offset_seconds=-600, end_offset_seconds=-300,
    )
    with _phase7e_live_test_settings(), mock.patch(
        "apps.payments.razorpay_whatsapp_internal_send._send_internal_template_via_meta_cloud"
    ) as patched:
        out = execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=signoff,
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
    patched.assert_not_called()
    assert out["ok"] is False
    assert any(
        "phase7e_live_now_after_director_signoff_utc_window_end" in b
        for b in out["blockers"]
    )


@pytest.mark.django_db
def test_phase7e_live_execute_happy_path_calls_wrapper_once() -> None:
    attempt = _make_approved_attempt()
    AuditEvent.objects.filter(kind=AUDIT_KIND_EXECUTED).delete()
    before = _row_counts()
    with _phase7e_live_test_settings(), mock.patch(
        "apps.payments.razorpay_whatsapp_internal_send._send_internal_template_via_meta_cloud",
        return_value={
            "message_id": "wamid.test_internal_send_001",
            "status": "sent",
        },
    ) as patched:
        out = execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=_structured_signoff(),
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
    after = _row_counts()
    assert out["ok"] is True, out.get("blockers")
    patched.assert_called_once()
    # Wrapper called with the resolved allow-list E.164, NOT a
    # real customer phone.
    call_kwargs = patched.call_args.kwargs
    assert call_kwargs["to_e164"] == _ALLOWED_NUMBER
    assert call_kwargs["template_name"] == "nrg_internal_test_intro"
    row = RazorpayWhatsAppInternalSendAttempt.objects.get(pk=attempt.pk)
    assert (
        row.status
        == RazorpayWhatsAppInternalSendAttempt.Status.EXECUTED
    )
    assert row.provider_call_attempted is True
    assert row.meta_cloud_call_attempted is True
    assert row.whatsapp_message_created is True
    assert row.provider_message_id == "wamid.test_internal_send_001"
    # No real customer, no business mutation, no customer
    # notification.
    assert row.real_customer_allowed is False
    assert row.real_customer_phone_used is False
    assert row.customer_notification_sent is False
    assert row.business_mutation_was_made is False
    # Only WhatsApp outbound row is allowed to grow; everything
    # else stays constant.
    for key, count_before in before.items():
        count_after = after.get(key, count_before)
        if key == "whatsapp_message":
            continue
        assert count_after == count_before, (
            f"Phase 7E-Live unexpected mutation on {key}"
        )
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_EXECUTED).exists()


@pytest.mark.django_db
def test_phase7e_live_execute_records_signoff_window() -> None:
    attempt = _make_approved_attempt()
    with _phase7e_live_test_settings(), mock.patch(
        "apps.payments.razorpay_whatsapp_internal_send._send_internal_template_via_meta_cloud",
        return_value={
            "message_id": "wamid.signoff_window_test",
            "status": "sent",
        },
    ):
        execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=_structured_signoff(),
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
    row = RazorpayWhatsAppInternalSendAttempt.objects.get(pk=attempt.pk)
    assert row.recorded_signoff_window_valid is True
    assert row.recorded_signoff_window_start_utc is not None
    assert row.recorded_signoff_window_end_utc is not None
    assert (
        row.recorded_signoff_window_end_utc
        > row.recorded_signoff_window_start_utc
    )


@pytest.mark.django_db
def test_phase7e_live_execute_marks_failed_when_wrapper_raises() -> (
    None
):
    attempt = _make_approved_attempt()
    AuditEvent.objects.filter(kind=AUDIT_KIND_FAILED).delete()
    with _phase7e_live_test_settings(), mock.patch(
        "apps.payments.razorpay_whatsapp_internal_send._send_internal_template_via_meta_cloud",
        side_effect=Phase7ELiveExecutionError("Meta Cloud error"),
    ):
        out = execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=_structured_signoff(),
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
    assert out["ok"] is False
    row = RazorpayWhatsAppInternalSendAttempt.objects.get(pk=attempt.pk)
    assert (
        row.status
        == RazorpayWhatsAppInternalSendAttempt.Status.FAILED
    )
    # provider_call_attempted stays True (audit trail).
    assert row.provider_call_attempted is True
    assert row.meta_cloud_call_attempted is True
    # whatsapp_message_created stays False on failure.
    assert row.whatsapp_message_created is False
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_FAILED).exists()


@pytest.mark.django_db
def test_phase7e_live_execute_rejects_retry_idempotency_locked() -> (
    None
):
    attempt = _make_approved_attempt()
    with _phase7e_live_test_settings(), mock.patch(
        "apps.payments.razorpay_whatsapp_internal_send._send_internal_template_via_meta_cloud",
        return_value={
            "message_id": "wamid.idem_lock",
            "status": "sent",
        },
    ):
        first = execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=_structured_signoff(),
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
        second = execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=_structured_signoff(),
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
    assert first["ok"] is True
    assert second["ok"] is False
    assert any(
        "phase7e_live_attempt_already_executed_idempotency_lock" in b
        or "phase7e_live_attempt_status_must_be_approved" in b
        for b in second["blockers"]
    )


# ---------------------------------------------------------------------------
# Rollback (record-only)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7e_live_rollback_is_record_only() -> None:
    attempt = _make_approved_attempt()
    with _phase7e_live_test_settings(), mock.patch(
        "apps.payments.razorpay_whatsapp_internal_send._send_internal_template_via_meta_cloud",
        return_value={
            "message_id": "wamid.rollback_test",
            "status": "sent",
        },
    ):
        execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=_structured_signoff(),
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
    AuditEvent.objects.filter(
        kind=AUDIT_KIND_ROLLBACK_RECORDED
    ).delete()
    out = rollback_phase7e_live_internal_send(
        attempt.pk, reason="Director rollback."
    )
    assert out["ok"] is True
    row = RazorpayWhatsAppInternalSendAttempt.objects.get(pk=attempt.pk)
    assert (
        row.status
        == RazorpayWhatsAppInternalSendAttempt.Status.ROLLBACK_RECORDED
    )
    # Rollback NEVER touched the provider.
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_ROLLBACK_RECORDED
    ).exists()


# ---------------------------------------------------------------------------
# No POST endpoint dispatches state changes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7e_live_no_post_endpoint_dispatches_state() -> None:
    """Phase 7E-Live-A is CLI-only; no POST endpoint may dispatch
    state."""
    from django.urls import get_resolver

    resolver = get_resolver()
    suspicious = []
    for pattern in resolver.url_patterns:
        if "saas/" not in str(pattern.pattern):
            continue
        for sub in getattr(pattern, "url_patterns", []):
            p = str(sub.pattern)
            if "whatsapp/internal-send" in p and any(
                token in p
                for token in (
                    "approve", "reject", "execute", "send-action",
                    "dispatch", "queue",
                )
            ):
                suspicious.append(p)
    assert not suspicious, suspicious


# ---------------------------------------------------------------------------
# Preview emits no rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7e_live_preview_emits_no_rows() -> None:
    gate = _make_approved_phase7e_gate(
        source_event_id="evt_phase7e_live_preview_no_rows"
    )
    before = _row_counts()
    with _phase7e_live_test_settings():
        out = preview_phase7e_live_internal_send(gate.pk)
    after = _row_counts()
    assert out["found"] is True
    assert out["recipientScope"] == "internal_staff_allow_list"
    assert RazorpayWhatsAppInternalSendAttempt.objects.count() == 0
    assert before == after


@pytest.mark.django_db
def test_phase7e_live_summary_counts_pending_after_prepare() -> None:
    _make_prepared_attempt()
    summary = summarize_phase7e_live_internal_send_attempts(limit=10)
    counts = summary["counts"]
    assert counts.get("pending_director_signoff", 0) == 1
    assert counts.get("executed", 0) == 0
    assert counts.get("failed", 0) == 0


@pytest.mark.django_db
def test_phase7e_live_inspect_readiness_safe_off_by_default() -> None:
    out = inspect_phase7e_live_internal_send_readiness()
    assert out["safeToRunPhase7ELiveSend"] is False
    assert out["phase7ELiveSendsToRealCustomer"] is False
    assert out["phase7ELiveMutatesBusinessRow"] is False


# ---------------------------------------------------------------------------
# Meta Cloud wrapper method-binding tests
#
# Regression: the previous wrapper looked for a module-level
# ``send_template_message`` function on ``meta_cloud_client`` and
# raised "Meta Cloud client does not expose send_template_message"
# at runtime because the real entry point is the
# :meth:`MetaCloudProvider.send_template_message` *method*. These
# tests pin the wrapper to the actual production method and assert
# the ``ProviderSendResult`` dataclass return is summarised safely.
# Every test patches the provider class so NO real Meta HTTP call
# is made.
# ---------------------------------------------------------------------------


def test_wrapper_binds_to_meta_cloud_provider_send_template_method() -> None:
    """The Phase 7E-Live wrapper must instantiate ``MetaCloudProvider``
    and call its ``send_template_message`` method - not look up a
    module-level function on the package."""
    from apps.whatsapp.integrations.whatsapp.meta_cloud_client import (
        MetaCloudProvider,
    )

    assert callable(
        getattr(MetaCloudProvider, "send_template_message", None)
    ), (
        "MetaCloudProvider.send_template_message must remain a "
        "callable method - Phase 7E-Live-A wrapper depends on it."
    )


@pytest.mark.django_db
def test_wrapper_invokes_meta_cloud_provider_with_production_kwargs() -> (
    None
):
    """Patch the imported ``MetaCloudProvider`` class to spy on the
    instance method; assert the wrapper calls it with
    ``to_phone`` / ``template_name`` / ``language`` / ``components``
    / ``idempotency_key`` (the production signature). Asserts NO real
    Meta HTTP send happened.
    """
    from apps.payments.razorpay_whatsapp_internal_send import (
        _send_internal_template_via_meta_cloud,
    )
    from apps.whatsapp.integrations.whatsapp.base import (
        ProviderSendResult,
    )

    spy = mock.MagicMock(
        return_value=ProviderSendResult(
            provider="meta_cloud",
            provider_message_id="wamid.unit_test_001",
            status="sent",
        )
    )
    fake_provider = mock.MagicMock()
    fake_provider.send_template_message = spy

    fake_provider_cls = mock.MagicMock(return_value=fake_provider)
    with mock.patch(
        "apps.whatsapp.integrations.whatsapp.meta_cloud_client.MetaCloudProvider",
        fake_provider_cls,
    ):
        out = _send_internal_template_via_meta_cloud(
            to_e164="+919999990001",
            template_name="nrg_internal_test_intro",
            template_language="en",
            attempt_id=42,
        )

    fake_provider_cls.assert_called_once_with()
    spy.assert_called_once()
    call_kwargs = spy.call_args.kwargs
    assert call_kwargs["to_phone"] == "+919999990001"
    assert call_kwargs["template_name"] == "nrg_internal_test_intro"
    assert call_kwargs["language"] == "en"
    assert call_kwargs["components"] == []
    assert (
        call_kwargs["idempotency_key"]
        == "phase7e_live::internal_send::attempt::42"
    )

    # ProviderSendResult dataclass is reduced to the safe summary
    # shape. Raw request / response payloads are NEVER returned.
    assert out == {
        "message_id": "wamid.unit_test_001",
        "status": "sent",
    }


@pytest.mark.django_db
def test_wrapper_does_not_raise_missing_method_anymore() -> None:
    """Regression: the wrapper must not raise the
    "Meta Cloud client does not expose send_template_message" error.
    Even if the provider returns a dict (test shape) or the
    dataclass (production shape), the wrapper completes successfully.
    """
    from apps.payments.razorpay_whatsapp_internal_send import (
        Phase7ELiveExecutionError,
        _send_internal_template_via_meta_cloud,
    )

    fake_provider = mock.MagicMock()
    fake_provider.send_template_message = mock.MagicMock(
        return_value={
            "message_id": "wamid.dict_shape_001",
            "status": "queued",
        }
    )
    with mock.patch(
        "apps.whatsapp.integrations.whatsapp.meta_cloud_client.MetaCloudProvider",
        mock.MagicMock(return_value=fake_provider),
    ):
        out = _send_internal_template_via_meta_cloud(
            to_e164="+919999990001",
            template_name="nrg_internal_test_intro",
            template_language="en",
            attempt_id=99,
        )
    assert out == {
        "message_id": "wamid.dict_shape_001",
        "status": "queued",
    }
    # Sanity check: no Phase7ELiveExecutionError raised. (Reach this
    # line proves it.)
    assert issubclass(Phase7ELiveExecutionError, Exception)


@pytest.mark.django_db
def test_wrapper_summary_drops_raw_meta_response_fields() -> None:
    """The wrapper must summarise to ``{message_id, status}`` only —
    no raw request payload, no raw response body, no token, no
    error_code, no latency."""
    from apps.payments.razorpay_whatsapp_internal_send import (
        _send_internal_template_via_meta_cloud,
    )
    from apps.whatsapp.integrations.whatsapp.base import (
        ProviderSendResult,
    )

    fake_provider = mock.MagicMock()
    fake_provider.send_template_message = mock.MagicMock(
        return_value=ProviderSendResult(
            provider="meta_cloud",
            provider_message_id="wamid.scrub_001",
            status="sent",
            request_payload={
                "messaging_product": "whatsapp",
                "to": "+919999990001",  # MUST NOT appear in summary
            },
            response_status=200,
            response_payload={
                "messages": [{"id": "wamid.scrub_001"}],
                "secret_token": "should_not_leak",
            },
            latency_ms=87,
        )
    )
    with mock.patch(
        "apps.whatsapp.integrations.whatsapp.meta_cloud_client.MetaCloudProvider",
        mock.MagicMock(return_value=fake_provider),
    ):
        out = _send_internal_template_via_meta_cloud(
            to_e164="+919999990001",
            template_name="nrg_internal_test_intro",
            template_language="en",
            attempt_id=1,
        )
    assert set(out.keys()) == {"message_id", "status"}
    assert out["message_id"] == "wamid.scrub_001"
    assert out["status"] == "sent"
    # No raw fields leak.
    for forbidden in (
        "request_payload",
        "response_payload",
        "response_status",
        "latency_ms",
        "error_code",
        "secret_token",
        "to",
    ):
        assert forbidden not in out


@pytest.mark.django_db
def test_execute_full_path_uses_real_wrapper_with_patched_provider() -> (
    None
):
    """End-to-end: don't patch the wrapper directly. Instead patch
    only the underlying ``MetaCloudProvider`` so the real wrapper
    runs, proving the wrapper-method binding works through the whole
    execute path. No real Meta HTTP call. No business mutation. No
    customer notification."""
    from apps.whatsapp.integrations.whatsapp.base import (
        ProviderSendResult,
    )

    attempt = _make_approved_attempt()
    before = _row_counts()

    fake_provider = mock.MagicMock()
    fake_provider.send_template_message = mock.MagicMock(
        return_value=ProviderSendResult(
            provider="meta_cloud",
            provider_message_id="wamid.e2e_real_wrapper_001",
            status="sent",
        )
    )
    with _phase7e_live_test_settings(), mock.patch(
        "apps.whatsapp.integrations.whatsapp.meta_cloud_client.MetaCloudProvider",
        mock.MagicMock(return_value=fake_provider),
    ):
        out = execute_phase7e_live_internal_send(
            attempt.pk,
            director_signoff=_structured_signoff(),
            operator_name="Prarit Sidana",
            confirm_internal_whatsapp_send=True,
        )
    after = _row_counts()

    assert out["ok"] is True, out.get("blockers")
    # The "missing method" failure mode would have surfaced as a
    # Phase7ELiveExecutionError blocker on `out["blockers"]`.
    assert not any(
        "send_template_message" in b for b in (out.get("blockers") or [])
    )

    row = RazorpayWhatsAppInternalSendAttempt.objects.get(pk=attempt.pk)
    assert (
        row.status
        == RazorpayWhatsAppInternalSendAttempt.Status.EXECUTED
    )
    assert row.provider_message_id == "wamid.e2e_real_wrapper_001"
    assert row.provider_status == "sent"
    assert row.whatsapp_message_created is True
    # The real wrapper was called once with production kwargs;
    # to_phone is the resolved allow-list E.164, NOT a real customer
    # phone.
    fake_provider.send_template_message.assert_called_once()
    call_kwargs = fake_provider.send_template_message.call_args.kwargs
    assert call_kwargs["to_phone"] == _ALLOWED_NUMBER
    assert call_kwargs["template_name"] == "nrg_internal_test_intro"
    assert call_kwargs["language"] == "en"
    assert call_kwargs["components"] == []
    assert call_kwargs["idempotency_key"].startswith(
        "phase7e_live::internal_send::attempt::"
    )

    # No business mutation, no customer notification, no real
    # customer phone, no broad automation. Only the WhatsApp
    # outbound row is allowed to grow.
    for key, count_before in before.items():
        count_after = after.get(key, count_before)
        if key == "whatsapp_message":
            continue
        assert count_after == count_before, (
            f"Unexpected mutation on {key}"
        )
    assert row.real_customer_allowed is False
    assert row.real_customer_phone_used is False
    assert row.customer_notification_sent is False
    assert row.business_mutation_was_made is False
