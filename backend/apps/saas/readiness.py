"""Phase 6C — Org-scoped API readiness diagnostic.

Single source of truth for ``inspect_org_scoped_api_readiness`` (CLI)
and ``GET /api/v1/saas/org-scope-readiness/`` (DRF). Read-only; no DB
mutations.
"""
from __future__ import annotations

from typing import Any

from .context import get_default_branch, get_default_organization
from .coverage import compute_default_organization_coverage


# Models the read APIs in Phase 6C explicitly scope. Order matters only
# for report readability.
_SCOPED_MODELS: tuple[str, ...] = (
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
    "audit.AuditEvent",
)


# Models intentionally NOT scoped this phase (system-level / shared
# config / webhook ingestion). Phase 6D / 6E will revisit the per-tenant
# story for the integration-credential ones.
_UNSCOPED_MODELS: tuple[str, ...] = (
    "crm.MetaLeadEvent",
    "whatsapp.WhatsAppConnection",
    "whatsapp.WhatsAppTemplate",
    "whatsapp.WhatsAppMessageAttachment",
    "whatsapp.WhatsAppMessageStatusEvent",
    "whatsapp.WhatsAppWebhookEvent",
    "whatsapp.WhatsAppSendLog",
    "whatsapp.WhatsAppInternalNote",
    "calls.ActiveCall",
    "calls.CallTranscriptLine",
    "calls.WebhookEvent",
    "payments.WebhookEvent",
    "shipments.WorkflowStep",
    "shipments.RescueAttempt",
)


# Read APIs that have org-aware querysets in Phase 6C. Strings only —
# we don't introspect the URLConf here because mock environments may
# not have every app loaded.
_SCOPED_APIS: tuple[str, ...] = (
    "GET /api/leads/",
    "GET /api/customers/",
    "GET /api/orders/",
    "GET /api/payments/",
    "GET /api/shipments/",
    "GET /api/calls/",
    "GET /api/whatsapp/inbox/",
    "GET /api/whatsapp/conversations/{id}/",
    "GET /api/whatsapp/conversations/{id}/messages/",
    "GET /api/whatsapp/lifecycle-events/",
    "GET /api/whatsapp/monitoring/overview/",
    "GET /api/whatsapp/monitoring/activity/",
    "GET /api/whatsapp/monitoring/cohort/",
    "GET /api/whatsapp/monitoring/audit/",
    "GET /api/whatsapp/monitoring/mutation-safety/",
    "GET /api/whatsapp/monitoring/unexpected-outbound/",
    "GET /api/v1/whatsapp/monitoring/overview/",
    "GET /api/v1/whatsapp/monitoring/pilot/",
    "GET /api/v1/saas/current-organization/",
    "GET /api/v1/saas/my-organizations/",
    "GET /api/v1/saas/feature-flags/",
    "GET /api/v1/saas/data-coverage/",
    "GET /api/v1/saas/org-scope-readiness/",
)


# Write APIs we haven't yet org-scoped. Phase 6D will tackle the create
# paths; Phase 6E will enforce non-nullable FKs once 100% coverage holds
# across deploys.
_UNSCOPED_APIS: tuple[str, ...] = (
    "POST /api/leads/",
    "POST /api/customers/",
    "POST /api/orders/",
    "POST /api/payments/",
    "POST /api/shipments/",
    "POST /api/calls/trigger/",
    "POST /api/whatsapp/conversations/{id}/run-ai/",
    "POST /api/whatsapp/conversations/{id}/handoff-to-call/",
    "POST /api/whatsapp/reorder/day20/run/",
)


def compute_org_scoped_api_readiness() -> dict[str, Any]:
    """Return the diagnostic payload."""
    coverage = compute_default_organization_coverage()
    org = get_default_organization()
    branch = get_default_branch()

    report: dict[str, Any] = {
        "defaultOrganizationExists": coverage["defaultOrganizationExists"],
        "defaultOrganizationCode": coverage["defaultOrganizationCode"],
        "defaultBranchExists": coverage["defaultBranchExists"],
        "defaultBranchCode": coverage["defaultBranchCode"],
        "organizationCoveragePercent": coverage["totals"][
            "organizationCoveragePercent"
        ],
        "branchCoveragePercent": coverage["totals"][
            "branchCoveragePercent"
        ],
        "scopedModels": list(_SCOPED_MODELS),
        "unscopedModels": list(_UNSCOPED_MODELS),
        "scopedApis": list(_SCOPED_APIS),
        "unscopedApis": list(_UNSCOPED_APIS),
        "auditAutoOrgContextEnabled": True,
        "globalTenantFilteringEnabled": False,
        "safeToStartPhase6D": False,
        "blockers": [],
        "warnings": [],
        "nextAction": "",
    }

    if not report["defaultOrganizationExists"]:
        report["blockers"].append(
            "Default organization is missing — run "
            "ensure_default_organization first."
        )
    if not report["defaultBranchExists"]:
        report["blockers"].append(
            "Default branch is missing — run "
            "ensure_default_organization first."
        )

    if report["organizationCoveragePercent"] < 99.5:
        report["warnings"].append(
            "Organization coverage is below 99.5%. "
            "Run backfill_default_organization_data --apply."
        )

    if report["organizationCoveragePercent"] >= 99.5 and (
        report["branchCoveragePercent"] >= 99.5
    ):
        report["safeToStartPhase6D"] = (
            org is not None
            and branch is not None
            and not report["blockers"]
        )

    if report["blockers"]:
        report["nextAction"] = "fix_org_scope_blockers"
    elif report["organizationCoveragePercent"] < 99.5:
        report["nextAction"] = "run_default_org_backfill_again"
    elif report["safeToStartPhase6D"]:
        report["nextAction"] = (
            "ready_for_phase_6d_write_path_org_assignment"
        )
    else:
        report["nextAction"] = "run_default_org_backfill_again"

    return report


__all__ = ("compute_org_scoped_api_readiness",)
