"""Phase 6F — Per-Org Runtime Integration Routing Plan.

Read-only resolver layer that previews how a per-org runtime would
look without actually switching the live providers off env / config.
Strict invariants:

- Runtime providers in this phase still consume env / config.
  ``runtimeSource`` is always ``"env_config"``;
  ``perOrgRuntimeEnabled`` is always ``False``.
- Secret values are NEVER returned. The resolver checks presence only,
  via ``os.environ`` for ``ENV:`` refs and a planned-but-not-resolved
  status for ``VAULT:`` refs.
- No external provider is contacted. No DB write happens.
- Mask shape mirrors the existing Phase 6E
  :func:`apps.saas.integration_settings.mask_secret_refs` so the
  frontend can render either source the same way.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable

from .integration_settings import (
    EXPECTED_SECRET_REFS,
    PROVIDER_LABELS,
    _has_secret_ref_value,
    _secret_ref_keys,
    mask_secret_refs as _mask_secret_refs,
)
from .models import (
    Organization,
    OrganizationIntegrationSetting,
)


_ENV_REF_RE = re.compile(r"^ENV:[A-Z][A-Z0-9_]*$")
_VAULT_REF_RE = re.compile(r"^VAULT:[A-Za-z0-9._/\-]+$")


# Phase 6F — env keys we expect to find when previewing per-org runtime
# routing for each provider. These are the same env vars Phase 5 / 6E
# already document; the resolver checks PRESENCE only (never value).
_DEFAULT_PROVIDER_ENV_KEYS: dict[str, dict[str, str]] = {
    OrganizationIntegrationSetting.ProviderType.WHATSAPP_META: {
        "access_token": "META_WA_ACCESS_TOKEN",
        "phone_number_id": "META_WA_PHONE_NUMBER_ID",
        "business_account_id": "META_WA_BUSINESS_ACCOUNT_ID",
        "verify_token": "META_WA_VERIFY_TOKEN",
        "app_secret": "META_WA_APP_SECRET",
    },
    OrganizationIntegrationSetting.ProviderType.RAZORPAY: {
        "key_id": "RAZORPAY_KEY_ID",
        "key_secret": "RAZORPAY_KEY_SECRET",
    },
    OrganizationIntegrationSetting.ProviderType.PAYU: {
        "merchant_key": "PAYU_KEY",
        "salt": "PAYU_SECRET",
    },
    OrganizationIntegrationSetting.ProviderType.DELHIVERY: {
        "api_token": "DELHIVERY_API_TOKEN",
    },
    OrganizationIntegrationSetting.ProviderType.VAPI: {
        "api_key": "VAPI_API_KEY",
    },
    OrganizationIntegrationSetting.ProviderType.OPENAI: {
        "api_key": "OPENAI_API_KEY",
    },
}


# ---------------------------------------------------------------------------
# Secret ref helpers
# ---------------------------------------------------------------------------


def mask_secret_ref(ref: Any) -> str:
    """Public re-export of the Phase 6E masking shape (single ref)."""
    if isinstance(ref, str) and (
        ref.startswith("ENV:") or ref.startswith("VAULT:")
    ):
        return _mask_secret_refs(ref)
    return _mask_secret_refs("****" if ref else "")


def validate_secret_ref_format(ref: Any) -> dict[str, Any]:
    """Validate that ``ref`` is an ENV / VAULT-style reference.

    Returns a structured ``{"valid": bool, "scheme": str, "reason": str}``.
    Never raises.
    """
    if not isinstance(ref, str) or not ref:
        return {
            "valid": False,
            "scheme": "",
            "reason": "ref must be a non-empty string",
        }
    if _ENV_REF_RE.match(ref):
        return {"valid": True, "scheme": "env", "reason": ""}
    if _VAULT_REF_RE.match(ref):
        return {"valid": True, "scheme": "vault", "reason": ""}
    if ref.startswith("ENV:") or ref.startswith("VAULT:"):
        return {
            "valid": False,
            "scheme": "env" if ref.startswith("ENV:") else "vault",
            "reason": "ref body has unsupported characters",
        }
    return {
        "valid": False,
        "scheme": "",
        "reason": "ref must start with ENV: or VAULT:",
    }


def get_secret_ref_status(ref: Any) -> dict[str, Any]:
    """Return resolution status for a single secret reference.

    Shape:

        {
          "valid": bool,
          "source": "env" | "vault" | "unknown",
          "maskedRef": str,
          "present": bool,             # ENV: only — VAULT: stays None
          "canResolveAtRuntime": bool, # presence + valid format
          "reason": str,
        }

    Never returns the raw value. ``VAULT:`` references stay
    ``planned`` — Phase 6F does not contact a real vault.
    """
    validation = validate_secret_ref_format(ref)
    masked = mask_secret_ref(ref) if isinstance(ref, str) else ""
    if not validation["valid"]:
        return {
            "valid": False,
            "source": validation["scheme"] or "unknown",
            "maskedRef": masked,
            "present": False,
            "canResolveAtRuntime": False,
            "reason": validation["reason"],
        }
    scheme = validation["scheme"]
    if scheme == "env":
        env_key = ref[4:]
        present = bool(os.environ.get(env_key))
        return {
            "valid": True,
            "source": "env",
            "maskedRef": masked,
            "present": present,
            "canResolveAtRuntime": present,
            "reason": (
                ""
                if present
                else f"env var '{env_key}' is not set"
            ),
        }
    # VAULT: scheme — Phase 6F does not contact a real vault.
    return {
        "valid": True,
        "source": "vault",
        "maskedRef": masked,
        "present": None,
        "canResolveAtRuntime": False,
        "reason": "vault resolution is planned but not configured in Phase 6F",
    }


def resolve_secret_ref_preview(ref: Any) -> dict[str, Any]:
    """Public alias for :func:`get_secret_ref_status` so callers can
    use the verb that matches their intent (``resolve`` vs ``status``).
    The behaviour is identical — neither variant ever returns the raw
    secret value.
    """
    return get_secret_ref_status(ref)


# ---------------------------------------------------------------------------
# Per-org runtime preview
# ---------------------------------------------------------------------------


def get_org_provider_setting(
    org: Organization | None,
    provider_type: str,
) -> OrganizationIntegrationSetting | None:
    if org is None or not provider_type:
        return None
    return (
        OrganizationIntegrationSetting.objects.filter(
            organization=org,
            provider_type=provider_type,
        )
        .order_by("-is_active", "display_name", "id")
        .first()
    )


def get_runtime_provider_source(
    _org: Organization | None,
    _provider_type: str,
) -> str:
    """Phase 6F invariant: runtime always reads from env / config."""
    return "env_config"


def should_use_per_org_provider_runtime(
    _org: Organization | None,
    _provider_type: str,
) -> bool:
    """Phase 6F invariant: per-org runtime routing is OFF.

    Phase 6G will introduce a dry-run flag; Phase 6H+ will be the
    earliest a request can flip this on.
    """
    return False


def _expected_secret_keys(provider_type: str) -> tuple[str, ...]:
    return EXPECTED_SECRET_REFS.get(provider_type, ())


def _env_keys_for_provider(provider_type: str) -> dict[str, str]:
    return _DEFAULT_PROVIDER_ENV_KEYS.get(provider_type, {})


def _evaluate_secret_refs(
    secret_refs: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Walk the secret_refs dict and return per-key status + warnings.

    Returns ``({key: status}, [warnings])``. Status payload is the
    same shape as :func:`get_secret_ref_status`; warnings flag refs
    that have a bad format or cannot resolve at runtime.
    """
    if not isinstance(secret_refs, dict):
        return {}, []
    statuses: dict[str, Any] = {}
    warnings: list[str] = []
    for key, value in secret_refs.items():
        status = get_secret_ref_status(value)
        statuses[str(key)] = status
        if not status["valid"]:
            warnings.append(
                f"secret_ref '{key}' invalid: {status['reason']}"
            )
        elif status["source"] == "env" and not status["present"]:
            warnings.append(
                f"secret_ref '{key}' refers to a missing env var"
            )
    return statuses, warnings


def get_provider_runtime_preview(
    org: Organization | None,
    provider_type: str,
) -> dict[str, Any]:
    """Compute the per-org runtime preview for a single provider.

    The return shape is stable so the management command, the DRF API,
    and the SaaS Admin UI all consume the same payload.
    """
    label = PROVIDER_LABELS.get(provider_type, provider_type)
    setting = get_org_provider_setting(org, provider_type)
    expected_keys = _expected_secret_keys(provider_type)
    env_keys = _env_keys_for_provider(provider_type)

    # Env-config presence — what the live runtime currently reads.
    env_status: dict[str, dict[str, Any]] = {}
    config_present = True
    for friendly, env_var in env_keys.items():
        present = bool(os.environ.get(env_var))
        env_status[friendly] = {
            "envVar": env_var,
            "present": present,
        }
        if not present:
            config_present = False

    secret_refs_statuses: dict[str, Any] = {}
    secret_refs_warnings: list[str] = []
    setting_payload: dict[str, Any] | None = None
    setting_status = "missing"
    setting_active = False
    secret_refs_present = False
    missing_secret_keys: list[str] = list(expected_keys)
    if setting is not None:
        setting_status = setting.status
        setting_active = bool(setting.is_active)
        secret_refs = setting.secret_refs or {}
        secret_refs_present = _has_secret_ref_value(secret_refs)
        missing_secret_keys = sorted(
            set(expected_keys) - _secret_ref_keys(secret_refs)
        )
        secret_refs_statuses, secret_refs_warnings = _evaluate_secret_refs(
            secret_refs
        )
        setting_payload = {
            "id": setting.id,
            "providerType": setting.provider_type,
            "displayName": setting.display_name,
            "status": setting.status,
            "isActive": bool(setting.is_active),
            "validationStatus": setting.validation_status,
            "validationMessage": setting.validation_message,
            # Mask the secret_refs the same way the read API does.
            "secretRefs": _mask_secret_refs(secret_refs),
            "config": dict(setting.config or {}),
        }

    blockers: list[str] = []
    warnings: list[str] = []
    warnings.extend(secret_refs_warnings)
    if not config_present:
        warnings.append(
            "Some env-config keys are missing for this provider; the "
            "live runtime will degrade if the env vars are not set."
        )
    if setting is None:
        warnings.append(
            "No per-org integration setting configured. Runtime stays "
            "on env / config."
        )
    elif missing_secret_keys:
        warnings.append(
            "Missing secret reference(s) on the per-org setting: "
            + ", ".join(missing_secret_keys)
        )

    next_action = "keep_runtime_env_config"
    if setting is None or missing_secret_keys:
        next_action = "configure_org_integration_settings_before_runtime_routing"
    else:
        # Setting exists, refs all there — Phase 6G-eligible.
        next_action = (
            "ready_for_phase_6g_controlled_runtime_routing_dry_run"
        )

    return {
        "providerType": provider_type,
        "providerLabel": label,
        "integrationSettingExists": setting is not None,
        "settingStatus": setting_status,
        "isActive": setting_active,
        "runtimeSource": "env_config",
        "perOrgRuntimeEnabled": False,
        "secretRefsPresent": secret_refs_present,
        "secretRefsResolvablePreview": {
            "perRef": secret_refs_statuses,
            "anyMissingEnv": any(
                status.get("source") == "env" and not status.get("present")
                for status in secret_refs_statuses.values()
            ),
        },
        "missingSecretRefs": missing_secret_keys,
        "configPresent": config_present,
        "envKeyStatus": env_status,
        "expectedSecretRefKeys": list(expected_keys),
        "setting": setting_payload,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
    }


def get_all_provider_runtime_previews(
    org: Organization | None,
) -> dict[str, Any]:
    """Compose previews for every provider type the SaaS Admin lists.

    Adds a ``global`` summary that mirrors the existing readiness
    diagnostics so the operator sees ``runtimeUsesPerOrgSettings`` and
    a typed ``nextAction``.
    """
    providers = [
        get_provider_runtime_preview(org, provider_type)
        for provider_type in PROVIDER_LABELS
    ]

    safe_to_start_phase_6g = bool(providers) and all(
        provider["integrationSettingExists"]
        and not provider["missingSecretRefs"]
        for provider in providers
    )

    global_blockers: list[str] = []
    global_warnings: list[str] = []
    if org is None:
        global_blockers.append(
            "Default organization is missing — run "
            "ensure_default_organization first."
        )
    if not safe_to_start_phase_6g:
        global_warnings.append(
            "At least one provider has no per-org integration setting "
            "or is missing secret refs; Phase 6G dry-run is blocked "
            "until every provider is configured."
        )

    if global_blockers:
        next_action = "fix_runtime_routing_blockers"
    elif safe_to_start_phase_6g:
        next_action = (
            "ready_for_phase_6g_controlled_runtime_routing_dry_run"
        )
    else:
        next_action = (
            "configure_org_integration_settings_before_runtime_routing"
        )

    return {
        "organization": (
            {"id": org.id, "code": org.code, "name": org.name}
            if org is not None
            else None
        ),
        "runtimeUsesPerOrgSettings": False,
        "perOrgRuntimeEnabled": False,
        "providers": providers,
        "global": {
            "safeToStartPhase6G": safe_to_start_phase_6g,
            "blockers": global_blockers,
            "warnings": global_warnings,
            "nextAction": next_action,
        },
        "warnings": global_warnings,
        "blockers": global_blockers,
        "nextAction": next_action,
    }


__all__ = (
    "mask_secret_ref",
    "validate_secret_ref_format",
    "get_secret_ref_status",
    "resolve_secret_ref_preview",
    "get_org_provider_setting",
    "get_runtime_provider_source",
    "should_use_per_org_provider_runtime",
    "get_provider_runtime_preview",
    "get_all_provider_runtime_previews",
)
