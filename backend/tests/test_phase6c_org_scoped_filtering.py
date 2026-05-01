"""Phase 6C — Org-Scoped API Filtering Plan tests.

Covers:

- Active-organization resolvers (default org, member org, staff
  fallback, request-stamped org).
- Queryset scoping helpers (org-aware models filter; non-org-aware
  models pass through; superusers see across tenants).
- Two-org leak tests: scoped helpers must NEVER return another
  tenant's rows.
- ``write_event`` auto-attaches the active organization to new
  ``AuditEvent`` rows; existing call sites still work.
- Diagnostic command + ``GET /api/v1/saas/org-scope-readiness/`` API.
"""
from __future__ import annotations

import io
import json
from typing import Any

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer, Lead
from apps.orders.models import Order
from apps.saas.context import (
    filter_queryset_by_organization,
    get_default_organization,
    get_user_active_branch,
    get_user_active_organization,
    model_has_organization_field,
    resolve_request_organization,
    scoped_queryset_for_request,
    scoped_queryset_for_user,
    user_has_org_access,
)
from apps.saas.models import (
    Branch,
    Organization,
    OrganizationMembership,
)
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ensure_default_org() -> Organization:
    out = io.StringIO()
    call_command(
        "ensure_default_organization", "--json", "--skip-memberships",
        stdout=out,
    )
    return Organization.objects.get(code="nirogidhara")


def _create_org(code: str, name: str | None = None) -> Organization:
    return Organization.objects.create(
        code=code,
        name=name or code,
        legal_name=name or code,
        status=Organization.Status.ACTIVE,
    )


def _create_branch(org: Organization, code: str = "hq") -> Branch:
    return Branch.objects.create(
        organization=org, code=code, name=code.upper()
    )


def _create_member(user, org: Organization, role: str = "admin"):
    return OrganizationMembership.objects.create(
        user=user,
        organization=org,
        role=role,
        status=OrganizationMembership.Status.ACTIVE,
    )


# ---------------------------------------------------------------------------
# Section A — Resolvers
# ---------------------------------------------------------------------------


def test_default_org_resolver(db):
    _ensure_default_org()
    org = get_default_organization()
    assert org is not None
    assert org.code == "nirogidhara"


def test_user_active_org_falls_back_to_default(db, admin_user):
    """A user with no membership row still gets the default org —
    Phase 6C must not break logins for existing single-tenant admins."""
    _ensure_default_org()
    org = get_user_active_organization(admin_user)
    assert org is not None
    assert org.code == "nirogidhara"


def test_user_active_org_picks_active_membership(db, admin_user):
    _ensure_default_org()
    other = _create_org("other-co", "Other Co")
    _create_member(admin_user, other, role="owner")
    org = get_user_active_organization(admin_user)
    assert org.code == "other-co"


def test_user_active_org_skips_disabled_membership(db, admin_user):
    """A disabled membership must not surface — fallback to default."""
    _ensure_default_org()
    other = _create_org("other-co", "Other Co")
    OrganizationMembership.objects.create(
        user=admin_user,
        organization=other,
        role="agent",
        status=OrganizationMembership.Status.DISABLED,
    )
    org = get_user_active_organization(admin_user)
    assert org.code == "nirogidhara"


def test_user_active_org_skips_inactive_organization(db, admin_user):
    _ensure_default_org()
    paused = _create_org("paused-co", "Paused Co")
    paused.status = Organization.Status.PAUSED
    paused.save()
    _create_member(admin_user, paused, role="owner")
    org = get_user_active_organization(admin_user)
    assert org.code == "nirogidhara"


def test_user_active_org_returns_none_for_anonymous(db):
    org = get_user_active_organization(None)
    assert org is None


def test_resolve_request_organization_uses_request_attr(
    db, admin_user, rf=None
):
    """A future middleware can stamp ``request.organization`` to skip
    the lookup. The resolver must honour that."""
    _ensure_default_org()
    other = _create_org("other-co", "Other Co")

    class _StubReq:
        pass

    req = _StubReq()
    req.organization = other
    req.user = admin_user
    org = resolve_request_organization(req)
    assert org.code == "other-co"


def test_user_has_org_access(db, admin_user, viewer_user):
    _ensure_default_org()
    other = _create_org("other-co", "Other Co")
    _create_member(admin_user, other, role="owner")
    assert user_has_org_access(admin_user, other) is True
    assert user_has_org_access(viewer_user, other) is False
    assert user_has_org_access(None, other) is False


def test_get_user_active_branch_returns_default_branch(db, admin_user):
    _ensure_default_org()
    branch = get_user_active_branch(admin_user)
    assert branch is not None
    assert branch.code == "main"


# ---------------------------------------------------------------------------
# Section B — Queryset scoping helpers
# ---------------------------------------------------------------------------


def test_model_has_organization_field_detects_correctly(db):
    assert model_has_organization_field(Lead) is True
    assert model_has_organization_field(Customer) is True
    # WhatsAppConnection is system-level — no org FK in Phase 6B.
    assert model_has_organization_field(WhatsAppConnection) is False


def test_filter_queryset_by_organization_filters_when_field_exists(db):
    org_a = _ensure_default_org()
    org_b = _create_org("other-co", "Other Co")
    Lead.objects.create(
        id="LD-A", name="A", phone="+91000000000",
        state="MH", city="A", language="en",
        source="seed", campaign="seed",
        product_interest="X",
        organization=org_a,
    )
    Lead.objects.create(
        id="LD-B", name="B", phone="+91111111111",
        state="MH", city="B", language="en",
        source="seed", campaign="seed",
        product_interest="X",
        organization=org_b,
    )
    qs = filter_queryset_by_organization(Lead.objects.all(), org_a)
    ids = list(qs.values_list("id", flat=True))
    assert ids == ["LD-A"]


def test_filter_queryset_by_organization_passes_through_global_models(db):
    """Models without an organization field must NOT crash; the
    helper returns the queryset unchanged."""
    org = _ensure_default_org()
    WhatsAppConnection.objects.create(
        id="WAC-X",
        provider=WhatsAppConnection.Provider.MOCK,
        display_name="X",
        phone_number="+91 9000099000",
        phone_number_id="x",
        business_account_id="x",
        status=WhatsAppConnection.Status.CONNECTED,
    )
    qs = filter_queryset_by_organization(
        WhatsAppConnection.objects.all(), org
    )
    assert qs.count() == 1


def test_filter_queryset_no_op_when_org_is_none(db):
    """``organization=None`` must NOT silently strip rows."""
    org = _ensure_default_org()
    Lead.objects.create(
        id="LD-NULL", name="X", phone="+91000000999",
        state="MH", city="X", language="en",
        source="seed", campaign="seed", product_interest="X",
        organization=org,
    )
    qs = filter_queryset_by_organization(Lead.objects.all(), None)
    assert qs.count() == 1


def test_scoped_queryset_for_user_returns_only_user_org_rows(db, admin_user):
    org_a = _ensure_default_org()
    org_b = _create_org("other-co", "Other Co")
    _create_member(admin_user, org_b, role="owner")
    Lead.objects.create(
        id="LD-A", name="A", phone="+91000000000",
        state="MH", city="A", language="en",
        source="seed", campaign="seed", product_interest="X",
        organization=org_a,
    )
    Lead.objects.create(
        id="LD-B", name="B", phone="+91111111111",
        state="MH", city="B", language="en",
        source="seed", campaign="seed", product_interest="X",
        organization=org_b,
    )
    qs = scoped_queryset_for_user(Lead.objects.all(), admin_user)
    ids = set(qs.values_list("id", flat=True))
    assert ids == {"LD-B"}, "scoping leaked rows from another org"


def test_scoped_queryset_for_user_returns_all_for_superuser(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    superuser = User.objects.create_superuser(
        username="root", password="root12345", email="root@nirogidhara.test"
    )
    org_a = _ensure_default_org()
    org_b = _create_org("other-co", "Other Co")
    Lead.objects.create(
        id="LD-A", name="A", phone="+91000000000",
        state="MH", city="A", language="en",
        source="seed", campaign="seed", product_interest="X",
        organization=org_a,
    )
    Lead.objects.create(
        id="LD-B", name="B", phone="+91111111111",
        state="MH", city="B", language="en",
        source="seed", campaign="seed", product_interest="X",
        organization=org_b,
    )
    qs = scoped_queryset_for_user(Lead.objects.all(), superuser)
    assert qs.count() == 2


# ---------------------------------------------------------------------------
# Section C — Two-org leak proofs (Customer / Order / WhatsApp)
# ---------------------------------------------------------------------------


def test_customer_two_org_leak_test(db, admin_user):
    _ensure_default_org()
    org_a = get_default_organization()
    org_b = _create_org("other-co", "Other Co")
    _create_member(admin_user, org_a, role="admin")

    Customer.objects.create(
        id="CUST-A", name="A", phone="+91000000001",
        state="MH", city="A", language="en", product_interest="X",
        organization=org_a,
    )
    Customer.objects.create(
        id="CUST-B", name="B", phone="+91000000002",
        state="MH", city="B", language="en", product_interest="X",
        organization=org_b,
    )

    qs = scoped_queryset_for_user(Customer.objects.all(), admin_user)
    ids = set(qs.values_list("id", flat=True))
    assert ids == {"CUST-A"}


def test_order_two_org_leak_test(db, admin_user):
    _ensure_default_org()
    org_a = get_default_organization()
    org_b = _create_org("other-co", "Other Co")
    _create_member(admin_user, org_a, role="admin")

    Order.objects.create(
        id="ORD-A", customer_name="A", phone="+91000000001",
        product="X", amount=3000, organization=org_a,
    )
    Order.objects.create(
        id="ORD-B", customer_name="B", phone="+91000000002",
        product="X", amount=3000, organization=org_b,
    )

    qs = scoped_queryset_for_user(Order.objects.all(), admin_user)
    ids = set(qs.values_list("id", flat=True))
    assert ids == {"ORD-A"}


def test_whatsapp_conversation_two_org_leak_test(db, admin_user):
    _ensure_default_org()
    org_a = get_default_organization()
    org_b = _create_org("other-co", "Other Co")
    _create_member(admin_user, org_a, role="admin")

    connection = WhatsAppConnection.objects.create(
        id="WAC-LEAK",
        provider=WhatsAppConnection.Provider.MOCK,
        display_name="Leak",
        phone_number="+91 9000099000",
        phone_number_id="leak",
        business_account_id="leak",
        status=WhatsAppConnection.Status.CONNECTED,
    )
    cust_a = Customer.objects.create(
        id="CUST-LEAK-A", name="A", phone="+91000000010",
        state="MH", city="A", language="en", product_interest="X",
        organization=org_a,
    )
    cust_b = Customer.objects.create(
        id="CUST-LEAK-B", name="B", phone="+91000000011",
        state="MH", city="B", language="en", product_interest="X",
        organization=org_b,
    )
    convo_a = WhatsAppConversation.objects.create(
        id="WCV-A", customer=cust_a, connection=connection,
        organization=org_a,
    )
    convo_b = WhatsAppConversation.objects.create(
        id="WCV-B", customer=cust_b, connection=connection,
        organization=org_b,
    )

    qs = scoped_queryset_for_user(
        WhatsAppConversation.objects.all(), admin_user
    )
    assert {c.id for c in qs} == {"WCV-A"}


# ---------------------------------------------------------------------------
# Section D — Audit auto-org context
# ---------------------------------------------------------------------------


def test_write_event_auto_attaches_default_organization(db):
    org = _ensure_default_org()
    event = write_event(
        kind="phase6c.test",
        text="auto attach test",
        payload={"foo": "bar"},
    )
    assert event.organization_id == org.id


def test_write_event_uses_explicit_organization_when_passed(db):
    _ensure_default_org()
    other = _create_org("other-co", "Other Co")
    event = write_event(
        kind="phase6c.test",
        text="explicit attach",
        payload={"foo": "bar"},
        organization=other,
    )
    assert event.organization_id == other.id


def test_write_event_resolves_organization_from_user(db, admin_user):
    _ensure_default_org()
    other = _create_org("other-co", "Other Co")
    _create_member(admin_user, other, role="owner")
    event = write_event(
        kind="phase6c.test",
        text="user attach",
        payload={},
        user=admin_user,
    )
    assert event.organization_id == other.id


def test_write_event_silent_when_org_resolution_unavailable(db):
    """No default org seeded — write_event must NOT crash; the row
    is created with organization=NULL."""
    event = write_event(
        kind="phase6c.test", text="no org", payload={}
    )
    assert event.id > 0
    assert event.organization_id is None


def test_existing_write_event_call_sites_unchanged(db):
    """Backwards compat — every existing call site keeps working
    without passing the new kwargs."""
    _ensure_default_org()
    event = write_event(kind="legacy.kind", text="legacy text")
    assert event.id > 0
    assert event.kind == "legacy.kind"


# ---------------------------------------------------------------------------
# Section E — Readiness command + API
# ---------------------------------------------------------------------------


def _run_readiness_cmd() -> dict[str, Any]:
    out = io.StringIO()
    call_command("inspect_org_scoped_api_readiness", "--json", stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_readiness_command_returns_expected_fields(db):
    _ensure_default_org()
    report = _run_readiness_cmd()
    expected_keys = {
        "defaultOrganizationExists",
        "defaultBranchExists",
        "organizationCoveragePercent",
        "branchCoveragePercent",
        "scopedModels",
        "unscopedModels",
        "scopedApis",
        "unscopedApis",
        "auditAutoOrgContextEnabled",
        "globalTenantFilteringEnabled",
        "safeToStartPhase6D",
        "blockers",
        "warnings",
        "nextAction",
    }
    assert expected_keys.issubset(report.keys())
    assert report["auditAutoOrgContextEnabled"] is True
    assert report["globalTenantFilteringEnabled"] is False


def test_readiness_command_blocks_when_default_org_missing(db):
    report = _run_readiness_cmd()
    assert report["defaultOrganizationExists"] is False
    assert report["nextAction"] == "fix_org_scope_blockers"


def test_readiness_endpoint_requires_auth(db, auth_client):
    _ensure_default_org()
    client = auth_client(None)
    res = client.get(reverse("saas-org-scope-readiness"))
    assert res.status_code in (401, 403)


def test_readiness_endpoint_returns_shape_for_authenticated(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-org-scope-readiness"))
    assert res.status_code == 200
    body = res.json()
    assert body["auditAutoOrgContextEnabled"] is True
    assert body["globalTenantFilteringEnabled"] is False
    # No tokens / secrets / phone numbers in the response.
    blob = json.dumps(body).lower()
    for needle in ("token", "secret", "password", "+919"):
        assert needle not in blob


def test_readiness_endpoint_rejects_post(db, admin_user, auth_client):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.post(reverse("saas-org-scope-readiness"), {})
    assert res.status_code == 405


# ---------------------------------------------------------------------------
# Section F — Existing endpoints still work
# ---------------------------------------------------------------------------


def test_existing_data_coverage_endpoint_still_works(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-data-coverage"))
    assert res.status_code == 200
    assert res.json()["defaultOrganizationExists"] is True


def test_existing_current_organization_endpoint_still_works(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-current-organization"))
    assert res.status_code == 200
    assert res.json()["organization"]["code"] == "nirogidhara"
