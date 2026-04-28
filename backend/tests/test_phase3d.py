"""Phase 3D tests — sandbox + prompt versioning + budget guards.

Coverage:

1. PromptVersion CRUD: create, list, list-by-agent, retrieve.
2. Only one active prompt per agent (constraint + activate flips others).
3. Rollback restores a previous version + writes audit + records reason.
4. Sandbox endpoint admin/director only; PATCH writes audit.
5. Sandbox=True prevents CeoBriefing refresh on a successful CEO run.
6. Active PromptVersion is loaded onto the AgentRun + injected into prompt.
7. Budget guard blocks dispatch when daily budget exceeded.
8. Budget warning AuditEvent fires at threshold (no provider call blocked).
9. Budget block does NOT trigger provider fallback.
10. ClaimVaultMissing still fails closed before any adapter is called.
11. CAIO still hard-stopped under the new guards.
12. Existing dispatchers still see the AgentRun with new fields populated.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.ai_governance.models import (
    AgentBudget,
    AgentRun,
    CeoBriefing,
    PromptVersion,
    SandboxState,
)
from apps.audit.models import AuditEvent
from apps.compliance.models import Claim
from apps.integrations.ai.base import AdapterResult, AdapterStatus


def _seed_one_claim() -> Claim:
    return Claim.objects.create(
        product="Weight Management",
        approved=["Supports healthy metabolism"],
        disallowed=["Guaranteed weight loss"],
        doctor="Approved",
        compliance="Approved",
        version="v3.2",
    )


# ---------- 1-3. PromptVersion CRUD + activate + rollback ----------


def test_admin_can_create_and_list_prompt_versions(admin_user, auth_client) -> None:
    _seed_one_claim()
    client = auth_client(admin_user)

    res = client.post(
        "/api/ai/prompt-versions/",
        {
            "agent": "ceo",
            "version": "v1.0",
            "title": "First CEO prompt",
            "systemPolicy": "Custom system policy",
            "rolePrompt": "Custom CEO role",
        },
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["agent"] == "ceo"
    assert body["version"] == "v1.0"
    assert body["isActive"] is False
    assert body["status"] == "draft"

    list_res = client.get("/api/ai/prompt-versions/?agent=ceo")
    assert list_res.status_code == 200
    rows = list_res.json()
    assert any(r["id"] == body["id"] for r in rows)


def test_only_one_active_prompt_per_agent(admin_user, auth_client) -> None:
    client = auth_client(admin_user)
    a = client.post(
        "/api/ai/prompt-versions/",
        {"agent": "ceo", "version": "v1.0", "title": "A"},
        format="json",
    ).json()
    b = client.post(
        "/api/ai/prompt-versions/",
        {"agent": "ceo", "version": "v2.0", "title": "B"},
        format="json",
    ).json()

    # Activate A.
    res_a = client.post(
        f"/api/ai/prompt-versions/{a['id']}/activate/", {}, format="json"
    )
    assert res_a.status_code == 200
    assert res_a.json()["isActive"] is True

    # Activate B → A should auto-archive.
    res_b = client.post(
        f"/api/ai/prompt-versions/{b['id']}/activate/", {}, format="json"
    )
    assert res_b.status_code == 200
    assert res_b.json()["isActive"] is True

    a_after = PromptVersion.objects.get(pk=a["id"])
    b_after = PromptVersion.objects.get(pk=b["id"])
    assert a_after.is_active is False
    assert b_after.is_active is True
    assert PromptVersion.objects.filter(agent="ceo", is_active=True).count() == 1


def test_rollback_restores_previous_version_and_records_reason(
    admin_user, auth_client
) -> None:
    client = auth_client(admin_user)
    a = client.post(
        "/api/ai/prompt-versions/",
        {"agent": "ceo", "version": "v1.0"},
        format="json",
    ).json()
    b = client.post(
        "/api/ai/prompt-versions/",
        {"agent": "ceo", "version": "v2.0"},
        format="json",
    ).json()

    client.post(f"/api/ai/prompt-versions/{a['id']}/activate/", {}, format="json")
    client.post(f"/api/ai/prompt-versions/{b['id']}/activate/", {}, format="json")

    AuditEvent.objects.all().delete()
    rollback_res = client.post(
        f"/api/ai/prompt-versions/{a['id']}/rollback/",
        {"reason": "B regressed accuracy"},
        format="json",
    )
    assert rollback_res.status_code == 200
    body = rollback_res.json()
    assert body["isActive"] is True
    assert body["id"] == a["id"]

    b_after = PromptVersion.objects.get(pk=b["id"])
    assert b_after.is_active is False
    assert b_after.rollback_reason == "B regressed accuracy"
    assert b_after.status == "rolled_back"

    audit = AuditEvent.objects.filter(kind="ai.prompt_version.rolled_back").first()
    assert audit is not None
    assert audit.payload["reason"] == "B regressed accuracy"


def test_prompt_version_endpoints_admin_only(viewer_user, auth_client) -> None:
    client = auth_client(viewer_user)
    res = client.get("/api/ai/prompt-versions/")
    assert res.status_code == 403


# ---------- 4. Sandbox endpoint perms + audit ----------


def test_sandbox_status_requires_admin(viewer_user, auth_client) -> None:
    client = auth_client(viewer_user)
    res = client.get("/api/ai/sandbox/status/")
    assert res.status_code == 403


def test_sandbox_patch_flips_state_and_writes_audit(
    admin_user, auth_client
) -> None:
    """Phase 3D: enabling sandbox is auto for admin; disabling is gated.

    Phase 4C tightens disabling sandbox to ``director_override`` per the
    approval matrix, so the OFF half of this test now lives in
    ``test_phase4c.py``.
    """
    client = auth_client(admin_user)
    AuditEvent.objects.all().delete()
    res = client.patch(
        "/api/ai/sandbox/status/",
        {"isEnabled": True, "note": "Trying new prompt"},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["isEnabled"] is True
    assert SandboxState.objects.get(pk=1).is_enabled is True
    assert AuditEvent.objects.filter(kind="ai.sandbox.enabled").exists()


# ---------- 5. Sandbox blocks CeoBriefing refresh ----------


def test_sandbox_mode_prevents_ceo_briefing_refresh(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    _seed_one_claim()
    SandboxState.objects.update_or_create(pk=1, defaults={"is_enabled": True})

    fake = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model="gpt-5.1",
        output={
            "summary": "Sandbox-only briefing",
            "headline": "Sandbox sample",
            "alerts": [],
            "recommendations": [],
        },
        latency_ms=10,
    )
    before = CeoBriefing.objects.count()
    with patch(
        "apps.integrations.ai.openai_client.dispatch", return_value=fake
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runtime/ceo/daily-brief/", format="json"
        )
    assert res.status_code == 201
    assert res.json()["status"] == "success"
    assert res.json()["sandboxMode"] is True
    # Crucial: sandbox successes do NOT mutate the CeoBriefing table.
    assert CeoBriefing.objects.count() == before


# ---------- 6. Active PromptVersion is loaded onto AgentRun ----------


def test_active_prompt_version_is_attached_to_agent_run(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    _seed_one_claim()

    pv = PromptVersion.objects.create(
        id="PV-TEST-001",
        agent="ceo",
        version="vX",
        system_policy="Custom policy",
        role_prompt="Custom role",
        is_active=True,
        status=PromptVersion.Status.ACTIVE,
    )

    fake = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model="gpt-5.1",
        output={"summary": "ok"},
    )
    with patch(
        "apps.integrations.ai.openai_client.dispatch", return_value=fake
    ) as mock_openai:
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ceo", "input": {"focus": "weight management"}},
            format="json",
        )
    assert res.status_code == 201
    body = res.json()
    assert body["promptVersionRef"] == pv.id
    assert body["promptVersion"] == f"ceo:vX"
    # The custom system_policy must show up in the messages dispatched.
    sent_messages = mock_openai.call_args.args[0]
    joined = "\n".join(m.get("content", "") for m in sent_messages)
    assert "Custom policy" in joined
    assert "Custom role" in joined
    # Claim Vault is still attached on top of the custom prompt.
    assert "Approved Claim Vault" in joined


# ---------- 7. Budget guard blocks dispatch ----------


def test_budget_guard_blocks_when_daily_exceeded(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    _seed_one_claim()

    AgentBudget.objects.create(
        agent="ceo",
        daily_budget_usd=Decimal("0.001000"),
        monthly_budget_usd=Decimal("100"),
        is_enforced=True,
        alert_threshold_pct=80,
    )
    # Pre-existing successful run already exhausted the daily budget.
    AgentRun.objects.create(
        id="AR-PRE-001",
        agent="ceo",
        status=AgentRun.Status.SUCCESS,
        provider="openai",
        cost_usd=Decimal("0.005000"),
        completed_at=__import__("django").utils.timezone.now(),
    )

    AuditEvent.objects.all().delete()
    with patch(
        "apps.integrations.ai.openai_client.dispatch",
        side_effect=AssertionError("openai must NOT be called when budget blocked"),
    ), patch(
        "apps.integrations.ai.anthropic_client.dispatch",
        side_effect=AssertionError("anthropic must NOT be called when budget blocked"),
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ceo", "input": {"focus": "weight management"}},
            format="json",
        )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "failed"
    assert body["budgetStatus"] == "blocked"
    assert "Budget guard blocked" in body["errorMessage"]
    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "ai.budget.blocked" in kinds


# ---------- 8. Budget warning AuditEvent at threshold ----------


def test_budget_warning_emitted_at_threshold(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    _seed_one_claim()

    AgentBudget.objects.create(
        agent="ceo",
        daily_budget_usd=Decimal("1.0000"),
        monthly_budget_usd=Decimal("100"),
        is_enforced=True,
        alert_threshold_pct=50,
    )
    AgentRun.objects.create(
        id="AR-WARN-001",
        agent="ceo",
        status=AgentRun.Status.SUCCESS,
        provider="openai",
        cost_usd=Decimal("0.6"),  # 60% of $1 daily budget → above 50%
        completed_at=__import__("django").utils.timezone.now(),
    )

    fake = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model="gpt-5.1",
        output={"summary": "ok"},
        latency_ms=10,
    )
    AuditEvent.objects.all().delete()
    with patch(
        "apps.integrations.ai.openai_client.dispatch", return_value=fake
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ceo", "input": {"focus": "weight management"}},
            format="json",
        )
    assert res.status_code == 201
    body = res.json()
    assert body["budgetStatus"] == "warning"
    assert body["status"] == "success"  # warning lets the run proceed
    assert AuditEvent.objects.filter(kind="ai.budget.warning").exists()


# ---------- 9. Budget block does NOT trigger provider fallback ----------


def test_budget_block_does_not_trigger_fallback(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    settings.AI_PROVIDER_FALLBACKS = ["openai", "anthropic"]
    _seed_one_claim()

    AgentBudget.objects.create(
        agent="ceo",
        daily_budget_usd=Decimal("0.001"),
        monthly_budget_usd=Decimal("100"),
        is_enforced=True,
    )
    AgentRun.objects.create(
        id="AR-BUDGET-FB-001",
        agent="ceo",
        status=AgentRun.Status.SUCCESS,
        provider="openai",
        cost_usd=Decimal("0.5"),
        completed_at=__import__("django").utils.timezone.now(),
    )

    with patch(
        "apps.integrations.ai.openai_client.dispatch",
        side_effect=AssertionError("openai must NOT be called"),
    ), patch(
        "apps.integrations.ai.anthropic_client.dispatch",
        side_effect=AssertionError("anthropic fallback must NOT be tried"),
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ceo", "input": {"focus": "weight management"}},
            format="json",
        )
    assert res.status_code == 201
    assert res.json()["status"] == "failed"


# ---------- 10. ClaimVaultMissing still fails closed ----------


def test_claim_vault_missing_still_fails_closed(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    Claim.objects.all().delete()
    with patch(
        "apps.integrations.ai.openai_client.dispatch",
        side_effect=AssertionError("must not dispatch when vault is empty"),
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "compliance", "input": {"product": "Weight Management"}},
            format="json",
        )
    assert res.status_code == 201
    assert res.json()["status"] == "failed"


# ---------- 11. CAIO still hard-stopped ----------


def test_caio_still_refused_under_phase3d(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    _seed_one_claim()
    with patch(
        "apps.integrations.ai.openai_client.dispatch",
        side_effect=AssertionError("CAIO execute must not reach an adapter"),
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "caio", "input": {"intent": "execute"}},
            format="json",
        )
    assert res.status_code == 201
    assert res.json()["status"] == "failed"
    assert "CAIO" in res.json()["errorMessage"]


# ---------- 12. AgentBudget endpoints + spend decoration ----------


def test_admin_can_upsert_and_list_agent_budgets(admin_user, auth_client) -> None:
    client = auth_client(admin_user)
    res = client.post(
        "/api/ai/budgets/",
        {
            "agent": "ceo",
            "dailyBudgetUsd": "5.0000",
            "monthlyBudgetUsd": "100.0000",
            "isEnforced": True,
            "alertThresholdPct": 80,
        },
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["agent"] == "ceo"
    assert "dailySpendUsd" in body
    assert "monthlySpendUsd" in body

    # Upsert is idempotent on agent — second POST updates the existing row.
    res2 = client.post(
        "/api/ai/budgets/",
        {
            "agent": "ceo",
            "dailyBudgetUsd": "10.0000",
            "monthlyBudgetUsd": "200.0000",
            "isEnforced": False,
            "alertThresholdPct": 90,
        },
        format="json",
    )
    assert res2.status_code == 201
    assert AgentBudget.objects.filter(agent="ceo").count() == 1
    assert AgentBudget.objects.get(agent="ceo").is_enforced is False

    list_res = client.get("/api/ai/budgets/")
    assert list_res.status_code == 200
    assert any(row["agent"] == "ceo" for row in list_res.json())


def test_budget_endpoints_admin_only(viewer_user, auth_client) -> None:
    client = auth_client(viewer_user)
    res = client.get("/api/ai/budgets/")
    assert res.status_code == 403
