"""Phase 6E SaaS admin overview selectors."""
from __future__ import annotations

from typing import Any

from django.conf import settings

from apps.audit.models import AuditEvent

from .coverage import compute_default_organization_coverage
from .integration_settings import (
    get_org_integration_readiness,
    get_org_integration_settings,
)
from .readiness import compute_org_scoped_api_readiness
from .selectors import (
    get_default_branch,
    get_default_organization,
    get_organization_feature_flags,
    get_organization_membership_summary,
)
from .write_readiness import compute_org_write_path_readiness


def _serialize_org(org) -> dict[str, Any] | None:
    if org is None:
        return None
    branch = get_default_branch()
    return {
        "id": org.id,
        "code": org.code,
        "name": org.name,
        "legalName": org.legal_name,
        "status": org.status,
        "timezone": org.timezone,
        "country": org.country,
        "userOrgRole": "",
        "createdAt": org.created_at.isoformat()
        if getattr(org, "created_at", None)
        else None,
        "defaultBranch": (
            {
                "id": branch.id,
                "code": branch.code,
                "name": branch.name,
                "status": branch.status,
            }
            if branch is not None
            else None
        ),
        "membershipSummary": get_organization_membership_summary(org),
        "featureFlags": get_organization_feature_flags(org),
        "integrationSettingsCount": len(get_org_integration_settings(org)),
    }


def _safety_locks() -> dict[str, Any]:
    auto_reply_enabled = bool(
        getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
    )
    return {
        "whatsappAutoReplyEnabled": auto_reply_enabled,
        "whatsappAutoReplyOff": not auto_reply_enabled,
        "limitedTestMode": bool(
            getattr(settings, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE", True)
        ),
        "campaignsLocked": True,
        "broadcastLocked": True,
        "callHandoffEnabled": bool(
            getattr(settings, "WHATSAPP_CALL_HANDOFF_ENABLED", False)
        ),
        "lifecycleAutomationEnabled": bool(
            getattr(settings, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED", False)
        ),
        "rescueDiscountEnabled": bool(
            getattr(settings, "WHATSAPP_RESCUE_DISCOUNT_ENABLED", False)
        ),
        "rtoRescueEnabled": bool(
            getattr(settings, "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED", False)
        ),
        "reorderDay20Enabled": bool(
            getattr(settings, "WHATSAPP_REORDER_DAY20_ENABLED", False)
        ),
        "runtimeUsesPerOrgSettings": False,
    }


def _recent_saas_audit_events(limit: int = 12) -> list[dict[str, Any]]:
    events = AuditEvent.objects.filter(kind__startswith="saas.").order_by(
        "-occurred_at"
    )[:limit]
    return [
        {
            "id": event.id,
            "kind": event.kind,
            "text": event.text,
            "tone": event.tone,
            "icon": event.icon,
            "createdAt": event.occurred_at.isoformat(),
            "organizationId": event.organization_id,
        }
        for event in events
    ]


def get_saas_admin_overview() -> dict[str, Any]:
    org = get_default_organization()
    coverage = compute_default_organization_coverage()
    org_scope_readiness = compute_org_scoped_api_readiness()
    write_path_readiness = compute_org_write_path_readiness()
    integration_readiness = get_org_integration_readiness(org)
    safety_locks = _safety_locks()

    blockers: list[str] = []
    warnings: list[str] = []
    blockers.extend(write_path_readiness.get("blockers", []))
    blockers.extend(org_scope_readiness.get("blockers", []))
    warnings.extend(write_path_readiness.get("warnings", []))
    warnings.extend(org_scope_readiness.get("warnings", []))
    warnings.extend(integration_readiness.get("warnings", []))

    lock_failures = [
        key
        for key in (
            "callHandoffEnabled",
            "lifecycleAutomationEnabled",
            "rescueDiscountEnabled",
            "rtoRescueEnabled",
            "reorderDay20Enabled",
        )
        if safety_locks[key]
    ]
    if safety_locks["whatsappAutoReplyEnabled"]:
        blockers.append("WhatsApp AI auto-reply is enabled; must remain OFF.")
    if lock_failures:
        blockers.append(
            "Automation lock(s) enabled: " + ", ".join(lock_failures)
        )

    safe_to_start_6f = (
        not blockers
        and bool(write_path_readiness.get("safeToStartPhase6F"))
        and bool(org_scope_readiness.get("safeToStartPhase6D", True))
    )
    return {
        "defaultOrganizationExists": coverage["defaultOrganizationExists"],
        "defaultBranchExists": coverage["defaultBranchExists"],
        "organization": _serialize_org(org),
        "orgScopeReadiness": org_scope_readiness,
        "writePathReadiness": write_path_readiness,
        "integrationReadiness": integration_readiness,
        "integrationSettings": get_org_integration_settings(org),
        "integrationSettingsCount": integration_readiness[
            "integrationSettingsCount"
        ],
        "providersConfigured": integration_readiness["providersConfigured"],
        "providersMissing": integration_readiness["providersMissing"],
        "secretRefsMissing": integration_readiness["secretRefsMissing"],
        "safetyLocks": safety_locks,
        "runtimeUsesPerOrgSettings": False,
        "auditTimeline": _recent_saas_audit_events(),
        "safeToStartPhase6F": safe_to_start_6f,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": (
            "phase_6f_per_org_runtime_integration_routing_plan"
            if safe_to_start_6f
            else "fix_saas_admin_readiness_blockers"
        ),
    }


__all__ = ("get_saas_admin_overview",)
