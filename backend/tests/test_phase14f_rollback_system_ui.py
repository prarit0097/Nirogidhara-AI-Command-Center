"""Phase 14F — backend tests for the Rollback System UI endpoint.

The existing Phase 3D ``POST /api/ai/prompt-versions/<pk>/rollback/``
endpoint stays untouched. Phase 14F adds a sister endpoint
``POST /api/ai/prompt-versions/rollback-from-ui/`` that takes the
Phase 14D / 14E typed-phrase + reason payload, records a Phase 4C
``mark_auto_approved`` row for the matrix audit trail, and writes a
new ``prompt_version.rollback.ui_changed`` audit kind alongside the
legacy ``ai.prompt_version.rolled_back`` row.

Tests cover:

- GET prompt-versions list (Phase 3D path) — auth-gated, returns
  safe metadata.
- POST rollback-from-ui auth (anonymous + viewer blocked, admin OK).
- POST payload validation (missing targetVersionId, short reason,
  wrong phrase, phrase swap with the kill-switch phrase).
- POST target version not found → 404.
- POST target version belongs to a different agent than submitted →
  400.
- POST target version is already active → 400 no-op.
- POST happy path: flips active version + records audit.
- AuditEvent contract — ``prompt_version.rollback.ui_changed`` carries
  phase=14F, source=settings_ui, agent, previous + target version
  ids, reason; coexists with the legacy
  ``ai.prompt_version.rolled_back`` row that the service writes.
- ApprovalRequest row created with status=auto_approved on
  ``ai.prompt_version.activate`` matrix action (Phase 4C audit trail).
- Defensive safety — POST does NOT call WhatsApp / Vapi / Razorpay /
  Delhivery outbound functions; does NOT mutate any business row.
- Existing Phase 3D POST /api/ai/prompt-versions/<pk>/rollback/ stays
  functional.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient


LIST_URL = "/api/ai/prompt-versions/"
ROLLBACK_FROM_UI_URL = "/api/ai/prompt-versions/rollback-from-ui/"
LEGACY_ROLLBACK_URL = "/api/ai/prompt-versions/{pk}/rollback/"
ACTIVATE_URL = "/api/ai/prompt-versions/{pk}/activate/"
CREATE_URL = "/api/ai/prompt-versions/"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, django_user_model) -> APIClient:
    user = django_user_model.objects.create_user(
        username="phase14f_admin",
        email="phase14f_admin@example.com",
        password="ignored-by-force-auth",
    )
    user.is_staff = True
    user.is_superuser = True
    user.role = "admin"
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def viewer_client(db, django_user_model) -> APIClient:
    user = django_user_model.objects.create_user(
        username="phase14f_viewer",
        email="phase14f_viewer@example.com",
        password="ignored-by-force-auth",
    )
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def anonymous_client() -> APIClient:
    return APIClient()


def _create_and_activate_pair(admin_client: APIClient) -> tuple[str, str]:
    """Create two CEO PromptVersions (v1, v2) and activate v2 so that
    v1 is the rollback target."""
    res_v1 = admin_client.post(
        CREATE_URL,
        {
            "agent": "ceo",
            "version": "v1.0",
            "title": "v1 baseline",
            "systemPolicy": "You are CEO AI.",
            "rolePrompt": "Act as the CEO orchestrator.",
        },
        format="json",
    )
    assert res_v1.status_code == 201, res_v1.content
    v1_id = res_v1.json()["id"]

    res_v2 = admin_client.post(
        CREATE_URL,
        {
            "agent": "ceo",
            "version": "v2.0",
            "title": "v2 incident regression",
            "systemPolicy": "You are CEO AI v2.",
            "rolePrompt": "Act as the CEO orchestrator v2.",
        },
        format="json",
    )
    assert res_v2.status_code == 201, res_v2.content
    v2_id = res_v2.json()["id"]

    # Activate v1 first, then v2 so v1's status becomes archived (the
    # legitimate rollback target) and v2 is the current active.
    admin_client.post(ACTIVATE_URL.format(pk=v1_id), {}, format="json")
    admin_client.post(ACTIVATE_URL.format(pk=v2_id), {}, format="json")

    return v1_id, v2_id


def _row_counts() -> dict:
    """Snapshot every business table the rollback must never mutate."""
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
# GET list (Phase 3D path — still functional)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_prompt_versions_blocks_anonymous(
    anonymous_client: APIClient,
) -> None:
    res = anonymous_client.get(LIST_URL)
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_get_prompt_versions_blocks_viewer(viewer_client: APIClient) -> None:
    res = viewer_client.get(LIST_URL)
    assert res.status_code == 403


@pytest.mark.django_db
def test_get_prompt_versions_admin_returns_safe_metadata(
    admin_client: APIClient,
) -> None:
    _create_and_activate_pair(admin_client)
    res = admin_client.get(LIST_URL)
    assert res.status_code == 200
    rows = res.json()
    assert isinstance(rows, list)
    assert len(rows) >= 2
    for row in rows:
        # Safe identifier fields surface for the UI to render.
        for key in (
            "id",
            "agent",
            "version",
            "title",
            "isActive",
            "status",
            "createdAt",
        ):
            assert key in row, f"row missing key {key!r}: {row}"
        # The endpoint does also expose systemPolicy / rolePrompt for
        # the existing Governance page; the Phase 14F Settings UI
        # deliberately does NOT render those bodies. This test
        # documents that the field exists but is not required for
        # the Phase 14F flow.


# ---------------------------------------------------------------------------
# POST rollback-from-ui validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_rollback_blocks_anonymous(anonymous_client: APIClient) -> None:
    res = anonymous_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": "PV-NOPE",
            "reason": "phase 14f drill",
            "confirmationPhrase": "ROLLBACK PROMPT VERSION",
        },
        format="json",
    )
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_post_rollback_blocks_viewer(viewer_client: APIClient) -> None:
    res = viewer_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": "PV-NOPE",
            "reason": "phase 14f drill — viewer must be refused",
            "confirmationPhrase": "ROLLBACK PROMPT VERSION",
        },
        format="json",
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_post_rollback_refuses_missing_target_version(
    admin_client: APIClient,
) -> None:
    res = admin_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": "",
            "reason": "phase 14f payload error test",
            "confirmationPhrase": "ROLLBACK PROMPT VERSION",
        },
        format="json",
    )
    assert res.status_code == 400
    assert "targetversionid" in res.json()["detail"].lower()


@pytest.mark.django_db
def test_post_rollback_refuses_short_reason(admin_client: APIClient) -> None:
    v1_id, _ = _create_and_activate_pair(admin_client)
    res = admin_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": v1_id,
            "reason": "too short",
            "confirmationPhrase": "ROLLBACK PROMPT VERSION",
        },
        format="json",
    )
    assert res.status_code == 400
    assert "reason" in res.json()["detail"].lower()


@pytest.mark.django_db
def test_post_rollback_refuses_wrong_phrase(admin_client: APIClient) -> None:
    v1_id, _ = _create_and_activate_pair(admin_client)
    res = admin_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": v1_id,
            "reason": "Phase 14F wrong-phrase test",
            "confirmationPhrase": "ROLLBACK PROMTP VERSION",  # typo
        },
        format="json",
    )
    assert res.status_code == 400
    assert "confirmation" in res.json()["detail"].lower()


@pytest.mark.django_db
def test_post_rollback_refuses_phrase_swap_with_kill_switch(
    admin_client: APIClient,
) -> None:
    """The rollback action must reject any other safety phrase even if
    that phrase is valid for a different action."""
    v1_id, _ = _create_and_activate_pair(admin_client)
    res = admin_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": v1_id,
            "reason": "Phase 14F phrase-swap test",
            "confirmationPhrase": "ACTIVATE KILL SWITCH",
        },
        format="json",
    )
    assert res.status_code == 400


@pytest.mark.django_db
def test_post_rollback_refuses_unknown_version(
    admin_client: APIClient,
) -> None:
    res = admin_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": "PV-DOES-NOT-EXIST",
            "reason": "Phase 14F missing-version test",
            "confirmationPhrase": "ROLLBACK PROMPT VERSION",
        },
        format="json",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_post_rollback_refuses_agent_mismatch(
    admin_client: APIClient,
) -> None:
    v1_id, _ = _create_and_activate_pair(admin_client)
    res = admin_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "cfo",  # v1 belongs to ceo
            "targetVersionId": v1_id,
            "reason": "Phase 14F cross-agent rollback attempt",
            "confirmationPhrase": "ROLLBACK PROMPT VERSION",
        },
        format="json",
    )
    assert res.status_code == 400
    assert "agent" in res.json()["detail"].lower()


@pytest.mark.django_db
def test_post_rollback_refuses_currently_active_version(
    admin_client: APIClient,
) -> None:
    _, v2_id = _create_and_activate_pair(admin_client)  # v2 is active
    res = admin_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": v2_id,
            "reason": "Phase 14F no-op refusal test",
            "confirmationPhrase": "ROLLBACK PROMPT VERSION",
        },
        format="json",
    )
    assert res.status_code == 400
    assert (
        "active" in res.json()["detail"].lower()
        or "no-op" in res.json()["detail"].lower()
    )


# ---------------------------------------------------------------------------
# POST happy path — rollback flips active version + writes audits
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_rollback_happy_path_flips_active_version_and_writes_audits(
    admin_client: APIClient,
) -> None:
    from apps.ai_governance.models import PromptVersion

    v1_id, v2_id = _create_and_activate_pair(admin_client)
    # Pre-state: v2 is active, v1 is archived.
    assert PromptVersion.objects.get(pk=v2_id).is_active is True
    assert PromptVersion.objects.get(pk=v1_id).is_active is False

    res = admin_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": v1_id,
            "reason": "Phase 14F happy-path rollback — v2 regressed accuracy",
            "confirmationPhrase": "ROLLBACK PROMPT VERSION",
        },
        format="json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["ok"] is True
    assert body["status"] == "rolled_back"
    assert body["agent"] == "ceo"
    assert body["previousActiveVersionId"] == v2_id
    assert body["targetVersionId"] == v1_id
    assert body["auditKind"] == "prompt_version.rollback.ui_changed"

    # Post-state: v1 is active, v2 is rolled_back.
    v1_after = PromptVersion.objects.get(pk=v1_id)
    v2_after = PromptVersion.objects.get(pk=v2_id)
    assert v1_after.is_active is True
    assert v1_after.status == "active"
    assert v2_after.is_active is False
    assert v2_after.status == "rolled_back"
    assert "Phase 14F happy-path" in v2_after.rollback_reason


@pytest.mark.django_db
def test_post_rollback_writes_phase14f_ui_audit_with_phase_field(
    admin_client: APIClient,
) -> None:
    from apps.audit.models import AuditEvent

    v1_id, v2_id = _create_and_activate_pair(admin_client)
    res = admin_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": v1_id,
            "reason": "Phase 14F audit-row contract test",
            "confirmationPhrase": "ROLLBACK PROMPT VERSION",
        },
        format="json",
    )
    assert res.status_code == 200

    ui_event = (
        AuditEvent.objects.filter(kind="prompt_version.rollback.ui_changed")
        .order_by("-pk")
        .first()
    )
    assert ui_event is not None, "Phase 14F UI audit row not written"
    payload = ui_event.payload or {}
    assert payload.get("phase") == "14F"
    assert payload.get("source") == "settings_ui"
    assert payload.get("agent") == "ceo"
    assert payload.get("previous_active_version_id") == v2_id
    assert payload.get("target_version_id") == v1_id
    assert payload.get("matrix_action") == "ai.prompt_version.activate"
    assert payload.get("matrix_status") == "auto_approved"
    assert "Phase 14F" in payload.get("reason", "")
    # No secrets leaked.
    payload_str = str(payload).lower()
    for forbidden in (
        "razorpay_key_secret",
        "meta_wa_token",
        "vapi_api_key",
        "openai_api_key",
        "anthropic_api_key",
    ):
        assert forbidden not in payload_str

    # Legacy audit row from the Phase 3D service must also exist.
    legacy_event = (
        AuditEvent.objects.filter(kind="ai.prompt_version.rolled_back")
        .order_by("-pk")
        .first()
    )
    assert legacy_event is not None, "Legacy Phase 3D audit row missing"


@pytest.mark.django_db
def test_post_rollback_records_approval_matrix_auto_approved_row(
    admin_client: APIClient,
) -> None:
    """Phase 4C — the matrix policy for ai.prompt_version.activate
    covers rollback (description: 'Activate or rollback an AI prompt
    version'). The Phase 14F endpoint records mark_auto_approved so
    the operator queue / audit trail reflects the rollback action.
    """
    from apps.ai_governance.models import ApprovalRequest

    v1_id, _ = _create_and_activate_pair(admin_client)
    before_count = ApprovalRequest.objects.filter(
        action="ai.prompt_version.activate"
    ).count()

    res = admin_client.post(
        ROLLBACK_FROM_UI_URL,
        {
            "agent": "ceo",
            "targetVersionId": v1_id,
            "reason": "Phase 14F approval-matrix audit-trail test",
            "confirmationPhrase": "ROLLBACK PROMPT VERSION",
        },
        format="json",
    )
    assert res.status_code == 200

    after_count = ApprovalRequest.objects.filter(
        action="ai.prompt_version.activate"
    ).count()
    assert after_count == before_count + 1

    fresh = (
        ApprovalRequest.objects.filter(action="ai.prompt_version.activate")
        .order_by("-pk")
        .first()
    )
    assert fresh is not None
    assert fresh.status == "auto_approved"


# ---------------------------------------------------------------------------
# Defensive safety — no providers + no business mutations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_rollback_never_calls_outbound_providers_or_mutates_business(
    admin_client: APIClient,
) -> None:
    """Phase 14F safety contract: rollback is a pure DB write on
    PromptVersion rows + audit events. It must never call any
    outbound provider and must never mutate any business row.
    """
    v1_id, _ = _create_and_activate_pair(admin_client)
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
            ROLLBACK_FROM_UI_URL,
            {
                "agent": "ceo",
                "targetVersionId": v1_id,
                "reason": "Phase 14F defensive safety test",
                "confirmationPhrase": "ROLLBACK PROMPT VERSION",
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
        f"Phase 14F rollback must not mutate any business row. "
        f"Before: {before}\nAfter: {after}"
    )


# ---------------------------------------------------------------------------
# Backward compatibility — legacy Phase 3D rollback endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_legacy_phase3d_rollback_endpoint_still_works(
    admin_client: APIClient,
) -> None:
    """Phase 14F does not break the Phase 3D
    ``POST /api/ai/prompt-versions/<pk>/rollback/`` endpoint. The
    existing Governance page + test_phase3d.py continue to work
    unchanged.
    """
    from apps.ai_governance.models import PromptVersion

    v1_id, v2_id = _create_and_activate_pair(admin_client)
    res = admin_client.post(
        LEGACY_ROLLBACK_URL.format(pk=v1_id),
        {"reason": "Phase 3D legacy path still works"},
        format="json",
    )
    assert res.status_code == 200
    assert PromptVersion.objects.get(pk=v1_id).is_active is True
    assert PromptVersion.objects.get(pk=v2_id).is_active is False
