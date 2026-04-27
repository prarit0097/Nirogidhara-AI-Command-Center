"""Phase 3C tests — Celery scheduler + cost tracking + provider fallback.

Coverage:

1. ``CELERY_TASK_ALWAYS_EAGER=True`` — tasks run synchronously and create
   AgentRuns without touching Redis.
2. Morning / evening schedule env vars are read into the beat schedule.
3. ``GET /api/ai/scheduler/status/`` works for admin/director and refuses
   viewer / operations / anonymous.
4. ``AI_PROVIDER=disabled`` produces a ``skipped`` AgentRun via the
   fallback dispatcher with no network calls.
5. Token usage + cost_usd + pricing_snapshot persist on the AgentRun.
6. Pricing table calculates OpenAI cost correctly for a known model.
7. Pricing table calculates Anthropic cost correctly for a known model.
8. Fallback chain hops to Anthropic when OpenAI returns a FAILED result;
   ``fallback_used=True`` and ``provider_attempts`` lists both attempts.
9. ClaimVaultMissing does NOT trigger fallback — failure is logged before
   any adapter is called.
10. CAIO still cannot execute (re-checked under the new dispatcher).
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.ai_governance.models import AgentRun
from apps.ai_governance.tasks import run_daily_ai_briefing_task
from apps.audit.models import AuditEvent
from apps.compliance.models import Claim
from apps.integrations.ai.base import AdapterResult, AdapterStatus
from apps.integrations.ai.pricing import (
    calculate_anthropic_cost,
    calculate_openai_cost,
)


# ---------- helpers ----------


def _seed_one_claim() -> Claim:
    return Claim.objects.create(
        product="Weight Management",
        approved=["Supports healthy metabolism"],
        disallowed=["Guaranteed weight loss"],
        doctor="Approved",
        compliance="Approved",
        version="v3.2",
    )


# ---------- 1. Celery eager mode runs the task ----------


def test_celery_task_runs_in_eager_mode(db, settings) -> None:
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    AgentRun.objects.all().delete()

    result = run_daily_ai_briefing_task.delay("morning").get(timeout=5)

    assert result["slot"] == "morning"
    assert result["ceo_status"] in {"skipped", "success", "failed"}
    assert result["caio_status"] in {"skipped", "success", "failed"}
    assert AgentRun.objects.filter(agent="ceo", triggered_by="scheduler:morning").exists()
    assert AgentRun.objects.filter(agent="caio", triggered_by="scheduler:morning").exists()
    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "ai.scheduler.daily_briefing.started" in kinds
    assert "ai.scheduler.daily_briefing.completed" in kinds


# ---------- 2. Schedule env vars reach Celery beat ----------


def test_beat_schedule_reads_env_settings(settings) -> None:
    settings.AI_DAILY_BRIEFING_MORNING_HOUR = 7
    settings.AI_DAILY_BRIEFING_MORNING_MINUTE = 30
    settings.AI_DAILY_BRIEFING_EVENING_HOUR = 20
    settings.AI_DAILY_BRIEFING_EVENING_MINUTE = 15
    from config.celery import build_beat_schedule

    schedule = build_beat_schedule()

    morning = schedule["ai-daily-briefing-morning"]["schedule"]
    evening = schedule["ai-daily-briefing-evening"]["schedule"]
    assert {7} == set(morning.hour)
    assert {30} == set(morning.minute)
    assert {20} == set(evening.hour)
    assert {15} == set(evening.minute)
    assert schedule["ai-daily-briefing-morning"]["args"] == ("morning",)
    assert schedule["ai-daily-briefing-evening"]["args"] == ("evening",)


# ---------- 3. Scheduler status endpoint perms ----------


def test_scheduler_status_admin_can_read(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "openai"
    settings.AI_PROVIDER_FALLBACKS = ["openai", "anthropic"]
    settings.AI_DAILY_BRIEFING_MORNING_HOUR = 9
    settings.AI_DAILY_BRIEFING_EVENING_HOUR = 18
    client = auth_client(admin_user)
    res = client.get("/api/ai/scheduler/status/")
    assert res.status_code == 200
    body = res.json()
    assert body["celeryConfigured"] is True
    assert body["redisConfigured"] is True
    assert body["timezone"] == "Asia/Kolkata"
    assert body["morningSchedule"] == {"hour": 9, "minute": 0}
    assert body["eveningSchedule"] == {"hour": 18, "minute": 0}
    assert body["aiProvider"] == "openai"
    assert body["fallbacks"] == ["openai", "anthropic"]


def test_scheduler_status_anonymous_blocked() -> None:
    res = APIClient().get("/api/ai/scheduler/status/")
    assert res.status_code in {401, 403}


def test_scheduler_status_viewer_blocked(viewer_user, auth_client) -> None:
    client = auth_client(viewer_user)
    res = client.get("/api/ai/scheduler/status/")
    assert res.status_code == 403


def test_scheduler_status_operations_blocked(operations_user, auth_client) -> None:
    client = auth_client(operations_user)
    res = client.get("/api/ai/scheduler/status/")
    assert res.status_code == 403


def test_scheduler_status_redacts_credentials(admin_user, auth_client, settings) -> None:
    settings.CELERY_BROKER_URL = "redis://user:supersecret@redis.internal:6379/0"
    client = auth_client(admin_user)
    res = client.get("/api/ai/scheduler/status/")
    assert res.status_code == 200
    body = res.json()
    assert "supersecret" not in body["brokerUrl"]
    assert body["brokerUrl"] == "redis://***@redis.internal:6379/0"


# ---------- 4. Disabled provider — no network call ----------


def test_disabled_provider_skips_network(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    settings.AI_PROVIDER_FALLBACKS = []
    _seed_one_claim()
    client = auth_client(admin_user)
    with patch(
        "apps.integrations.ai.openai_client.dispatch",
        side_effect=AssertionError("openai must NOT be called"),
    ), patch(
        "apps.integrations.ai.anthropic_client.dispatch",
        side_effect=AssertionError("anthropic must NOT be called"),
    ):
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ceo", "input": {"focus": "weight management"}},
            format="json",
        )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "skipped"
    assert body["provider"] == "disabled"


# ---------- 5. Cost tracking persists ----------


def test_cost_tracking_persists_on_agent_run(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    settings.AI_PROVIDER_FALLBACKS = ["openai"]
    settings.AI_MODEL = "gpt-5.1"
    _seed_one_claim()

    fake = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model="gpt-5.1",
        output={"text": "ok"},
        latency_ms=42,
        prompt_tokens=2000,
        completion_tokens=500,
        total_tokens=2500,
        cost_usd=float(
            calculate_openai_cost(
                model="gpt-5.1", prompt_tokens=2000, completion_tokens=500
            )[0]
        ),
        pricing_snapshot={
            "provider": "openai",
            "model": "gpt-5.1",
            "rates": {"input": 1.25, "output": 10.00},
        },
    )
    with patch("apps.integrations.ai.openai_client.dispatch", return_value=fake):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ceo", "input": {"focus": "weight management"}},
            format="json",
        )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "success"
    assert body["promptTokens"] == 2000
    assert body["completionTokens"] == 500
    assert body["totalTokens"] == 2500
    assert body["costUsd"] is not None
    assert body["pricingSnapshot"]["model"] == "gpt-5.1"

    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "ai.cost_tracked" in kinds


# ---------- 6. OpenAI pricing math ----------


def test_openai_pricing_calculation_matches_spec() -> None:
    # gpt-5.1: input 1.25, output 10.00 per 1M tokens.
    # Sample call: 2,000 input + 500 output, no cache hits.
    cost, snapshot = calculate_openai_cost(
        model="gpt-5.1",
        prompt_tokens=2000,
        completion_tokens=500,
    )
    # (2000 / 1_000_000) * 1.25 + (500 / 1_000_000) * 10.00
    # = 0.0025 + 0.005 = 0.0075
    assert cost == Decimal("0.007500")
    assert snapshot["model"] == "gpt-5.1"
    assert snapshot["unit"] == "per_1M_tokens"
    assert snapshot["rates"]["input"] == 1.25


def test_openai_pricing_with_cached_input() -> None:
    # 1,000 prompt total, 800 of which served from cache.
    # Non-cached: 200 × 1.25  → 0.00025
    # Cached: 800 × 0.125     → 0.00010
    # Output: 100 × 10.00     → 0.001
    # Total: 0.00135
    cost, _ = calculate_openai_cost(
        model="gpt-5.1",
        prompt_tokens=1000,
        completion_tokens=100,
        cached_input_tokens=800,
    )
    assert cost == Decimal("0.001350")


def test_openai_pricing_unknown_model_returns_none() -> None:
    cost, snapshot = calculate_openai_cost(
        model="gpt-99-imaginary",
        prompt_tokens=1000,
        completion_tokens=500,
    )
    assert cost is None
    assert snapshot["rates"] == {}


# ---------- 7. Anthropic pricing math ----------


def test_anthropic_pricing_calculation_matches_spec() -> None:
    # claude-sonnet-4-6: input 3, cache_write 3.75, cache_read 0.30, output 15.
    # Call: 1000 input + 500 output, 200 cache_write, 400 cache_read.
    # 1000 × 3.00       = 3000
    # 200 × 3.75        = 750
    # 400 × 0.30        = 120
    # 500 × 15.00       = 7500
    # Total raw = 11370 / 1_000_000 = 0.01137
    cost, snapshot = calculate_anthropic_cost(
        model="claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=500,
        cache_creation_tokens=200,
        cache_read_tokens=400,
    )
    assert cost == Decimal("0.011370")
    assert snapshot["model"] == "claude-sonnet-4-6"
    assert snapshot["rates"]["cache_write_5m"] == 3.75


# ---------- 8. Fallback chain — OpenAI fails, Anthropic succeeds ----------


def test_fallback_used_when_openai_fails(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    settings.AI_PROVIDER_FALLBACKS = ["openai", "anthropic"]
    _seed_one_claim()

    openai_failed = AdapterResult(
        status=AdapterStatus.FAILED,
        provider="openai",
        model="gpt-5.1",
        latency_ms=12,
        error_message="rate limit exceeded",
    )
    anthropic_success = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="anthropic",
        model="claude-sonnet-4-6",
        output={"text": "rescued by Claude"},
        latency_ms=88,
        prompt_tokens=1200,
        completion_tokens=400,
        total_tokens=1600,
        cost_usd=0.001234,
        pricing_snapshot={"provider": "anthropic", "model": "claude-sonnet-4-6"},
    )

    AuditEvent.objects.all().delete()
    with patch(
        "apps.integrations.ai.openai_client.dispatch", return_value=openai_failed
    ), patch(
        "apps.integrations.ai.anthropic_client.dispatch",
        return_value=anthropic_success,
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ceo", "input": {"focus": "weight management"}},
            format="json",
        )

    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "success"
    assert body["provider"] == "anthropic"
    assert body["fallbackUsed"] is True
    attempts = body["providerAttempts"]
    assert len(attempts) == 2
    assert attempts[0]["provider"] == "openai"
    assert attempts[0]["status"] == "failed"
    assert "rate limit" in attempts[0]["error"]
    assert attempts[1]["provider"] == "anthropic"
    assert attempts[1]["status"] == "success"

    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "ai.provider.fallback_used" in kinds


def test_no_fallback_when_first_provider_succeeds(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    settings.AI_PROVIDER_FALLBACKS = ["openai", "anthropic"]
    _seed_one_claim()

    success = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model="gpt-5.1",
        output={"text": "ok"},
    )
    with patch(
        "apps.integrations.ai.openai_client.dispatch", return_value=success
    ), patch(
        "apps.integrations.ai.anthropic_client.dispatch",
        side_effect=AssertionError("anthropic must NOT be called"),
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "ceo", "input": {"focus": "x"}},
            format="json",
        )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "success"
    assert body["fallbackUsed"] is False
    assert len(body["providerAttempts"]) == 1


# ---------- 9. ClaimVaultMissing must NOT trigger fallback ----------


def test_claim_vault_missing_does_not_invoke_any_adapter(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    settings.AI_PROVIDER_FALLBACKS = ["openai", "anthropic"]
    Claim.objects.all().delete()  # vault empty → ClaimVaultMissing
    with patch(
        "apps.integrations.ai.openai_client.dispatch",
        side_effect=AssertionError("openai must NOT be called"),
    ), patch(
        "apps.integrations.ai.anthropic_client.dispatch",
        side_effect=AssertionError("anthropic must NOT be called"),
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {"agent": "compliance", "input": {"product": "Weight Management"}},
            format="json",
        )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "failed"
    assert "approved claims" in body["errorMessage"].lower() or "claim" in body["errorMessage"].lower()


# ---------- 10. CAIO hard-stop survives the fallback refactor ----------


def test_caio_execute_intent_still_refused(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    settings.AI_PROVIDER_FALLBACKS = ["openai", "anthropic"]
    _seed_one_claim()
    with patch(
        "apps.integrations.ai.openai_client.dispatch",
        side_effect=AssertionError("openai must NOT be called for CAIO execute"),
    ), patch(
        "apps.integrations.ai.anthropic_client.dispatch",
        side_effect=AssertionError("anthropic must NOT be called for CAIO execute"),
    ):
        client = auth_client(admin_user)
        res = client.post(
            "/api/ai/agent-runs/",
            {
                "agent": "caio",
                "input": {"intent": "execute", "target": "order NRG-9999"},
            },
            format="json",
        )
    assert res.status_code == 201
    assert res.json()["status"] == "failed"
    assert "CAIO" in res.json()["errorMessage"]
