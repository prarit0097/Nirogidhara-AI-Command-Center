"""Phase 14D — backend tests for the AI Kill Switch UI wiring.

The Phase 6H ``GET /api/v1/saas/runtime-live-gate/kill-switch/`` view is
extended in Phase 14D with a typed-phrase + reason-gated POST. The
existing CLI commands ``enable_runtime_kill_switch`` /
``disable_runtime_kill_switch`` continue to work — the POST is an
additional UI surface, not a replacement.

These tests cover:

- GET auth (anonymous blocked, viewer blocked, admin OK).
- Phase 14D unambiguous response fields.
- POST auth + payload validation (action, reason length, confirmation phrase).
- POST activate_emergency_stop → ``RuntimeKillSwitch.enabled=True`` + audit.
- POST resume_ai_operations → ``RuntimeKillSwitch.enabled=False`` + audit.
- AuditEvent: ``runtime.kill_switch.ui_changed`` carries ``phase="14D"``,
  actor, previous/new state, reason; never leaks tokens / phones / payloads.
- Defensive safety — POST does NOT call WhatsApp / Vapi / Razorpay /
  Delhivery / Meta Cloud outbound functions; does NOT mutate any
  ``Order`` / ``Payment`` / ``Customer`` / ``Lead`` / ``Shipment`` /
  ``WhatsAppMessage`` / ``Call`` business row.
- Existing CLI commands still flip the same canonical row.
"""
from __future__ import annotations

from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient


KILL_SWITCH_URL = "/api/v1/saas/runtime-live-gate/kill-switch/"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, django_user_model) -> APIClient:
    user = django_user_model.objects.create_user(
        username="phase14d_admin",
        email="phase14d_admin@example.com",
        password="ignored-by-force-auth",
    )
    user.is_staff = True
    user.is_superuser = True
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def viewer_client(db, django_user_model) -> APIClient:
    """Authenticated non-admin user (the Phase 14D POST + GET refuse it)."""
    user = django_user_model.objects.create_user(
        username="phase14d_viewer",
        email="phase14d_viewer@example.com",
        password="ignored-by-force-auth",
    )
    # Note: not staff, not superuser, no admin/director role.
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def anonymous_client() -> APIClient:
    return APIClient()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_counts() -> dict[str, int]:
    """Snapshot every business table the kill switch must never mutate."""
    from apps.orders.models import Order, DiscountOfferLog
    from apps.payments.models import Payment
    from apps.crm.models import Customer, Lead
    from apps.shipments.models import Shipment
    from apps.whatsapp.models import WhatsAppMessage
    from apps.calls.models import Call
    from apps.audit.models import AuditEvent

    return {
        "Order": Order.objects.count(),
        "DiscountOfferLog": DiscountOfferLog.objects.count(),
        "Payment": Payment.objects.count(),
        "Customer": Customer.objects.count(),
        "Lead": Lead.objects.count(),
        "Shipment": Shipment.objects.count(),
        "WhatsAppMessage": WhatsAppMessage.objects.count(),
        "Call": Call.objects.count(),
        # AuditEvent count is intentionally NOT in the defensive
        # assertion — the POST is expected to add audit rows.
    }


# ---------------------------------------------------------------------------
# GET behaviour
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_kill_switch_blocks_anonymous(anonymous_client: APIClient) -> None:
    res = anonymous_client.get(KILL_SWITCH_URL)
    # 401 or 403 both acceptable — depends on the auth class layering.
    assert res.status_code in (401, 403), res.status_code


@pytest.mark.django_db
def test_get_kill_switch_blocks_viewer(viewer_client: APIClient) -> None:
    res = viewer_client.get(KILL_SWITCH_URL)
    # Phase 14D tightened from IsAuthenticated to AdminSaasPermission.
    assert res.status_code == 403


@pytest.mark.django_db
def test_get_kill_switch_admin_returns_phase14d_fields(
    admin_client: APIClient,
) -> None:
    res = admin_client.get(KILL_SWITCH_URL)
    assert res.status_code == 200
    body = res.json()
    # Phase 14D unambiguous fields.
    assert "enabled" in body
    assert "runtimeKillSwitchEnabled" in body
    assert "aiExecutionBlocked" in body
    assert "statusLabel" in body
    assert body["statusLabel"] in {"running", "paused"}
    # statusLabel must agree with the canonical enabled field.
    if body["enabled"]:
        assert body["statusLabel"] == "paused"
        assert body["aiExecutionBlocked"] is True
    else:
        assert body["statusLabel"] == "running"
        assert body["aiExecutionBlocked"] is False
    # Confirmation phrases must be present so the frontend can render
    # the exact strings it has to require typed.
    assert body["confirmationPhrases"]["activateEmergencyStop"] == "ACTIVATE KILL SWITCH"
    assert body["confirmationPhrases"]["resumeAiOperations"] == "RESUME AI OPERATIONS"


# ---------------------------------------------------------------------------
# POST validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_kill_switch_blocks_anonymous(
    anonymous_client: APIClient,
) -> None:
    res = anonymous_client.post(
        KILL_SWITCH_URL,
        {"action": "activate_emergency_stop", "reason": "doesnt matter",
         "confirmationPhrase": "ACTIVATE KILL SWITCH"},
        format="json",
    )
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_post_kill_switch_blocks_viewer(viewer_client: APIClient) -> None:
    res = viewer_client.post(
        KILL_SWITCH_URL,
        {"action": "activate_emergency_stop", "reason": "doesnt matter at all",
         "confirmationPhrase": "ACTIVATE KILL SWITCH"},
        format="json",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_post_kill_switch_refuses_unknown_action(
    admin_client: APIClient,
) -> None:
    res = admin_client.post(
        KILL_SWITCH_URL,
        {"action": "nuke_everything", "reason": "definitely not allowed",
         "confirmationPhrase": "ACTIVATE KILL SWITCH"},
        format="json",
    )
    assert res.status_code == 400
    assert "action" in res.json()["detail"].lower()


@pytest.mark.django_db
def test_post_kill_switch_refuses_missing_reason(
    admin_client: APIClient,
) -> None:
    res = admin_client.post(
        KILL_SWITCH_URL,
        {"action": "activate_emergency_stop", "reason": "",
         "confirmationPhrase": "ACTIVATE KILL SWITCH"},
        format="json",
    )
    assert res.status_code == 400
    assert "reason" in res.json()["detail"].lower()


@pytest.mark.django_db
def test_post_kill_switch_refuses_short_reason(
    admin_client: APIClient,
) -> None:
    res = admin_client.post(
        KILL_SWITCH_URL,
        {"action": "activate_emergency_stop", "reason": "too short",
         "confirmationPhrase": "ACTIVATE KILL SWITCH"},
        format="json",
    )
    assert res.status_code == 400


@pytest.mark.django_db
def test_post_kill_switch_refuses_wrong_confirmation_phrase(
    admin_client: APIClient,
) -> None:
    res = admin_client.post(
        KILL_SWITCH_URL,
        {"action": "activate_emergency_stop",
         "reason": "Operator drill — refusal test",
         "confirmationPhrase": "ACTIVATE KILL SWICH"},  # typo on purpose
        format="json",
    )
    assert res.status_code == 400
    assert "confirmation" in res.json()["detail"].lower()


@pytest.mark.django_db
def test_post_kill_switch_refuses_phrase_swap(
    admin_client: APIClient,
) -> None:
    """Activate-emergency-stop action must reject the resume phrase, even
    though both phrases are valid for *some* action."""
    res = admin_client.post(
        KILL_SWITCH_URL,
        {"action": "activate_emergency_stop",
         "reason": "Operator drill — wrong phrase",
         "confirmationPhrase": "RESUME AI OPERATIONS"},
        format="json",
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# POST happy paths — activate + resume
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_activate_emergency_stop_sets_enabled_true(
    admin_client: APIClient,
) -> None:
    from apps.saas.live_gate import get_or_create_default_runtime_kill_switch
    from apps.saas.models import RuntimeKillSwitch

    # Start from a known-disabled state so the transition is real.
    switch = get_or_create_default_runtime_kill_switch()
    switch.enabled = False
    switch.save()

    res = admin_client.post(
        KILL_SWITCH_URL,
        {"action": "activate_emergency_stop",
         "reason": "Compliance incident drill — pause AI",
         "confirmationPhrase": "ACTIVATE KILL SWITCH"},
        format="json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["enabled"] is True
    assert body["aiExecutionBlocked"] is True
    assert body["statusLabel"] == "paused"

    # Canonical DB state matches API response.
    fresh = RuntimeKillSwitch.objects.get(
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        organization=None,
        provider_type="",
        operation_type="",
    )
    assert fresh.enabled is True


@pytest.mark.django_db
def test_post_resume_ai_operations_sets_enabled_false(
    admin_client: APIClient,
) -> None:
    from apps.saas.live_gate import get_or_create_default_runtime_kill_switch
    from apps.saas.models import RuntimeKillSwitch

    # Start from a known-active (paused) state.
    switch = get_or_create_default_runtime_kill_switch()
    switch.enabled = True
    switch.save()

    res = admin_client.post(
        KILL_SWITCH_URL,
        {"action": "resume_ai_operations",
         "reason": "Incident resolved — resume daily AI sweeps",
         "confirmationPhrase": "RESUME AI OPERATIONS"},
        format="json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["enabled"] is False
    assert body["aiExecutionBlocked"] is False
    assert body["statusLabel"] == "running"

    fresh = RuntimeKillSwitch.objects.get(
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        organization=None,
        provider_type="",
        operation_type="",
    )
    assert fresh.enabled is False


# ---------------------------------------------------------------------------
# AuditEvent emission
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_writes_runtime_kill_switch_ui_changed_audit(
    admin_client: APIClient,
) -> None:
    from apps.audit.models import AuditEvent
    from apps.saas.live_gate import get_or_create_default_runtime_kill_switch

    switch = get_or_create_default_runtime_kill_switch()
    switch.enabled = False
    switch.save()

    res = admin_client.post(
        KILL_SWITCH_URL,
        {"action": "activate_emergency_stop",
         "reason": "Phase 14D audit-emission test",
         "confirmationPhrase": "ACTIVATE KILL SWITCH"},
        format="json",
    )
    assert res.status_code == 200

    ui_event = (
        AuditEvent.objects.filter(kind="runtime.kill_switch.ui_changed")
        .order_by("-pk")
        .first()
    )
    assert ui_event is not None, "Phase 14D UI audit row not written"
    payload = ui_event.payload or {}
    assert payload.get("phase") == "14D"
    assert payload.get("source") == "ui"
    assert payload.get("action") == "activate_emergency_stop"
    assert payload.get("previous_enabled") is False
    assert payload.get("new_enabled") is True
    assert payload.get("previous_ai_execution_blocked") is False
    assert payload.get("new_ai_execution_blocked") is True
    assert "Phase 14D" in payload.get("reason", "")
    # No secrets / phones / tokens / raw payloads in the audit body.
    payload_str = str(payload).lower()
    for forbidden in (
        "razorpay_key_secret",
        "meta_wa_token",
        "vapi_api_key",
        "openai_api_key",
        "anthropic_api_key",
    ):
        assert forbidden not in payload_str

    # The legacy enabled/disabled audit row from set_runtime_kill_switch
    # also fires — verify both coexist (defense in depth at audit time).
    legacy_event = (
        AuditEvent.objects.filter(kind="runtime.kill_switch.enabled")
        .order_by("-pk")
        .first()
    )
    assert legacy_event is not None, "Legacy CLI-style audit row missing"


# ---------------------------------------------------------------------------
# Defensive safety — Phase 14D NEVER calls providers or mutates business rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_never_calls_outbound_providers_or_mutates_business(
    admin_client: APIClient,
) -> None:
    """Phase 14D safety contract: the UI flip is a pure DB write on one
    RuntimeKillSwitch row + audit events. It must never call any
    outbound provider and must never mutate any business row.
    """
    from apps.saas.live_gate import get_or_create_default_runtime_kill_switch

    switch = get_or_create_default_runtime_kill_switch()
    switch.enabled = False
    switch.save()

    before = _row_counts()

    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as m_queue_template, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as m_send_freeform, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as m_trigger_call, mock.patch(
        "apps.shipments.services.create_shipment"
    ) as m_create_shipment:
        res = admin_client.post(
            KILL_SWITCH_URL,
            {
                "action": "activate_emergency_stop",
                "reason": "Phase 14D defensive safety test",
                "confirmationPhrase": "ACTIVATE KILL SWITCH",
            },
            format="json",
        )
        assert res.status_code == 200

        # No provider entrypoint may be called.
        m_queue_template.assert_not_called()
        m_send_freeform.assert_not_called()
        m_trigger_call.assert_not_called()
        m_create_shipment.assert_not_called()

    after = _row_counts()
    assert before == after, (
        f"Phase 14D POST must not mutate any business row. "
        f"Before: {before}\nAfter: {after}"
    )


# ---------------------------------------------------------------------------
# Backward compatibility — existing CLI helpers still flip the same row
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_existing_cli_helpers_still_flip_same_canonical_row() -> None:
    """Phase 14D does not break ``enable_runtime_kill_switch`` /
    ``disable_runtime_kill_switch``. They call the same
    ``set_runtime_kill_switch`` helper the new POST does.
    """
    from apps.saas.live_gate import (
        get_or_create_default_runtime_kill_switch,
        set_runtime_kill_switch,
    )
    from apps.saas.models import RuntimeKillSwitch

    switch = get_or_create_default_runtime_kill_switch()
    switch.enabled = False
    switch.save()

    set_runtime_kill_switch(
        enabled=True,
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        reason="CLI smoke from test",
    )
    assert (
        RuntimeKillSwitch.objects.get(
            scope=RuntimeKillSwitch.Scope.GLOBAL,
            organization=None,
            provider_type="",
            operation_type="",
        ).enabled
        is True
    )

    set_runtime_kill_switch(
        enabled=False,
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        reason="CLI smoke disable",
    )
    assert (
        RuntimeKillSwitch.objects.get(
            scope=RuntimeKillSwitch.Scope.GLOBAL,
            organization=None,
            provider_type="",
            operation_type="",
        ).enabled
        is False
    )
