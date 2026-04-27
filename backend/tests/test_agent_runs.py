"""Phase 3A tests — AgentRun foundation + provider routing + compliance gates.

Coverage:

1. ``AI_PROVIDER=disabled`` (default) returns a ``skipped`` AgentRun without
   touching any SDK.
2. Missing key never crashes — the run row is persisted with the skip
   reason captured in ``error_message``.
3. OpenAI / Anthropic / Grok configs route through the correct adapter
   when ``current_config`` is patched (the real SDKs are NEVER imported).
4. AgentRun list / detail endpoints work for admin and reject viewer.
5. Anonymous → 401, viewer → 403, operations → 403, admin / director → 200.
6. CAIO never executes: a payload with a forbidden intent is rejected with
   a ``failed`` AgentRun before any LLM dispatch.
7. The prompt builder includes Claim Vault entries when products are
   mentioned, refuses to build a medical/product prompt when the vault is
   empty, and skips the vault for non-medical agents on neutral input.
8. ``ai.agent_run.created`` / ``ai.agent_run.completed`` / ``ai.agent_run.failed``
   audit events are written.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps._ai_config import AIConfig
from apps.ai_governance.models import AgentRun
from apps.ai_governance.prompting import (
    ClaimVaultMissing,
    PROMPT_VERSION,
    build_messages,
    needs_claim_vault,
)
from apps.audit.models import AuditEvent
from apps.compliance.models import Claim
from apps.integrations.ai.base import AdapterResult, AdapterStatus


# ---------- helpers ----------


def _seed_one_claim(product: str = "Weight Management") -> Claim:
    return Claim.objects.create(
        product=product,
        approved=["Supports healthy metabolism", "Ayurvedic blend"],
        disallowed=["Guaranteed weight loss", "No side effects"],
        doctor="Approved",
        compliance="Approved",
        version="v3.2",
    )


def _disabled_config() -> AIConfig:
    return AIConfig(
        provider="disabled",
        model="",
        api_key="",
        base_url="",
        extra={},
        temperature=0.2,
        max_tokens=1000,
        timeout_seconds=30,
    )


def _enabled_config(provider: str, key: str = "key_xxx", model: str = "test-model") -> AIConfig:
    return AIConfig(
        provider=provider,
        model=model,
        api_key=key,
        base_url="",
        extra={},
        temperature=0.2,
        max_tokens=1000,
        timeout_seconds=30,
    )


# ---------- 1. Disabled default returns skipped ----------


def test_disabled_provider_creates_skipped_run(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    settings.OPENAI_API_KEY = ""
    settings.ANTHROPIC_API_KEY = ""
    settings.GROK_API_KEY = ""
    _seed_one_claim()
    client = auth_client(admin_user)
    res = client.post(
        "/api/ai/agent-runs/",
        {"agent": "ceo", "input": {"product": "Weight Management"}},
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "skipped"
    assert body["provider"] == "disabled"
    assert body["dryRun"] is True
    assert body["promptVersion"] == PROMPT_VERSION
    assert "disabled" in body["errorMessage"].lower() or body["errorMessage"] == ""


# ---------- 2. Missing key never crashes ----------


def test_missing_key_is_skipped_not_failed(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = ""  # provider set, key empty
    _seed_one_claim()
    client = auth_client(admin_user)
    res = client.post(
        "/api/ai/agent-runs/",
        {"agent": "compliance", "input": {"product": "Weight Management"}},
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "skipped"


# ---------- 3a. OpenAI routing (adapter patched) ----------


def test_openai_routing_uses_openai_adapter(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    _seed_one_claim()
    fake_result = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model="gpt-4o-mini",
        output={"text": "stubbed CEO briefing"},
        latency_ms=42,
    )
    client = auth_client(admin_user)
    with patch(
        "apps.integrations.ai.openai_client.dispatch",
        return_value=fake_result,
    ) as mock_openai, patch(
        "apps.integrations.ai.anthropic_client.dispatch",
        side_effect=AssertionError("anthropic must not be called"),
    ), patch(
        "apps.integrations.ai.grok_client.dispatch",
        side_effect=AssertionError("grok must not be called"),
    ):
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ceo", "input": {"focus": "weight management"}},
            format="json",
        )
    assert res.status_code == 201
    assert mock_openai.called
    body = res.json()
    assert body["status"] == "success"
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-4o-mini"
    assert body["outputPayload"]["text"] == "stubbed CEO briefing"


# ---------- 3b. Anthropic routing ----------


def test_anthropic_routing_uses_anthropic_adapter(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "anthropic"
    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    _seed_one_claim()
    fake_result = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="anthropic",
        model="claude-3-5-sonnet-latest",
        output={"text": "stubbed audit"},
        latency_ms=88,
    )
    client = auth_client(admin_user)
    with patch(
        "apps.integrations.ai.anthropic_client.dispatch",
        return_value=fake_result,
    ) as mock_anthropic, patch(
        "apps.integrations.ai.openai_client.dispatch",
        side_effect=AssertionError("openai must not be called"),
    ), patch(
        "apps.integrations.ai.grok_client.dispatch",
        side_effect=AssertionError("grok must not be called"),
    ):
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "compliance", "input": {"draft_script": "review this"}},
            format="json",
        )
    assert res.status_code == 201
    assert mock_anthropic.called
    assert res.json()["provider"] == "anthropic"


# ---------- 3c. Grok routing ----------


def test_grok_routing_uses_grok_adapter(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "grok"
    settings.GROK_API_KEY = "xai-test"
    _seed_one_claim()
    fake_result = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="grok",
        model="grok-2-latest",
        output={"text": "stubbed grok"},
        latency_ms=120,
    )
    client = auth_client(admin_user)
    with patch(
        "apps.integrations.ai.grok_client.dispatch",
        return_value=fake_result,
    ) as mock_grok, patch(
        "apps.integrations.ai.openai_client.dispatch",
        side_effect=AssertionError("openai must not be called"),
    ), patch(
        "apps.integrations.ai.anthropic_client.dispatch",
        side_effect=AssertionError("anthropic must not be called"),
    ):
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ads", "input": {"campaign": "monsoon-detox"}},
            format="json",
        )
    assert res.status_code == 201
    assert mock_grok.called
    assert res.json()["provider"] == "grok"


# ---------- 4. List / detail endpoints ----------


def test_admin_can_list_agent_runs(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    AgentRun.objects.create(
        id="AR-LIST-001",
        agent="ceo",
        status=AgentRun.Status.SKIPPED,
        provider="disabled",
    )
    client = auth_client(admin_user)
    res = client.get("/api/ai/agent-runs/")
    assert res.status_code == 200
    assert any(row["id"] == "AR-LIST-001" for row in res.json())


def test_admin_can_retrieve_agent_run(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    AgentRun.objects.create(
        id="AR-DETAIL-001",
        agent="ceo",
        status=AgentRun.Status.SKIPPED,
        provider="disabled",
    )
    client = auth_client(admin_user)
    res = client.get("/api/ai/agent-runs/AR-DETAIL-001/")
    assert res.status_code == 200
    assert res.json()["id"] == "AR-DETAIL-001"


# ---------- 5. Auth + role gating ----------


def test_anonymous_cannot_trigger_agent_run() -> None:
    res = APIClient().post(
        "/api/ai/agent-runs/",
        {"agent": "ceo", "input": {}},
        format="json",
    )
    assert res.status_code in {401, 403}


def test_viewer_blocked_from_agent_runs(viewer_user, auth_client) -> None:
    client = auth_client(viewer_user)
    res = client.post(
        "/api/ai/agent-runs/",
        {"agent": "ceo", "input": {}},
        format="json",
    )
    assert res.status_code == 403


def test_operations_blocked_from_agent_runs(operations_user, auth_client) -> None:
    client = auth_client(operations_user)
    res = client.post(
        "/api/ai/agent-runs/",
        {"agent": "ceo", "input": {}},
        format="json",
    )
    assert res.status_code == 403


def test_viewer_blocked_from_agent_run_list(viewer_user, auth_client) -> None:
    client = auth_client(viewer_user)
    res = client.get("/api/ai/agent-runs/")
    assert res.status_code == 403


# ---------- 6. CAIO never executes business actions ----------


def test_caio_with_execute_intent_is_refused(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    client = auth_client(admin_user)
    res = client.post(
        "/api/ai/agent-runs/",
        {
            "agent": "caio",
            "input": {
                "intent": "execute",
                "target": "order NRG-1234",
            },
        },
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "failed"
    assert "CAIO" in body["errorMessage"]


def test_caio_with_create_order_payload_is_refused(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    client = auth_client(admin_user)
    res = client.post(
        "/api/ai/agent-runs/",
        {
            "agent": "caio",
            "input": {"create_order": {"customer": "x"}},
        },
        format="json",
    )
    assert res.status_code == 201
    assert res.json()["status"] == "failed"


# ---------- 7. Claim Vault enforcement ----------


def test_prompt_builder_includes_claim_vault_when_product_seeded(db) -> None:
    _seed_one_claim("Weight Management")
    bundle = build_messages(
        agent="ceo", input_payload={"focus": "weight management products"}
    )
    assert "Weight Management" in bundle.claims_used
    joined = "\n".join(m["content"] for m in bundle.messages)
    assert "Approved Claim Vault" in joined
    assert "Supports healthy metabolism" in joined


def test_prompt_builder_refuses_when_vault_is_empty(db) -> None:
    Claim.objects.all().delete()
    with pytest.raises(ClaimVaultMissing):
        build_messages(agent="compliance", input_payload={"product": "anything"})


def test_prompt_builder_skips_vault_for_non_medical_agent(db) -> None:
    Claim.objects.all().delete()
    bundle = build_messages(agent="rto", input_payload={"order_id": "NRG-12345"})
    assert bundle.claims_used == []
    joined = "\n".join(m["content"] for m in bundle.messages)
    assert "not required for this agent run" in joined


def test_prompt_builder_blocks_when_payload_mentions_product_but_vault_empty(db) -> None:
    Claim.objects.all().delete()
    with pytest.raises(ClaimVaultMissing):
        build_messages(
            agent="rto",
            input_payload={"summary": "draft customer message about product side effects"},
        )


def test_needs_claim_vault_heuristic() -> None:
    assert needs_claim_vault("compliance", {}) is True
    assert needs_claim_vault("rto", {"order_id": "x"}) is False
    assert needs_claim_vault("rto", {"draft": "ad copy for blood purification"}) is True


# ---------- 8. Audit events written ----------


def test_audit_events_for_create_and_completion(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    _seed_one_claim()
    AuditEvent.objects.all().delete()
    fake_result = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model="gpt-4o-mini",
        output={"text": "ok"},
        latency_ms=10,
    )
    with patch(
        "apps.integrations.ai.openai_client.dispatch", return_value=fake_result
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ceo", "input": {"focus": "weight management"}},
            format="json",
        )
    assert res.status_code == 201
    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "ai.agent_run.created" in kinds
    assert "ai.agent_run.completed" in kinds


def test_audit_event_for_failure(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    Claim.objects.all().delete()  # force ClaimVaultMissing → fail
    AuditEvent.objects.all().delete()
    client = auth_client(admin_user)
    res = client.post(
        "/api/ai/agent-runs/",
        {"agent": "compliance", "input": {"product": "anything"}},
        format="json",
    )
    assert res.status_code == 201
    assert res.json()["status"] == "failed"
    failure_audit = AuditEvent.objects.filter(kind="ai.agent_run.failed").first()
    assert failure_audit is not None
    assert failure_audit.tone == AuditEvent.Tone.DANGER


# ---------- 9. Forward-compat: dryRun=False is forced to fail in Phase 3A ----------


def test_phase3a_blocks_non_dry_run(admin_user, auth_client, settings) -> None:
    """Per services.run_readonly_agent_analysis: non-dry-run runs short-circuit
    with a failed row until Phase 5 wires the approval-matrix middleware.
    The wire ``dryRun`` field is accepted but currently ignored — dry_run
    is forced to True at the view layer. This test exercises the service
    directly to confirm the guard.
    """
    from apps.ai_governance.services import run_readonly_agent_analysis

    _seed_one_claim()
    run = run_readonly_agent_analysis(
        agent="ceo", input_payload={"focus": "x"}, dry_run=False
    )
    assert run.status == AgentRun.Status.FAILED
    assert "Phase 3A" in run.error_message


# ---------- 10. Adapter unit tests ----------


def test_openai_adapter_skipped_when_disabled() -> None:
    from apps.integrations.ai import openai_client

    result = openai_client.dispatch([], config=_disabled_config())
    assert result.status == AdapterStatus.SKIPPED
    assert result.provider == "openai"


def test_anthropic_adapter_skipped_when_disabled() -> None:
    from apps.integrations.ai import anthropic_client

    result = anthropic_client.dispatch([], config=_disabled_config())
    assert result.status == AdapterStatus.SKIPPED


def test_grok_adapter_skipped_when_disabled() -> None:
    from apps.integrations.ai import grok_client

    result = grok_client.dispatch([], config=_disabled_config())
    assert result.status == AdapterStatus.SKIPPED


def test_dispatch_messages_routes_to_disabled_when_no_key() -> None:
    from apps.integrations.ai.dispatch import dispatch_messages

    with patch(
        "apps.integrations.ai.dispatch.current_config",
        return_value=_disabled_config(),
    ):
        result = dispatch_messages([])
    assert result.status == AdapterStatus.SKIPPED
