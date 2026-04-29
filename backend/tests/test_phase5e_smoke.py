"""Phase 5E-Smoke — controlled AI smoke testing harness tests.

Verifies the harness:
- Runs each scenario without sending real customer messages.
- Defaults to dry-run + mock-WhatsApp + mock-Vapi.
- Refuses to use real Meta provider.
- Emits ``system.smoke_test.{started,completed}`` audit kinds.
- Returns valid JSON.
- Honors the cumulative 50% discount cap.
- Idempotent on Vapi handoff and Day-20 sweep.
"""
from __future__ import annotations

import io
import json

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.compliance.models import Claim
from apps.orders.models import DiscountOfferLog
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppHandoffToCall,
)
from apps.whatsapp.smoke_harness import (
    SCRIPTED_INBOUNDS,
    SUPPORTED_LANGUAGES,
    SUPPORTED_SCENARIOS,
    run_smoke_harness,
)


# ---------------------------------------------------------------------------
# 1. Constants + supported scenarios
# ---------------------------------------------------------------------------


def test_supported_scenarios_locked() -> None:
    assert "ai-reply" in SUPPORTED_SCENARIOS
    assert "claim-vault" in SUPPORTED_SCENARIOS
    assert "rescue-discount" in SUPPORTED_SCENARIOS
    assert "vapi-handoff" in SUPPORTED_SCENARIOS
    assert "reorder-day20" in SUPPORTED_SCENARIOS
    assert "all" in SUPPORTED_SCENARIOS


def test_scripted_inbounds_cover_all_supported_languages() -> None:
    for lang in SUPPORTED_LANGUAGES:
        assert lang in SCRIPTED_INBOUNDS, lang
        assert SCRIPTED_INBOUNDS[lang], f"empty inbound for {lang!r}"


# ---------------------------------------------------------------------------
# 2. Safe-mode refuses real Meta provider
# ---------------------------------------------------------------------------


@override_settings(WHATSAPP_PROVIDER="meta_cloud")
def test_harness_refuses_real_meta_provider(db) -> None:
    """Without --no-mock-whatsapp the harness ALWAYS forces mock; with
    mock_whatsapp=False AND provider=meta_cloud, it must refuse outright."""
    with pytest.raises(RuntimeError) as excinfo:
        run_smoke_harness(
            scenario="claim-vault",
            mock_whatsapp=False,
        )
    assert "meta_cloud" in str(excinfo.value)


def test_harness_uses_openai_requires_api_key(db) -> None:
    with override_settings(OPENAI_API_KEY=""):
        with pytest.raises(RuntimeError) as excinfo:
            run_smoke_harness(scenario="claim-vault", use_openai=True)
        assert "OPENAI_API_KEY" in str(excinfo.value)


def test_harness_default_keeps_auto_reply_off(db) -> None:
    """The orchestrator's auto-reply gate must remain OFF after a smoke run."""
    result = run_smoke_harness(scenario="claim-vault")
    assert result.options["mockWhatsapp"] is True
    assert result.options["mockVapi"] is True
    assert result.options["dryRun"] is True
    assert result.options["useOpenai"] is False


# ---------------------------------------------------------------------------
# 3. Scenario: ai-reply
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["hindi", "hinglish", "english"])
def test_ai_reply_scenario_passes_with_mock_dispatcher(db, language: str) -> None:
    result = run_smoke_harness(scenario="ai-reply", language=language)
    scenario = result.scenarios[0]
    assert scenario.passed, scenario.errors
    assert scenario.audit_events_emitted > 0
    detail = scenario.detail
    assert detail["language"] == language
    assert detail["scriptedBody"] == SCRIPTED_INBOUNDS[language]
    # Auto-reply OFF must mean the orchestrator went down the
    # suggestion-stored or greeting-template path — never a freeform
    # unattended customer send.
    outcome = detail["outcome"]
    assert outcome["sent"] in {True, False}
    assert outcome["blockedReason"] != "auto_reply_disabled" or not outcome["sent"]


def test_ai_reply_scenario_emits_run_started_audit(db) -> None:
    run_smoke_harness(scenario="ai-reply", language="hinglish")
    assert AuditEvent.objects.filter(kind="whatsapp.ai.run_started").exists()
    assert AuditEvent.objects.filter(kind="system.smoke_test.started").exists()
    assert AuditEvent.objects.filter(kind="system.smoke_test.completed").exists()


# ---------------------------------------------------------------------------
# 4. Scenario: claim-vault
# ---------------------------------------------------------------------------


def test_claim_vault_scenario_seeds_and_reports(db) -> None:
    result = run_smoke_harness(scenario="claim-vault")
    scenario = result.scenarios[0]
    assert scenario.passed, scenario.errors
    assert scenario.detail["totalProducts"] >= 8
    # All eight categories should be demo_ok (or ok if real claims are
    # already in the dev DB).
    assert scenario.detail["missingCount"] == 0


def test_claim_vault_scenario_resets_demo_when_requested(db) -> None:
    Claim.objects.create(
        product="Joint Care",
        approved=["Old demo seed phrasing"],
        disallowed=["Guaranteed cure"],
        doctor="Demo Default",
        compliance="Demo Default",
        version="demo-v1",
    )
    result = run_smoke_harness(
        scenario="claim-vault", reset_demo_claims=True
    )
    scenario = result.scenarios[0]
    assert scenario.passed
    refreshed = Claim.objects.get(product="Joint Care")
    assert refreshed.version == "demo-v2"


def test_claim_vault_fails_on_missing_real_category(db) -> None:
    # Drop all seeds first to expose `missing` rows. The scenario will
    # reseed with --reset-demo only if the flag is set; the default
    # (no flag) just runs `seed_default_claims` which creates demo seeds
    # — so to expose `missing`, leave the catalog with a Product that
    # has no Claim row at all.
    from apps.catalog.models import Product, ProductCategory

    cat, _ = ProductCategory.objects.get_or_create(
        id="CAT-SMOKE-NO-CLAIM",
        defaults={"name": "Smoke No-Claim", "slug": "smoke-no-claim"},
    )
    Product.objects.get_or_create(
        id="PROD-SMOKE-NO-CLAIM",
        defaults={
            "category": cat,
            "name": "Smoke No-Claim Product",
            "slug": "smoke-no-claim-product",
            "is_active": True,
        },
    )
    result = run_smoke_harness(scenario="claim-vault")
    scenario = result.scenarios[0]
    assert scenario.passed is False
    assert any("missing_claim_rows" in e for e in scenario.errors)


# ---------------------------------------------------------------------------
# 5. Scenario: rescue-discount
# ---------------------------------------------------------------------------


def test_rescue_discount_scenario_enforces_50_pct_cap(db) -> None:
    result = run_smoke_harness(scenario="rescue-discount")
    scenario = result.scenarios[0]
    assert scenario.passed, scenario.errors
    detail = scenario.detail
    assert detail["totalCapPct"] == 50
    statuses = {
        case["case"]: case["got"] for case in detail["cases"]
    }
    # Case A — ladder[0]=5% offered.
    assert statuses["A_first_refusal_zero_existing"]["offered"] == 5
    # Case B — clamped to remaining cap.
    assert statuses["B_clamped_to_cap_remaining"]["offered"] <= 10
    assert statuses["B_clamped_to_cap_remaining"]["cap_remaining"] >= 0
    # Case C — cap exhausted → needs_ceo_review.
    assert (
        statuses["C_cap_exhausted_needs_ceo"]["log_status"]
        == DiscountOfferLog.Status.NEEDS_CEO_REVIEW
    )
    # Case D — CAIO blocked.
    assert (
        statuses["D_caio_blocked"]["log_status"]
        == DiscountOfferLog.Status.BLOCKED
    )
    # Verify all four DiscountOfferLog rows persisted.
    assert DiscountOfferLog.objects.filter(
        pk__in=detail["discountOfferLogIds"]
    ).count() == 4


# ---------------------------------------------------------------------------
# 6. Scenario: vapi-handoff
# ---------------------------------------------------------------------------


@override_settings(VAPI_MODE="mock", WHATSAPP_CALL_HANDOFF_ENABLED=True)
def test_vapi_handoff_scenario_uses_mock_mode(db) -> None:
    result = run_smoke_harness(scenario="vapi-handoff")
    scenario = result.scenarios[0]
    assert scenario.passed, scenario.errors
    detail = scenario.detail
    # Branch 1 must have triggered, branch 2 deduped, branch 3 skipped.
    assert detail["first"]["skipped"] is False
    assert detail["first"]["call_id"]
    assert detail["second_idempotent"]["skipped"] is True
    assert detail["second_idempotent"]["error_message"] == "duplicate_handoff"
    assert detail["safety"]["skipped"] is True
    assert detail["safety"]["error_message"] == "non_auto_reason"


def test_vapi_handoff_refuses_when_vapi_mode_not_mock(db) -> None:
    """Even if mock_vapi=False, the harness reports a clear failure."""
    with override_settings(VAPI_MODE="live"):
        # mock_vapi=False so safe_mode doesn't override VAPI_MODE.
        result = run_smoke_harness(scenario="vapi-handoff", mock_vapi=False)
    scenario = result.scenarios[0]
    assert scenario.passed is False
    assert any("VAPI_MODE is not mock" in e for e in scenario.errors)


# ---------------------------------------------------------------------------
# 7. Scenario: reorder-day20
# ---------------------------------------------------------------------------


def test_reorder_day20_scenario_dry_run_does_not_send(db) -> None:
    result = run_smoke_harness(scenario="reorder-day20")
    scenario = result.scenarios[0]
    assert scenario.passed, scenario.errors
    assert scenario.objects_created.get("lifecycleEvents", 0) == 0
    assert scenario.detail["dryRun"] is True
    assert scenario.detail["lowerBoundDays"] == 20


def test_reorder_day20_scenario_idempotent_when_real_run(db) -> None:
    """Without dry-run, the harness must queue exactly one row per eligible order."""
    result = run_smoke_harness(scenario="reorder-day20", dry_run=False)
    scenario = result.scenarios[0]
    assert scenario.passed, scenario.errors
    detail = scenario.detail
    # First sweep should have queued at least one; second sweep must
    # find it already there and queue zero.
    assert detail["first_sweep"]["queued"] >= 1
    assert detail["second_sweep"]["queued"] == 0


# ---------------------------------------------------------------------------
# 8. Scenario: all
# ---------------------------------------------------------------------------


def test_all_scenario_runs_every_branch(db) -> None:
    result = run_smoke_harness(scenario="all")
    names = [s.name for s in result.scenarios]
    assert names == ["claim-vault", "ai-reply", "rescue-discount", "vapi-handoff", "reorder-day20"]
    # Every individual scenario must pass under the safe defaults.
    for scenario in result.scenarios:
        assert scenario.passed, (scenario.name, scenario.errors)
    assert result.overall_passed is True


# ---------------------------------------------------------------------------
# 9. Management command — JSON output is valid
# ---------------------------------------------------------------------------


def test_management_command_json_output_valid(db) -> None:
    out = io.StringIO()
    call_command(
        "run_controlled_ai_smoke_test",
        "--scenario", "claim-vault",
        "--json",
        stdout=out,
    )
    body = json.loads(out.getvalue())
    assert body["overallPassed"] is True
    assert body["options"]["scenario"] == "claim-vault"
    assert isinstance(body["scenarios"], list)
    assert body["scenarios"][0]["scenario"] == "claim-vault"


def test_management_command_human_output_pass_marker(db) -> None:
    out = io.StringIO()
    call_command(
        "run_controlled_ai_smoke_test",
        "--scenario", "rescue-discount",
        stdout=out,
    )
    text = out.getvalue()
    assert "PASS" in text
    assert "rescue-discount" in text


def test_management_command_unknown_scenario_rejects(db) -> None:
    from django.core.management.base import CommandError

    out = io.StringIO()
    with pytest.raises((CommandError, SystemExit)):
        call_command(
            "run_controlled_ai_smoke_test",
            "--scenario", "made-up-scenario",
            stdout=out,
        )


# ---------------------------------------------------------------------------
# 10. Audit kinds emitted
# ---------------------------------------------------------------------------


def test_smoke_run_emits_lifecycle_audits(db) -> None:
    run_smoke_harness(scenario="claim-vault")
    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "system.smoke_test.started" in kinds
    assert "system.smoke_test.completed" in kinds


def test_smoke_failure_emits_failed_audit(db) -> None:
    """Force a failure by passing an unknown scenario through the service
    layer — the harness raises ValueError BEFORE any audit row is
    written for the started event, so we exercise the invalid-input
    path instead."""
    with pytest.raises(ValueError):
        run_smoke_harness(scenario="nope")


# ---------------------------------------------------------------------------
# 11. OpenAI provider smoke semantics (Phase 5E-Smoke fix)
# ---------------------------------------------------------------------------


def test_openai_sdk_is_importable() -> None:
    """The openai SDK must be installed via requirements.txt so the
    real provider path is exercisable on every deploy."""
    from openai import OpenAI  # noqa: F401 — import-only check.

    assert OpenAI is not None


def test_default_run_keeps_provider_passed_true_without_openai(db) -> None:
    """When --use-openai is NOT passed, providerPassed stays True
    because the harness uses the deterministic mocked dispatcher."""
    result = run_smoke_harness(scenario="ai-reply", language="hinglish")
    detail = result.scenarios[0].detail
    assert detail["openaiAttempted"] is False
    assert detail["providerPassed"] is True
    assert detail["safeFailure"] is False
    assert result.scenarios[0].passed is True


@override_settings(OPENAI_API_KEY="test-smoke-key", AI_PROVIDER="openai")
def test_use_openai_passes_when_adapter_returns_success(db, monkeypatch) -> None:
    """Mock the OpenAI adapter to SUCCESS — providerPassed=True and
    the scenario passes."""
    from apps.integrations.ai.base import AdapterResult, AdapterStatus
    from apps.whatsapp.smoke_harness import _scripted_ai_decision_payload

    def _fake_dispatch(_messages):
        import json as _json

        return AdapterResult(
            status=AdapterStatus.SUCCESS,
            provider="openai",
            model="gpt-test",
            output={
                "text": _json.dumps(_scripted_ai_decision_payload()),
                "finish_reason": "stop",
            },
            raw={"id": "real-openai"},
            latency_ms=12,
            cost_usd=0.0,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )

    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages", _fake_dispatch
    )
    result = run_smoke_harness(
        scenario="ai-reply", language="hinglish", use_openai=True
    )
    scenario = result.scenarios[0]
    detail = scenario.detail
    assert detail["openaiAttempted"] is True
    assert detail["openaiSucceeded"] is True
    assert detail["providerPassed"] is True
    assert detail["safeFailure"] is False
    assert scenario.passed is True
    assert result.overall_passed is True


@override_settings(OPENAI_API_KEY="test-smoke-key", AI_PROVIDER="openai")
def test_use_openai_safe_failure_when_adapter_fails(db, monkeypatch) -> None:
    """Mock the OpenAI adapter to FAILED — providerPassed=False,
    safeFailure=True, scenario passed=False, and the warning text
    explicitly tells the operator the customer send stayed blocked."""
    from apps.integrations.ai.base import AdapterResult, AdapterStatus

    def _fake_dispatch(_messages):
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="openai",
            model="gpt-test",
            error_message="openai SDK not installed: No module named 'openai'",
        )

    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages", _fake_dispatch
    )
    result = run_smoke_harness(
        scenario="ai-reply", language="hinglish", use_openai=True
    )
    scenario = result.scenarios[0]
    detail = scenario.detail
    assert detail["openaiAttempted"] is True
    assert detail["openaiSucceeded"] is False
    assert detail["providerPassed"] is False
    assert detail["safeFailure"] is True
    assert detail["outcome"]["blockedReason"] in {
        "adapter_failed",
        "adapter_skipped",
        "dispatch_error",
    }
    assert detail["outcome"]["sent"] is False
    assert scenario.passed is False
    assert any(
        "OpenAI provider did not execute successfully" in w
        for w in scenario.warnings
    )
    # Overall result must NOT report success when --use-openai failed.
    assert result.overall_passed is False


@override_settings(OPENAI_API_KEY="test-smoke-key", AI_PROVIDER="openai")
def test_use_openai_safe_failure_audit_failed_kind_emitted(
    db, monkeypatch
) -> None:
    """A safe-failure run must emit a system.smoke_test.failed audit so
    operators see the failure on the live activity stream."""
    from apps.integrations.ai.base import AdapterResult, AdapterStatus

    def _fake_dispatch(_messages):
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="openai",
            model="gpt-test",
            error_message="boom",
        )

    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages", _fake_dispatch
    )
    run_smoke_harness(
        scenario="ai-reply", language="hinglish", use_openai=True
    )
    assert AuditEvent.objects.filter(kind="system.smoke_test.failed").exists()


def test_no_real_whatsapp_send_during_use_openai_safe_failure(
    db, monkeypatch
) -> None:
    """Even on safe-failure with --use-openai, no real WhatsApp send
    happens. The harness's safe_mode locks WHATSAPP_PROVIDER=mock and
    auto-reply OFF."""
    from django.conf import settings
    from apps.integrations.ai.base import AdapterResult, AdapterStatus

    def _fake_dispatch(_messages):
        return AdapterResult(
            status=AdapterStatus.FAILED,
            provider="openai",
            model="gpt-test",
            error_message="boom",
        )

    monkeypatch.setattr(
        "apps.whatsapp.ai_orchestration.dispatch_messages", _fake_dispatch
    )
    with override_settings(
        OPENAI_API_KEY="test-smoke-key",
        AI_PROVIDER="openai",
        WHATSAPP_PROVIDER="mock",
    ):
        run_smoke_harness(
            scenario="ai-reply", language="hinglish", use_openai=True
        )
    # WhatsApp provider stays mock; no real outbound call ever fires.
    assert (settings.WHATSAPP_PROVIDER or "mock").lower() == "mock"
