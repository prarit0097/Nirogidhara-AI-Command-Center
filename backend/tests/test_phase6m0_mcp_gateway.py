"""Phase 6M-0 — MCP Gateway Foundation tests.

Hard rules asserted:

- Defaults: ``MCP_ENABLED=False``, ``MCP_READ_ONLY_MODE=True``,
  ``MCP_WRITE_TOOLS_ENABLED=False``, ``MCP_PROVIDER_TOOLS_ENABLED=False``.
- Forbidden tools never get registered, never get dispatched.
- Default tools are read-only with
  ``provider_call_allowed=False`` and
  ``business_mutation_allowed=False``.
- Tool simulator runs each handler without an external provider call
  and without mutating business records.
- Outputs mask phones / emails / provider keys.
- Audit log row is written on every invocation.
- DRF endpoints are auth + admin protected.
- ``providerCallAttemptedCount`` and
  ``businessMutationAttemptedCount`` stay at zero.
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
from apps.mcp_gateway.models import (
    McpPromptDefinition,
    McpResourceDefinition,
    McpToolDefinition,
    McpToolInvocationLog,
)
from apps.mcp_gateway.services import tool_handlers  # noqa: F401
from apps.mcp_gateway.services.audit import (
    AUDIT_KIND_CALL_BLOCKED,
    AUDIT_KIND_CALL_SUCCEEDED,
    AUDIT_KIND_REGISTRY_SEEDED,
)
from apps.mcp_gateway.services.masking import (
    detect_full_pii,
    detect_raw_secret,
    mask_email,
    mask_payload,
    mask_phone,
    mask_secret_value,
)
from apps.mcp_gateway.services.readiness import (
    get_mcp_gateway_readiness,
    get_mcp_security_posture,
)
from apps.mcp_gateway.services.registry import register_default_mcp_tools
from apps.mcp_gateway.services.schemas import (
    ENABLED_SCOPES,
    FORBIDDEN_TOOLS,
    FUTURE_DISABLED_SCOPES,
    is_forbidden_tool,
)
from apps.mcp_gateway.services.tool_executor import execute_mcp_tool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_mcp(db):
    register_default_mcp_tools()
    yield


# ---------------------------------------------------------------------------
# Section A — Settings + scope vocabulary
# ---------------------------------------------------------------------------


def test_a01_default_env_keeps_mcp_disabled_and_read_only(settings):
    assert settings.MCP_ENABLED is False
    assert settings.MCP_READ_ONLY_MODE is True
    assert settings.MCP_WRITE_TOOLS_ENABLED is False
    assert settings.MCP_PROVIDER_TOOLS_ENABLED is False
    assert settings.MCP_REQUIRE_AUTH is True
    assert settings.MCP_AUDIT_ENABLED is True
    assert settings.MCP_MASK_PII is True


def test_a02_enabled_scopes_are_read_only_only():
    for scope in ENABLED_SCOPES:
        assert "write" not in scope
        assert "provider" not in scope
        assert "execute" not in scope


def test_a03_future_disabled_scopes_cover_write_and_provider():
    for scope in FUTURE_DISABLED_SCOPES:
        assert "write" in scope or "provider" in scope


def test_a04_forbidden_tool_helper_works():
    for name in FORBIDDEN_TOOLS:
        assert is_forbidden_tool(name) is True
    assert is_forbidden_tool("system.get_phase_status") is False


# ---------------------------------------------------------------------------
# Section B — register_default_mcp_tools
# ---------------------------------------------------------------------------


def test_b01_register_default_creates_tools_resources_prompts(db):
    counters = register_default_mcp_tools()
    assert counters["toolsCreated"] >= 10
    assert counters["resourcesCreated"] >= 7
    assert counters["promptsCreated"] >= 6
    assert McpToolDefinition.objects.count() >= 10
    assert McpResourceDefinition.objects.count() >= 7
    assert McpPromptDefinition.objects.count() >= 6


def test_b02_register_default_is_idempotent(db):
    register_default_mcp_tools()
    second = register_default_mcp_tools()
    assert second["toolsCreated"] == 0
    assert second["resourcesCreated"] == 0
    assert second["promptsCreated"] == 0


def test_b03_register_default_does_not_seed_forbidden_tools(db):
    register_default_mcp_tools()
    for name in FORBIDDEN_TOOLS:
        assert McpToolDefinition.objects.filter(name=name).exists() is False


def test_b04_default_tools_are_read_only_no_provider_no_mutation(db, seeded_mcp):
    qs = McpToolDefinition.objects.all()
    assert qs.exists()
    for tool in qs:
        assert tool.read_only is True
        assert tool.provider_call_allowed is False
        assert tool.business_mutation_allowed is False
        assert tool.requires_auth is True


# ---------------------------------------------------------------------------
# Section C — Readiness + security posture selectors
# ---------------------------------------------------------------------------


def test_c01_readiness_default_state(db, seeded_mcp):
    report = get_mcp_gateway_readiness()
    assert report["mcpEnabled"] is False
    assert report["readOnlyMode"] is True
    assert report["writeToolsEnabled"] is False
    assert report["providerToolsEnabled"] is False
    assert report["forbiddenToolsRegisteredCount"] == 0
    assert report["writeToolEnabledCount"] == 0
    assert report["providerToolEnabledCount"] == 0
    assert report["providerCallAttemptedCount"] == 0
    assert report["businessMutationAttemptedCount"] == 0


def test_c02_security_posture_default_state(db, seeded_mcp):
    posture = get_mcp_security_posture()
    assert posture["forbiddenToolsRegistered"] is False
    assert posture["writeToolsEnabled"] is False
    assert posture["providerToolsEnabled"] is False
    assert posture["authRequired"] is True
    assert posture["safe"] is True
    assert posture["providerCallAttemptedCount"] == 0
    assert posture["businessMutationAttemptedCount"] == 0


# ---------------------------------------------------------------------------
# Section D — Tool executor
# ---------------------------------------------------------------------------


def test_d01_executor_blocks_forbidden_tool(db, seeded_mcp):
    result = execute_mcp_tool(
        "razorpay.create_order",
        bypass_auth_for_internal=True,
    )
    assert result["passed"] is False
    assert result["status"] == "blocked"
    assert result["blockedReason"] == "forbidden_tool_phase_6m_0"
    # Audit row must be written.
    assert McpToolInvocationLog.objects.filter(
        tool_name="razorpay.create_order",
        status=McpToolInvocationLog.Status.BLOCKED,
    ).exists()


def test_d02_executor_blocks_unregistered_tool(db, seeded_mcp):
    result = execute_mcp_tool(
        "system.does_not_exist",
        bypass_auth_for_internal=True,
    )
    assert result["passed"] is False
    assert result["blockedReason"] == "tool_not_registered"


def test_d03_executor_runs_phase_status(db, seeded_mcp):
    result = execute_mcp_tool(
        "system.get_phase_status",
        bypass_auth_for_internal=True,
    )
    assert result["passed"] is True
    assert result["providerCallAttempted"] is False
    assert result["businessMutationAttempted"] is False
    assert result["readOnly"] is True
    assert "currentPhase" in (result["result"] or {})


def test_d04_executor_writes_invocation_audit(db, seeded_mcp):
    AuditEvent.objects.all().delete()
    execute_mcp_tool(
        "system.get_phase_status",
        bypass_auth_for_internal=True,
    )
    assert AuditEvent.objects.filter(
        kind=AUDIT_KIND_CALL_SUCCEEDED
    ).exists()
    log = McpToolInvocationLog.objects.filter(
        tool_name="system.get_phase_status"
    ).first()
    assert log is not None
    assert log.status == McpToolInvocationLog.Status.SUCCEEDED
    assert log.provider_call_attempted is False
    assert log.business_mutation_attempted is False


def test_d05_executor_blocks_when_auth_required(db, seeded_mcp):
    result = execute_mcp_tool("system.get_phase_status")
    assert result["passed"] is False
    assert result["blockedReason"] == "auth_required"
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_CALL_BLOCKED).exists()


def test_d06_simulator_invocation_provider_counts_remain_zero(db, seeded_mcp):
    for name in (
        "system.get_phase_status",
        "system.get_health",
        "saas.get_current_org",
        "razorpay.inspect_webhook_readiness",
        "razorpay.plan_webhook_readiness",
    ):
        execute_mcp_tool(name, bypass_auth_for_internal=True)
    qs = McpToolInvocationLog.objects.all()
    assert qs.filter(provider_call_attempted=True).count() == 0
    assert qs.filter(business_mutation_attempted=True).count() == 0


def test_d07_razorpay_inspect_does_not_call_razorpay(db, seeded_mcp):
    with mock.patch(
        "apps.saas.razorpay_test_execution._create_order_via_sdk"
    ) as sdk_mock:
        execute_mcp_tool(
            "razorpay.inspect_webhook_readiness",
            bypass_auth_for_internal=True,
        )
        execute_mcp_tool(
            "razorpay.plan_webhook_readiness",
            bypass_auth_for_internal=True,
        )
    sdk_mock.assert_not_called()


def test_d08_whatsapp_inspect_does_not_send_message(db, seeded_mcp):
    # Patch the freeform-text sender — if the gateway ever drove a
    # WhatsApp send, this mock would fire.
    with mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as send_mock:
        execute_mcp_tool(
            "whatsapp.inspect_auto_reply_gate",
            bypass_auth_for_internal=True,
        )
    send_mock.assert_not_called()


def test_d09_provider_tool_globally_disabled(db, seeded_mcp):
    """Even if a row is mutated to declare provider_call_allowed=True,
    the executor must refuse it because MCP_PROVIDER_TOOLS_ENABLED=False."""
    tool = McpToolDefinition.objects.get(name="razorpay.inspect_webhook_readiness")
    tool.provider_call_allowed = True
    tool.save(update_fields=["provider_call_allowed"])
    result = execute_mcp_tool(
        "razorpay.inspect_webhook_readiness",
        bypass_auth_for_internal=True,
    )
    assert result["passed"] is False
    assert result["blockedReason"] == "provider_tools_disabled_in_phase_6m_0"


def test_d10_write_tool_globally_disabled(db, seeded_mcp):
    tool = McpToolDefinition.objects.get(name="system.get_phase_status")
    tool.business_mutation_allowed = True
    tool.save(update_fields=["business_mutation_allowed"])
    result = execute_mcp_tool(
        "system.get_phase_status",
        bypass_auth_for_internal=True,
    )
    assert result["passed"] is False
    assert result["blockedReason"] == "write_tools_disabled_in_phase_6m_0"


# ---------------------------------------------------------------------------
# Section E — Masking helpers
# ---------------------------------------------------------------------------


def test_e01_mask_phone_keeps_last_four_only():
    masked = mask_phone("+919812345678")
    assert masked.endswith("5678")
    assert "98123456" not in masked


def test_e02_mask_email_redacts_local_part():
    masked = mask_email("alice@example.com")
    assert masked.startswith("a***@")
    assert "alice" not in masked


def test_e03_mask_secret_value_drops_middle():
    masked = mask_secret_value("rzp_test_FAKEsecretvalue")
    assert masked.startswith("rzp")
    assert "FAKEsecret" not in masked


def test_e04_mask_payload_scrubs_phone_and_secrets():
    out = mask_payload(
        {
            "phone": "+919812345678",
            "razorpay_key_secret": "rzp_test_FAKEsecret_DO_NOT_LEAK",
            "nested": {"customer_email": "alice@example.com"},
            "ok_value": "hello world",
        }
    )
    blob = json.dumps(out)
    assert "9812345678" not in blob
    assert "FAKEsecret" not in blob
    assert "alice@" not in blob
    assert "hello world" in blob


def test_e05_detect_full_pii_skips_iso_timestamps():
    assert (
        detect_full_pii({"executedAt": "2026-05-03T10:01:05.000000+00:00"})
        is False
    )
    assert detect_full_pii({"phone": "9812345678"}) is True


def test_e06_detect_raw_secret_flags_provider_keys():
    assert detect_raw_secret({"x": "rzp_test_FAKEsecretvalue"}) is True
    assert detect_raw_secret({"x": "ok"}) is False


# ---------------------------------------------------------------------------
# Section F — Management commands
# ---------------------------------------------------------------------------


def _run(cmd: str, *args: str) -> dict:
    out = io.StringIO()
    call_command(cmd, "--json", *args, stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_f01_ensure_mcp_defaults_runs(db):
    report = _run("ensure_mcp_defaults")
    assert report["passed"] is True
    assert report["mcpEnabled"] is False
    assert report["writeToolsEnabled"] is False
    assert report["providerToolsEnabled"] is False
    assert AuditEvent.objects.filter(kind=AUDIT_KIND_REGISTRY_SEEDED).exists()


def test_f02_inspect_readiness_command(db, seeded_mcp):
    report = _run("inspect_mcp_gateway_readiness")
    assert report["mcpEnabled"] is False
    assert report["readOnlyMode"] is True
    assert report["providerCallAttemptedCount"] == 0


def test_f03_inspect_security_posture_command(db, seeded_mcp):
    report = _run("inspect_mcp_security_posture")
    assert report["safe"] is True
    assert report["forbiddenToolsRegistered"] is False


def test_f04_list_tools_command(db, seeded_mcp):
    report = _run("list_mcp_tools")
    names = {row["name"] for row in report["tools"]}
    for required in (
        "system.get_phase_status",
        "razorpay.inspect_webhook_readiness",
        "razorpay.plan_webhook_readiness",
        "whatsapp.inspect_auto_reply_gate",
    ):
        assert required in names


def test_f05_simulate_command_succeeds(db, seeded_mcp):
    report = _run(
        "simulate_mcp_tool_call",
        "--tool",
        "system.get_phase_status",
    )
    assert report["passed"] is True
    assert report["providerCallAttempted"] is False
    assert report["businessMutationAttempted"] is False


def test_f06_simulate_command_blocks_forbidden_tool(db, seeded_mcp):
    report = _run(
        "simulate_mcp_tool_call",
        "--tool",
        "razorpay.create_order",
    )
    assert report["passed"] is False
    assert report["blockedReason"] == "forbidden_tool_phase_6m_0"


# ---------------------------------------------------------------------------
# Section G — DRF endpoints
# ---------------------------------------------------------------------------


def test_g01_readiness_requires_auth(db, seeded_mcp, auth_client):
    res = auth_client(None).get(reverse("mcp-readiness"))
    assert res.status_code in (401, 403)


def test_g02_readiness_admin_returns_shape(
    db, seeded_mcp, admin_user, auth_client
):
    res = auth_client(admin_user).get(reverse("mcp-readiness"))
    assert res.status_code == 200
    body = res.json()
    assert body["mcpEnabled"] is False
    assert body["readOnlyMode"] is True
    assert body["providerCallAttemptedCount"] == 0


def test_g03_security_posture_admin(db, seeded_mcp, admin_user, auth_client):
    res = auth_client(admin_user).get(reverse("mcp-security-posture"))
    assert res.status_code == 200
    body = res.json()
    assert body["safe"] is True
    assert body["forbiddenToolsRegistered"] is False


def test_g04_tools_endpoint_admin(db, seeded_mcp, admin_user, auth_client):
    res = auth_client(admin_user).get(reverse("mcp-tools"))
    assert res.status_code == 200
    body = res.json()
    assert body["count"] >= 10
    assert body["readOnlyMode"] is True
    assert body["writeToolsEnabled"] is False
    assert body["providerToolsEnabled"] is False


def test_g05_resources_endpoint_auth(db, seeded_mcp, auth_client, viewer_user):
    res = auth_client(viewer_user).get(reverse("mcp-resources"))
    assert res.status_code == 200
    body = res.json()
    assert body["count"] >= 7


def test_g06_invocations_endpoint_admin(
    db, seeded_mcp, admin_user, auth_client
):
    res = auth_client(admin_user).get(reverse("mcp-invocations"))
    assert res.status_code == 200
    body = res.json()
    assert body["providerCallAttempted"] is False
    assert body["businessMutationAttempted"] is False


def test_g07_simulate_endpoint_blocks_viewer(
    db, seeded_mcp, viewer_user, auth_client
):
    res = auth_client(viewer_user).post(
        reverse("mcp-tools-simulate"),
        {"toolName": "system.get_phase_status"},
    )
    assert res.status_code in (401, 403)


def test_g08_simulate_endpoint_admin_runs(
    db, seeded_mcp, admin_user, auth_client
):
    res = auth_client(admin_user).post(
        reverse("mcp-tools-simulate"),
        {"toolName": "system.get_phase_status"},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["passed"] is True
    assert body["providerCallAttempted"] is False
    assert body["businessMutationAttempted"] is False


def test_g09_endpoints_no_raw_secrets_in_response(
    db, seeded_mcp, admin_user, auth_client
):
    raw = "rzp_test_FAKEsecret_DO_NOT_LEAK_MCP"
    with mock.patch.dict(
        os.environ,
        {
            "RAZORPAY_KEY_SECRET": raw,
            "RAZORPAY_KEY_ID": "rzp_test_FAKEphase6m",
        },
    ):
        client = auth_client(admin_user)
        for name in (
            "mcp-readiness",
            "mcp-security-posture",
            "mcp-tools",
            "mcp-resources",
            "mcp-prompts",
            "mcp-invocations",
        ):
            res = client.get(reverse(name))
            assert res.status_code == 200
            blob = json.dumps(res.json(), default=str)
            assert raw not in blob


def test_g10_simulate_endpoint_blocks_unauthenticated(db, seeded_mcp, auth_client):
    res = auth_client(None).post(
        reverse("mcp-tools-simulate"),
        {"toolName": "system.get_phase_status"},
    )
    assert res.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Section H — Audit handler outputs do not leak full PII
# ---------------------------------------------------------------------------


def test_h01_audit_search_handler_masks_full_phones(
    db, seeded_mcp, admin_user, auth_client
):
    # Plant a synthetic audit row with a full phone number.
    from apps.audit.signals import write_event
    from apps.audit.models import AuditEvent as AE

    write_event(
        kind="mcp.demo.full_phone_test",
        text="customer phone is +919812345678",
        tone=AE.Tone.INFO,
        payload={"phone": "+919812345678", "note": "test"},
    )
    res = auth_client(admin_user).post(
        reverse("mcp-tools-simulate"),
        {
            "toolName": "audit.search_events_masked",
            "input": {"limit": 10, "kind_prefix": "mcp.demo."},
        },
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    blob = json.dumps(body)
    # 10+ digit run for the full phone number must NOT appear.
    assert "9812345678" not in blob
