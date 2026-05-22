"""Phase 15A — backend tests for the read-only Rollback History endpoint.

The new ``GET /api/ai/prompt-versions/rollback-history/`` endpoint
surfaces a sanitised view of Phase 14F UI rollback rows
(``prompt_version.rollback.ui_changed``) + Phase 3D service rollback
rows (``ai.prompt_version.rolled_back``) only.

Coverage:

- Auth: anonymous + viewer blocked; admin OK.
- Empty history → 200 with ``items=[]``, ``count=0``.
- Both Phase 14F + Phase 3D kinds surface and sort newest-first.
- Unrelated audit kinds (e.g. ``ai.prompt_version.activated``,
  ``ai.sandbox.enabled``) are excluded.
- Response is sanitised: no ``system_policy`` / ``role_prompt`` /
  ``instruction_payload`` / tokens / phones / raw secrets even if a
  poisoned audit payload leaks one of those keys.
- Agent filter narrows results.
- Kind filter accepts only the two allow-listed kinds; anything else
  → 400.
- Limit/offset pagination works + ``limit`` is hard-capped at 200.
- Defensive safety: the endpoint NEVER calls
  ``rollback_prompt_version`` or any outbound provider; PromptVersion
  + business-row counts unchanged.
- Phase 14F backing audit (``ai.prompt_version.rolled_back`` row
  written by the service) coexists with the Phase 14F UI row in the
  same response.
"""
from __future__ import annotations

from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient


HISTORY_URL = "/api/ai/prompt-versions/rollback-history/"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, django_user_model) -> APIClient:
    user = django_user_model.objects.create_user(
        username="phase15a_admin",
        email="phase15a_admin@example.com",
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
        username="phase15a_viewer",
        email="phase15a_viewer@example.com",
        password="ignored-by-force-auth",
    )
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def anonymous_client() -> APIClient:
    return APIClient()


def _seed_audit_events(db) -> dict:
    """Insert a representative mix of audit events covering the two
    allow-listed kinds + several unrelated kinds. Returns a dict of
    handy references for assertion."""
    from apps.audit.models import AuditEvent

    # 1. Phase 14F UI rollback row for CEO agent (newest expected).
    ui_row = AuditEvent.objects.create(
        kind="prompt_version.rollback.ui_changed",
        text="Prompt rollback via Settings UI by phase15a_admin · agent=ceo → v1.0",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "phase": "14F",
            "source": "settings_ui",
            "action": "prompt_version.rollback",
            "actor": "phase15a_admin",
            "agent": "ceo",
            "previous_active_version_id": "PV-80002",
            "target_version_id": "PV-80001",
            "target_version_label": "v1.0",
            "matrix_action": "ai.prompt_version.activate",
            "matrix_status": "auto_approved",
            "reason": "Phase 15A history fixture — UI rollback",
        },
    )

    # 2. Phase 3D service-backed row that the Phase 14F view also
    # emits via the underlying rollback_prompt_version call. In
    # production both rows coexist for the same physical rollback;
    # the test fixture inserts them separately to assert both
    # surfaces in the response.
    service_row = AuditEvent.objects.create(
        kind="ai.prompt_version.rolled_back",
        text="Agent ceo rolled back to v1.0 (prev v2.0)",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "agent": "ceo",
            "target_version_id": "PV-80001",
            "target_version": "v1.0",
            "previous_version_id": "PV-80002",
            "previous_version": "v2.0",
            "reason": "Phase 15A history fixture — service row",
            "by": "phase15a_admin",
        },
    )

    # 3. Service-only rollback for a different agent (CFO) — useful
    # for the agent-filter test.
    cfo_row = AuditEvent.objects.create(
        kind="ai.prompt_version.rolled_back",
        text="Agent cfo rolled back to v1.0",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "agent": "cfo",
            "target_version_id": "PV-80003",
            "target_version": "v1.0",
            "previous_version_id": "PV-80004",
            "previous_version": "v2.0",
            "reason": "CFO test rollback",
            "by": "phase15a_admin",
        },
    )

    # 4-6. Noise rows — unrelated audit kinds that MUST be excluded.
    AuditEvent.objects.create(
        kind="ai.prompt_version.activated",
        text="PromptVersion PV-80002 activated · ceo:v2.0",
        tone=AuditEvent.Tone.SUCCESS,
        payload={"agent": "ceo", "version": "v2.0"},
    )
    AuditEvent.objects.create(
        kind="ai.sandbox.enabled",
        text="AI sandbox enabled by admin",
        tone=AuditEvent.Tone.WARNING,
        payload={"enabled": True, "note": "Phase 15A noise row"},
    )
    AuditEvent.objects.create(
        kind="runtime.kill_switch.ui_changed",
        text="AI Kill Switch activated via UI by admin",
        tone=AuditEvent.Tone.WARNING,
        payload={"phase": "14D", "source": "ui", "agent": "ceo"},
    )

    return {
        "ui_row": ui_row,
        "service_row": service_row,
        "cfo_row": cfo_row,
    }


def _row_counts() -> dict:
    """Snapshot every model the rollback-history GET must never mutate."""
    from apps.ai_governance.models import PromptVersion
    from apps.orders.models import Order, DiscountOfferLog
    from apps.payments.models import Payment
    from apps.crm.models import Customer, Lead
    from apps.shipments.models import Shipment
    from apps.whatsapp.models import WhatsAppMessage
    from apps.calls.models import Call

    return {
        "PromptVersion": PromptVersion.objects.count(),
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
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_history_blocks_anonymous(anonymous_client: APIClient) -> None:
    res = anonymous_client.get(HISTORY_URL)
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_history_blocks_viewer(viewer_client: APIClient) -> None:
    res = viewer_client.get(HISTORY_URL)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Empty + happy path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_history_empty_returns_200_with_empty_items(
    admin_client: APIClient,
) -> None:
    res = admin_client.get(HISTORY_URL)
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["count"] == 0
    # The kindsIncluded contract documents what the endpoint will ever
    # return so the frontend never silently misses a new audit kind.
    assert "prompt_version.rollback.ui_changed" in body["kindsIncluded"]
    assert "ai.prompt_version.rolled_back" in body["kindsIncluded"]


@pytest.mark.django_db
def test_history_surfaces_both_phase14f_and_phase3d_rows(
    db, admin_client: APIClient
) -> None:
    refs = _seed_audit_events(db)
    res = admin_client.get(HISTORY_URL)
    assert res.status_code == 200
    body = res.json()
    # Exactly the 3 rollback rows; the 3 noise rows are excluded.
    assert body["count"] == 3
    assert len(body["items"]) == 3
    kinds = {row["kind"] for row in body["items"]}
    assert kinds == {
        "prompt_version.rollback.ui_changed",
        "ai.prompt_version.rolled_back",
    }
    # Newest-first ordering — the CFO row was inserted last so it
    # should appear first.
    assert body["items"][0]["id"] == refs["cfo_row"].id


@pytest.mark.django_db
def test_history_excludes_unrelated_audit_kinds(
    db, admin_client: APIClient
) -> None:
    _seed_audit_events(db)
    res = admin_client.get(HISTORY_URL)
    body = res.json()
    # Specifically verify none of the noise kinds leaked in.
    for row in body["items"]:
        assert row["kind"] not in {
            "ai.prompt_version.activated",
            "ai.sandbox.enabled",
            "runtime.kill_switch.ui_changed",
        }


# ---------------------------------------------------------------------------
# Sanitised response — no prompt body / secrets
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_history_does_not_leak_prompt_body_or_secrets(
    db, admin_client: APIClient
) -> None:
    """Even if a future audit-writer accidentally stuffs a sensitive
    field into payload, the Phase 15A allow-list slice must drop it."""
    from apps.audit.models import AuditEvent

    AuditEvent.objects.create(
        kind="prompt_version.rollback.ui_changed",
        text="Poisoned audit row for sanitisation test",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "phase": "14F",
            "source": "settings_ui",
            "agent": "ceo",
            "target_version_id": "PV-80001",
            "target_version_label": "v1.0",
            "previous_active_version_id": "PV-80002",
            "reason": "Sanitisation test",
            # All of the following MUST be filtered out by the view.
            "system_policy": "POISONED-SYSTEM-POLICY-BODY-NEVER-RENDER",
            "role_prompt": "POISONED-ROLE-PROMPT-BODY-NEVER-RENDER",
            "instruction_payload": {"sensitive": "blob"},
            "razorpay_key_secret": "rzp_secret_NEVER",
            "meta_wa_token": "EAAB_NEVER",
            "vapi_api_key": "vapi_NEVER",
            "openai_api_key": "sk-NEVER",
            "phone": "+91XXXXXXXXXX",
            "email": "victim@example.com",
        },
    )

    res = admin_client.get(HISTORY_URL)
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    row = body["items"][0]
    # Allow-listed fields surface.
    assert row["agent"] == "ceo"
    assert row["reason"] == "Sanitisation test"
    # Forbidden fields MUST be absent from the serialised row.
    raw = str(row).lower()
    for forbidden in (
        "poisoned-system-policy-body",
        "poisoned-role-prompt-body",
        "rzp_secret",
        "eaab_never",
        "vapi_never",
        "sk-never",
        "+91xxxxxxxxxx",
        "victim@example.com",
        "system_policy",
        "role_prompt",
        "instruction_payload",
    ):
        assert forbidden not in raw, (
            f"Phase 15A response leaked forbidden token {forbidden!r}: "
            f"{row}"
        )


# ---------------------------------------------------------------------------
# Filters + pagination
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_history_agent_filter_narrows_results(
    db, admin_client: APIClient
) -> None:
    _seed_audit_events(db)
    res = admin_client.get(HISTORY_URL, {"agent": "cfo"})
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["items"][0]["agent"] == "cfo"


@pytest.mark.django_db
def test_history_kind_filter_accepts_only_allow_listed_kinds(
    db, admin_client: APIClient
) -> None:
    _seed_audit_events(db)

    # Allow-listed kind passes.
    res = admin_client.get(
        HISTORY_URL, {"kind": "prompt_version.rollback.ui_changed"}
    )
    assert res.status_code == 200
    body = res.json()
    assert all(
        row["kind"] == "prompt_version.rollback.ui_changed"
        for row in body["items"]
    )

    # Unknown kind refused with 400.
    res_bad = admin_client.get(
        HISTORY_URL, {"kind": "ai.sandbox.enabled"}
    )
    assert res_bad.status_code == 400


@pytest.mark.django_db
def test_history_limit_offset_pagination(
    db, admin_client: APIClient
) -> None:
    _seed_audit_events(db)
    res_p1 = admin_client.get(HISTORY_URL, {"limit": 2, "offset": 0})
    assert res_p1.status_code == 200
    assert len(res_p1.json()["items"]) == 2
    assert res_p1.json()["count"] == 3

    res_p2 = admin_client.get(HISTORY_URL, {"limit": 2, "offset": 2})
    assert len(res_p2.json()["items"]) == 1
    assert res_p2.json()["count"] == 3


@pytest.mark.django_db
def test_history_limit_is_hard_capped(
    admin_client: APIClient,
) -> None:
    """Malformed limit must not drain the audit table."""
    res = admin_client.get(HISTORY_URL, {"limit": 9999})
    assert res.status_code == 200
    assert res.json()["limit"] == 200  # _MAX_LIMIT


# ---------------------------------------------------------------------------
# Defensive safety — read-only contract
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_history_get_never_mutates_anything(
    db, admin_client: APIClient
) -> None:
    """Phase 15A is read-only. The GET must NOT call
    rollback_prompt_version, must NOT call any outbound provider, and
    must NOT mutate PromptVersion / business tables."""
    _seed_audit_events(db)
    before = _row_counts()

    with mock.patch(
        "apps.ai_governance.prompt_versions.rollback_prompt_version"
    ) as m_rollback, mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as m_queue_template, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as m_send_freeform, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as m_trigger_call, mock.patch(
        "apps.shipments.services.create_shipment"
    ) as m_create_shipment:
        res = admin_client.get(HISTORY_URL)
        assert res.status_code == 200

        m_rollback.assert_not_called()
        m_queue_template.assert_not_called()
        m_send_freeform.assert_not_called()
        m_trigger_call.assert_not_called()
        m_create_shipment.assert_not_called()

    after = _row_counts()
    assert before == after, (
        f"Phase 15A GET must not mutate any row. "
        f"Before: {before}\nAfter: {after}"
    )


@pytest.mark.django_db
def test_history_does_not_support_post_put_patch_delete(
    admin_client: APIClient,
) -> None:
    """Defence in depth — POST/PUT/PATCH/DELETE all return 405."""
    res_post = admin_client.post(HISTORY_URL, {}, format="json")
    assert res_post.status_code == 405
    res_put = admin_client.put(HISTORY_URL, {}, format="json")
    assert res_put.status_code == 405
    res_patch = admin_client.patch(HISTORY_URL, {}, format="json")
    assert res_patch.status_code == 405
    res_delete = admin_client.delete(HISTORY_URL)
    assert res_delete.status_code == 405
