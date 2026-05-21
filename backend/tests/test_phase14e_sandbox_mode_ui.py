"""Phase 14E — backend tests for the Sandbox Mode UI wiring.

The existing Phase 3D ``GET / PATCH /api/ai/sandbox/status/`` view is
extended in Phase 14E with a typed-phrase + reason-gated POST. The
existing GET + PATCH stay backward-compatible — Phase 3D / 4D
consumers continue to work unchanged.

These tests cover:

- GET auth (anonymous blocked, viewer blocked, admin returns
  Phase 14E unambiguous fields).
- POST auth + payload validation (action, reason length, confirmation
  phrase, phrase swap).
- POST ``enable_sandbox_mode`` flips ``SandboxState.is_enabled`` to
  True and writes a ``sandbox.mode.ui_changed`` audit row alongside
  the legacy ``ai.sandbox.enabled`` row.
- POST ``disable_sandbox_mode`` flips back to False AND preserves the
  Phase 4C approval matrix gate (director-only via ``director_override``
  — a director user is allowed, a plain admin would be refused by the
  matrix).
- AuditEvent payload contract — phase=14E, source=ui, previous/new
  state, actor — never tokens / phones / raw secrets.
- Defensive safety — POST does NOT call WhatsApp / Vapi / Razorpay /
  Delhivery outbound functions; does NOT mutate any business row.
- Existing CLI / service helper still flips the same singleton.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient


SANDBOX_URL = "/api/ai/sandbox/status/"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def director_client(db, django_user_model) -> APIClient:
    """Director user — passes the Phase 4C matrix gate on disable."""
    user = django_user_model.objects.create_user(
        username="phase14e_director",
        email="phase14e_director@example.com",
        password="ignored-by-force-auth",
    )
    user.is_staff = True
    user.is_superuser = True
    # The Phase 4C matrix gate on ai.sandbox.disable is director_override
    # mode — a non-director admin gets refused.
    user.role = "director"
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def viewer_client(db, django_user_model) -> APIClient:
    """Authenticated non-admin user — refused by _AdminAndUpAlways."""
    user = django_user_model.objects.create_user(
        username="phase14e_viewer",
        email="phase14e_viewer@example.com",
        password="ignored-by-force-auth",
    )
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


def _row_counts() -> dict:
    """Snapshot every business table the sandbox flip must never mutate."""
    from apps.orders.models import Order, DiscountOfferLog
    from apps.payments.models import Payment
    from apps.crm.models import Customer, Lead
    from apps.shipments.models import Shipment
    from apps.whatsapp.models import WhatsAppMessage
    from apps.calls.models import Call

    return {
        "Order": Order.objects.count(),
        "DiscountOfferLog": DiscountOfferLog.objects.count(),
        "Payment": Payment.objects.count(),
        "Customer": Customer.objects.count(),
        "Lead": Lead.objects.count(),
        "Shipment": Shipment.objects.count(),
        "WhatsAppMessage": WhatsAppMessage.objects.count(),
        "Call": Call.objects.count(),
    }


# ---------------------------------------------------------------------------
# GET behaviour
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_sandbox_blocks_anonymous(anonymous_client: APIClient) -> None:
    res = anonymous_client.get(SANDBOX_URL)
    assert res.status_code in (401, 403), res.status_code


@pytest.mark.django_db
def test_get_sandbox_blocks_viewer(viewer_client: APIClient) -> None:
    res = viewer_client.get(SANDBOX_URL)
    assert res.status_code == 403


@pytest.mark.django_db
def test_get_sandbox_admin_returns_phase14e_fields(
    director_client: APIClient,
) -> None:
    res = director_client.get(SANDBOX_URL)
    assert res.status_code == 200
    body = res.json()
    # Phase 3D legacy fields still present.
    assert "isEnabled" in body
    assert "updatedBy" in body
    # Phase 14E unambiguous additions.
    assert "sandboxEnabled" in body
    assert "statusLabel" in body
    assert body["statusLabel"] in {"enabled", "disabled"}
    assert "confirmationPhrases" in body
    assert body["confirmationPhrases"]["enableSandboxMode"] == "ENABLE SANDBOX MODE"
    assert (
        body["confirmationPhrases"]["disableSandboxMode"]
        == "DISABLE SANDBOX MODE"
    )
    # statusLabel must agree with the canonical isEnabled value.
    if body["isEnabled"]:
        assert body["statusLabel"] == "enabled"
        assert body["sandboxEnabled"] is True
    else:
        assert body["statusLabel"] == "disabled"
        assert body["sandboxEnabled"] is False


# ---------------------------------------------------------------------------
# POST validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_sandbox_blocks_anonymous(anonymous_client: APIClient) -> None:
    res = anonymous_client.post(
        SANDBOX_URL,
        {
            "action": "enable_sandbox_mode",
            "reason": "doesnt matter",
            "confirmationPhrase": "ENABLE SANDBOX MODE",
        },
        format="json",
    )
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_post_sandbox_blocks_viewer(viewer_client: APIClient) -> None:
    res = viewer_client.post(
        SANDBOX_URL,
        {
            "action": "enable_sandbox_mode",
            "reason": "doesnt matter at all",
            "confirmationPhrase": "ENABLE SANDBOX MODE",
        },
        format="json",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_post_sandbox_refuses_unknown_action(
    director_client: APIClient,
) -> None:
    res = director_client.post(
        SANDBOX_URL,
        {
            "action": "nuke_everything",
            "reason": "definitely not allowed",
            "confirmationPhrase": "ENABLE SANDBOX MODE",
        },
        format="json",
    )
    assert res.status_code == 400
    assert "action" in res.json()["detail"].lower()


@pytest.mark.django_db
def test_post_sandbox_refuses_missing_reason(
    director_client: APIClient,
) -> None:
    res = director_client.post(
        SANDBOX_URL,
        {
            "action": "enable_sandbox_mode",
            "reason": "",
            "confirmationPhrase": "ENABLE SANDBOX MODE",
        },
        format="json",
    )
    assert res.status_code == 400
    assert "reason" in res.json()["detail"].lower()


@pytest.mark.django_db
def test_post_sandbox_refuses_short_reason(
    director_client: APIClient,
) -> None:
    res = director_client.post(
        SANDBOX_URL,
        {
            "action": "enable_sandbox_mode",
            "reason": "too short",
            "confirmationPhrase": "ENABLE SANDBOX MODE",
        },
        format="json",
    )
    assert res.status_code == 400


@pytest.mark.django_db
def test_post_sandbox_refuses_wrong_phrase(
    director_client: APIClient,
) -> None:
    res = director_client.post(
        SANDBOX_URL,
        {
            "action": "enable_sandbox_mode",
            "reason": "Sandbox enable drill",
            "confirmationPhrase": "ENABLE SANBOX MODE",  # typo
        },
        format="json",
    )
    assert res.status_code == 400
    assert "confirmation" in res.json()["detail"].lower()


@pytest.mark.django_db
def test_post_sandbox_refuses_phrase_swap(
    director_client: APIClient,
) -> None:
    """The enable action must reject the disable phrase, and vice versa.

    Both phrases are individually valid, but only one matches each
    action.
    """
    res = director_client.post(
        SANDBOX_URL,
        {
            "action": "enable_sandbox_mode",
            "reason": "Sandbox enable drill — wrong phrase",
            "confirmationPhrase": "DISABLE SANDBOX MODE",
        },
        format="json",
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# POST happy paths — enable + disable
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_enable_sandbox_mode_flips_state_true(
    director_client: APIClient,
) -> None:
    from apps.ai_governance.models import SandboxState
    from apps.ai_governance.sandbox import get_state

    state = get_state()
    state.is_enabled = False
    state.save()

    res = director_client.post(
        SANDBOX_URL,
        {
            "action": "enable_sandbox_mode",
            "reason": "Operator drill — enable sandbox",
            "confirmationPhrase": "ENABLE SANDBOX MODE",
        },
        format="json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["isEnabled"] is True
    assert body["sandboxEnabled"] is True
    assert body["statusLabel"] == "enabled"

    # Canonical DB state matches API response.
    assert SandboxState.objects.get(pk=1).is_enabled is True


@pytest.mark.django_db
def test_post_disable_sandbox_mode_flips_state_false_for_director(
    director_client: APIClient,
) -> None:
    from apps.ai_governance.models import SandboxState
    from apps.ai_governance.sandbox import get_state

    state = get_state()
    state.is_enabled = True
    state.save()

    res = director_client.post(
        SANDBOX_URL,
        {
            "action": "disable_sandbox_mode",
            "reason": "Operator drill — back to live AI",
            "confirmationPhrase": "DISABLE SANDBOX MODE",
        },
        format="json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["isEnabled"] is False
    assert body["sandboxEnabled"] is False
    assert body["statusLabel"] == "disabled"

    assert SandboxState.objects.get(pk=1).is_enabled is False


# ---------------------------------------------------------------------------
# AuditEvent emission
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_writes_sandbox_mode_ui_changed_audit_with_phase_14e(
    director_client: APIClient,
) -> None:
    from apps.audit.models import AuditEvent
    from apps.ai_governance.sandbox import get_state

    state = get_state()
    state.is_enabled = False
    state.save()

    res = director_client.post(
        SANDBOX_URL,
        {
            "action": "enable_sandbox_mode",
            "reason": "Phase 14E audit-emission test",
            "confirmationPhrase": "ENABLE SANDBOX MODE",
        },
        format="json",
    )
    assert res.status_code == 200

    ui_event = (
        AuditEvent.objects.filter(kind="sandbox.mode.ui_changed")
        .order_by("-pk")
        .first()
    )
    assert ui_event is not None, "Phase 14E UI audit row not written"
    payload = ui_event.payload or {}
    assert payload.get("phase") == "14E"
    assert payload.get("source") == "ui"
    assert payload.get("action") == "enable_sandbox_mode"
    assert payload.get("previous_enabled") is False
    assert payload.get("new_enabled") is True
    assert "Phase 14E" in payload.get("reason", "")
    # No secrets / tokens / raw payloads in the audit body.
    payload_str = str(payload).lower()
    for forbidden in (
        "razorpay_key_secret",
        "meta_wa_token",
        "vapi_api_key",
        "openai_api_key",
        "anthropic_api_key",
    ):
        assert forbidden not in payload_str

    # The legacy ai.sandbox.enabled audit row written by
    # set_sandbox_enabled must coexist.
    legacy_event = (
        AuditEvent.objects.filter(kind="ai.sandbox.enabled")
        .order_by("-pk")
        .first()
    )
    assert legacy_event is not None, "Legacy Phase 3D audit row missing"


# ---------------------------------------------------------------------------
# Defensive safety — Phase 14E never calls providers or mutates business rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_never_calls_outbound_providers_or_mutates_business(
    director_client: APIClient,
) -> None:
    """Phase 14E safety contract: the UI flip is a pure DB write on the
    SandboxState singleton + audit events. It must never call any
    outbound provider and must never mutate any business row.
    """
    from apps.ai_governance.sandbox import get_state

    state = get_state()
    state.is_enabled = False
    state.save()

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
        res = director_client.post(
            SANDBOX_URL,
            {
                "action": "enable_sandbox_mode",
                "reason": "Phase 14E defensive safety test",
                "confirmationPhrase": "ENABLE SANDBOX MODE",
            },
            format="json",
        )
        assert res.status_code == 200

        m_queue_template.assert_not_called()
        m_send_freeform.assert_not_called()
        m_trigger_call.assert_not_called()
        m_create_shipment.assert_not_called()

    after = _row_counts()
    assert before == after, (
        f"Phase 14E POST must not mutate any business row. "
        f"Before: {before}\nAfter: {after}"
    )


# ---------------------------------------------------------------------------
# Backward compatibility — legacy PATCH + service helper still work
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_existing_set_sandbox_enabled_service_still_flips_singleton() -> None:
    """Phase 14E does not break the Phase 3D / 4D service helper. The
    new POST and the existing PATCH both delegate to the same
    ``set_sandbox_enabled`` helper.
    """
    from apps.ai_governance.models import SandboxState
    from apps.ai_governance.sandbox import (
        get_state,
        set_sandbox_enabled,
    )

    state = get_state()
    state.is_enabled = False
    state.save()

    set_sandbox_enabled(enabled=True, note="CLI smoke from test")
    assert SandboxState.objects.get(pk=1).is_enabled is True

    set_sandbox_enabled(enabled=False, note="CLI smoke disable")
    assert SandboxState.objects.get(pk=1).is_enabled is False


@pytest.mark.django_db
def test_existing_patch_endpoint_still_works(
    director_client: APIClient,
) -> None:
    """Phase 3D PATCH path is untouched by Phase 14E — existing
    consumers (e.g. integration scripts) keep functioning.
    """
    from apps.ai_governance.sandbox import get_state

    state = get_state()
    state.is_enabled = False
    state.save()

    res = director_client.patch(
        SANDBOX_URL,
        {"isEnabled": True, "note": "Legacy PATCH still works"},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["isEnabled"] is True
    # The Phase 14E enrichment is applied to PATCH responses too.
    assert body["statusLabel"] == "enabled"
