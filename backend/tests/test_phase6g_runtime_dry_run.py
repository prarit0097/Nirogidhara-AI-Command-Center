"""Phase 6G — Controlled Runtime Routing Dry Run + AI Provider Routing tests.

Covers:

- Operation taxonomy completeness (14 operations).
- Per-operation invariants (``dryRunAllowed=True`` + ``liveAllowedInPhase6G=False``).
- Dry-run preview shape — ``runtimeSource="env_config"``,
  ``perOrgRuntimeEnabled=False``, ``liveExecutionAllowed=False``,
  ``externalCallWillBeMade=False``, ``dryRun=True``.
- Provider-specific no-side-effect proofs (no WhatsApp send, no Razorpay
  order create, no Delhivery shipment, no Vapi call, no AI dispatch).
- AI provider routing — NVIDIA primary models, task-wise ``max_tokens``
  resolution from env + default fallback, env-key presence reporting,
  raw NVIDIA / OpenAI / Anthropic keys NEVER leak in any output.
- Three management commands (``inspect_controlled_runtime_routing_dry_run``,
  ``inspect_ai_provider_routing``, ``preview_runtime_operation``).
- Three new DRF endpoints (auth-required, admin-only, POST → 405,
  no-secrets).
"""
from __future__ import annotations

import io
import json
import os
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.saas.ai_runtime_preview import (
    AI_TASK_ROUTES,
    get_ai_runtime_mode,
    get_ai_task_max_tokens,
    get_ai_task_route,
    mask_ai_provider_env_status,
    preview_ai_provider_route,
    preview_all_ai_provider_routes,
    validate_ai_model_envs,
)
from apps.saas.models import Organization
from apps.saas.runtime_dry_run import (
    preview_all_runtime_operations,
    preview_runtime_routing_for_operation,
    resolve_provider_for_operation,
    summarize_runtime_dry_run_readiness,
    validate_dry_run_has_no_side_effects,
)
from apps.saas.runtime_operations import (
    RUNTIME_OPERATIONS,
    filter_operations,
    get_runtime_operation_definition,
    list_runtime_operations,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_REQUIRED_OPERATION_TYPES = (
    "whatsapp.send_text",
    "whatsapp.send_template",
    "razorpay.create_order",
    "razorpay.create_payment_link",
    "payu.create_payment",
    "delhivery.create_shipment",
    "vapi.place_call",
    "openai.agent_completion",
    "ai.reports_summary",
    "ai.ceo_planning",
    "ai.caio_compliance",
    "ai.customer_hinglish_chat",
    "ai.critical_fallback",
    "ai.smoke_test",
)


_REQUIRED_AI_TASK_TYPES = (
    "reports_summaries",
    "ceo_planning",
    "caio_compliance",
    "hinglish_customer_chat",
    "critical_fallback",
    "smoke_test",
)


def _ensure_default_org() -> Organization:
    out = io.StringIO()
    call_command(
        "ensure_default_organization",
        "--json",
        "--skip-memberships",
        stdout=out,
    )
    return Organization.objects.get(code="nirogidhara")


# ---------------------------------------------------------------------------
# Section A — Operation taxonomy
# ---------------------------------------------------------------------------


def test_a01_taxonomy_includes_all_required_operations():
    operation_types = {op.operation_type for op in list_runtime_operations()}
    for required in _REQUIRED_OPERATION_TYPES:
        assert required in operation_types, (
            f"missing operation: {required}"
        )


def test_a02_taxonomy_has_exactly_14_operations():
    assert len(RUNTIME_OPERATIONS) == 14


def test_a03_every_operation_has_dry_run_allowed_and_live_blocked():
    for op in RUNTIME_OPERATIONS:
        assert op.dry_run_allowed is True, (
            f"{op.operation_type} must allow dry-run"
        )
        assert op.live_allowed_in_phase_6g is False, (
            f"{op.operation_type} must block live execution in Phase 6G"
        )


def test_a04_every_operation_serializes_to_dict_safely():
    for op in RUNTIME_OPERATIONS:
        payload = op.to_dict()
        assert payload["operationType"] == op.operation_type
        assert payload["dryRunAllowed"] is True
        assert payload["liveAllowedInPhase6G"] is False
        # Required-secret-refs / env-keys / config-keys must always be
        # plain JSON-serializable lists, never tuples in the dict shape.
        assert isinstance(payload["requiredSecretRefs"], list)
        assert isinstance(payload["requiredEnvKeys"], list)
        assert isinstance(payload["requiredConfigKeys"], list)


def test_a05_filter_operations_by_provider_type_works():
    whatsapp = filter_operations(provider_types={"whatsapp_meta"})
    assert {op.operation_type for op in whatsapp} == {
        "whatsapp.send_text",
        "whatsapp.send_template",
    }
    none_filter = filter_operations(provider_types=None)
    assert len(none_filter) == 14


def test_a06_get_runtime_operation_definition_handles_unknown():
    assert get_runtime_operation_definition("nope.unknown") is None
    assert (
        get_runtime_operation_definition("whatsapp.send_text").provider_type
        == "whatsapp_meta"
    )


# ---------------------------------------------------------------------------
# Section B — Dry-run preview invariants
# ---------------------------------------------------------------------------


def test_b01_dry_run_runtime_source_is_env_config(db):
    org = _ensure_default_org()
    for op in RUNTIME_OPERATIONS:
        decision = preview_runtime_routing_for_operation(
            op.operation_type, org=org
        )
        assert decision["runtimeSource"] == "env_config", (
            f"{op.operation_type} must report runtimeSource=env_config"
        )


def test_b02_dry_run_per_org_runtime_disabled(db):
    org = _ensure_default_org()
    for op in RUNTIME_OPERATIONS:
        decision = preview_runtime_routing_for_operation(
            op.operation_type, org=org
        )
        assert decision["perOrgRuntimeEnabled"] is False


def test_b03_dry_run_live_execution_disabled(db):
    org = _ensure_default_org()
    for op in RUNTIME_OPERATIONS:
        decision = preview_runtime_routing_for_operation(
            op.operation_type, org=org
        )
        assert decision["dryRun"] is True
        assert decision["liveExecutionAllowed"] is False
        assert decision["externalCallWillBeMade"] is False


def test_b04_dry_run_invariant_validator_passes_every_operation(db):
    org = _ensure_default_org()
    report = preview_all_runtime_operations(org)
    for op in report["operations"]:
        assert validate_dry_run_has_no_side_effects(op) is True


def test_b05_unknown_operation_returns_blocker_shape(db):
    decision = preview_runtime_routing_for_operation("nope.unknown")
    assert decision["dryRun"] is True
    assert decision["liveExecutionAllowed"] is False
    assert decision["externalCallWillBeMade"] is False
    assert any("Unknown operation" in b for b in decision["blockers"])


def test_b06_resolve_provider_for_operation_reports_env_config(db):
    org = _ensure_default_org()
    resolved = resolve_provider_for_operation(
        "razorpay.create_order", org=org
    )
    assert resolved["runtimeSource"] == "env_config"
    assert resolved["perOrgRuntimeEnabled"] is False
    assert resolved["providerType"] == "razorpay"


def test_b07_summary_reports_safe_to_start_phase_6h_only_when_no_blockers(db):
    org = _ensure_default_org()
    summary = summarize_runtime_dry_run_readiness(org)
    assert summary["dryRun"] is True
    assert summary["liveExecutionAllowed"] is False
    assert summary["operationCount"] == 14
    assert summary["aiTaskCount"] == 6
    # Without NVIDIA / OPENAI keys set, blockers exist → safe=False.
    if summary["blockers"]:
        assert summary["safeToStartPhase6H"] is False
        assert summary["nextAction"] == "fix_runtime_routing_blockers"
    else:
        assert summary["safeToStartPhase6H"] is True


# ---------------------------------------------------------------------------
# Section C — Provider-specific no-side-effect proofs
# ---------------------------------------------------------------------------


def test_c01_whatsapp_dry_run_does_not_call_send_freeform_text(db):
    org = _ensure_default_org()
    with mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as send_mock, mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as queue_mock:
        preview_runtime_routing_for_operation(
            "whatsapp.send_text", org=org
        )
        preview_runtime_routing_for_operation(
            "whatsapp.send_template", org=org
        )
    send_mock.assert_not_called()
    queue_mock.assert_not_called()


def test_c02_razorpay_dry_run_does_not_create_order(db):
    org = _ensure_default_org()
    with mock.patch(
        "apps.payments.integrations.razorpay_client.create_payment_link"
    ) as link_mock:
        preview_runtime_routing_for_operation(
            "razorpay.create_order", org=org
        )
        preview_runtime_routing_for_operation(
            "razorpay.create_payment_link", org=org
        )
    link_mock.assert_not_called()


def test_c03_delhivery_dry_run_does_not_create_shipment(db):
    org = _ensure_default_org()
    with mock.patch(
        "apps.shipments.integrations.delhivery_client.create_awb"
    ) as awb_mock:
        preview_runtime_routing_for_operation(
            "delhivery.create_shipment", org=org
        )
    awb_mock.assert_not_called()


def test_c04_vapi_dry_run_does_not_place_call(db):
    org = _ensure_default_org()
    with mock.patch(
        "apps.calls.integrations.vapi_client.trigger_call"
    ) as trigger_mock:
        preview_runtime_routing_for_operation(
            "vapi.place_call", org=org
        )
    trigger_mock.assert_not_called()


def test_c05_openai_dry_run_does_not_dispatch_completion(db):
    org = _ensure_default_org()
    with mock.patch(
        "apps.integrations.ai.dispatch.dispatch_messages"
    ) as dispatch_mock:
        preview_runtime_routing_for_operation(
            "openai.agent_completion", org=org
        )
        for ai_op in (
            "ai.reports_summary",
            "ai.ceo_planning",
            "ai.caio_compliance",
            "ai.customer_hinglish_chat",
            "ai.critical_fallback",
            "ai.smoke_test",
        ):
            preview_runtime_routing_for_operation(ai_op, org=org)
    dispatch_mock.assert_not_called()


def test_c06_dry_run_writes_no_audit_rows(db):
    """The preview path itself must NOT emit audit events."""
    _ensure_default_org()
    AuditEvent.objects.all().delete()
    preview_all_runtime_operations()
    # Default-org seeder may have emitted rows BEFORE this call; we check
    # that the preview itself didn't add new ones.
    new_kinds = list(
        AuditEvent.objects.values_list("kind", flat=True).distinct()
    )
    for kind in new_kinds:
        # The dry-run engine must never persist its own audit rows.
        assert not kind.startswith("saas.runtime_dry_run.")
        assert not kind.startswith("ai.provider_route.")


def test_c07_payu_and_delhivery_missing_envs_surface_as_warning_not_blocker(db):
    org = _ensure_default_org()
    env_without = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PAYU_KEY", "PAYU_SECRET", "DELHIVERY_API_TOKEN"}
    }
    with mock.patch.dict(os.environ, env_without, clear=True):
        payu = preview_runtime_routing_for_operation(
            "payu.create_payment", org=org
        )
        delhivery = preview_runtime_routing_for_operation(
            "delhivery.create_shipment", org=org
        )
    assert any("payu" in w.lower() for w in payu["warnings"])
    assert any("delhivery" in w.lower() for w in delhivery["warnings"])
    # Deferred providers must not block Phase 6G start.
    assert all(
        "Required env keys missing for payu" not in b
        for b in payu["blockers"]
    )


def test_c08_vapi_partial_config_surfaces_as_warning(db):
    org = _ensure_default_org()
    env_partial = {
        k: v
        for k, v in os.environ.items()
        if k not in {"VAPI_PHONE_NUMBER_ID", "VAPI_WEBHOOK_SECRET"}
    }
    env_partial["VAPI_API_KEY"] = "vapi_dummy_key_DO_NOT_LEAK"
    with mock.patch.dict(os.environ, env_partial, clear=True):
        decision = preview_runtime_routing_for_operation(
            "vapi.place_call", org=org
        )
    assert any(
        "phone_number_id" in w.lower() or "vapi" in w.lower()
        for w in decision["warnings"]
    )


# ---------------------------------------------------------------------------
# Section D — AI provider routing
# ---------------------------------------------------------------------------


def test_d01_ai_task_routes_cover_all_required_tasks():
    routes = {route.task_type for route in AI_TASK_ROUTES}
    for required in _REQUIRED_AI_TASK_TYPES:
        assert required in routes, f"missing AI task: {required}"


def test_d02_nvidia_models_match_locked_mapping():
    expected = {
        "reports_summaries": "minimaxai/minimax-m2.7",
        "ceo_planning": "moonshotai/kimi-k2.6",
        "caio_compliance": "mistralai/mistral-medium-3.5-128b",
        "hinglish_customer_chat": "google/gemma-4-31b-it",
        "critical_fallback": "mistralai/mistral-medium-3.5-128b",
        "smoke_test": "google/gemma-4-31b-it",
    }
    for task_type, expected_model in expected.items():
        route = get_ai_task_route(task_type)
        assert route is not None
        assert route.primary_provider == "nvidia"
        assert route.primary_model_default == expected_model


def test_d03_task_max_tokens_default_fallback_when_env_missing():
    # Ensure no overriding env var. We strip task-specific MAX_TOKENS keys.
    keys_to_strip = {route.max_tokens_env for route in AI_TASK_ROUTES}
    env_clean = {k: v for k, v in os.environ.items() if k not in keys_to_strip}
    expected_defaults = {
        "reports_summaries": 3000,
        "ceo_planning": 2048,
        "caio_compliance": 1024,
        "hinglish_customer_chat": 512,
        "critical_fallback": 1024,
        "smoke_test": 32,
    }
    with mock.patch.dict(os.environ, env_clean, clear=True):
        for task_type, expected_value in expected_defaults.items():
            result = get_ai_task_max_tokens(task_type)
            assert result["value"] == expected_value
            assert result["source"] == "default"


def test_d04_task_max_tokens_env_override_wins():
    env_override = {
        "AI_MAX_TOKENS_REPORTS": "5000",
        "AI_MAX_TOKENS_CEO": "4096",
        "AI_MAX_TOKENS_COMPLIANCE": "2048",
        "AI_MAX_TOKENS_CUSTOMER_CHAT": "768",
        "AI_MAX_TOKENS_SMOKE": "16",
    }
    with mock.patch.dict(os.environ, env_override):
        assert get_ai_task_max_tokens("reports_summaries")["value"] == 5000
        assert get_ai_task_max_tokens("ceo_planning")["value"] == 4096
        assert get_ai_task_max_tokens("caio_compliance")["value"] == 2048
        assert get_ai_task_max_tokens(
            "hinglish_customer_chat"
        )["value"] == 768
        assert get_ai_task_max_tokens("smoke_test")["value"] == 16
        for task in (
            "reports_summaries",
            "ceo_planning",
            "caio_compliance",
            "hinglish_customer_chat",
            "smoke_test",
        ):
            assert get_ai_task_max_tokens(task)["source"] == "env"


def test_d05_task_max_tokens_invalid_env_falls_back_to_default():
    env_bad = {"AI_MAX_TOKENS_REPORTS": "not-an-integer"}
    with mock.patch.dict(os.environ, env_bad):
        result = get_ai_task_max_tokens("reports_summaries")
    assert result["value"] == 3000
    assert result["source"] == "default"


def test_d06_runtime_mode_defaults_to_preview():
    env_clean = {
        k: v
        for k, v in os.environ.items()
        if k != "AI_PROVIDER_RUNTIME_MODE"
    }
    with mock.patch.dict(os.environ, env_clean, clear=True):
        assert get_ai_runtime_mode() == "preview"


def test_d07_validate_ai_model_envs_returns_booleans_only():
    env_with_keys = {
        "NVIDIA_API_KEY": "sk_RAW_NVIDIA_KEY_NEVER_LEAK",
        "OPENAI_API_KEY": "sk_RAW_OPENAI_KEY_NEVER_LEAK",
        "ANTHROPIC_API_KEY": "sk-ant-RAW_ANTHROPIC_NEVER_LEAK",
    }
    with mock.patch.dict(os.environ, env_with_keys):
        presence = validate_ai_model_envs()
    assert presence["NVIDIA_API_KEY"] is True
    assert presence["OPENAI_API_KEY"] is True
    assert presence["ANTHROPIC_API_KEY"] is True
    blob = json.dumps(presence)
    for raw in env_with_keys.values():
        assert raw not in blob


def test_d08_preview_ai_route_never_leaks_raw_keys():
    raw_key = "sk_TOTALLY_FAKE_NVIDIA_DO_NOT_LEAK_qq42"
    with mock.patch.dict(
        os.environ,
        {
            "NVIDIA_API_KEY": raw_key,
            "NVIDIA_API_BASE_URL": "https://example.invalid/v1",
            "OPENAI_API_KEY": "sk_OPENAI_FAKE",
            "ANTHROPIC_API_KEY": "sk-ant-FAKE",
        },
    ):
        for task in _REQUIRED_AI_TASK_TYPES:
            preview = preview_ai_provider_route(task)
            blob = json.dumps(preview)
            assert raw_key not in blob
            assert "sk_OPENAI_FAKE" not in blob
            assert "sk-ant-FAKE" not in blob
            assert preview["liveCallWillBeMade"] is False
            assert preview["dryRun"] is True
            assert preview["primaryProvider"] == "nvidia"


def test_d09_preview_ai_route_unknown_task_returns_invalid():
    payload = preview_ai_provider_route("not_a_real_task")
    assert payload["valid"] is False
    assert payload["nextAction"] == "fix_ai_task_route_lookup"


def test_d10_customer_chat_route_flags_safety_wrappers_required():
    preview = preview_ai_provider_route("hinglish_customer_chat")
    assert preview["safetyWrappersRequired"] is True
    assert any(
        "claim vault" in note.lower() for note in preview["safetyNotes"]
    )


def test_d11_caio_compliance_route_flags_human_review_fallback():
    preview = preview_ai_provider_route("caio_compliance")
    assert preview["safetyWrappersRequired"] is True
    assert any(
        "human-review" in note.lower() or "human review" in note.lower()
        for note in preview["safetyNotes"]
    )


def test_d12_preview_all_ai_routes_returns_runtime_summary():
    report = preview_all_ai_provider_routes()
    assert report["dryRun"] is True
    assert report["liveCallWillBeMade"] is False
    assert len(report["tasks"]) == 6
    runtime = report["runtime"]
    assert runtime["primaryProvider"] == "nvidia"
    assert runtime["fallbackProvider"] == "openai"
    # Booleans only — no raw values.
    presence = runtime["envKeyPresence"]
    for value in presence.values():
        assert isinstance(value, bool)


def test_d13_mask_ai_provider_env_status_has_no_secrets():
    raw_key = "sk_AI_RAW_NEVER_LEAK_ZZ"
    with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": raw_key}):
        report = mask_ai_provider_env_status()
    blob = json.dumps(report)
    assert raw_key not in blob


# ---------------------------------------------------------------------------
# Section E — Management commands
# ---------------------------------------------------------------------------


def _run_inspect_runtime_cmd(*args: str) -> dict:
    out = io.StringIO()
    call_command(
        "inspect_controlled_runtime_routing_dry_run",
        "--json",
        *args,
        stdout=out,
    )
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_e01_inspect_runtime_returns_all_14_operations(db):
    _ensure_default_org()
    report = _run_inspect_runtime_cmd()
    assert len(report["operations"]) == 14
    assert report["runtimeSource"] == "env_config"
    assert report["perOrgRuntimeEnabled"] is False
    assert report["dryRun"] is True
    assert report["liveExecutionAllowed"] is False


def test_e02_inspect_runtime_single_operation(db):
    _ensure_default_org()
    report = _run_inspect_runtime_cmd("--operation", "razorpay.create_order")
    assert len(report["operations"]) == 1
    assert (
        report["operations"][0]["operationType"]
        == "razorpay.create_order"
    )


def test_e03_inspect_runtime_no_raw_secrets(db):
    raw_key = "sk_RAZORPAY_RAW_NEVER_LEAK_xx"
    _ensure_default_org()
    with mock.patch.dict(
        os.environ,
        {
            "RAZORPAY_KEY_ID": "rzp_test_dummy_id",
            "RAZORPAY_KEY_SECRET": raw_key,
            "NVIDIA_API_KEY": "sk_NVIDIA_RAW_NEVER_LEAK_yy",
            "OPENAI_API_KEY": "sk_OPENAI_RAW_NEVER_LEAK_zz",
        },
    ):
        report = _run_inspect_runtime_cmd()
    blob = json.dumps(report)
    assert raw_key not in blob
    assert "sk_NVIDIA_RAW_NEVER_LEAK_yy" not in blob
    assert "sk_OPENAI_RAW_NEVER_LEAK_zz" not in blob


def test_e04_inspect_ai_provider_routing_command(db):
    out = io.StringIO()
    call_command("inspect_ai_provider_routing", "--json", stdout=out)
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert report["dryRun"] is True
    assert report["liveCallWillBeMade"] is False
    assert len(report["tasks"]) == 6
    assert report["runtime"]["primaryProvider"] == "nvidia"


def test_e05_inspect_ai_provider_no_raw_keys(db):
    raw = "sk_AI_RAW_DO_NOT_LEAK_42"
    out = io.StringIO()
    with mock.patch.dict(
        os.environ,
        {
            "NVIDIA_API_KEY": raw,
            "OPENAI_API_KEY": raw + "_openai",
            "ANTHROPIC_API_KEY": raw + "_anthropic",
        },
    ):
        call_command("inspect_ai_provider_routing", "--json", stdout=out)
    blob = out.getvalue()
    assert raw not in blob
    assert raw + "_openai" not in blob
    assert raw + "_anthropic" not in blob


def test_e06_preview_runtime_operation_command_single_op(db):
    _ensure_default_org()
    out = io.StringIO()
    call_command(
        "preview_runtime_operation",
        "--operation",
        "whatsapp.send_text",
        "--json",
        stdout=out,
    )
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert report["operationType"] == "whatsapp.send_text"
    assert report["runtimeSource"] == "env_config"
    assert report["dryRun"] is True
    assert report["liveExecutionAllowed"] is False
    assert report["externalCallWillBeMade"] is False


def test_e07_preview_runtime_operation_unknown_returns_blocker(db):
    _ensure_default_org()
    out = io.StringIO()
    call_command(
        "preview_runtime_operation",
        "--operation",
        "nope.unknown",
        "--json",
        stdout=out,
    )
    report = json.loads(out.getvalue().strip().splitlines()[-1])
    assert any(
        "Unknown operation" in b for b in report.get("blockers", [])
    )


def test_e08_inspect_commands_do_not_mutate_db(db):
    _ensure_default_org()
    audit_before = AuditEvent.objects.count()
    _run_inspect_runtime_cmd()
    out = io.StringIO()
    call_command("inspect_ai_provider_routing", "--json", stdout=out)
    call_command(
        "preview_runtime_operation",
        "--operation",
        "razorpay.create_order",
        "--json",
        stdout=io.StringIO(),
    )
    audit_after = AuditEvent.objects.count()
    # Inspect / preview commands must NOT emit any audit rows.
    assert audit_after == audit_before


# ---------------------------------------------------------------------------
# Section F — DRF endpoints
# ---------------------------------------------------------------------------


def test_f01_runtime_dry_run_endpoint_requires_auth(db, auth_client):
    _ensure_default_org()
    client = auth_client(None)
    res = client.get(reverse("saas-runtime-dry-run"))
    assert res.status_code in (401, 403)


def test_f02_runtime_dry_run_endpoint_blocks_viewer(
    db, viewer_user, auth_client
):
    _ensure_default_org()
    client = auth_client(viewer_user)
    res = client.get(reverse("saas-runtime-dry-run"))
    assert res.status_code in (401, 403)


def test_f03_runtime_dry_run_endpoint_admin_returns_full_shape(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-runtime-dry-run"))
    assert res.status_code == 200
    body = res.json()
    assert body["runtimeSource"] == "env_config"
    assert body["perOrgRuntimeEnabled"] is False
    assert body["dryRun"] is True
    assert body["liveExecutionAllowed"] is False
    assert len(body["operations"]) == 14
    assert body["aiProviderRoutes"] is not None
    assert "global" in body
    assert "safeToStartPhase6H" in body["global"]


def test_f04_runtime_dry_run_endpoint_single_operation_filter(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(
        reverse("saas-runtime-dry-run") + "?operation=whatsapp.send_text"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["operationType"] == "whatsapp.send_text"
    assert body["runtimeSource"] == "env_config"
    assert body["dryRun"] is True


def test_f05_runtime_dry_run_endpoint_rejects_post(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.post(reverse("saas-runtime-dry-run"), {})
    assert res.status_code == 405


def test_f06_runtime_dry_run_endpoint_no_raw_secrets(
    db, admin_user, auth_client
):
    _ensure_default_org()
    raw = "sk_RAW_PROD_KEY_NEVER_LEAK_aa42"
    client = auth_client(admin_user)
    with mock.patch.dict(
        os.environ,
        {
            "NVIDIA_API_KEY": raw,
            "OPENAI_API_KEY": raw + "_open",
            "RAZORPAY_KEY_SECRET": raw + "_rzp",
            "META_WA_ACCESS_TOKEN": raw + "_meta",
            "VAPI_API_KEY": raw + "_vapi",
        },
    ):
        res = client.get(reverse("saas-runtime-dry-run"))
    blob = json.dumps(res.json())
    for needle in (
        raw,
        raw + "_open",
        raw + "_rzp",
        raw + "_meta",
        raw + "_vapi",
    ):
        assert needle not in blob


def test_f07_ai_provider_routing_endpoint_requires_auth(db, auth_client):
    _ensure_default_org()
    client = auth_client(None)
    res = client.get(reverse("saas-ai-provider-routing"))
    assert res.status_code in (401, 403)


def test_f08_ai_provider_routing_endpoint_blocks_viewer(
    db, viewer_user, auth_client
):
    _ensure_default_org()
    client = auth_client(viewer_user)
    res = client.get(reverse("saas-ai-provider-routing"))
    assert res.status_code in (401, 403)


def test_f09_ai_provider_routing_endpoint_admin_shape(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-ai-provider-routing"))
    assert res.status_code == 200
    body = res.json()
    assert body["dryRun"] is True
    assert body["liveCallWillBeMade"] is False
    assert len(body["tasks"]) == 6
    assert body["runtime"]["primaryProvider"] == "nvidia"


def test_f10_ai_provider_routing_endpoint_rejects_post(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.post(reverse("saas-ai-provider-routing"), {})
    assert res.status_code == 405


def test_f11_controlled_runtime_readiness_endpoint_requires_auth(
    db, auth_client
):
    _ensure_default_org()
    client = auth_client(None)
    res = client.get(reverse("saas-controlled-runtime-readiness"))
    assert res.status_code in (401, 403)


def test_f12_controlled_runtime_readiness_endpoint_admin_shape(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.get(reverse("saas-controlled-runtime-readiness"))
    assert res.status_code == 200
    body = res.json()
    assert body["runtimeSource"] == "env_config"
    assert body["perOrgRuntimeEnabled"] is False
    assert body["dryRun"] is True
    assert body["liveExecutionAllowed"] is False
    assert body["operationCount"] == 14
    assert body["aiTaskCount"] == 6


def test_f13_controlled_runtime_readiness_endpoint_rejects_post(
    db, admin_user, auth_client
):
    _ensure_default_org()
    client = auth_client(admin_user)
    res = client.post(reverse("saas-controlled-runtime-readiness"), {})
    assert res.status_code == 405


def test_f14_controlled_runtime_readiness_blocks_viewer(
    db, viewer_user, auth_client
):
    _ensure_default_org()
    client = auth_client(viewer_user)
    res = client.get(reverse("saas-controlled-runtime-readiness"))
    assert res.status_code in (401, 403)
