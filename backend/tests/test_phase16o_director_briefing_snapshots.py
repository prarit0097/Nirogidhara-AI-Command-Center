"""Phase 16O — Director Briefing Snapshot History + Acknowledgement Trail tests.

Coverage (directive 1-21):
  1. Snapshot list requires auth.
  2. Snapshot detail requires auth.
  3. Snapshot creation requires Director/Admin.
  4. Viewer / non-admin cannot create.
  5. Creation calls the internal Phase 16N briefing service only + stores sanitized payload.
  6. Snapshot stores the locked safety flags.
  7. Summary endpoint works.
  8. Acknowledge requires Director/Admin.
  9. Acknowledge sets status=acknowledged + acknowledged_by + acknowledged_at.
  10. Mark needs-follow-up works.
  11. Archive works.
  12. Add internal note works.
  13. Event trail created for created/acknowledged/follow-up/archive/note.
  14. Safe-text endpoint returns sanitized internal-only text.
  15. No live provider calls (5 entrypoints patched).
  16. RuntimeKillSwitch / SandboxState untouched.
  17. Lead/Customer/Order/Payment counts unchanged.
  18. No AiApprovedAction mutation.
  19. (No Celery enqueue — read/snapshot path triggers no business task.)
  20. Unsupported methods rejected (405).
  21. Phase 16N/16M/16L targeted suites still pass (run separately).

Everything is internal-only / DB-only. No live provider / customer-facing action.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai_copilot.models import (
    AiApprovedAction,
    AiDirectorBriefingSnapshot,
    AiDirectorBriefingSnapshotEvent,
)

SNAP = "/api/v1/ai-copilot/director-briefing/snapshots/"
SUMMARY = SNAP + "summary/"


@pytest.fixture
def director_user(db):
    u = User.objects.create_user(username="d16o", password="d16o12345", email="d16o@n.test")
    u.role = User.Role.DIRECTOR
    u.save(update_fields=["role"])
    return u


def _create(client, *, window_days=7, title=""):
    body = {"windowDays": window_days}
    if title:
        body["title"] = title
    return client.post(SNAP, body, format="json")


def _act(client, snapshot_id, verb, body=None):
    return client.post(f"{SNAP}{snapshot_id}/{verb}/", body or {}, format="json")


# --------------------------------------------------------------------------
# 1-2 auth
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_requires_auth() -> None:
    assert APIClient().get(SNAP).status_code in {401, 403}


@pytest.mark.django_db
def test_detail_requires_auth(director_user, auth_client) -> None:
    sid = _create(auth_client(director_user)).json()["id"]
    assert APIClient().get(f"{SNAP}{sid}/").status_code in {401, 403}


@pytest.mark.django_db
def test_summary_requires_auth() -> None:
    assert APIClient().get(SUMMARY).status_code in {401, 403}


@pytest.mark.django_db
def test_viewer_can_read_list(viewer_user, auth_client) -> None:
    assert auth_client(viewer_user).get(SNAP).status_code == 200


# --------------------------------------------------------------------------
# 3-4 create requires Director/Admin
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_requires_admin(director_user, auth_client) -> None:
    assert _create(auth_client(director_user)).status_code == 201


@pytest.mark.django_db
def test_viewer_cannot_create(viewer_user, auth_client) -> None:
    assert _create(auth_client(viewer_user)).status_code == 403


@pytest.mark.django_db
def test_operations_cannot_create(operations_user, auth_client) -> None:
    assert _create(auth_client(operations_user)).status_code == 403


# --------------------------------------------------------------------------
# 5-6 sanitized payload + locked flags
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_stores_sanitized_payload_and_flags(director_user, auth_client) -> None:
    body = _create(auth_client(director_user), window_days=7).json()
    assert body["status"] == "unreviewed"
    assert body["readonly"] is True
    assert body["internalOnly"] is True
    assert body["providerCallMade"] is False
    assert body["externalActionTaken"] is False
    assert body["liveAutonomousLocked"] is True
    # The persisted payload is the Phase 16N briefing (reused service).
    assert "executiveSummary" in body
    assert "blockedLiveActions" in body
    assert body["briefingPayload"]["phase"] == "16N"
    assert body["safetySnapshot"]["phase15ShellFrozenCommit"] == "eefd8b3"
    # Model row confirms locked flags.
    row = AiDirectorBriefingSnapshot.objects.get(pk=body["id"])
    assert row.provider_call_made is False
    assert row.external_action_taken is False
    assert row.internal_only is True
    assert row.readonly is True
    assert row.live_autonomous_locked is True


@pytest.mark.django_db
def test_summary_endpoint(director_user, auth_client) -> None:
    dc = auth_client(director_user)
    _create(dc)
    _create(dc)
    body = auth_client(director_user).get(SUMMARY).json()
    assert body["total"] == 2
    assert body["unreviewed"] == 2
    assert body["phase"] == "16O"
    assert body["providerCallMade"] is False
    assert body["liveAutonomousLocked"] is True


# --------------------------------------------------------------------------
# 8-9 acknowledge
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_acknowledge_requires_admin(director_user, operations_user, auth_client) -> None:
    sid = _create(auth_client(director_user)).json()["id"]
    assert _act(auth_client(operations_user), sid, "acknowledge", {"note": "x"}).status_code == 403


@pytest.mark.django_db
def test_acknowledge_sets_state(director_user, auth_client) -> None:
    dc = auth_client(director_user)
    sid = _create(dc).json()["id"]
    res = _act(dc, sid, "acknowledge", {"note": "reviewed, looks fine"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "acknowledged"
    assert body["acknowledgedBy"] == director_user.username
    assert body["acknowledgedAt"] is not None
    assert "reviewed, looks fine" in body["directorNote"]
    assert body["providerCallMade"] is False
    assert body["externalActionTaken"] is False


# --------------------------------------------------------------------------
# 10-12 needs-follow-up / archive / note
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_mark_needs_follow_up(director_user, auth_client) -> None:
    dc = auth_client(director_user)
    sid = _create(dc).json()["id"]
    res = _act(dc, sid, "needs-follow-up", {"note": "check finance overdue"})
    assert res.status_code == 200
    assert res.json()["status"] == "needs_follow_up"


@pytest.mark.django_db
def test_archive(director_user, auth_client) -> None:
    dc = auth_client(director_user)
    sid = _create(dc).json()["id"]
    res = _act(dc, sid, "archive", {"note": "old"})
    assert res.status_code == 200
    assert res.json()["status"] == "archived"
    # archived snapshot cannot be acknowledged
    assert _act(dc, sid, "acknowledge").status_code == 409


@pytest.mark.django_db
def test_add_note(director_user, auth_client) -> None:
    dc = auth_client(director_user)
    sid = _create(dc).json()["id"]
    res = _act(dc, sid, "notes", {"note": "internal observation"})
    assert res.status_code == 200
    assert "internal observation" in res.json()["directorNote"]
    # blank note refused
    assert _act(dc, sid, "notes", {"note": "   "}).status_code == 409


# --------------------------------------------------------------------------
# 13 event trail
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_trail(director_user, auth_client) -> None:
    dc = auth_client(director_user)
    sid = _create(dc).json()["id"]
    _act(dc, sid, "acknowledge", {"note": "ack"})
    _act(dc, sid, "notes", {"note": "n1"})
    _act(dc, sid, "needs-follow-up", {"note": "fu"})
    _act(dc, sid, "archive", {"note": "done"})
    detail = dc.get(f"{SNAP}{sid}/").json()
    kinds = {e["eventType"] for e in detail["events"]}
    assert {"created", "acknowledged", "note_added", "marked_needs_follow_up", "archived"} <= kinds
    assert AiDirectorBriefingSnapshotEvent.objects.filter(snapshot_id=sid).count() >= 5


# --------------------------------------------------------------------------
# 14 safe-text
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_safe_text(director_user, auth_client) -> None:
    dc = auth_client(director_user)
    sid = _create(dc).json()["id"]
    res = dc.get(f"{SNAP}{sid}/safe-text/")
    assert res.status_code == 200
    body = res.json()
    txt = body["safeText"]
    assert "DIRECTOR AI BRIEFING SNAPSHOT (internal-only)" in txt
    assert "phase15ShellFrozenCommit=eefd8b3" in txt
    assert "never sent to any customer or external service" in txt
    assert body["providerCallMade"] is False
    assert body["internalOnly"] is True


# --------------------------------------------------------------------------
# 15-19 defensive: no provider call, no business mutation, safety state intact
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_provider_or_business_side_effect(director_user, viewer_user, auth_client) -> None:
    from apps.ai_governance.sandbox import is_sandbox_enabled
    from apps.crm.models import Customer, Lead
    from apps.orders.models import Order
    from apps.payments.models import Payment
    from apps.saas.models import RuntimeKillSwitch

    sandbox_before = is_sandbox_enabled()
    ks_before = RuntimeKillSwitch.objects.count()
    counts_before = (
        Lead.objects.count(), Customer.objects.count(),
        Order.objects.count(), Payment.objects.count(),
    )
    actions_before = AiApprovedAction.objects.count()

    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as wa_t, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as wa_f, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as vapi, mock.patch(
        "apps.payments.integrations.razorpay_client.create_payment_link"
    ) as rz, mock.patch(
        "apps.shipments.integrations.delhivery_client.create_awb"
    ) as dl:
        dc = auth_client(director_user)
        sid = _create(dc).json()["id"]
        _act(dc, sid, "acknowledge", {"note": "ack"})
        _act(dc, sid, "notes", {"note": "n"})
        _act(dc, sid, "needs-follow-up")
        sid2 = _create(dc).json()["id"]
        _act(dc, sid2, "archive")
        dc.get(SNAP)
        dc.get(SUMMARY)
        dc.get(f"{SNAP}{sid}/")
        dc.get(f"{SNAP}{sid}/safe-text/")
        auth_client(viewer_user).get(SNAP)

    wa_t.assert_not_called()
    wa_f.assert_not_called()
    vapi.assert_not_called()
    rz.assert_not_called()
    dl.assert_not_called()
    assert is_sandbox_enabled() == sandbox_before
    assert RuntimeKillSwitch.objects.count() == ks_before
    assert (
        Lead.objects.count(), Customer.objects.count(),
        Order.objects.count(), Payment.objects.count(),
    ) == counts_before
    # snapshot creation never creates/mutates an AiApprovedAction
    assert AiApprovedAction.objects.count() == actions_before


# --------------------------------------------------------------------------
# 20 unsupported methods rejected
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_unsupported_methods_rejected(director_user, auth_client) -> None:
    dc = auth_client(director_user)
    sid = _create(dc).json()["id"]
    # list/create view: PATCH/DELETE unsupported
    assert dc.patch(SNAP, {}, format="json").status_code == 405
    assert dc.delete(SNAP).status_code == 405
    # detail view: POST/DELETE unsupported
    assert dc.delete(f"{SNAP}{sid}/").status_code == 405
    # transition views are POST-only: GET unsupported
    assert dc.get(f"{SNAP}{sid}/acknowledge/").status_code == 405
    # summary GET-only
    assert dc.post(SUMMARY, {}, format="json").status_code == 405


# --------------------------------------------------------------------------
# Regression smoke — Phase 16N briefing endpoint still works
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase16n_briefing_still_works(director_user, auth_client) -> None:
    res = auth_client(director_user).get("/api/v1/ai-copilot/director-briefing/")
    assert res.status_code == 200
    assert res.json()["phase"] == "16N"
