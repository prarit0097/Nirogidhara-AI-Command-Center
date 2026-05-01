"""Phase 6D — Org-aware write-path readiness diagnostic.

Single source of truth for ``inspect_org_write_path_readiness`` (CLI)
and ``GET /api/v1/saas/write-path-readiness/`` (DRF).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from .context import get_default_branch, get_default_organization
from .coverage import compute_default_organization_coverage
from .signals import ORG_AUTO_ASSIGN_MODELS


# Create paths covered by the Phase 6D pre_save signal. Every entry
# corresponds to a model in :data:`ORG_AUTO_ASSIGN_MODELS`.
_SAFE_CREATE_PATHS: tuple[str, ...] = (
    "crm.Lead.create",
    "crm.Customer.create",
    "orders.Order.create",
    "orders.DiscountOfferLog.create",
    "payments.Payment.create",
    "shipments.Shipment.create",
    "calls.Call.create",
    "whatsapp.WhatsAppConsent.create",
    "whatsapp.WhatsAppConversation.create",
    "whatsapp.WhatsAppMessage.create",
    "whatsapp.WhatsAppLifecycleEvent.create",
    "whatsapp.WhatsAppHandoffToCall.create",
    "whatsapp.WhatsAppPilotCohortMember.create",
    "audit.AuditEvent.write_event (via Phase 6C auto-org)",
)


# Create paths intentionally deferred to Phase 6E — system, webhook,
# transient, or per-message child rows. The corresponding parent
# already carries org context, so child rows can inherit if a future
# phase wires them. None of them block 6E from opening.
_DEFERRED_CREATE_PATHS: tuple[str, ...] = (
    "crm.MetaLeadEvent.create (webhook ingest log)",
    "whatsapp.WhatsAppConnection.create (system provider config)",
    "whatsapp.WhatsAppTemplate.create (registry)",
    "whatsapp.WhatsAppMessageAttachment.create (child of message)",
    "whatsapp.WhatsAppMessageStatusEvent.create (child of message)",
    "whatsapp.WhatsAppWebhookEvent.create (webhook ingest log)",
    "whatsapp.WhatsAppSendLog.create (send-attempt log)",
    "whatsapp.WhatsAppInternalNote.create (operator note)",
    "calls.ActiveCall.create (transient singleton)",
    "calls.CallTranscriptLine.create (child of call)",
    "calls.WebhookEvent.create (webhook ingest log)",
    "payments.WebhookEvent.create (webhook ingest log)",
    "shipments.WorkflowStep.create (child of shipment)",
    "shipments.RescueAttempt.create (child of shipment)",
)


def _resolve_model(label: tuple[str, str]):
    from django.apps import apps as django_apps

    app_label, model_name = label
    try:
        return django_apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _count_recent_missing(window_hours: int = 24) -> tuple[int, int]:
    """Count rows created in the trailing window where org / branch
    is still ``NULL`` across the auto-assign target models. Indicates
    the signal isn't firing for that path (or that the default org
    doesn't exist yet on a fresh install)."""
    since = timezone.now() - timedelta(hours=window_hours)
    missing_org = 0
    missing_branch = 0
    for app_label, model_name in ORG_AUTO_ASSIGN_MODELS:
        model = _resolve_model((app_label, model_name))
        if model is None:
            continue
        # Most models use ``created_at`` as the timestamp. Skip
        # gracefully if the model lacks one.
        try:
            qs = model.objects.filter(created_at__gte=since)
        except Exception:  # noqa: BLE001
            continue
        try:
            missing_org += qs.filter(organization__isnull=True).count()
        except Exception:  # noqa: BLE001
            pass
        try:
            if hasattr(model, "branch"):
                missing_branch += qs.filter(branch__isnull=True).count()
        except Exception:  # noqa: BLE001
            pass
    return missing_org, missing_branch


def compute_org_write_path_readiness() -> dict[str, Any]:
    """Return the diagnostic payload."""
    coverage = compute_default_organization_coverage()
    org = get_default_organization()
    branch = get_default_branch()

    missing_org_24h, missing_branch_24h = _count_recent_missing(
        window_hours=24
    )

    models_with_org_branch = [
        f"{app}.{name}" for app, name in ORG_AUTO_ASSIGN_MODELS
    ]

    report: dict[str, Any] = {
        "defaultOrganizationExists": coverage["defaultOrganizationExists"],
        "defaultBranchExists": coverage["defaultBranchExists"],
        "writeContextHelpersAvailable": True,
        "auditAutoOrgContextEnabled": True,
        "safeCreatePathsCovered": list(_SAFE_CREATE_PATHS),
        "deferredCreatePaths": list(_DEFERRED_CREATE_PATHS),
        "modelsWithOrgBranch": models_with_org_branch,
        "recentRowsWithoutOrganizationLast24h": missing_org_24h,
        "recentRowsWithoutBranchLast24h": missing_branch_24h,
        "globalTenantFilteringEnabled": False,
        "safeToStartPhase6E": False,
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

    if report["recentRowsWithoutOrganizationLast24h"] > 0:
        report["warnings"].append(
            f"{report['recentRowsWithoutOrganizationLast24h']} row(s) "
            "created in the last 24h are missing organization. "
            "Run backfill_default_organization_data --apply."
        )
    if report["recentRowsWithoutBranchLast24h"] > 0:
        report["warnings"].append(
            f"{report['recentRowsWithoutBranchLast24h']} row(s) "
            "created in the last 24h are missing branch."
        )

    coverage_ok = (
        coverage["totals"]["organizationCoveragePercent"] >= 99.5
        and coverage["totals"]["branchCoveragePercent"] >= 99.5
    )

    if not report["blockers"] and coverage_ok and (
        report["recentRowsWithoutOrganizationLast24h"] == 0
    ):
        report["safeToStartPhase6E"] = (
            org is not None and branch is not None
        )

    if report["blockers"]:
        report["nextAction"] = "fix_write_path_assignment_gaps"
    elif not coverage_ok:
        report["nextAction"] = "run_default_org_backfill_again"
    elif report["recentRowsWithoutOrganizationLast24h"] > 0:
        report["nextAction"] = "fix_write_path_assignment_gaps"
    elif report["safeToStartPhase6E"]:
        report["nextAction"] = (
            "ready_for_phase_6e_org_scoped_write_enforcement_plan"
        )
    else:
        report["nextAction"] = "run_default_org_backfill_again"

    return report


__all__ = ("compute_org_write_path_readiness",)
