"""Phase 6B — read-only default-org coverage selector.

Single source of truth for the per-model ``organization`` / ``branch``
coverage report. Consumed by:

- ``inspect_default_organization_coverage`` management command (CLI).
- ``GET /api/v1/saas/data-coverage/`` DRF endpoint.

LOCKED rules:

- Strictly read-only — no DB writes, no audit rows, no external calls.
- Shape is stable: callers can pin tests against
  :func:`compute_default_organization_coverage`.
- ``globalTenantFilteringEnabled`` is hard-coded ``False`` for the
  whole Phase 6B window. Phase 6C flips it to ``True`` once the
  middleware lands and the per-tenant queryset filtering is wired.
"""
from __future__ import annotations

from typing import Any

from django.apps import apps as django_apps

from .selectors import (
    DEFAULT_BRANCH_CODE,
    DEFAULT_ORGANIZATION_CODE,
    get_default_branch,
    get_default_organization,
)


# Same target list as the backfill command. Order matters only for
# the report's readability.
_TARGETS: tuple[tuple[str, str, bool], ...] = (
    ("crm.Lead", "crm.Lead", True),
    ("crm.Customer", "crm.Customer", True),
    ("orders.Order", "orders.Order", True),
    ("orders.DiscountOfferLog", "orders.DiscountOfferLog", False),
    ("payments.Payment", "payments.Payment", True),
    ("shipments.Shipment", "shipments.Shipment", True),
    ("calls.Call", "calls.Call", True),
    ("whatsapp.WhatsAppConsent", "whatsapp.WhatsAppConsent", False),
    ("whatsapp.WhatsAppConversation", "whatsapp.WhatsAppConversation", True),
    ("whatsapp.WhatsAppMessage", "whatsapp.WhatsAppMessage", False),
    (
        "whatsapp.WhatsAppLifecycleEvent",
        "whatsapp.WhatsAppLifecycleEvent",
        False,
    ),
    (
        "whatsapp.WhatsAppHandoffToCall",
        "whatsapp.WhatsAppHandoffToCall",
        False,
    ),
    (
        "whatsapp.WhatsAppPilotCohortMember",
        "whatsapp.WhatsAppPilotCohortMember",
        False,
    ),
    ("audit.AuditEvent", "audit.AuditEvent", False),
)


def _resolve_model(label: str):
    app_label, model_name = label.split(".", 1)
    return django_apps.get_model(app_label, model_name)


def _percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 100.0
    return round((numerator / denominator) * 100.0, 2)


def compute_default_organization_coverage() -> dict[str, Any]:
    """Return the full read-only coverage report.

    Shape:

    .. code-block:: text

        {
          "defaultOrganizationExists": bool,
          "defaultOrganizationCode": "nirogidhara",
          "defaultBranchExists": bool,
          "defaultBranchCode": "main",
          "globalTenantFilteringEnabled": False,    # Phase 6C flips this
          "safeToStartPhase6C": bool,
          "models": [
            {
              "model": "crm.Lead",
              "totalRows": int,
              "withOrganization": int,
              "withoutOrganization": int,
              "organizationCoveragePercent": float,
              "hasBranchField": bool,
              "withBranch": int,
              "withoutBranch": int,
              "branchCoveragePercent": float,
            },
            ...
          ],
          "totals": {
            "totalRows": int,
            "totalWithOrganization": int,
            "totalWithoutOrganization": int,
            "totalWithBranch": int,
            "totalWithoutBranch": int,
            "organizationCoveragePercent": float,
            "branchCoveragePercent": float,
          },
          "blockers": [str, ...],
          "warnings": [str, ...],
          "nextAction": str,
        }
    """
    org = get_default_organization()
    branch = get_default_branch()

    report: dict[str, Any] = {
        "defaultOrganizationExists": org is not None,
        "defaultOrganizationCode": DEFAULT_ORGANIZATION_CODE,
        "defaultBranchExists": branch is not None,
        "defaultBranchCode": DEFAULT_BRANCH_CODE,
        "globalTenantFilteringEnabled": False,
        "safeToStartPhase6C": False,
        "models": [],
        "totals": {
            "totalRows": 0,
            "totalWithOrganization": 0,
            "totalWithoutOrganization": 0,
            "totalWithBranch": 0,
            "totalWithoutBranch": 0,
            "organizationCoveragePercent": 0.0,
            "branchCoveragePercent": 0.0,
        },
        "blockers": [],
        "warnings": [],
        "nextAction": "",
    }

    if org is None:
        report["blockers"].append(
            "Default organization is missing — run "
            "ensure_default_organization first."
        )
    if branch is None:
        report["blockers"].append(
            "Default branch is missing — run "
            "ensure_default_organization first."
        )

    branch_eligible_total = 0
    for label, model_path, has_branch in _TARGETS:
        try:
            model = _resolve_model(model_path)
        except LookupError:
            report["warnings"].append(f"{label}: model not found")
            continue

        qs = model.objects.all()
        total = qs.count()
        with_org = qs.exclude(organization__isnull=True).count()
        without_org = total - with_org
        org_pct = _percent(with_org, total)

        with_branch = 0
        without_branch = 0
        branch_pct = 100.0
        if has_branch:
            with_branch = qs.exclude(branch__isnull=True).count()
            without_branch = total - with_branch
            branch_pct = _percent(with_branch, total)

        row = {
            "model": label,
            "totalRows": total,
            "withOrganization": with_org,
            "withoutOrganization": without_org,
            "organizationCoveragePercent": org_pct,
            "hasBranchField": has_branch,
            "withBranch": with_branch,
            "withoutBranch": without_branch,
            "branchCoveragePercent": branch_pct,
        }
        report["models"].append(row)
        report["totals"]["totalRows"] += total
        report["totals"]["totalWithOrganization"] += with_org
        report["totals"]["totalWithoutOrganization"] += without_org
        if has_branch:
            branch_eligible_total += total
            report["totals"]["totalWithBranch"] += with_branch
            report["totals"]["totalWithoutBranch"] += without_branch

    report["totals"]["organizationCoveragePercent"] = _percent(
        report["totals"]["totalWithOrganization"],
        report["totals"]["totalRows"],
    )
    report["totals"]["branchCoveragePercent"] = _percent(
        report["totals"]["totalWithBranch"], branch_eligible_total
    )

    has_missing = (
        report["totals"]["totalWithoutOrganization"] > 0
        or report["totals"]["totalWithoutBranch"] > 0
    )
    report["safeToStartPhase6C"] = (
        org is not None
        and branch is not None
        and not has_missing
        and not report["blockers"]
    )

    if report["blockers"]:
        report["nextAction"] = "fix_backfill_blockers"
    elif has_missing:
        report["nextAction"] = (
            "run_backfill_default_organization_data_apply"
        )
    else:
        report["nextAction"] = (
            "ready_for_phase_6c_org_scoped_api_filtering_plan"
        )

    return report


__all__ = ("compute_default_organization_coverage",)
