"""Phase 15B — backend tests for the read-only Director Briefing
Sidebar badge endpoint.

The new ``GET /api/v1/ceo-orchestration/snapshots/sidebar-status/``
endpoint surfaces a slim allow-listed shape so the Sidebar badge can
render without pulling the entire Phase 9F snapshot (which includes
the full internal ``briefingText`` body that's too rich for a
sidebar fetch).

Coverage:

- Auth: anonymous + viewer blocked; admin OK.
- Missing snapshot → 200 with ``status="missing"``.
- Fresh CRITICAL tier → 200 with ``status="critical"`` (overrides
  the freshness check).
- Fresh GOOD/FAIR tier → 200 with ``status="ready"``.
- Snapshot older than the 36h stale threshold → 200 with
  ``status="stale"``.
- Response shape is sanitised: NEVER includes ``briefingText``,
  ``crossCuttingAlerts``, ``top3Priorities``, ``agentStatusSummary``,
  or any other field that could expose hidden reasoning / sensitive
  body.
- ``targetRoute`` is always ``"/ceo-ai"`` so the frontend doesn't
  have to derive it.
- POST/PUT/PATCH/DELETE return 405.
- Defensive safety contract: GET NEVER calls
  ``run_ceo_orchestration_agent_daily``, NEVER calls any outbound
  provider, NEVER mutates any business row, NEVER creates a new
  ``CeoOrchestrationSnapshot`` row.
"""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient


SIDEBAR_URL = "/api/v1/ceo-orchestration/snapshots/sidebar-status/"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, django_user_model) -> APIClient:
    user = django_user_model.objects.create_user(
        username="phase15b_admin",
        email="phase15b_admin@example.com",
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
        username="phase15b_viewer",
        email="phase15b_viewer@example.com",
        password="ignored-by-force-auth",
    )
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def anonymous_client() -> APIClient:
    return APIClient()


def _make_snapshot(
    *,
    health_tier: str,
    health_score: int,
    age_hours: float,
    briefing_text: str = (
        "POISONED-BRIEFING-BODY — must not leak through the sidebar endpoint."
    ),
):
    """Insert a CeoOrchestrationSnapshot row with controllable age + tier."""
    from apps.agents.ceo_orchestration.models import CeoOrchestrationSnapshot

    snapshot = CeoOrchestrationSnapshot.objects.create(
        snapshot_at=timezone.now() - timedelta(hours=age_hours),
        business_health_score=health_score,
        health_tier=health_tier,
        cross_cutting_alerts=[
            {"code": "POISONED_ALERT_CODE", "severity": "high"}
        ],
        top_3_priorities=[
            "POISONED-PRIORITY-1",
            "POISONED-PRIORITY-2",
            "POISONED-PRIORITY-3",
        ],
        agent_status_summary={
            "ceo": "POISONED-AGENT-STATUS",
            "cfo": "POISONED-AGENT-STATUS-2",
        },
        briefing_text=briefing_text,
        alerts=[
            {"code": "POISONED_ALERT", "severity": "critical"}
        ],
    )
    return snapshot


def _row_counts() -> dict:
    """Snapshot every model the sidebar-status GET must never mutate."""
    from apps.agents.ceo_orchestration.models import CeoOrchestrationSnapshot
    from apps.ai_governance.models import PromptVersion
    from apps.orders.models import Order, DiscountOfferLog
    from apps.payments.models import Payment
    from apps.crm.models import Customer, Lead
    from apps.shipments.models import Shipment
    from apps.whatsapp.models import WhatsAppMessage
    from apps.calls.models import Call

    return {
        "CeoOrchestrationSnapshot": CeoOrchestrationSnapshot.objects.count(),
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
def test_sidebar_status_blocks_anonymous(anonymous_client: APIClient) -> None:
    res = anonymous_client.get(SIDEBAR_URL)
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_sidebar_status_blocks_viewer(viewer_client: APIClient) -> None:
    res = viewer_client.get(SIDEBAR_URL)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Missing snapshot
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sidebar_status_missing_when_no_snapshot_exists(
    admin_client: APIClient,
) -> None:
    res = admin_client.get(SIDEBAR_URL)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "missing"
    assert body["label"] == "No briefing yet"
    assert body["latestSnapshotId"] is None
    assert body["latestSnapshotAt"] is None
    assert body["ageMinutes"] is None
    assert body["healthScore"] is None
    assert body["tier"] is None
    assert body["targetRoute"] == "/ceo-ai"


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sidebar_status_ready_for_fresh_good_tier(
    db, admin_client: APIClient
) -> None:
    snapshot = _make_snapshot(health_tier="good", health_score=72, age_hours=2)
    res = admin_client.get(SIDEBAR_URL)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ready"
    assert body["label"] == "Briefing ready"
    assert body["latestSnapshotId"] == snapshot.pk
    assert body["healthScore"] == 72
    assert body["tier"] == "good"
    # Age ~120 minutes — give a generous window for test flake.
    assert 100 <= body["ageMinutes"] <= 200


@pytest.mark.django_db
def test_sidebar_status_critical_even_when_fresh(
    db, admin_client: APIClient
) -> None:
    _make_snapshot(health_tier="critical", health_score=15, age_hours=1)
    res = admin_client.get(SIDEBAR_URL)
    body = res.json()
    assert body["status"] == "critical"
    assert body["label"] == "Briefing flags critical"
    assert body["tier"] == "critical"


@pytest.mark.django_db
def test_sidebar_status_stale_for_old_snapshot(
    db, admin_client: APIClient
) -> None:
    # Older than the 36h threshold but not critical tier.
    _make_snapshot(health_tier="good", health_score=72, age_hours=48)
    res = admin_client.get(SIDEBAR_URL)
    body = res.json()
    assert body["status"] == "stale"
    assert body["label"] == "Briefing stale"
    assert body["tier"] == "good"
    assert body["ageMinutes"] >= 36 * 60


@pytest.mark.django_db
def test_sidebar_status_returns_latest_snapshot_when_multiple_exist(
    db, admin_client: APIClient
) -> None:
    older = _make_snapshot(health_tier="fair", health_score=55, age_hours=10)
    newer = _make_snapshot(health_tier="good", health_score=85, age_hours=1)
    res = admin_client.get(SIDEBAR_URL)
    body = res.json()
    assert body["latestSnapshotId"] == newer.pk
    assert body["latestSnapshotId"] != older.pk
    assert body["healthScore"] == 85


# ---------------------------------------------------------------------------
# Sanitisation — no body leakage
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sidebar_status_does_not_leak_briefing_body_or_alerts(
    db, admin_client: APIClient
) -> None:
    """Even though the underlying snapshot has a poisoned briefing
    body + top-3 priorities + agent_status_summary, the sidebar
    endpoint must return only the allow-listed slim keys."""
    _make_snapshot(
        health_tier="fair",
        health_score=60,
        age_hours=2,
        briefing_text=(
            "POISONED-BRIEFING-BODY — must not leak through the sidebar "
            "endpoint. Contains internal Director-only commentary that "
            "should never reach the chrome surface."
        ),
    )
    res = admin_client.get(SIDEBAR_URL)
    assert res.status_code == 200
    body = res.json()

    # Allow-listed keys present.
    for key in (
        "status",
        "label",
        "latestSnapshotId",
        "latestSnapshotAt",
        "ageMinutes",
        "healthScore",
        "tier",
        "targetRoute",
    ):
        assert key in body, f"sidebar response missing allow-listed key {key!r}"

    # Forbidden keys absent.
    for forbidden in (
        "briefingText",
        "briefing_text",
        "crossCuttingAlerts",
        "cross_cutting_alerts",
        "top3Priorities",
        "top_3_priorities",
        "agentStatusSummary",
        "agent_status_summary",
        "alerts",
        "agentRunId",
        "agent_run_id",
    ):
        assert forbidden not in body, (
            f"sidebar response leaked forbidden key {forbidden!r}: {body}"
        )

    # Defence in depth — serialise the response and grep for the
    # poison marker.
    raw = str(body).lower()
    assert "poisoned-briefing-body" not in raw
    assert "poisoned-priority" not in raw
    assert "poisoned-agent-status" not in raw
    assert "poisoned_alert" not in raw


# ---------------------------------------------------------------------------
# Method gates
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sidebar_status_only_supports_get(admin_client: APIClient) -> None:
    """Defence in depth — POST/PUT/PATCH/DELETE all return 405."""
    assert admin_client.post(SIDEBAR_URL, {}, format="json").status_code == 405
    assert admin_client.put(SIDEBAR_URL, {}, format="json").status_code == 405
    assert admin_client.patch(SIDEBAR_URL, {}, format="json").status_code == 405
    assert admin_client.delete(SIDEBAR_URL).status_code == 405


# ---------------------------------------------------------------------------
# Defensive safety — read-only contract
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sidebar_status_never_mutates_anything_or_calls_providers(
    db, admin_client: APIClient
) -> None:
    """Phase 15B is read-only: the GET must NOT call
    ``run_ceo_orchestration_agent_daily``, must NOT call any outbound
    provider, must NOT enqueue Celery tasks, must NOT mutate any row
    (including the snapshot table itself)."""
    _make_snapshot(health_tier="good", health_score=80, age_hours=1)
    before = _row_counts()

    with mock.patch(
        "apps.agents.ceo_orchestration.tasks.run_ceo_orchestration_agent_daily"
    ) as m_run, mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as m_queue, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as m_send, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as m_trigger, mock.patch(
        "apps.shipments.services.create_shipment"
    ) as m_ship:
        res = admin_client.get(SIDEBAR_URL)
        assert res.status_code == 200

        m_run.assert_not_called()
        m_queue.assert_not_called()
        m_send.assert_not_called()
        m_trigger.assert_not_called()
        m_ship.assert_not_called()

    after = _row_counts()
    assert before == after, (
        f"Phase 15B GET must not mutate any row. "
        f"Before: {before}\nAfter: {after}"
    )
