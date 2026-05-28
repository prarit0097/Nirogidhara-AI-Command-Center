"""Phase 16C — Director Daily Briefing + Team Roles UI backend tests.

Coverage:
  - Director briefing overview read requires auth + returns safe empty state.
  - Briefing overview surfaces the latest snapshot status when one exists.
  - Director review/note create works, requires auth, and is admin/director-only.
  - Team-roles list requires auth and returns members + role options.
  - Team-role assignment requires admin/director; non-admins are blocked.
  - Assignment stores the expected operational role + writes a non-PII audit.
  - Defensive safety: no provider / WhatsApp / payment / courier / Vapi call,
    no Celery enqueue, RuntimeKillSwitch + SandboxState untouched.
"""
from __future__ import annotations

from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.agents.ceo_orchestration.models import CeoOrchestrationSnapshot
from apps.audit.models import AuditEvent
from apps.directorops.models import DirectorBriefingReview, TeamRoleAssignment

BRIEFING_OVERVIEW = "/api/v1/director-ops/briefing-overview/"
BRIEFING_REVIEWS = "/api/v1/director-ops/briefing-reviews/"
TEAM_ROLES = "/api/v1/director-ops/team-roles/"
TEAM_ROLES_ASSIGN = "/api/v1/director-ops/team-roles/assign/"


@pytest.fixture
def director_user(db):
    user = User.objects.create_user(
        username="director_user",
        password="director12345",
        email="director@nirogidhara.test",
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


# --------------------------------------------------------------------------
# Director Briefing — read
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_briefing_overview_unauthenticated_blocked() -> None:
    res = APIClient().get(BRIEFING_OVERVIEW)
    assert res.status_code in {401, 403}


@pytest.mark.django_db
def test_briefing_overview_empty_state_when_no_snapshot(
    admin_user, auth_client
) -> None:
    res = auth_client(admin_user).get(BRIEFING_OVERVIEW)
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["briefing"]["status"] == "missing"
    assert body["briefing"]["source"] == "unavailable"
    assert body["briefing"]["snapshotId"] is None
    assert body["generatedByProvider"] is False
    assert body["readiness"]["safetyShellFrozen"] is True
    assert body["readiness"]["liveAutomationApproved"] is False
    assert body["latestReview"] is None


@pytest.mark.django_db
def test_briefing_overview_returns_latest_snapshot_status(
    director_user, auth_client
) -> None:
    CeoOrchestrationSnapshot.objects.create(
        snapshot_at=timezone.now(),
        business_health_score=72,
        health_tier="good",
        briefing_text="Internal Director briefing body.",
        alerts=["sample_alert"],
        top_3_priorities=["p1", "p2", "p3"],
    )
    res = auth_client(director_user).get(BRIEFING_OVERVIEW)
    assert res.status_code == 200, res.content
    briefing = res.json()["briefing"]
    assert briefing["status"] == "fresh"
    assert briefing["source"] == "system_snapshot"
    assert briefing["healthScore"] == 72
    assert briefing["healthTier"] == "good"
    assert briefing["briefingText"] == "Internal Director briefing body."


# --------------------------------------------------------------------------
# Director Briefing — review/note create
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_briefing_review_create_requires_auth() -> None:
    res = APIClient().post(
        BRIEFING_REVIEWS, {"note": "x", "decisionStatus": "reviewed"}, format="json"
    )
    assert res.status_code in {401, 403}


@pytest.mark.django_db
def test_briefing_review_create_non_admin_blocked(
    viewer_user, operations_user, auth_client
) -> None:
    for user in (viewer_user, operations_user):
        res = auth_client(user).post(
            BRIEFING_REVIEWS,
            {"note": "n", "decisionStatus": "reviewed"},
            format="json",
        )
        assert res.status_code == 403, (user.role, res.content)


@pytest.mark.django_db
def test_briefing_review_create_persists_and_audits(
    director_user, auth_client
) -> None:
    audits_before = AuditEvent.objects.count()
    res = auth_client(director_user).post(
        BRIEFING_REVIEWS,
        {
            "note": "Reviewed today; pilot calling team first.",
            "decisionStatus": "needs_action",
            "snapshotRef": 5,
        },
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["decisionStatus"] == "needs_action"
    assert body["snapshotRef"] == 5
    assert body["reviewerUsername"] == "director_user"

    review = DirectorBriefingReview.objects.get(pk=body["id"])
    assert review.reviewer_id == director_user.id
    assert review.note.startswith("Reviewed today")

    assert AuditEvent.objects.count() == audits_before + 1
    audit = AuditEvent.objects.filter(
        kind="directorops.briefing_review.created"
    ).latest("occurred_at")
    # Non-PII payload guarantee.
    assert "note" not in audit.payload
    assert audit.payload["decision_status"] == "needs_action"
    assert audit.payload["has_note"] is True


@pytest.mark.django_db
def test_briefing_review_invalid_status_rejected(
    director_user, auth_client
) -> None:
    res = auth_client(director_user).post(
        BRIEFING_REVIEWS,
        {"note": "n", "decisionStatus": "bogus"},
        format="json",
    )
    assert res.status_code == 400
    assert res.json()["field"] == "decisionStatus"


@pytest.mark.django_db
def test_briefing_review_needs_action_requires_note(
    director_user, auth_client
) -> None:
    res = auth_client(director_user).post(
        BRIEFING_REVIEWS,
        {"note": "", "decisionStatus": "needs_action"},
        format="json",
    )
    assert res.status_code == 400
    assert res.json()["field"] == "note"


# --------------------------------------------------------------------------
# Team Roles — list
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_team_roles_list_requires_auth() -> None:
    res = APIClient().get(TEAM_ROLES)
    assert res.status_code in {401, 403}


@pytest.mark.django_db
def test_team_roles_list_returns_members_and_options(
    viewer_user, admin_user, auth_client
) -> None:
    # Any authenticated user (even a viewer) may READ the list.
    res = auth_client(viewer_user).get(TEAM_ROLES)
    assert res.status_code == 200, res.content
    body = res.json()
    usernames = {m["username"] for m in body["members"]}
    assert {"viewer", "admin_user"} <= usernames
    assert len(body["operationalRoleOptions"]) == 8
    # Email is masked, never raw.
    for member in body["members"]:
        assert "@" not in member["emailMasked"] or member[
            "emailMasked"
        ].count("*") >= 1


# --------------------------------------------------------------------------
# Team Roles — assign
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_team_role_assign_requires_auth(operations_user) -> None:
    res = APIClient().post(
        TEAM_ROLES_ASSIGN,
        {"userId": operations_user.id, "operationalRole": "calling_agent"},
        format="json",
    )
    assert res.status_code in {401, 403}


@pytest.mark.django_db
def test_team_role_assign_non_admin_blocked(
    viewer_user, operations_user, auth_client
) -> None:
    for actor in (viewer_user, operations_user):
        res = auth_client(actor).post(
            TEAM_ROLES_ASSIGN,
            {"userId": operations_user.id, "operationalRole": "calling_agent"},
            format="json",
        )
        assert res.status_code == 403, (actor.role, res.content)
    assert TeamRoleAssignment.objects.count() == 0


@pytest.mark.django_db
def test_team_role_assign_admin_stores_role_and_audits(
    admin_user, operations_user, auth_client
) -> None:
    audits_before = AuditEvent.objects.count()
    res = auth_client(admin_user).post(
        TEAM_ROLES_ASSIGN,
        {
            "userId": operations_user.id,
            "operationalRole": "confirmation_team",
            "isActive": True,
            "notes": "Pilot confirmation handler",
        },
        format="json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["userId"] == operations_user.id
    assert body["operationalRole"] == "confirmation_team"
    assert body["operationalRoleLabel"] == "Confirmation Team"

    assignment = TeamRoleAssignment.objects.get(user=operations_user)
    assert assignment.operational_role == "confirmation_team"
    assert assignment.assigned_by_id == admin_user.id
    assert assignment.notes == "Pilot confirmation handler"

    assert AuditEvent.objects.count() == audits_before + 1
    audit = AuditEvent.objects.filter(
        kind="directorops.team_role.assigned"
    ).latest("occurred_at")
    assert audit.payload["target_user_id"] == operations_user.id
    assert audit.payload["operational_role"] == "confirmation_team"
    # No email / name leaked into the audit payload.
    assert "email" not in audit.payload
    assert "username" not in audit.payload


@pytest.mark.django_db
def test_team_role_assign_director_upserts_existing(
    director_user, operations_user, auth_client
) -> None:
    client = auth_client(director_user)
    client.post(
        TEAM_ROLES_ASSIGN,
        {"userId": operations_user.id, "operationalRole": "calling_agent"},
        format="json",
    )
    res = client.post(
        TEAM_ROLES_ASSIGN,
        {"userId": operations_user.id, "operationalRole": "finance_accounts"},
        format="json",
    )
    assert res.status_code == 200, res.content
    # Upsert — exactly one row, role updated.
    assert TeamRoleAssignment.objects.filter(user=operations_user).count() == 1
    assignment = TeamRoleAssignment.objects.get(user=operations_user)
    assert assignment.operational_role == "finance_accounts"


@pytest.mark.django_db
def test_team_role_assign_invalid_role_rejected(
    admin_user, operations_user, auth_client
) -> None:
    res = auth_client(admin_user).post(
        TEAM_ROLES_ASSIGN,
        {"userId": operations_user.id, "operationalRole": "ceo_overlord"},
        format="json",
    )
    assert res.status_code == 400
    assert res.json()["field"] == "operationalRole"
    assert TeamRoleAssignment.objects.count() == 0


@pytest.mark.django_db
def test_team_role_assign_unknown_user_404(admin_user, auth_client) -> None:
    res = auth_client(admin_user).post(
        TEAM_ROLES_ASSIGN,
        {"userId": 999999, "operationalRole": "calling_agent"},
        format="json",
    )
    assert res.status_code == 404
    assert res.json()["field"] == "userId"


# --------------------------------------------------------------------------
# Defensive safety — no provider/business side effects, safety state untouched
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase16c_paths_trigger_no_provider_or_business_side_effect(
    director_user, operations_user, auth_client
) -> None:
    from apps.ai_governance.sandbox import is_sandbox_enabled
    from apps.saas.models import RuntimeKillSwitch

    sandbox_before = is_sandbox_enabled()
    killswitch_before = RuntimeKillSwitch.objects.count()

    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as wa_template, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as wa_freeform, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as vapi_call, mock.patch(
        "apps.shipments.services.create_shipment"
    ) as courier:
        client = auth_client(director_user)
        client.get(BRIEFING_OVERVIEW)
        client.post(
            BRIEFING_REVIEWS,
            {"note": "ok", "decisionStatus": "reviewed"},
            format="json",
        )
        client.get(TEAM_ROLES)
        client.post(
            TEAM_ROLES_ASSIGN,
            {"userId": operations_user.id, "operationalRole": "qa_compliance"},
            format="json",
        )

    wa_template.assert_not_called()
    wa_freeform.assert_not_called()
    vapi_call.assert_not_called()
    courier.assert_not_called()

    # Phase 15 safety shell state untouched by any Phase 16C path.
    assert is_sandbox_enabled() == sandbox_before
    assert RuntimeKillSwitch.objects.count() == killswitch_before
