"""Phase 6E integration-setting selectors and secret masking.

Runtime providers still use env/config in this phase. These helpers expose
only readiness metadata for future per-org routing.
"""
from __future__ import annotations

from typing import Any

from .models import Organization, OrganizationIntegrationSetting


PROVIDER_LABELS: dict[str, str] = {
    OrganizationIntegrationSetting.ProviderType.WHATSAPP_META: "WhatsApp Meta",
    OrganizationIntegrationSetting.ProviderType.RAZORPAY: "Razorpay",
    OrganizationIntegrationSetting.ProviderType.PAYU: "PayU",
    OrganizationIntegrationSetting.ProviderType.DELHIVERY: "Delhivery",
    OrganizationIntegrationSetting.ProviderType.VAPI: "Vapi",
    OrganizationIntegrationSetting.ProviderType.OPENAI: "OpenAI",
}

EXPECTED_SECRET_REFS: dict[str, tuple[str, ...]] = {
    OrganizationIntegrationSetting.ProviderType.WHATSAPP_META: (
        "access_token",
        "app_secret",
        "verify_token",
    ),
    OrganizationIntegrationSetting.ProviderType.RAZORPAY: ("key_secret",),
    OrganizationIntegrationSetting.ProviderType.PAYU: ("merchant_key", "salt"),
    OrganizationIntegrationSetting.ProviderType.DELHIVERY: ("api_token",),
    OrganizationIntegrationSetting.ProviderType.VAPI: ("api_key",),
    OrganizationIntegrationSetting.ProviderType.OPENAI: ("api_key",),
}


def _mask_secret_ref(value: str) -> str:
    if not value:
        return ""
    if value.startswith("ENV:"):
        body = value[4:]
        if len(body) <= 8:
            return "ENV:****"
        return f"ENV:{body[:3]}***{body[-4:]}"
    if value.startswith("VAULT:"):
        body = value[6:]
        if len(body) <= 8:
            return "VAULT:****"
        return f"VAULT:{body[:4]}***{body[-4:]}"
    return "****"


def mask_secret_refs(secret_refs: Any) -> Any:
    """Return a structure with masked refs only; raw values never pass."""
    if isinstance(secret_refs, dict):
        return {
            str(key): mask_secret_refs(value)
            for key, value in secret_refs.items()
        }
    if isinstance(secret_refs, list):
        return [mask_secret_refs(value) for value in secret_refs]
    if isinstance(secret_refs, str):
        return _mask_secret_ref(secret_refs)
    if secret_refs in (None, "", {}, []):
        return secret_refs
    return "****"


def _has_secret_ref_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("ENV:") or value.startswith("VAULT:")
    if isinstance(value, dict):
        return any(_has_secret_ref_value(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_secret_ref_value(v) for v in value)
    return False


def _secret_ref_keys(secret_refs: Any) -> set[str]:
    if not isinstance(secret_refs, dict):
        return set()
    return {
        str(key)
        for key, value in secret_refs.items()
        if _has_secret_ref_value(value)
    }


def serialize_integration_setting(
    setting: OrganizationIntegrationSetting,
) -> dict[str, Any]:
    secret_refs = setting.secret_refs or {}
    return {
        "id": setting.id,
        "organizationId": setting.organization_id,
        "organizationCode": setting.organization.code,
        "providerType": setting.provider_type,
        "providerLabel": PROVIDER_LABELS.get(
            setting.provider_type,
            setting.provider_type,
        ),
        "status": setting.status,
        "displayName": setting.display_name,
        "config": dict(setting.config or {}),
        "secretRefs": mask_secret_refs(secret_refs),
        "secretRefsPresent": _has_secret_ref_value(secret_refs),
        "secretRefKeys": sorted(_secret_ref_keys(secret_refs)),
        "isActive": bool(setting.is_active),
        "lastValidatedAt": (
            setting.last_validated_at.isoformat()
            if setting.last_validated_at
            else None
        ),
        "validationStatus": setting.validation_status,
        "validationMessage": setting.validation_message,
        "metadata": dict(setting.metadata or {}),
        "runtimeEnabled": False,
        "runtimeUsesPerOrgSettings": False,
        "createdAt": setting.created_at.isoformat(),
        "updatedAt": setting.updated_at.isoformat(),
    }


def get_org_integration_settings(
    org: Organization | None,
) -> list[dict[str, Any]]:
    if org is None:
        return []
    qs = OrganizationIntegrationSetting.objects.filter(
        organization=org
    ).order_by("provider_type", "display_name")
    return [serialize_integration_setting(setting) for setting in qs]


def get_provider_readiness(
    org: Organization | None,
    provider_type: str,
) -> dict[str, Any]:
    expected_refs = set(EXPECTED_SECRET_REFS.get(provider_type, ()))
    setting = None
    if org is not None:
        setting = (
            OrganizationIntegrationSetting.objects.filter(
                organization=org,
                provider_type=provider_type,
            )
            .order_by("-is_active", "display_name", "id")
            .first()
        )

    warnings: list[str] = []
    missing_refs = sorted(expected_refs)
    serialized = None
    status = "missing"
    validation_status = "not_checked"
    secret_refs_present = False

    if setting is not None:
        serialized = serialize_integration_setting(setting)
        status = setting.status
        validation_status = setting.validation_status
        present_keys = _secret_ref_keys(setting.secret_refs or {})
        missing_refs = sorted(expected_refs - present_keys)
        secret_refs_present = bool(present_keys)
        if missing_refs:
            warnings.append(
                "Missing secret reference(s): " + ", ".join(missing_refs)
            )
    else:
        warnings.append("No per-org integration setting configured.")

    configured = setting is not None and status in {
        OrganizationIntegrationSetting.Status.CONFIGURED,
        OrganizationIntegrationSetting.Status.ACTIVE,
    }
    return {
        "providerType": provider_type,
        "providerLabel": PROVIDER_LABELS.get(provider_type, provider_type),
        "status": status,
        "configured": configured,
        "isActive": bool(setting.is_active) if setting is not None else False,
        "secretRefsPresent": secret_refs_present,
        "missingSecretRefs": missing_refs,
        "validationStatus": validation_status,
        "validationMessage": (
            setting.validation_message if setting is not None else ""
        ),
        "runtimeEnabled": False,
        "runtimeUsesPerOrgSettings": False,
        "setting": serialized,
        "warnings": warnings,
        "nextAction": (
            "configure_secret_refs_before_phase_6f"
            if missing_refs
            else "ready_for_phase_6f_routing_plan"
        ),
    }


def get_org_integration_readiness(
    org: Organization | None,
) -> dict[str, Any]:
    providers = [
        get_provider_readiness(org, provider_type)
        for provider_type in PROVIDER_LABELS
    ]
    configured = [
        provider["providerType"]
        for provider in providers
        if provider["configured"]
    ]
    missing = [
        provider["providerType"]
        for provider in providers
        if not provider["configured"]
    ]
    secret_refs_missing = [
        provider["providerType"]
        for provider in providers
        if provider["missingSecretRefs"]
    ]
    return {
        "organization": (
            {"id": org.id, "code": org.code, "name": org.name}
            if org is not None
            else None
        ),
        "providers": providers,
        "providersConfigured": configured,
        "providersMissing": missing,
        "secretRefsMissing": secret_refs_missing,
        "integrationSettingsCount": (
            OrganizationIntegrationSetting.objects.filter(
                organization=org
            ).count()
            if org is not None
            else 0
        ),
        "runtimeUsesPerOrgSettings": False,
        "safeToStartPhase6F": True,
        "warnings": [
            "Per-org provider routing is deferred; runtime still uses env/config."
        ],
        "nextAction": "phase_6f_per_org_runtime_integration_routing_plan",
    }


__all__ = (
    "EXPECTED_SECRET_REFS",
    "PROVIDER_LABELS",
    "get_org_integration_settings",
    "get_org_integration_readiness",
    "get_provider_readiness",
    "mask_secret_refs",
    "serialize_integration_setting",
)
