"""Phase 6B — Default Org Data Backfill tests.

Covers:

- Adding nullable ``organization`` / ``branch`` fields does not require
  org on create — every existing factory keeps working.
- ``ensure_default_organization`` remains idempotent.
- ``backfill_default_organization_data`` defaults to dry-run; ``--apply``
  is required for any DB write.
- The backfill never overwrites an existing ``organization`` / ``branch``
  assignment.
- The backfill emits the started + completed audit rows.
- ``inspect_default_organization_coverage`` reports correct percentages
  + a typed ``nextAction``.
- ``GET /api/v1/saas/data-coverage/`` is auth-protected, read-only, and
  carries no secrets / no PII.
"""
from __future__ import annotations

import io
import json
from typing import Any

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer, Lead
from apps.orders.models import Order
from apps.saas.models import (
    Branch,
    Organization,
)


def _ensure_default_org() -> Organization:
    out = io.StringIO()
    call_command(
        "ensure_default_organization", "--json", "--skip-memberships",
        stdout=out,
    )
    return Organization.objects.get(code="nirogidhara")


def _seed_one_lead() -> Lead:
    return Lead.objects.create(
        id="LD-PHASE6B-001",
        name="Backfill Lead",
        phone="+919999900001",
        state="MH",
        city="Pune",
        language="en",
        source="seed",
        campaign="seed",
        product_interest="Weight Management",
    )


def _seed_one_customer() -> Customer:
    return Customer.objects.create(
        id="NRG-CUST-PHASE6B-001",
        name="Backfill Customer",
        phone="+919999900002",
        state="MH",
        city="Pune",
        language="en",
        product_interest="Weight Management",
    )


def _seed_one_order(customer_phone: str = "+919999900002") -> Order:
    return Order.objects.create(
        id="ORD-PHASE6B-001",
        customer_name="Backfill Customer",
        phone=customer_phone,
        product="Weight Management",
        amount=3000,
    )


def _run_backfill(apply: bool = False) -> dict[str, Any]:
    out = io.StringIO()
    args = ["backfill_default_organization_data", "--json"]
    if apply:
        args.append("--apply")
    else:
        args.append("--dry-run")
    call_command(*args, stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def _run_inspect() -> dict[str, Any]:
    out = io.StringIO()
    call_command(
        "inspect_default_organization_coverage", "--json", stdout=out,
    )
    return json.loads(out.getvalue().strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# Section A — schema is backward compatible
# ---------------------------------------------------------------------------


def test_lead_create_without_organization(db):
    """Phase 6B fields are nullable — every existing factory keeps working."""
    lead = _seed_one_lead()
    assert lead.organization_id is None
    assert lead.branch_id is None


def test_customer_create_without_organization(db):
    cust = _seed_one_customer()
    assert cust.organization_id is None
    assert cust.branch_id is None


def test_order_create_without_organization(db):
    order = _seed_one_order()
    assert order.organization_id is None
    assert order.branch_id is None


# ---------------------------------------------------------------------------
# Section B — ensure_default_organization is still idempotent
# ---------------------------------------------------------------------------


def test_ensure_default_organization_remains_idempotent(db):
    org1 = _ensure_default_org()
    org2 = _ensure_default_org()
    assert org1.id == org2.id
    assert Organization.objects.filter(code="nirogidhara").count() == 1
    assert Branch.objects.filter(code="main").count() == 1


# ---------------------------------------------------------------------------
# Section C — backfill default = dry-run; --apply writes
# ---------------------------------------------------------------------------


def test_backfill_dry_run_does_not_update(db):
    _ensure_default_org()
    _seed_one_lead()
    _seed_one_customer()
    _seed_one_order()

    report = _run_backfill(apply=False)
    assert report["passed"] is True
    assert report["dryRun"] is True
    assert report["totalUpdatedOrganization"] == 0
    assert report["totalUpdatedBranch"] == 0
    # All rows still missing org.
    for model_row in report["models"]:
        if model_row["model"] in {"crm.Lead", "crm.Customer", "orders.Order"}:
            assert model_row["missingOrganization"] >= 1

    # Verify the DB itself was not touched.
    assert Lead.objects.filter(organization__isnull=True).count() == 1
    assert Customer.objects.filter(organization__isnull=True).count() == 1
    assert Order.objects.filter(organization__isnull=True).count() == 1


def test_backfill_apply_updates_missing_organization_and_branch(db):
    _ensure_default_org()
    _seed_one_lead()
    _seed_one_customer()
    _seed_one_order()

    report = _run_backfill(apply=True)
    assert report["passed"] is True
    assert report["dryRun"] is False
    assert report["totalUpdatedOrganization"] >= 3
    assert report["totalUpdatedBranch"] >= 3

    org = Organization.objects.get(code="nirogidhara")
    branch = Branch.objects.get(code="main")
    lead = Lead.objects.get(id="LD-PHASE6B-001")
    assert lead.organization_id == org.id
    assert lead.branch_id == branch.id
    cust = Customer.objects.get(id="NRG-CUST-PHASE6B-001")
    assert cust.organization_id == org.id
    assert cust.branch_id == branch.id
    order = Order.objects.get(id="ORD-PHASE6B-001")
    assert order.organization_id == org.id
    assert order.branch_id == branch.id


def test_backfill_apply_does_not_overwrite_existing_org(db):
    """Rows that already have an org / branch must NOT be touched."""
    _ensure_default_org()
    other_org = Organization.objects.create(
        code="other-org",
        name="Other Co",
        legal_name="Other Co",
    )
    other_branch = Branch.objects.create(
        organization=other_org, code="hq", name="HQ"
    )
    lead = _seed_one_lead()
    lead.organization = other_org
    lead.branch = other_branch
    lead.save()
    _seed_one_customer()  # this one IS missing org → should be touched.

    report = _run_backfill(apply=True)
    assert report["passed"] is True

    lead.refresh_from_db()
    assert lead.organization_id == other_org.id
    assert lead.branch_id == other_branch.id

    cust = Customer.objects.get(id="NRG-CUST-PHASE6B-001")
    default_org = Organization.objects.get(code="nirogidhara")
    assert cust.organization_id == default_org.id


def test_backfill_apply_emits_audit_rows(db):
    _ensure_default_org()
    _seed_one_lead()
    _run_backfill(apply=True)
    assert AuditEvent.objects.filter(
        kind="saas.default_org_backfill.started"
    ).exists()
    completed = AuditEvent.objects.filter(
        kind="saas.default_org_backfill.completed"
    ).first()
    assert completed is not None
    assert completed.payload["mode"] == "apply"
    assert completed.payload["organization_code"] == "nirogidhara"


def test_backfill_dry_run_emits_started_completed_audits(db):
    _ensure_default_org()
    _seed_one_lead()
    _run_backfill(apply=False)
    assert AuditEvent.objects.filter(
        kind="saas.default_org_backfill.started",
        payload__mode="dry_run",
    ).exists()
    assert AuditEvent.objects.filter(
        kind="saas.default_org_backfill.completed",
        payload__mode="dry_run",
    ).exists()


def test_backfill_audit_rows_omit_secrets(db):
    _ensure_default_org()
    _seed_one_lead()
    _run_backfill(apply=True)
    blob = json.dumps(
        list(
            AuditEvent.objects.filter(
                kind__startswith="saas.default_org_backfill"
            ).values_list("payload", flat=True)
        )
    ).lower()
    for needle in ("token", "secret", "password", "api_key"):
        assert needle not in blob


def test_backfill_idempotent_second_run_updates_nothing(db):
    """Running the backfill twice must not double-update."""
    _ensure_default_org()
    _seed_one_lead()
    _run_backfill(apply=True)
    second = _run_backfill(apply=True)
    # On the second pass every business row already has an org. Audit
    # rows written by the first run are the only thing left missing
    # (the started/completed rows from run 1). The total should be
    # tiny, but business-row update count must be zero.
    assert second["passed"] is True
    # Every model row already had org assignments; no business model
    # should report an update on the second run.
    for row in second["models"]:
        if row["model"] in {
            "crm.Lead",
            "crm.Customer",
            "orders.Order",
            "orders.DiscountOfferLog",
            "payments.Payment",
            "shipments.Shipment",
            "calls.Call",
            "whatsapp.WhatsAppConsent",
            "whatsapp.WhatsAppConversation",
            "whatsapp.WhatsAppMessage",
            "whatsapp.WhatsAppLifecycleEvent",
            "whatsapp.WhatsAppHandoffToCall",
            "whatsapp.WhatsAppPilotCohortMember",
        }:
            assert row["updatedOrganization"] == 0, (
                f"{row['model']} re-updated on second pass"
            )


# ---------------------------------------------------------------------------
# Section D — coverage inspector
# ---------------------------------------------------------------------------


def test_inspect_coverage_reports_missing_then_present(db):
    _ensure_default_org()
    _seed_one_lead()
    _seed_one_customer()
    _seed_one_order()

    before = _run_inspect()
    assert before["defaultOrganizationExists"] is True
    assert before["defaultBranchExists"] is True
    assert before["globalTenantFilteringEnabled"] is False
    assert before["safeToStartPhase6C"] is False
    # Pre-backfill: business rows missing org.
    lead_row = next(r for r in before["models"] if r["model"] == "crm.Lead")
    assert lead_row["organizationCoveragePercent"] == 0.0
    assert (
        before["nextAction"]
        == "run_backfill_default_organization_data_apply"
    )

    _run_backfill(apply=True)
    after = _run_inspect()
    lead_row = next(r for r in after["models"] if r["model"] == "crm.Lead")
    assert lead_row["organizationCoveragePercent"] == 100.0
    assert lead_row["branchCoveragePercent"] == 100.0


def test_inspect_coverage_blocks_when_default_org_missing(db):
    # Don't seed anything — defaults are missing.
    report = _run_inspect()
    assert report["defaultOrganizationExists"] is False
    assert report["defaultBranchExists"] is False
    assert report["safeToStartPhase6C"] is False
    assert any(
        "Default organization is missing" in b for b in report["blockers"]
    )
    assert report["nextAction"] == "fix_backfill_blockers"


# ---------------------------------------------------------------------------
# Section E — data-coverage API endpoint
# ---------------------------------------------------------------------------


def test_data_coverage_endpoint_requires_auth(db, auth_client):
    _ensure_default_org()
    client = auth_client(None)
    res = client.get(reverse("saas-data-coverage"))
    assert res.status_code in (401, 403)


def test_data_coverage_endpoint_returns_shape_for_authenticated(
    db, admin_user, auth_client
):
    _ensure_default_org()
    _seed_one_lead()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-data-coverage"))
    assert res.status_code == 200
    body = res.json()
    assert body["defaultOrganizationExists"] is True
    assert body["globalTenantFilteringEnabled"] is False
    assert "models" in body
    assert "totals" in body
    # No tokens / secrets / phone numbers in the response.
    blob = json.dumps(body).lower()
    for needle in (
        "token",
        "secret",
        "password",
        "+919999900001",  # the seeded phone never appears in coverage
    ):
        assert needle not in blob


def test_data_coverage_endpoint_rejects_post(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.post(reverse("saas-data-coverage"), {})
    assert res.status_code == 405


# ---------------------------------------------------------------------------
# Section F — existing endpoints still pass
# ---------------------------------------------------------------------------


def test_existing_saas_current_organization_still_works(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-current-organization"))
    assert res.status_code == 200
    body = res.json()
    assert body["organization"]["code"] == "nirogidhara"
