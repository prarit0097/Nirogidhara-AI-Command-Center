"""Phase 5E-Smoke — Controlled Mock + OpenAI Smoke Testing Harness.

A safe surface for verifying the WhatsApp AI Chat Sales Agent, Claim
Vault gates, rescue discount engine, Vapi handoff, and Day-20 reorder
without sending real customer messages.

LOCKED safety rules:

- Defaults to ``dry_run=True``, ``mock_whatsapp=True``, ``mock_vapi=True``.
- Never flips ``WHATSAPP_PROVIDER`` away from ``mock`` unless the caller
  explicitly opts in via ``mock_whatsapp=False`` (the harness rejects
  ``meta_cloud`` outright — only mock + Baileys-dev allowed).
- Never calls real Vapi unless ``mock_vapi=False`` AND ``VAPI_MODE !=
  "mock"``. Default keeps mock.
- Real WhatsApp / Real Vapi customer-facing actions never fire by
  default. The smoke run NEVER promotes itself to live.
- All test fixtures use deterministic ``SMOKE-`` prefixed IDs so a
  re-run never duplicates rows.
- Master Event Ledger writes ``system.smoke_test.{started,completed,
  failed,warning}`` rows for every harness invocation.

The harness is invoked via:

    python manage.py run_controlled_ai_smoke_test --scenario <name>

See :mod:`apps.whatsapp.management.commands.run_controlled_ai_smoke_test`
for CLI wiring.
"""
from __future__ import annotations

import json
import logging
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Iterator
from unittest import mock

from django.conf import settings
from django.test.utils import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.compliance.coverage import build_coverage_report, coverage_for_product
from apps.compliance.models import Claim
from apps.crm.models import Customer
from apps.integrations.ai.base import AdapterResult, AdapterStatus
from apps.orders.models import DiscountOfferLog, Order
from apps.orders.rescue_discount import (
    TOTAL_DISCOUNT_HARD_CAP_PCT,
    calculate_rescue_discount_offer,
    create_rescue_discount_offer,
)

from .models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)


logger = logging.getLogger(__name__)


SUPPORTED_SCENARIOS: tuple[str, ...] = (
    "ai-reply",
    "claim-vault",
    "rescue-discount",
    "vapi-handoff",
    "reorder-day20",
    "all",
)

SUPPORTED_LANGUAGES: tuple[str, ...] = ("hindi", "hinglish", "english")

# Scripted inbound messages used by the ai-reply scenario. Each entry is
# a non-medical, conservative customer message that exercises the
# language detector + greeting + claim vault path.
SCRIPTED_INBOUNDS: dict[str, str] = {
    "hindi": "Namaste mujhe weight loss ke liye help chahiye",
    "hinglish": "Hi mujhe weight loss product ke baare me batana",
    "english": "Hello, I want to know about weight management product",
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    """Result of a single scenario run."""

    name: str
    passed: bool
    objects_created: dict[str, int] = field(default_factory=dict)
    audit_events_emitted: int = 0
    new_audit_kinds: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_action: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.name,
            "passed": self.passed,
            "objectsCreated": self.objects_created,
            "auditEventsEmitted": self.audit_events_emitted,
            "newAuditKinds": list(self.new_audit_kinds),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "nextAction": self.next_action,
            "detail": dict(self.detail),
        }


@dataclass
class HarnessResult:
    """Aggregate result returned to the management command + tests."""

    options: dict[str, Any]
    scenarios: list[ScenarioResult] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    overall_passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "options": dict(self.options),
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
            "overallPassed": self.overall_passed,
            "scenarios": [s.to_dict() for s in self.scenarios],
        }


# ---------------------------------------------------------------------------
# Safe-mode context
# ---------------------------------------------------------------------------


SMOKE_FORBIDDEN_PROVIDERS: frozenset[str] = frozenset({"meta_cloud"})


@contextmanager
def _safe_mode(
    *,
    mock_whatsapp: bool,
    mock_vapi: bool,
    use_openai: bool,
) -> Iterator[None]:
    """Apply the safest possible settings for a smoke run.

    The context manager rejects unsafe combinations (real Meta provider
    is never allowed by the harness; the operator must flip the
    ``WHATSAPP_PROVIDER`` env explicitly outside the harness if they
    really want a live send).
    """
    overrides: dict[str, Any] = {}

    current_provider = (
        getattr(settings, "WHATSAPP_PROVIDER", "mock") or "mock"
    ).lower()
    if mock_whatsapp:
        overrides["WHATSAPP_PROVIDER"] = "mock"
    elif current_provider in SMOKE_FORBIDDEN_PROVIDERS:
        raise RuntimeError(
            f"Smoke harness refuses to run with WHATSAPP_PROVIDER="
            f"{current_provider!r}. Set --mock-whatsapp or switch the "
            "provider to 'mock' / 'baileys_dev' before re-running."
        )

    if mock_vapi:
        overrides["VAPI_MODE"] = "mock"

    # Auto-reply must remain off during smoke so no real customer
    # message can leak even with provider=mock + use-openai. The flag
    # gates the ORCHESTRATOR action, not the LLM call — perfect for
    # smoke runs that only want to verify suggestions are stored.
    overrides["WHATSAPP_AI_AUTO_REPLY_ENABLED"] = False

    if use_openai:
        # Caller explicitly wants to hit OpenAI. Don't override
        # AI_PROVIDER — trust the env. Validate the API key exists.
        if not getattr(settings, "OPENAI_API_KEY", ""):
            raise RuntimeError(
                "use_openai=True requires OPENAI_API_KEY to be set in "
                "settings/.env. Refusing to run."
            )
    else:
        # Force the dispatcher into 'disabled' so the orchestrator
        # never makes a network call. The harness mocks the dispatcher
        # response separately when the scenario needs a deterministic
        # JSON decision (see :func:`_mock_ai_decision`).
        overrides["AI_PROVIDER"] = "disabled"

    with override_settings(**overrides):
        yield


# ---------------------------------------------------------------------------
# Scenario: ai-reply
# ---------------------------------------------------------------------------


def _scripted_ai_decision_payload() -> dict[str, Any]:
    """Deterministic JSON decision the harness feeds the orchestrator
    when ``use_openai=False``. Designed to pass every safety gate so
    the smoke run completes through to ``run_completed`` without
    triggering handoff."""
    return {
        "action": "send_reply",
        "language": "hinglish",
        "category": "weight-management",
        "confidence": 0.92,
        "replyText": (
            "Hi! Weight management ke liye humare paas Ayurvedic blend "
            "hai jo healthy lifestyle ke saath kaam karta hai. Aap "
            "apna naam aur city share kar sakte ho?"
        ),
        "needsTemplate": False,
        "handoffReason": "",
        "orderDraft": {
            "customerName": "",
            "phone": "",
            "product": "",
            "skuId": "",
            "quantity": 1,
            "address": "",
            "pincode": "",
            "city": "",
            "state": "",
            "landmark": "",
            "discountPct": 0,
            "amount": 3000,
        },
        "payment": {"shouldCreateAdvanceLink": False, "amount": 499},
        "safety": {
            "claimVaultUsed": True,
            "medicalEmergency": False,
            "sideEffectComplaint": False,
            "legalThreat": False,
            "angryCustomer": False,
        },
    }


def _mock_dispatch_messages(_messages):
    return AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="smoke-mock",
        model="smoke-mock",
        output={
            "text": json.dumps(_scripted_ai_decision_payload()),
            "finish_reason": "stop",
        },
        raw={"id": "smoke-mock"},
        latency_ms=1,
        cost_usd=0.0,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )


def _ensure_smoke_connection() -> WhatsAppConnection:
    connection, _ = WhatsAppConnection.objects.get_or_create(
        id="WAC-SMOKE-001",
        defaults={
            "provider": WhatsAppConnection.Provider.MOCK,
            "display_name": "Smoke Harness Connection",
            "phone_number": "+91 9000099900",
            "status": WhatsAppConnection.Status.CONNECTED,
        },
    )
    return connection


def _ensure_smoke_customer(*, language: str = "hinglish") -> Customer:
    customer, _ = Customer.objects.get_or_create(
        id="SMOKE-CUST-001",
        defaults={
            "name": "Smoke Test Customer",
            "phone": "+919999900001",
            "state": "MH",
            "city": "Pune",
            "language": language,
            "product_interest": "Weight Management",
            "consent_whatsapp": True,
        },
    )
    if customer.language != language:
        customer.language = language
        customer.save(update_fields=["language"])
    WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={
            "consent_state": WhatsAppConsent.State.GRANTED,
            "granted_at": timezone.now(),
            "source": "smoke",
        },
    )
    return customer


def _ensure_smoke_conversation(
    customer: Customer, connection: WhatsAppConnection
) -> WhatsAppConversation:
    convo, _ = WhatsAppConversation.objects.get_or_create(
        id="WCV-SMOKE-001",
        defaults={
            "customer": customer,
            "connection": connection,
            "status": WhatsAppConversation.Status.OPEN,
            "ai_status": WhatsAppConversation.AiStatus.AUTO_AFTER_APPROVAL,
            "unread_count": 1,
        },
    )
    return convo


def _create_smoke_inbound(
    convo: WhatsAppConversation, *, body: str, suffix: str
) -> WhatsAppMessage:
    msg, _ = WhatsAppMessage.objects.get_or_create(
        id=f"WAM-SMOKE-IN-{suffix}",
        defaults={
            "conversation": convo,
            "customer": convo.customer,
            "provider_message_id": f"wamid.SMOKE-{suffix}",
            "direction": WhatsAppMessage.Direction.INBOUND,
            "status": WhatsAppMessage.Status.DELIVERED,
            "type": WhatsAppMessage.Type.TEXT,
            "body": body,
            "queued_at": timezone.now(),
            "sent_at": timezone.now(),
            "delivered_at": timezone.now(),
        },
    )
    return msg


_PROVIDER_FAILURE_BLOCKED_REASONS: frozenset[str] = frozenset(
    {
        "ai_provider_disabled",
        "adapter_failed",
        "adapter_skipped",
        "dispatch_error",
    }
)


def _provider_succeeded(blocked_reason: str) -> bool:
    """Return True iff the LLM adapter actually returned SUCCESS.

    Phase 5E-Smoke uses ``blocked_reason`` from
    :class:`apps.whatsapp.ai_orchestration.OrchestrationOutcome` to
    decide whether the AI provider executed cleanly. Anything in
    :data:`_PROVIDER_FAILURE_BLOCKED_REASONS` means the adapter never
    returned SUCCESS — the orchestrator's downstream gates (claim
    vault, safety, blocked phrase, low confidence) DO count as
    provider success because the LLM did respond and the filtering
    happened on top of its output.
    """
    return blocked_reason not in _PROVIDER_FAILURE_BLOCKED_REASONS


def run_ai_reply_scenario(
    *,
    language: str,
    use_openai: bool,
    dry_run: bool,
) -> ScenarioResult:
    from apps.whatsapp.ai_orchestration import run_whatsapp_ai_agent
    from apps.whatsapp.template_registry import sync_templates_from_provider

    result = ScenarioResult(
        name="ai-reply",
        passed=False,
        next_action=(
            "Review WhatsAppConversation.metadata.ai + AuditEvent rows "
            "with kind 'whatsapp.ai.run_completed' to verify the scripted "
            "reply landed safely. Auto-reply stays OFF — no customer-facing "
            "send was made."
        ),
    )

    body = SCRIPTED_INBOUNDS.get(language, SCRIPTED_INBOUNDS["hinglish"])

    connection = _ensure_smoke_connection()
    # Seed the canonical lifecycle templates so the greeting fast-path
    # has a row to dispatch (mock-mode-only).
    sync_templates_from_provider(connection=connection, actor="smoke")
    customer = _ensure_smoke_customer(language=language)
    convo = _ensure_smoke_conversation(customer, connection)

    # Pre-seed an outbound on this conversation so the greeting
    # fast-path inside the orchestrator never short-circuits dispatch.
    # The scripted smoke inbounds all start with "hi" / "hello" /
    # "namaste" — without this seed, a fresh conversation would route
    # through the locked Hindi greeting template and the LLM adapter
    # would never be exercised. Idempotent via get_or_create.
    WhatsAppMessage.objects.get_or_create(
        id="WAM-SMOKE-AI-PRESEED",
        defaults={
            "conversation": convo,
            "customer": customer,
            "direction": WhatsAppMessage.Direction.OUTBOUND,
            "status": WhatsAppMessage.Status.SENT,
            "type": WhatsAppMessage.Type.TEMPLATE,
            "body": "smoke-preseed",
            "queued_at": timezone.now(),
            "sent_at": timezone.now(),
        },
    )

    inbound = _create_smoke_inbound(
        convo, body=body, suffix=f"AI-{language.upper()}"
    )

    pre_audit_count = AuditEvent.objects.count()
    pre_kinds = set(AuditEvent.objects.values_list("kind", flat=True).distinct())

    try:
        with ExitStack() as stack:
            if not use_openai:
                stack.enter_context(
                    mock.patch(
                        "apps.whatsapp.ai_orchestration.dispatch_messages",
                        new=_mock_dispatch_messages,
                    )
                )
                # When use_openai is False, the safe-mode context already
                # set AI_PROVIDER=disabled. Force re-enable just for this
                # scenario so the orchestrator passes the provider gate
                # but uses our mocked dispatch above.
                stack.enter_context(override_settings(AI_PROVIDER="smoke-mock"))
            outcome = run_whatsapp_ai_agent(
                conversation_id=convo.id,
                inbound_message_id=inbound.id,
                triggered_by="smoke",
                actor_role="ai_chat",
                force=True,
            )
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"orchestrator_raised: {exc}")
        return result

    new_audit = AuditEvent.objects.count() - pre_audit_count
    post_kinds = set(AuditEvent.objects.values_list("kind", flat=True).distinct())
    new_kinds = sorted(post_kinds - pre_kinds)

    # Phase 5E-Smoke fix — when --use-openai is passed, the harness
    # must distinguish a real provider success from a "safe failure"
    # where the adapter raised but the orchestrator correctly kept
    # any customer message blocked. Both are safety-correct, but only
    # the former proves the provider integration actually works.
    openai_attempted = bool(use_openai)
    openai_succeeded = (
        openai_attempted and _provider_succeeded(outcome.blocked_reason)
    )
    provider_passed = (not openai_attempted) or openai_succeeded
    safe_failure = openai_attempted and not openai_succeeded
    # Surface the adapter / handoff error string so operators don't
    # have to dig through nested outcome fields. Empty when the
    # provider succeeded.
    provider_error = (
        outcome.handoff_reason
        if (openai_attempted and not openai_succeeded)
        else ""
    )

    result.audit_events_emitted = new_audit
    result.new_audit_kinds = new_kinds
    result.objects_created = {
        "customers": 0
        if Customer.objects.filter(pk=customer.id).count() == 1
        else 1,
        "conversations": 1,
        "messages": 1,
    }
    result.detail = {
        "language": language,
        "scriptedBody": body,
        "outcome": {
            "action": outcome.action,
            "sent": outcome.sent,
            "blockedReason": outcome.blocked_reason,
            "handoffRequired": outcome.handoff_required,
            "handoffReason": outcome.handoff_reason,
            "stage": outcome.stage,
            "confidence": outcome.confidence,
            "detectedLanguage": outcome.detection_language,
            "detectedCategory": outcome.detected_category,
            "orderId": outcome.order_id,
            "paymentId": outcome.payment_id,
            "sentMessageId": outcome.sent_message_id,
        },
        "useOpenai": use_openai,
        "dryRun": dry_run,
        "openaiAttempted": openai_attempted,
        "openaiSucceeded": openai_succeeded,
        "providerPassed": provider_passed,
        "safeFailure": safe_failure,
        "providerError": provider_error,
        "blockedReason": outcome.blocked_reason,
    }

    if outcome.handoff_required and outcome.blocked_reason in {
        "medical_emergency",
        "side_effect_complaint",
        "legal_threat",
    }:
        result.errors.append(
            f"orchestrator_handoff_safety: {outcome.blocked_reason}"
        )
        return result

    # Soft warnings vs. hard fails.
    if outcome.blocked_reason == "claim_vault_missing":
        result.warnings.append(
            "claim_vault_missing — run scenario 'claim-vault' or "
            "'seed_default_claims' first."
        )
    if outcome.blocked_reason in {"ai_provider_disabled"}:
        result.warnings.append(
            "ai_provider_disabled — pass --use-openai or wire a mock "
            "dispatcher to exercise the LLM path."
        )

    expected_run_started = "whatsapp.ai.run_started" in new_kinds or any(
        k == "whatsapp.ai.run_started" for k in post_kinds
    )
    if not AuditEvent.objects.filter(kind="whatsapp.ai.run_started").exists():
        result.warnings.append("no whatsapp.ai.run_started audit row found")

    # Pass criteria: orchestrator returned without an unrecoverable
    # error, audits were emitted, and the auto-reply gate kept any
    # auto-send firmly off.
    auto_enabled = bool(getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False))
    if auto_enabled:
        result.errors.append(
            "WHATSAPP_AI_AUTO_REPLY_ENABLED was True during smoke — "
            "harness must keep it OFF."
        )
        return result
    if new_audit == 0:
        result.errors.append("no audit events emitted; orchestrator silent")
        return result

    # Phase 5E-Smoke fix — `--use-openai` requires the adapter to have
    # actually returned SUCCESS. A safe-failure (adapter blew up but
    # the orchestrator correctly kept the customer message blocked) is
    # explicitly reported but does NOT count as a pass — operators
    # would otherwise miss "the SDK isn't installed" or "the API key
    # is wrong" while the safe-defaults made everything look fine.
    if safe_failure:
        result.warnings.append(
            "OpenAI provider did not execute successfully; customer "
            "send remained safely blocked. "
            f"(blockedReason={outcome.blocked_reason!r}, "
            f"providerError={provider_error!r}). Treat as PROVIDER "
            "FAILURE — fix the OpenAI integration before flipping any "
            "automation flag."
        )
        result.next_action = (
            "Install the OpenAI SDK (pip install 'openai>=1.0,<2.0'), "
            "verify OPENAI_API_KEY + AI_PROVIDER=openai, then re-run "
            "with --use-openai. The harness must report "
            "openaiSucceeded=true before any flag flip."
        )
        return result

    result.passed = True
    return result


# ---------------------------------------------------------------------------
# Scenario: claim-vault
# ---------------------------------------------------------------------------


def run_claim_vault_scenario(*, reset_demo: bool = False) -> ScenarioResult:
    from django.core.management import call_command

    result = ScenarioResult(
        name="claim-vault",
        passed=False,
        next_action=(
            "If risk=missing or risk=weak appears, replace the row with a "
            "doctor-approved Claim before flipping any automation flag. "
            "If risk=demo_ok, the row is a demo seed — replace with real "
            "doctor-approved phrasing before live rollout."
        ),
    )

    pre_audit_count = AuditEvent.objects.count()

    try:
        if reset_demo:
            call_command("seed_default_claims", "--reset-demo")
        else:
            call_command("seed_default_claims")
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"seed_command_raised: {exc}")
        return result

    report = build_coverage_report()
    items = [item.to_dict() for item in report.items]

    missing = [i for i in items if i["risk"] == "missing"]
    weak = [i for i in items if i["risk"] == "weak"]
    demo_ok = [i for i in items if i["risk"] == "demo_ok"]
    ok = [i for i in items if i["risk"] == "ok"]
    weak_demo = [i for i in weak if i.get("isDemoDefault")]
    weak_real = [i for i in weak if not i.get("isDemoDefault")]

    if missing:
        result.errors.append(
            f"missing_claim_rows: {[i['product'] for i in missing]}"
        )
    if weak_demo:
        # Demo seeds should never be weak — Phase 5E-Hotfix-2 ensures
        # demo-v2 entries carry safe usage phrases. If any demo row is
        # still weak, the seed is broken — fail the scenario.
        result.errors.append(
            f"weak_demo_seeds: {[i['product'] for i in weak_demo]} — "
            "demo-v2 seeds should never be weak; re-run the harness "
            "with --reset-demo-claims."
        )
    if weak_real:
        # Real admin-added rows that lack usage hints are a soft signal:
        # ops should replace them with doctor-approved phrasing before
        # flipping any automation flag for the affected categories.
        result.warnings.append(
            f"weak_real_claim_rows: {[i['product'] for i in weak_real]} — "
            "real admin claims missing usage hints; ops must replace with "
            "doctor-approved wording before enabling automation for these "
            "categories."
        )
    for item in demo_ok:
        result.warnings.append(
            f"demo_ok: {item['product']} — replace with doctor-approved "
            "claim before live rollout."
        )

    result.audit_events_emitted = AuditEvent.objects.count() - pre_audit_count
    result.objects_created = {"claims": Claim.objects.count()}
    result.detail = {
        "totalProducts": report.total_products,
        "okCount": len(ok),
        "demoOkCount": len(demo_ok),
        "weakCount": len(weak),
        "weakDemoCount": len(weak_demo),
        "weakRealCount": len(weak_real),
        "missingCount": len(missing),
        "items": items,
    }
    result.passed = not missing and not weak_demo
    return result


# ---------------------------------------------------------------------------
# Scenario: rescue-discount
# ---------------------------------------------------------------------------


def _ensure_smoke_order_for_rescue(
    suffix: str, *, current_discount_pct: int
) -> Order:
    customer = _ensure_smoke_customer()
    order, _ = Order.objects.get_or_create(
        id=f"NRG-SMOKE-{suffix}",
        defaults={
            "customer_name": customer.name,
            "phone": customer.phone,
            "product": "Weight Management",
            "state": "MH",
            "city": "Pune",
            "amount": 3000,
            "discount_pct": current_discount_pct,
            "stage": Order.Stage.CONFIRMATION_PENDING,
            "agent": "Smoke",
            "created_at_label": "smoke",
        },
    )
    if order.discount_pct != current_discount_pct:
        order.discount_pct = current_discount_pct
        order.save(update_fields=["discount_pct"])
    return order


def run_rescue_discount_scenario() -> ScenarioResult:
    result = ScenarioResult(
        name="rescue-discount",
        passed=False,
        next_action=(
            "Review DiscountOfferLog rows for status=offered / "
            "needs_ceo_review / blocked. The 50% cumulative cap must "
            "block all over-cap requests; blocked rows should automint "
            "an ApprovalRequest via discount.rescue.ceo_review."
        ),
    )

    pre_audit_count = AuditEvent.objects.count()
    cases: list[dict[str, Any]] = []

    # Phase 5E rescue flags are normally OFF in production. The smoke
    # scenario exercises the math + cap + CEO escalation paths, so we
    # flip the flags ON for the duration of this scenario only — this
    # never sends a real customer message because WhatsApp is mocked
    # by the harness's safe_mode context, and the rescue creator only
    # writes DB rows + audit events.
    with override_settings(
        WHATSAPP_RESCUE_DISCOUNT_ENABLED=True,
        WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=True,
    ):
        # Case A — first refusal at 0% existing discount must allow
        # ladder[0]=5%.
        order_a = _ensure_smoke_order_for_rescue("A", current_discount_pct=0)
        rescue_a = calculate_rescue_discount_offer(
            order_a, stage=DiscountOfferLog.Stage.CONFIRMATION, refusal_count=1
        )
        log_a = create_rescue_discount_offer(
            order=order_a,
            stage=DiscountOfferLog.Stage.CONFIRMATION,
            source_channel=DiscountOfferLog.SourceChannel.OPERATOR,
            trigger_reason="smoke_first_refusal",
            refusal_count=1,
            actor_role="operations",
            actor_agent="smoke",
        )
        cases.append({
            "case": "A_first_refusal_zero_existing",
            "expected": {"allowed": True, "offered": 5},
            "got": {
                "allowed": rescue_a.allowed,
                "offered": rescue_a.offered_additional_pct,
                "log_status": log_a.status,
            },
        })

        # Case B — 40% existing → cap allows only 10% extra; ladder
        # asking for 15% must clamp.
        order_b = _ensure_smoke_order_for_rescue("B", current_discount_pct=40)
        rescue_b = calculate_rescue_discount_offer(
            order_b,
            stage=DiscountOfferLog.Stage.RTO,
            refusal_count=2,
            risk_level="high",
        )
        log_b = create_rescue_discount_offer(
            order=order_b,
            stage=DiscountOfferLog.Stage.RTO,
            source_channel=DiscountOfferLog.SourceChannel.RTO,
            trigger_reason="smoke_high_risk",
            refusal_count=2,
            risk_level="high",
            actor_role="operations",
            actor_agent="smoke",
        )
        cases.append({
            "case": "B_clamped_to_cap_remaining",
            "expected": {"offered_max": 10, "cap_remaining": 0},
            "got": {
                "offered": rescue_b.offered_additional_pct,
                "cap_remaining": rescue_b.cap_remaining_pct,
                "log_status": log_b.status,
            },
        })

        # Case C — 50% existing → cap exhausted, must flip to needs_ceo_review.
        order_c = _ensure_smoke_order_for_rescue("C", current_discount_pct=50)
        rescue_c = calculate_rescue_discount_offer(
            order_c, stage=DiscountOfferLog.Stage.CONFIRMATION, refusal_count=1
        )
        log_c = create_rescue_discount_offer(
            order=order_c,
            stage=DiscountOfferLog.Stage.CONFIRMATION,
            source_channel=DiscountOfferLog.SourceChannel.OPERATOR,
            trigger_reason="smoke_cap_exhausted",
            refusal_count=1,
            actor_role="operations",
            actor_agent="smoke",
        )
        cases.append({
            "case": "C_cap_exhausted_needs_ceo",
            "expected": {
                "allowed": False,
                "log_status": DiscountOfferLog.Status.NEEDS_CEO_REVIEW,
            },
            "got": {
                "allowed": rescue_c.allowed,
                "log_status": log_c.status,
            },
        })

        # Case D — CAIO actor must be refused at the rescue creator entry.
        order_d = _ensure_smoke_order_for_rescue("D", current_discount_pct=0)
        log_d = create_rescue_discount_offer(
            order=order_d,
            stage=DiscountOfferLog.Stage.CONFIRMATION,
            source_channel=DiscountOfferLog.SourceChannel.OPERATOR,
            trigger_reason="smoke_caio",
            refusal_count=1,
            actor_role="director",
            actor_agent="caio",
        )
        cases.append({
            "case": "D_caio_blocked",
            "expected": {"log_status": DiscountOfferLog.Status.BLOCKED},
            "got": {"log_status": log_d.status, "reason": log_d.blocked_reason},
        })

    # Pass criteria.
    failures: list[str] = []
    if not rescue_a.allowed or rescue_a.offered_additional_pct != 5:
        failures.append("A: first-refusal ladder[0]=5 not honored")
    if rescue_b.offered_additional_pct > 10 or rescue_b.cap_remaining_pct < 0:
        failures.append("B: cap clamping failed")
    if log_c.status != DiscountOfferLog.Status.NEEDS_CEO_REVIEW:
        failures.append("C: cap-exhausted did not flip to needs_ceo_review")
    if log_d.status != DiscountOfferLog.Status.BLOCKED:
        failures.append("D: CAIO actor was not refused")

    result.detail = {
        "cases": cases,
        "totalCapPct": TOTAL_DISCOUNT_HARD_CAP_PCT,
        "discountOfferLogIds": [log_a.pk, log_b.pk, log_c.pk, log_d.pk],
    }
    result.audit_events_emitted = AuditEvent.objects.count() - pre_audit_count
    result.objects_created = {"orders": 4, "discountOfferLogs": 4}

    if failures:
        result.errors.extend(failures)
        return result

    result.passed = True
    return result


# ---------------------------------------------------------------------------
# Scenario: vapi-handoff
# ---------------------------------------------------------------------------


def run_vapi_handoff_scenario() -> ScenarioResult:
    """Exercise the WhatsApp → Vapi handoff path in mock mode."""
    from apps.whatsapp.call_handoff import (
        NON_AUTO_REASONS,
        SAFE_CALL_REASONS,
        trigger_vapi_call_from_whatsapp,
    )

    result = ScenarioResult(
        name="vapi-handoff",
        passed=False,
        next_action=(
            "Inspect WhatsAppHandoffToCall rows + audit kinds "
            "whatsapp.handoff.* for the smoke conversation. The mock "
            "Vapi adapter wrote a deterministic provider_call_id; no "
            "real customer was dialed."
        ),
    )

    if (getattr(settings, "VAPI_MODE", "mock") or "mock").lower() != "mock":
        result.errors.append(
            "VAPI_MODE is not mock — refusing to run vapi-handoff smoke."
        )
        return result
    if not getattr(settings, "WHATSAPP_CALL_HANDOFF_ENABLED", False):
        # The flag is off, but the call_handoff service ignores the
        # flag in production — it's the orchestrator that gates on it.
        # The smoke run can still call the service directly.
        result.warnings.append(
            "WHATSAPP_CALL_HANDOFF_ENABLED is False — orchestrator "
            "would not auto-dial; harness exercises the service directly."
        )

    pre_audit_count = AuditEvent.objects.count()

    connection = _ensure_smoke_connection()
    customer = _ensure_smoke_customer()
    convo = _ensure_smoke_conversation(customer, connection)

    # Each smoke run needs a clean slate so prior `(conversation,
    # inbound_message, reason)` triples don't dedupe-skip the new run.
    # We delete only smoke-prefixed inbound rows + their handoff rows
    # — real production rows would never carry the SMOKE id prefix.
    WhatsAppHandoffToCall.objects.filter(
        conversation=convo,
        inbound_message__id__startswith="WAM-SMOKE-IN-VAPI-",
    ).delete()
    WhatsAppMessage.objects.filter(
        conversation=convo,
        id__startswith="WAM-SMOKE-IN-VAPI-",
    ).delete()

    # Different inbound rows for each test branch — the unique
    # constraint is on (conversation, inbound_message, reason).
    inbound_a = _create_smoke_inbound(convo, body="Call me please", suffix="VAPI-A")
    inbound_b = _create_smoke_inbound(convo, body="My side effect", suffix="VAPI-B")

    smoke_meta = {"smoke": True, "scenario": "vapi-handoff"}
    # Branch 1 — safe sales call reason. Should trigger.
    first = trigger_vapi_call_from_whatsapp(
        conversation=convo,
        reason="customer_requested_call",
        inbound_message=inbound_a,
        trigger_source=WhatsAppHandoffToCall.TriggerSource.SYSTEM,
        metadata=dict(smoke_meta),
    )
    # Branch 2 — same triple → idempotent skip.
    second = trigger_vapi_call_from_whatsapp(
        conversation=convo,
        reason="customer_requested_call",
        inbound_message=inbound_a,
        trigger_source=WhatsAppHandoffToCall.TriggerSource.SYSTEM,
        metadata=dict(smoke_meta),
    )
    # Branch 3 — medical emergency → must NOT auto-dial.
    safety = trigger_vapi_call_from_whatsapp(
        conversation=convo,
        reason="medical_emergency",
        inbound_message=inbound_b,
        trigger_source=WhatsAppHandoffToCall.TriggerSource.SYSTEM,
        metadata=dict(smoke_meta),
    )

    failures: list[str] = []
    if first.skipped:
        failures.append(
            f"safe-reason handoff was skipped: {first.error_message}"
        )
    if not second.skipped:
        failures.append("idempotent re-fire did NOT skip")
    if first.handoff_id != second.handoff_id:
        failures.append("idempotent re-fire returned a different handoff_id")
    if not safety.skipped:
        failures.append(
            "medical_emergency reason auto-dialed — must always skip"
        )
    if safety.error_message != "non_auto_reason":
        failures.append(
            f"medical_emergency error_message != 'non_auto_reason' "
            f"(got {safety.error_message!r})"
        )

    handoff_count = WhatsAppHandoffToCall.objects.filter(
        conversation=convo
    ).count()

    result.audit_events_emitted = AuditEvent.objects.count() - pre_audit_count
    result.objects_created = {"whatsappHandoffToCall": handoff_count}
    result.detail = {
        "first": {
            "handoff_id": first.handoff_id,
            "status": first.status,
            "call_id": first.call_id,
            "provider_call_id": first.provider_call_id,
            "skipped": first.skipped,
        },
        "second_idempotent": {
            "handoff_id": second.handoff_id,
            "skipped": second.skipped,
            "error_message": second.error_message,
        },
        "safety": {
            "handoff_id": safety.handoff_id,
            "skipped": safety.skipped,
            "error_message": safety.error_message,
            "status": safety.status,
        },
        "safeReasons": sorted(SAFE_CALL_REASONS),
        "nonAutoReasons": sorted(NON_AUTO_REASONS),
    }

    if failures:
        result.errors.extend(failures)
        return result
    result.passed = True
    return result


# ---------------------------------------------------------------------------
# Scenario: reorder-day20
# ---------------------------------------------------------------------------


def run_reorder_day20_scenario(*, dry_run: bool = True) -> ScenarioResult:
    from apps.whatsapp.reorder import (
        DAY20_LOWER_BOUND_DAYS,
        DAY20_UPPER_BOUND_DAYS,
        run_day20_reorder_sweep,
    )
    from apps.whatsapp.template_registry import sync_templates_from_provider

    result = ScenarioResult(
        name="reorder-day20",
        passed=False,
        next_action=(
            "Review WhatsAppLifecycleEvent rows with action_key="
            "whatsapp.reorder_day20_reminder. Idempotent: a re-run on "
            "the same eligible window produces zero new queued rows."
        ),
    )

    connection = _ensure_smoke_connection()
    sync_templates_from_provider(connection=connection, actor="smoke")
    customer = _ensure_smoke_customer()

    # Build (or refresh) a delivered order ~22 days old so it's in the
    # 20–27 day eligibility window.
    order, _ = Order.objects.get_or_create(
        id="NRG-SMOKE-DAY20",
        defaults={
            "customer_name": customer.name,
            "phone": customer.phone,
            "product": "Weight Management",
            "state": "MH",
            "city": "Pune",
            "amount": 3000,
            "stage": Order.Stage.DELIVERED,
            "agent": "Smoke",
            "created_at_label": "22 days ago",
        },
    )
    new_age = timezone.now() - timedelta(days=22)
    Order.objects.filter(pk=order.pk).update(
        created_at=new_age, stage=Order.Stage.DELIVERED
    )

    pre_audit_count = AuditEvent.objects.count()
    pre_lifecycle = WhatsAppLifecycleEvent.objects.filter(
        action_key="whatsapp.reorder_day20_reminder"
    ).count()

    # Always force lifecycle automation enabled inside the harness so
    # the sweep doesn't short-circuit on the global flag. The
    # WHATSAPP_REORDER_DAY20_ENABLED flag is honoured by the sweep
    # itself via `dry_run` (sweep returns early when both are false).
    with override_settings(
        WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True,
        WHATSAPP_REORDER_DAY20_ENABLED=True,
    ):
        sweep_first = run_day20_reorder_sweep(dry_run=dry_run)
        # Second sweep must be idempotent.
        sweep_second = run_day20_reorder_sweep(dry_run=dry_run)

    post_lifecycle = WhatsAppLifecycleEvent.objects.filter(
        action_key="whatsapp.reorder_day20_reminder"
    ).count()

    result.audit_events_emitted = AuditEvent.objects.count() - pre_audit_count
    result.objects_created = {
        "lifecycleEvents": post_lifecycle - pre_lifecycle,
    }
    result.detail = {
        "first_sweep": sweep_first.to_dict(),
        "second_sweep": sweep_second.to_dict(),
        "lowerBoundDays": DAY20_LOWER_BOUND_DAYS,
        "upperBoundDays": DAY20_UPPER_BOUND_DAYS,
        "dryRun": dry_run,
    }

    failures: list[str] = []
    if sweep_first.eligible < 1:
        failures.append("first sweep found zero eligible orders")
    if dry_run:
        # In dry-run we don't write WhatsAppLifecycleEvent rows, so
        # idempotency cannot be checked here — both sweeps will count
        # the same eligible order. Just confirm the count is stable.
        if sweep_second.eligible != sweep_first.eligible:
            failures.append(
                "second sweep eligible count differs from first in dry-run"
            )
    else:
        if sweep_first.queued < 1:
            failures.append("first sweep did not queue any reminder")
        if sweep_second.queued > 0:
            failures.append(
                "second sweep queued additional reminders — idempotency broken"
            )

    if failures:
        result.errors.extend(failures)
        return result
    result.passed = True
    return result


# ---------------------------------------------------------------------------
# Top-level harness runner
# ---------------------------------------------------------------------------


def run_smoke_harness(
    *,
    scenario: str = "all",
    dry_run: bool = True,
    mock_whatsapp: bool = True,
    mock_vapi: bool = True,
    use_openai: bool = False,
    language: str = "hinglish",
    customer_phone: str = "",
    reset_demo_claims: bool = False,
) -> HarnessResult:
    """Single entrypoint used by the management command + the test suite."""
    if scenario not in SUPPORTED_SCENARIOS:
        raise ValueError(
            f"Unsupported scenario {scenario!r}. "
            f"Choose from: {', '.join(SUPPORTED_SCENARIOS)}."
        )
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language {language!r}. "
            f"Choose from: {', '.join(SUPPORTED_LANGUAGES)}."
        )

    options = {
        "scenario": scenario,
        "dryRun": dry_run,
        "mockWhatsapp": mock_whatsapp,
        "mockVapi": mock_vapi,
        "useOpenai": use_openai,
        "language": language,
        "customerPhone": customer_phone,
        "resetDemoClaims": reset_demo_claims,
    }
    aggregate = HarnessResult(
        options=options,
        started_at=timezone.now().isoformat(),
    )

    write_event(
        kind="system.smoke_test.started",
        text=f"Smoke test started · scenario={scenario}",
        tone=AuditEvent.Tone.INFO,
        payload=options,
    )

    scenarios_to_run = (
        ["claim-vault", "ai-reply", "rescue-discount", "vapi-handoff", "reorder-day20"]
        if scenario == "all"
        else [scenario]
    )

    try:
        with _safe_mode(
            mock_whatsapp=mock_whatsapp,
            mock_vapi=mock_vapi,
            use_openai=use_openai,
        ):
            for name in scenarios_to_run:
                if name == "ai-reply":
                    aggregate.scenarios.append(
                        run_ai_reply_scenario(
                            language=language,
                            use_openai=use_openai,
                            dry_run=dry_run,
                        )
                    )
                elif name == "claim-vault":
                    aggregate.scenarios.append(
                        run_claim_vault_scenario(reset_demo=reset_demo_claims)
                    )
                elif name == "rescue-discount":
                    aggregate.scenarios.append(run_rescue_discount_scenario())
                elif name == "vapi-handoff":
                    aggregate.scenarios.append(run_vapi_handoff_scenario())
                elif name == "reorder-day20":
                    aggregate.scenarios.append(
                        run_reorder_day20_scenario(dry_run=dry_run)
                    )
    except Exception as exc:  # noqa: BLE001
        aggregate.overall_passed = False
        aggregate.completed_at = timezone.now().isoformat()
        write_event(
            kind="system.smoke_test.failed",
            text=f"Smoke test failed: {exc}",
            tone=AuditEvent.Tone.DANGER,
            payload={**options, "error": str(exc)[:480]},
        )
        raise

    aggregate.overall_passed = all(s.passed for s in aggregate.scenarios)
    aggregate.completed_at = timezone.now().isoformat()

    has_warnings = any(s.warnings for s in aggregate.scenarios)
    if not aggregate.overall_passed:
        write_event(
            kind="system.smoke_test.failed",
            text=(
                f"Smoke test FAILED · scenario={scenario} · "
                f"failed={[s.name for s in aggregate.scenarios if not s.passed]}"
            ),
            tone=AuditEvent.Tone.DANGER,
            payload={
                **options,
                "summary": [
                    {"scenario": s.name, "passed": s.passed, "errors": s.errors}
                    for s in aggregate.scenarios
                ],
            },
        )
    else:
        if has_warnings:
            write_event(
                kind="system.smoke_test.warning",
                text=f"Smoke test PASSED with warnings · scenario={scenario}",
                tone=AuditEvent.Tone.WARNING,
                payload={
                    **options,
                    "warnings": {
                        s.name: list(s.warnings)
                        for s in aggregate.scenarios
                        if s.warnings
                    },
                },
            )
        write_event(
            kind="system.smoke_test.completed",
            text=f"Smoke test completed · scenario={scenario}",
            tone=AuditEvent.Tone.SUCCESS,
            payload={
                **options,
                "summary": [
                    {
                        "scenario": s.name,
                        "passed": s.passed,
                        "warnings": list(s.warnings),
                    }
                    for s in aggregate.scenarios
                ],
            },
        )
    return aggregate


__all__ = (
    "HarnessResult",
    "SCRIPTED_INBOUNDS",
    "ScenarioResult",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_SCENARIOS",
    "run_ai_reply_scenario",
    "run_claim_vault_scenario",
    "run_rescue_discount_scenario",
    "run_reorder_day20_scenario",
    "run_smoke_harness",
    "run_vapi_handoff_scenario",
)
