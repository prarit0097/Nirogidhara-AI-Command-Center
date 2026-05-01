"""Phase 6E - SaaS admin and integration settings tests."""
from __future__ import annotations

import io
import json

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.saas.integration_settings import (
    get_org_integration_readiness,
    mask_secret_refs,
    serialize_integration_setting,
)
from apps.saas.models import (
    Organization,
    OrganizationIntegrationSetting,
    OrganizationMembership,
)
from apps.saas.write_context import (
    OrgWriteAccessError,
    validate_org_write_access,
)
from apps.saas.write_readiness import compute_org_write_path_readiness


def _ensure_default_org() -> Organization:
    out = io.StringIO()
    call_command(
        "ensure_default_organization",
        "--json",
        "--skip-memberships",
        stdout=out,
    )
    return Organization.objects.get(code="nirogidhara")


def _create_other_org() -> Organization:
    return Organization.objects.create(
        code="other-phase6e",
        name="Other Phase 6E",
        legal_name="Other Phase 6E",
        status=Organization.Status.ACTIVE,
    )


def test_organization_integration_setting_model_creation(db):
    org = _ensure_default_org()
    setting = OrganizationIntegrationSetting.objects.create(
        organization=org,
        provider_type=OrganizationIntegrationSetting.ProviderType.OPENAI,
        status=OrganizationIntegrationSetting.Status.CONFIGURED,
        display_name="Default OpenAI",
        config={"model": "gpt-safe"},
        secret_refs={"api_key": "ENV:OPENAI_API_KEY"},
        validation_status=(
            OrganizationIntegrationSetting.ValidationStatus.NOT_CHECKED
        ),
    )
    assert setting.id is not None
    assert setting.organization_id == org.id


def test_raw_secret_refs_are_rejected(db):
    org = _ensure_default_org()
    with pytest.raises(ValidationError):
        OrganizationIntegrationSetting.objects.create(
            organization=org,
            provider_type=OrganizationIntegrationSetting.ProviderType.OPENAI,
            secret_refs={"api_key": "sk-raw-secret"},
        )


def test_sensitive_config_keys_are_rejected(db):
    org = _ensure_default_org()
    with pytest.raises(ValidationError):
        OrganizationIntegrationSetting.objects.create(
            organization=org,
            provider_type=OrganizationIntegrationSetting.ProviderType.RAZORPAY,
            config={"key_secret": "raw"},
            secret_refs={"key_secret": "ENV:RAZORPAY_KEY_SECRET"},
        )


def test_secret_refs_are_masked_in_serializer(db):
    org = _ensure_default_org()
    setting = OrganizationIntegrationSetting.objects.create(
        organization=org,
        provider_type=OrganizationIntegrationSetting.ProviderType.WHATSAPP_META,
        status=OrganizationIntegrationSetting.Status.CONFIGURED,
        secret_refs={
            "access_token": "ENV:META_WA_ACCESS_TOKEN",
            "app_secret": "VAULT:whatsapp/meta/app_secret",
        },
    )
    payload = serialize_integration_setting(setting)
    blob = json.dumps(payload)
    assert "META_WA_ACCESS_TOKEN" not in blob
    assert "whatsapp/meta/app_secret" not in blob
    assert payload["secretRefsPresent"] is True
    assert mask_secret_refs({"x": "ENV:OPENAI_API_KEY"})["x"].startswith(
        "ENV:OPE***"
    )


def test_integration_readiness_reports_missing_providers(db):
    org = _ensure_default_org()
    readiness = get_org_integration_readiness(org)
    assert "whatsapp_meta" in readiness["providersMissing"]
    assert readiness["runtimeUsesPerOrgSettings"] is False


def test_integration_readiness_reports_configured_provider(db):
    org = _ensure_default_org()
    OrganizationIntegrationSetting.objects.create(
        organization=org,
        provider_type=OrganizationIntegrationSetting.ProviderType.DELHIVERY,
        status=OrganizationIntegrationSetting.Status.CONFIGURED,
        secret_refs={"api_token": "ENV:DELHIVERY_API_TOKEN"},
    )
    readiness = get_org_integration_readiness(org)
    assert "delhivery" in readiness["providersConfigured"]
    delhivery = next(
        p for p in readiness["providers"] if p["providerType"] == "delhivery"
    )
    assert delhivery["secretRefsPresent"] is True
    assert delhivery["missingSecretRefs"] == []


def test_saas_admin_overview_api_auth_protected(db, auth_client):
    _ensure_default_org()
    res = auth_client(None).get(reverse("saas-admin-overview"))
    assert res.status_code in (401, 403)


def test_integration_settings_api_auth_protected(db, auth_client):
    _ensure_default_org()
    res = auth_client(None).get(reverse("saas-admin-integration-settings"))
    assert res.status_code in (401, 403)


def test_admin_mutation_audits_integration_setting(
    db,
    admin_user,
    auth_client,
):
    org = _ensure_default_org()
    client = auth_client(admin_user)
    res = client.post(
        reverse("saas-admin-integration-settings"),
        {
            "organizationId": org.id,
            "providerType": "openai",
            "status": "configured",
            "displayName": "OpenAI refs",
            "config": {"model": "gpt-safe"},
            "secretRefs": {"api_key": "ENV:OPENAI_API_KEY"},
        },
        format="json",
    )
    assert res.status_code == 201
    assert AuditEvent.objects.filter(
        kind="saas.integration_setting.created",
        organization=org,
    ).exists()


def test_write_path_readiness_safe_to_start_phase6f_when_clean(db):
    _ensure_default_org()
    report = compute_org_write_path_readiness()
    assert report["recentUnscopedWritesLast24h"] == 0
    assert report["safeToStartPhase6F"] is True


def test_org_write_access_blocks_wrong_org(db, viewer_user):
    _ensure_default_org()
    other = _create_other_org()
    with pytest.raises(OrgWriteAccessError):
        validate_org_write_access(viewer_user, other)


def test_admin_can_read_masked_integration_settings(
    db,
    admin_user,
    auth_client,
):
    org = _ensure_default_org()
    OrganizationMembership.objects.create(
        organization=org,
        user=admin_user,
        role=OrganizationMembership.OrgRole.ADMIN,
        status=OrganizationMembership.Status.ACTIVE,
    )
    OrganizationIntegrationSetting.objects.create(
        organization=org,
        provider_type=OrganizationIntegrationSetting.ProviderType.OPENAI,
        status=OrganizationIntegrationSetting.Status.CONFIGURED,
        secret_refs={"api_key": "ENV:OPENAI_API_KEY"},
    )
    res = auth_client(admin_user).get(
        reverse("saas-admin-integration-settings")
    )
    assert res.status_code == 200
    blob = json.dumps(res.json())
    assert "OPENAI_API_KEY" not in blob
    assert "+91" not in blob
    assert "ENV:OPE***" in blob
