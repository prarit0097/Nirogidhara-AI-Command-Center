"""Phase 6A — SaaS Foundation tests.

Covers:

- Models: Organization / Branch / OrganizationMembership /
  OrganizationFeatureFlag / OrganizationSetting.
- Uniqueness constraints.
- ``ensure_default_organization`` is idempotent and writes the audit
  row without printing secrets.
- Selectors: ``get_default_organization``, ``get_user_organizations``,
  ``get_organization_feature_flags``, ``is_feature_enabled``,
  ``get_non_sensitive_settings`` (sensitive rows omitted).
- API endpoints: auth required, no secrets returned, sensitive
  settings never appear, feature flag map matches selectors.
"""
from __future__ import annotations

import io
import json

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.saas import selectors as saas_selectors
from apps.saas.models import (
    Branch,
    Organization,
    OrganizationFeatureFlag,
    OrganizationMembership,
    OrganizationSetting,
)


# ---------------------------------------------------------------------------
# Section A — Model + uniqueness
# ---------------------------------------------------------------------------


def _create_org(code: str = "acme", name: str = "Acme Corp") -> Organization:
    return Organization.objects.create(
        code=code,
        name=name,
        legal_name=name,
        status=Organization.Status.ACTIVE,
        timezone="Asia/Kolkata",
        country="IN",
    )


def test_organization_creation_minimum_fields(db):
    org = _create_org()
    assert org.id > 0
    assert org.status == Organization.Status.ACTIVE
    assert org.timezone == "Asia/Kolkata"
    assert org.country == "IN"
    assert org.metadata == {}


def test_branch_creation_under_organization(db):
    org = _create_org()
    branch = Branch.objects.create(
        organization=org, code="hq", name="HQ"
    )
    assert branch.organization_id == org.id
    assert branch.status == Branch.Status.ACTIVE


def test_branch_unique_per_org_code(db):
    org = _create_org()
    Branch.objects.create(organization=org, code="hq", name="HQ")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Branch.objects.create(
                organization=org, code="hq", name="Duplicate"
            )


def test_membership_uniqueness(db, admin_user):
    org = _create_org()
    OrganizationMembership.objects.create(
        organization=org,
        user=admin_user,
        role=OrganizationMembership.OrgRole.OWNER,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            OrganizationMembership.objects.create(
                organization=org,
                user=admin_user,
                role=OrganizationMembership.OrgRole.ADMIN,
            )


def test_feature_flag_lookup_returns_default_when_missing(db):
    org = _create_org()
    assert saas_selectors.is_feature_enabled(org, "missing.flag") is False
    assert (
        saas_selectors.is_feature_enabled(org, "missing.flag", default=True)
        is True
    )
    OrganizationFeatureFlag.objects.create(
        organization=org, key="ai.beta", enabled=True
    )
    assert saas_selectors.is_feature_enabled(org, "ai.beta") is True


def test_feature_flag_unique_per_org_key(db):
    org = _create_org()
    OrganizationFeatureFlag.objects.create(
        organization=org, key="ai.beta", enabled=True
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            OrganizationFeatureFlag.objects.create(
                organization=org, key="ai.beta", enabled=False
            )


def test_organization_setting_sensitive_is_filtered_from_public_selector(db):
    org = _create_org()
    OrganizationSetting.objects.create(
        organization=org,
        key="display.theme",
        value="emerald",
        is_sensitive=False,
    )
    OrganizationSetting.objects.create(
        organization=org,
        key="razorpay.api_key",
        value="rzp_secret_must_not_leak",
        is_sensitive=True,
    )
    public = saas_selectors.get_non_sensitive_settings(org)
    assert public == {"display.theme": "emerald"}
    assert "razorpay.api_key" not in public
    assert "rzp_secret_must_not_leak" not in json.dumps(public)


def test_organization_setting_unique_per_org_key(db):
    org = _create_org()
    OrganizationSetting.objects.create(
        organization=org, key="locale", value="en-IN"
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            OrganizationSetting.objects.create(
                organization=org, key="locale", value="hi-IN"
            )


# ---------------------------------------------------------------------------
# Section B — ensure_default_organization
# ---------------------------------------------------------------------------


def _run_ensure(**kwargs) -> dict:
    out = io.StringIO()
    call_command("ensure_default_organization", "--json", stdout=out, **kwargs)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_ensure_default_organization_idempotent(db, admin_user):
    first = _run_ensure()
    assert first["passed"] is True
    assert first["organizationCode"] == "nirogidhara"
    assert first["createdOrganization"] is True
    assert first["createdBranch"] is True
    org_id = first["organizationId"]
    assert (
        Organization.objects.filter(code="nirogidhara").count() == 1
    )

    second = _run_ensure()
    assert second["passed"] is True
    assert second["createdOrganization"] is False
    assert second["createdBranch"] is False
    assert second["organizationId"] == org_id
    # No duplicate org or branch was created.
    assert (
        Organization.objects.filter(code="nirogidhara").count() == 1
    )
    assert Branch.objects.filter(code="main").count() == 1


def test_ensure_default_organization_writes_audit_row(db, admin_user):
    _run_ensure()
    audit = AuditEvent.objects.filter(
        kind="saas.default_organization.ensured"
    ).first()
    assert audit is not None
    assert audit.payload["organization_code"] == "nirogidhara"
    # Never leaks secrets.
    blob = json.dumps(audit.payload).lower()
    for needle in ("token", "secret", "password", "api_key"):
        assert needle not in blob


def test_ensure_default_organization_skip_memberships_flag(db, admin_user):
    report = _run_ensure(skip_memberships=True)
    assert report["membershipsSkipped"] is True
    assert report["membershipsCreated"] == 0
    assert (
        OrganizationMembership.objects.filter(
            organization_id=report["organizationId"]
        ).count()
        == 0
    )


def test_ensure_default_organization_does_not_mutate_business_data(
    db, admin_user
):
    """Sanity check — running the seed must not touch business-state
    tables. We assert the imported models stay un-touched (counts
    captured at fixture time will be zero in a fresh test DB)."""
    from apps.crm.models import Customer
    from apps.orders.models import DiscountOfferLog, Order
    from apps.payments.models import Payment
    from apps.shipments.models import Shipment

    before = (
        Customer.objects.count(),
        Order.objects.count(),
        Payment.objects.count(),
        Shipment.objects.count(),
        DiscountOfferLog.objects.count(),
    )
    _run_ensure()
    after = (
        Customer.objects.count(),
        Order.objects.count(),
        Payment.objects.count(),
        Shipment.objects.count(),
        DiscountOfferLog.objects.count(),
    )
    assert before == after


# ---------------------------------------------------------------------------
# Section C — Selectors
# ---------------------------------------------------------------------------


def test_get_default_organization_returns_seeded_org(db):
    _run_ensure(skip_memberships=True)
    org = saas_selectors.get_default_organization()
    assert org is not None
    assert org.code == "nirogidhara"


def test_get_user_organizations_falls_back_to_default(db, admin_user):
    """A user with no membership rows still gets the default org."""
    _run_ensure(skip_memberships=True)
    orgs = saas_selectors.get_user_organizations(admin_user)
    assert len(orgs) == 1
    assert orgs[0].code == "nirogidhara"


def test_get_user_organizations_returns_only_active_memberships(
    db, admin_user
):
    _run_ensure()
    org = saas_selectors.get_default_organization()
    other = _create_org(code="other", name="Other Co")
    # Disabled membership must NOT appear in the active list.
    OrganizationMembership.objects.create(
        organization=other,
        user=admin_user,
        role=OrganizationMembership.OrgRole.AGENT,
        status=OrganizationMembership.Status.DISABLED,
    )
    orgs = saas_selectors.get_user_organizations(admin_user)
    codes = {o.code for o in orgs}
    assert org.code in codes
    assert "other" not in codes


def test_get_organization_feature_flags_shape(db):
    org = _create_org()
    OrganizationFeatureFlag.objects.create(
        organization=org, key="ai.beta", enabled=True, config={"tier": "v3"}
    )
    OrganizationFeatureFlag.objects.create(
        organization=org, key="campaigns", enabled=False
    )
    flags = saas_selectors.get_organization_feature_flags(org)
    assert flags["ai.beta"] == {"enabled": True, "config": {"tier": "v3"}}
    assert flags["campaigns"] == {"enabled": False, "config": {}}


# ---------------------------------------------------------------------------
# Section D — API endpoints
# ---------------------------------------------------------------------------


META_OK = {}  # placeholder — no env override needed for SaaS endpoints


def test_current_organization_endpoint_requires_auth(
    db, auth_client
):
    _run_ensure(skip_memberships=True)
    client = auth_client(None)
    res = client.get(reverse("saas-current-organization"))
    assert res.status_code in (401, 403)


def test_current_organization_endpoint_returns_default_for_admin(
    db, admin_user, auth_client
):
    _run_ensure()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-current-organization"))
    assert res.status_code == 200
    body = res.json()
    assert body["organization"]["code"] == "nirogidhara"
    assert body["organization"]["defaultBranch"]["code"] == "main"
    assert body["organization"]["userOrgRole"] in {
        "owner",
        "admin",
        "manager",
        "agent",
        "viewer",
        "",
    }


def test_my_organizations_endpoint_returns_list(
    db, admin_user, auth_client
):
    _run_ensure()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-my-organizations"))
    assert res.status_code == 200
    body = res.json()
    assert body["count"] >= 1
    assert any(
        o is not None and o["code"] == "nirogidhara"
        for o in body["organizations"]
    )


def test_feature_flags_endpoint_omits_sensitive_settings(
    db, admin_user, auth_client
):
    _run_ensure()
    org = saas_selectors.get_default_organization()
    OrganizationFeatureFlag.objects.create(
        organization=org, key="ai.beta", enabled=True
    )
    OrganizationSetting.objects.create(
        organization=org,
        key="razorpay.api_key",
        value="rzp_must_not_leak",
        is_sensitive=True,
    )
    client = auth_client(admin_user)
    res = client.get(reverse("saas-feature-flags"))
    assert res.status_code == 200
    blob = json.dumps(res.json()).lower()
    assert "ai.beta" in blob
    assert "rzp_must_not_leak" not in blob
    assert "razorpay.api_key" not in blob


def test_current_organization_endpoint_omits_sensitive_settings(
    db, admin_user, auth_client
):
    _run_ensure()
    org = saas_selectors.get_default_organization()
    OrganizationSetting.objects.create(
        organization=org,
        key="display.theme",
        value="emerald",
        is_sensitive=False,
    )
    OrganizationSetting.objects.create(
        organization=org,
        key="meta.access_token",
        value="must_not_leak_xyz",
        is_sensitive=True,
    )
    client = auth_client(admin_user)
    res = client.get(reverse("saas-current-organization"))
    body = res.json()
    blob = json.dumps(body).lower()
    assert "must_not_leak_xyz" not in blob
    assert body["settings"] == {"display.theme": "emerald"}


def test_saas_endpoints_reject_post(db, admin_user, auth_client):
    _run_ensure()
    client = auth_client(admin_user)
    for name in (
        "saas-current-organization",
        "saas-my-organizations",
        "saas-feature-flags",
    ):
        url = reverse(name)
        res = client.post(url, {})
        assert res.status_code == 405, f"{name} accepted POST"
