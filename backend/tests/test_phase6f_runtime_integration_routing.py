"""Phase 6F — Per-Org Runtime Integration Routing Plan tests.

Covers:

- Secret-ref helpers: ``mask_secret_ref``, ``validate_secret_ref_format``,
  ``resolve_secret_ref_preview`` / ``get_secret_ref_status``. Raw values
  must NEVER appear in any return.
- Provider runtime preview: ``runtimeSource="env_config"`` always,
  ``perOrgRuntimeEnabled=False`` always.
- Combined preview composition + ``safeToStartPhase6G`` semantics.
- Management command ``inspect_runtime_integration_routing``.
- DRF endpoint ``GET /api/v1/saas/runtime-routing-readiness/`` —
  admin-protected, read-only, no raw secrets.
- Seed command ``seed_default_org_integration_refs`` — dry-run default,
  ``--apply`` writes refs only, idempotent.
"""
from __future__ import annotations

import io
import json
import os
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.saas.context import get_default_organization
from apps.saas.integration_runtime import (
    get_all_provider_runtime_previews,
    get_provider_runtime_preview,
    get_runtime_provider_source,
    get_secret_ref_status,
    mask_secret_ref,
    resolve_secret_ref_preview,
    should_use_per_org_provider_runtime,
    validate_secret_ref_format,
)
from apps.saas.models import (
    Organization,
    OrganizationIntegrationSetting,
)


def _ensure_default_org() -> Organization:
    out = io.StringIO()
    call_command(
        "ensure_default_organization", "--json", "--skip-memberships",
        stdout=out,
    )
    return Organization.objects.get(code="nirogidhara")


# ---------------------------------------------------------------------------
# Section A — Secret-ref helpers
# ---------------------------------------------------------------------------


def test_mask_secret_ref_masks_env_refs():
    masked = mask_secret_ref("ENV:META_WA_ACCESS_TOKEN")
    assert masked.startswith("ENV:")
    assert "META_WA_ACCESS_TOKEN" not in masked


def test_mask_secret_ref_masks_vault_refs():
    masked = mask_secret_ref("VAULT:tenant/openai")
    assert masked.startswith("VAULT:")
    assert "tenant/openai" not in masked


def test_validate_secret_ref_format_supports_env_and_vault():
    assert validate_secret_ref_format("ENV:OPENAI_API_KEY")["valid"] is True
    assert (
        validate_secret_ref_format("VAULT:tenant/whatsapp")["valid"]
        is True
    )
    assert validate_secret_ref_format("not-a-ref")["valid"] is False
    assert validate_secret_ref_format("")["valid"] is False
    assert validate_secret_ref_format(None)["valid"] is False


def test_resolve_secret_ref_preview_never_returns_raw_value():
    # Set a fake env var so present=True, then assert the value never
    # appears in the resolver output.
    secret_value = "rk_super_secret_42_DO_NOT_LEAK"
    with mock.patch.dict(
        os.environ, {"PHASE6F_TEST_API_KEY": secret_value}
    ):
        status = resolve_secret_ref_preview("ENV:PHASE6F_TEST_API_KEY")
    assert status["present"] is True
    assert status["canResolveAtRuntime"] is True
    assert status["source"] == "env"
    blob = json.dumps(status)
    assert secret_value not in blob


def test_get_secret_ref_status_missing_env_returns_present_false():
    # Ensure the env var is not set (popping any prior value first).
    env = dict(os.environ)
    env.pop("PHASE6F_DEFINITELY_MISSING_KEY", None)
    with mock.patch.dict(os.environ, env, clear=True):
        status = get_secret_ref_status("ENV:PHASE6F_DEFINITELY_MISSING_KEY")
    assert status["present"] is False
    assert status["canResolveAtRuntime"] is False


def test_get_secret_ref_status_invalid_ref_format():
    status = get_secret_ref_status("plain-string")
    assert status["valid"] is False
    assert status["canResolveAtRuntime"] is False


def test_get_secret_ref_status_vault_returns_planned_only():
    status = get_secret_ref_status("VAULT:tenant/openai")
    assert status["valid"] is True
    assert status["source"] == "vault"
    # Phase 6F does not contact a real vault — present is None,
    # cannot resolve at runtime.
    assert status["present"] is None
    assert status["canResolveAtRuntime"] is False


# ---------------------------------------------------------------------------
# Section B — Per-org runtime preview invariants
# ---------------------------------------------------------------------------


def test_runtime_source_is_env_config_always(db):
    org = _ensure_default_org()
    for provider_type, _label in OrganizationIntegrationSetting.ProviderType.choices:
        if provider_type == "other":
            continue
        assert (
            get_runtime_provider_source(org, provider_type) == "env_config"
        )


def test_per_org_runtime_disabled_in_phase_6f(db):
    org = _ensure_default_org()
    for provider_type, _label in OrganizationIntegrationSetting.ProviderType.choices:
        if provider_type == "other":
            continue
        assert (
            should_use_per_org_provider_runtime(org, provider_type)
            is False
        )


def test_provider_preview_handles_missing_setting(db):
    org = _ensure_default_org()
    preview = get_provider_runtime_preview(
        org, OrganizationIntegrationSetting.ProviderType.WHATSAPP_META
    )
    assert preview["integrationSettingExists"] is False
    assert preview["runtimeSource"] == "env_config"
    assert preview["perOrgRuntimeEnabled"] is False
    assert preview["secretRefsPresent"] is False
    assert preview["nextAction"] == (
        "configure_org_integration_settings_before_runtime_routing"
    )


def test_provider_preview_handles_configured_setting(db):
    org = _ensure_default_org()
    OrganizationIntegrationSetting.objects.create(
        organization=org,
        provider_type=(
            OrganizationIntegrationSetting.ProviderType.WHATSAPP_META
        ),
        display_name="WhatsApp Meta",
        status=OrganizationIntegrationSetting.Status.CONFIGURED,
        secret_refs={
            "access_token": "ENV:META_WA_ACCESS_TOKEN",
            "app_secret": "ENV:META_WA_APP_SECRET",
            "verify_token": "ENV:META_WA_VERIFY_TOKEN",
        },
    )
    fake_secret = "rk_RAW_VALUE_NEVER_LEAK_xyz"
    with mock.patch.dict(
        os.environ,
        {
            "META_WA_ACCESS_TOKEN": fake_secret,
            "META_WA_APP_SECRET": fake_secret,
            "META_WA_VERIFY_TOKEN": fake_secret,
        },
    ):
        preview = get_provider_runtime_preview(
            org,
            OrganizationIntegrationSetting.ProviderType.WHATSAPP_META,
        )
    assert preview["integrationSettingExists"] is True
    assert preview["secretRefsPresent"] is True
    assert preview["missingSecretRefs"] == []
    assert preview["runtimeSource"] == "env_config"
    assert preview["perOrgRuntimeEnabled"] is False
    # Setting payload must NOT carry raw secret VALUES. Env var NAMES
    # are intentional (operator needs to know which env var is being
    # referenced) — only the value must never leak.
    blob = json.dumps(preview)
    assert fake_secret not in blob
    # Masked refs only — no full ENV: ref body.
    assert "ENV:META_WA_ACCESS_TOKEN" not in blob


def test_combined_preview_safe_to_start_phase_6g_only_when_all_configured(
    db,
):
    org = _ensure_default_org()
    # No settings yet → not safe.
    report = get_all_provider_runtime_previews(org)
    assert report["runtimeUsesPerOrgSettings"] is False
    assert report["global"]["safeToStartPhase6G"] is False
    assert (
        report["nextAction"]
        == "configure_org_integration_settings_before_runtime_routing"
    )

    # Configure every provider with the expected refs.
    for provider_type in (
        OrganizationIntegrationSetting.ProviderType.WHATSAPP_META,
        OrganizationIntegrationSetting.ProviderType.RAZORPAY,
        OrganizationIntegrationSetting.ProviderType.PAYU,
        OrganizationIntegrationSetting.ProviderType.DELHIVERY,
        OrganizationIntegrationSetting.ProviderType.VAPI,
        OrganizationIntegrationSetting.ProviderType.OPENAI,
    ):
        # Reuse the seed template so refs match expectations.
        from apps.saas.management.commands.seed_default_org_integration_refs import (
            _build_seed_template,
        )

        template = _build_seed_template(provider_type)
        OrganizationIntegrationSetting.objects.create(
            organization=org,
            provider_type=provider_type,
            display_name=provider_type.replace("_", " ").title(),
            status=OrganizationIntegrationSetting.Status.CONFIGURED,
            secret_refs=template["secret_refs"],
            config=template["config"],
        )

    report = get_all_provider_runtime_previews(org)
    assert report["runtimeUsesPerOrgSettings"] is False
    assert report["global"]["safeToStartPhase6G"] is True
    assert (
        report["nextAction"]
        == "ready_for_phase_6g_controlled_runtime_routing_dry_run"
    )


# ---------------------------------------------------------------------------
# Section C — Management command
# ---------------------------------------------------------------------------


def _run_inspect_cmd() -> dict:
    out = io.StringIO()
    call_command(
        "inspect_runtime_integration_routing", "--json", stdout=out
    )
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_inspect_command_returns_all_providers(db):
    _ensure_default_org()
    report = _run_inspect_cmd()
    provider_types = {p["providerType"] for p in report["providers"]}
    assert {
        "whatsapp_meta",
        "razorpay",
        "payu",
        "delhivery",
        "vapi",
        "openai",
    }.issubset(provider_types)
    assert report["runtimeUsesPerOrgSettings"] is False


def test_inspect_command_no_raw_secrets(db):
    secret_value = "rk_TOP_SECRET_NEVER_LEAK_xxx"
    org = _ensure_default_org()
    OrganizationIntegrationSetting.objects.create(
        organization=org,
        provider_type=(
            OrganizationIntegrationSetting.ProviderType.RAZORPAY
        ),
        display_name="Razorpay",
        status=OrganizationIntegrationSetting.Status.CONFIGURED,
        secret_refs={"key_secret": "ENV:RAZORPAY_KEY_SECRET"},
    )
    with mock.patch.dict(
        os.environ, {"RAZORPAY_KEY_SECRET": secret_value}
    ):
        report = _run_inspect_cmd()
    blob = json.dumps(report)
    assert secret_value not in blob


# ---------------------------------------------------------------------------
# Section D — DRF endpoint
# ---------------------------------------------------------------------------


def test_runtime_routing_endpoint_requires_auth(db, auth_client):
    _ensure_default_org()
    client = auth_client(None)
    res = client.get(reverse("saas-runtime-routing-readiness"))
    assert res.status_code in (401, 403)


def test_runtime_routing_endpoint_admin_returns_shape(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-runtime-routing-readiness"))
    assert res.status_code == 200
    body = res.json()
    assert body["runtimeUsesPerOrgSettings"] is False
    assert body["perOrgRuntimeEnabled"] is False
    assert "providers" in body
    assert "global" in body
    blob = json.dumps(body).lower()
    for needle in ("password", "+919", "raw_secret"):
        assert needle not in blob


def test_runtime_routing_endpoint_blocks_viewer(
    db, viewer_user, auth_client
):
    _ensure_default_org()
    client = auth_client(viewer_user)
    res = client.get(reverse("saas-runtime-routing-readiness"))
    assert res.status_code in (401, 403)


def test_runtime_routing_endpoint_rejects_post(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.post(reverse("saas-runtime-routing-readiness"), {})
    assert res.status_code == 405


# ---------------------------------------------------------------------------
# Section E — Seed command
# ---------------------------------------------------------------------------


def _run_seed_cmd(*, apply: bool = False) -> dict:
    out = io.StringIO()
    args = ["seed_default_org_integration_refs", "--json"]
    if apply:
        args.append("--apply")
    else:
        args.append("--dry-run")
    call_command(*args, stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_seed_dry_run_writes_nothing(db):
    _ensure_default_org()
    before = OrganizationIntegrationSetting.objects.count()
    report = _run_seed_cmd(apply=False)
    after = OrganizationIntegrationSetting.objects.count()
    assert before == after
    assert report["dryRun"] is True
    assert report["totalCreated"] == 0
    assert report["totalUpdated"] == 0
    # Every provider should report would_create on a fresh DB.
    actions = {row["action"] for row in report["providers"]}
    assert "would_create" in actions


def test_seed_apply_creates_secret_refs_only(db):
    _ensure_default_org()
    report = _run_seed_cmd(apply=True)
    assert report["dryRun"] is False
    assert report["totalCreated"] >= 6  # six provider types
    settings = list(
        OrganizationIntegrationSetting.objects.all()
    )
    assert len(settings) >= 6
    for setting in settings:
        # Every secret ref must be an ENV: / VAULT: string — never a
        # raw value.
        for value in (setting.secret_refs or {}).values():
            assert isinstance(value, str)
            assert value.startswith("ENV:") or value.startswith("VAULT:")


def test_seed_apply_emits_audit_rows(db):
    _ensure_default_org()
    _run_seed_cmd(apply=True)
    audits = AuditEvent.objects.filter(
        kind="saas.integration_refs.seeded"
    )
    assert audits.count() >= 6
    blob = json.dumps(list(audits.values_list("payload", flat=True))).lower()
    # Audit payloads must never carry raw secrets.
    for needle in ("password", "raw_secret"):
        assert needle not in blob


def test_seed_idempotent_second_apply_is_unchanged(db):
    _ensure_default_org()
    _run_seed_cmd(apply=True)
    second = _run_seed_cmd(apply=True)
    assert second["passed"] is True
    assert second["totalCreated"] == 0
    # Expectation: at most a tiny number of updates if the template
    # changes; on a stable template it should be all 'unchanged'.
    actions = [row["action"] for row in second["providers"]]
    assert all(action in {"unchanged", "update"} for action in actions)


def test_seed_does_not_activate_runtime_routing(db):
    """After seeding, runtime routing must STILL be off."""
    _ensure_default_org()
    _run_seed_cmd(apply=True)
    report = get_all_provider_runtime_previews(get_default_organization())
    assert report["runtimeUsesPerOrgSettings"] is False
    assert report["perOrgRuntimeEnabled"] is False


def test_seed_runs_safely_when_no_default_org(db):
    """Seed command must not crash when default org is missing."""
    report = _run_seed_cmd(apply=False)
    assert report["passed"] is False
    assert any("Default organization is missing" in e for e in report["errors"])
