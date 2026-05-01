"""Phase 5C — WhatsApp AI Chat Sales Agent orchestration.

End-to-end pipeline triggered by an inbound message:

1. Idempotency check on the inbound message id.
2. Conversation context build (recent messages, customer 360, recent
   order/payment, Claim Vault for the detected category, current AI
   state).
3. Greeting fast-path — if the inbound matches a generic intro AND the
   conversation has no prior outbound, send the locked greeting
   template via :mod:`apps.whatsapp.services.queue_template_message`.
4. LLM dispatch via :mod:`apps.integrations.ai.dispatch.dispatch_messages`
   when ``AI_PROVIDER != "disabled"``. Prompt is built locally (this
   module) and grounded against the Approved Claim Vault.
5. JSON schema validation via :mod:`.ai_schema`.
6. Auto-send rate gate. Failures → suggestion stored, conversation
   flagged, no customer-facing send.
7. Order booking when ``action == 'book_order'`` AND all gates pass.
8. ₹499 advance payment link (Razorpay) when the LLM marks
   ``payment.shouldCreateAdvanceLink``.

Hard rules:
- ``AI_PROVIDER == 'disabled'`` → run is recorded but no auto-send.
- Claim Vault missing → fail closed; no medical content sent.
- CAIO actor token → refused at the WhatsApp service entry.
- Failed sends NEVER mutate Order / Payment / Shipment.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Mapping

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.compliance.models import Claim
from apps.crm.models import Customer
from apps.integrations.ai.base import AdapterStatus
from apps.integrations.ai.dispatch import dispatch_messages

from . import services
from .ai_schema import (
    BLOCKED_CLAIM_PHRASES,
    ChatAgentDecision,
    ChatAgentSchemaError,
    SALES_STAGES,
    SUPPORTED_CATEGORIES,
    parse_decision,
    reply_contains_blocked_phrase,
)
from .consent import has_whatsapp_consent
from .discount_policy import (
    PROACTIVE_RESCUE_TRIGGERS,
    TOTAL_DISCOUNT_HARD_CAP_PCT,
    evaluate_whatsapp_discount,
)
from .language import (
    LANG_HINDI,
    LANG_HINGLISH,
    LANGUAGE_CHOICES,
    detect_from_history,
    normalize_language,
)
from .models import (
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppTemplate,
)
from .claim_mapping import category_to_claim_product
from .grounded_reply_builder import (
    build_grounded_product_reply,
    build_objection_aware_reply,
    can_build_grounded_product_reply,
    can_build_objection_reply,
    classify_inbound_intent,
)
from .order_booking import OrderBookingError, book_order_from_decision
from .safety_validation import validate_safety_flags
from .template_registry import (
    GREETING_LOCKED_HINDI,
    TemplateRegistryError,
    get_template_for_action,
    language_to_template_tag,
)


logger = logging.getLogger(__name__)


GREETING_TRIGGER_KEYWORDS: tuple[str, ...] = (
    "hi",
    "hello",
    "hii",
    "hey",
    "namaste",
    "namaskar",
    "namaskaar",
    "hola",
    "help",
    "info",
    "details",
    "good morning",
    "good evening",
    "नमस्ते",
    "नमस्कार",
)


@dataclass
class OrchestrationOutcome:
    """Result of :func:`run_whatsapp_ai_agent`. Used by the API layer + tests."""

    conversation_id: str
    inbound_message_id: str
    action: str = "no_action"
    sent: bool = False
    sent_message_id: str = ""
    handoff_required: bool = False
    handoff_reason: str = ""
    order_id: str = ""
    payment_id: str = ""
    payment_url: str = ""
    detection_language: str = ""
    detected_category: str = ""
    stage: str = ""
    decision: ChatAgentDecision | None = None
    blocked_reason: str = ""
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run_whatsapp_ai_agent(
    *,
    conversation_id: str,
    inbound_message_id: str = "",
    triggered_by: str = "auto",
    actor_role: str = "ai_chat",
    force: bool = False,
    force_auto_reply: bool = False,
) -> OrchestrationOutcome:
    """Drive the AI Chat Agent for one conversation turn.

    The function is idempotent on ``inbound_message_id`` — the same
    inbound message will not produce two AI runs unless ``force=True``
    (used by the operator-triggered ``run-ai`` endpoint).

    Phase 5F-Gate Controlled AI Auto-Reply Test Harness:
    ``force_auto_reply=True`` lets a trusted CLI caller (the
    ``run_controlled_ai_auto_reply_test`` management command) bypass
    the ``WHATSAPP_AI_AUTO_REPLY_ENABLED`` env gate for one orchestrator
    call without flipping the env globally. Every other safety check
    (allow-list, Claim Vault, blocked phrase, safety flags, CAIO,
    matrix, idempotency) still runs. The CLI is responsible for
    confirming the destination is on the allow-list BEFORE forcing
    auto-reply; the limited-test-mode guard inside
    ``send_freeform_text_message`` is the last-line defence.
    """
    convo = (
        WhatsAppConversation.objects.select_related("customer", "connection")
        .filter(pk=conversation_id)
        .first()
    )
    if convo is None:
        raise ValueError(f"Conversation {conversation_id!r} not found.")

    inbound = None
    if inbound_message_id:
        inbound = (
            WhatsAppMessage.objects.filter(
                pk=inbound_message_id,
                conversation=convo,
                direction=WhatsAppMessage.Direction.INBOUND,
            ).first()
        )
        if inbound is None:
            raise ValueError(
                f"Inbound message {inbound_message_id!r} not found on conversation "
                f"{conversation_id!r}."
            )
    else:
        inbound = (
            WhatsAppMessage.objects.filter(
                conversation=convo,
                direction=WhatsAppMessage.Direction.INBOUND,
            )
            .order_by("-created_at")
            .first()
        )

    outcome = OrchestrationOutcome(
        conversation_id=convo.id,
        inbound_message_id=inbound.id if inbound else "",
    )

    ai_state = _read_ai_state(convo)
    outcome.stage = ai_state.get("stage") or "greeting"
    # Phase 5F-Gate Limited Auto-Reply Flag Plan — record the trigger
    # so downstream emits can distinguish a CLI-forced run from a
    # real webhook-driven one even though both share this orchestrator.
    ai_state["lastTriggeredBy"] = triggered_by
    ai_state["lastForceAutoReply"] = bool(force_auto_reply)

    # Idempotency on inbound id (skip if already processed unless force).
    if inbound is not None and not force:
        if inbound.id in (ai_state.get("processedMessageIds") or []):
            outcome.notes.append("idempotent_skip")
            return outcome

    write_event(
        kind="whatsapp.ai.run_started",
        text=f"WhatsApp AI run started · conversation={convo.id}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "conversation_id": convo.id,
            "inbound_message_id": inbound.id if inbound else "",
            "triggered_by": triggered_by,
        },
    )

    # ---- Hard-stop guards ----
    if not has_whatsapp_consent(convo.customer):
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            blocked_reason="consent_missing",
            handoff_reason="Customer has not opted in to WhatsApp.",
        )

    # AI suggestions disabled → just record + skip dispatch.
    if not _is_ai_enabled(convo, ai_state):
        outcome.notes.append("ai_disabled_for_conversation")
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            blocked_reason="ai_disabled",
        )

    # ---- Detect language up front. ----
    detection = detect_from_history(convo, inbound_message=inbound)
    outcome.detection_language = detection.language
    write_event(
        kind="whatsapp.ai.language_detected",
        text=f"Language detected · {detection.language}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "conversation_id": convo.id,
            "language": detection.language,
            "devanagari_ratio": detection.devanagari_ratio,
            "marker_hits": detection.hinglish_marker_hits,
        },
    )

    # ---- Greeting fast-path ----
    inbound_body = (inbound.body if inbound else "").strip()
    convo_has_outbound = WhatsAppMessage.objects.filter(
        conversation=convo,
        direction=WhatsAppMessage.Direction.OUTBOUND,
    ).exists()

    if (
        not convo_has_outbound
        and _looks_like_greeting(inbound_body)
    ):
        return _send_greeting(
            convo,
            outcome,
            ai_state,
            inbound,
            language=detection.language,
            triggered_by=triggered_by,
            actor_role=actor_role,
        )

    # ---- AI provider gate ----
    provider = (getattr(settings, "AI_PROVIDER", "disabled") or "disabled").lower()
    if provider == "disabled":
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            blocked_reason="ai_provider_disabled",
            handoff_reason="AI provider disabled in settings.",
        )

    # ---- Build context + prompt ----
    try:
        context = _build_context(convo, inbound, detection.language, ai_state)
        messages = _build_prompt(convo, inbound, context)
    except _ClaimVaultMissingError as exc:
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            blocked_reason="claim_vault_missing",
            handoff_reason=str(exc),
        )

    # ---- Dispatch ----
    try:
        result = dispatch_messages(messages)
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("WhatsApp AI dispatch raised: %s", exc)
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            blocked_reason="dispatch_error",
            handoff_reason=f"AI dispatch error: {exc}",
        )

    if result.status != AdapterStatus.SUCCESS:
        reason_msg = (
            result.error_message
            or (result.raw or {}).get("reason")
            or "AI dispatch did not succeed"
        )
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            blocked_reason=f"adapter_{result.status}",
            handoff_reason=str(reason_msg),
        )

    # ---- Parse + validate JSON ----
    response_text = str((result.output or {}).get("text") or "").strip()
    try:
        decision = parse_decision(_extract_json(response_text))
    except (ChatAgentSchemaError, ValueError) as exc:
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            blocked_reason="schema_invalid",
            handoff_reason=f"AI returned invalid JSON: {exc}",
        )

    outcome.decision = decision
    outcome.confidence = decision.confidence
    outcome.detected_category = decision.category
    if decision.category and decision.category != "unknown":
        normalized_product = category_to_claim_product(decision.category)
        counts = _claim_grounding_counts(decision.category)
        write_event(
            kind="whatsapp.ai.category_detected",
            text=f"Category detected · {decision.category}",
            tone=AuditEvent.Tone.INFO,
            payload={
                "conversation_id": convo.id,
                "category": decision.category,
                "normalized_claim_product": normalized_product,
                "claim_row_count": counts["claim_row_count"],
                "approved_claim_count": counts["approved_claim_count"],
                "disallowed_phrase_count": counts["disallowed_phrase_count"],
                # Backward-compat: old logs / queries that read
                # ``claim_count`` continue to work and now reflect the
                # **approved-phrase** count (the count operators care
                # about for grounding).
                "claim_count": counts["approved_claim_count"],
                "confidence": decision.confidence,
            },
        )

    # ---- Server-side safety flag validation (Phase 5E-Smoke-Fix-3 +
    # Phase 5F-Gate Real Inbound Deterministic Fallback Fix latest-
    # inbound safety isolation) ----
    # The LLM occasionally over-flags normal product inquiries as a
    # safety event — sometimes because older messages in the same
    # conversation history (synthetic scenario tests, prior unsafe
    # threads) bias its classification. Before evaluating the blockers,
    # downgrade any flag whose signal vocabulary is absent from the
    # LATEST inbound text. Real safety phrases stay intact.
    inbound_text_for_safety = (inbound.body if inbound is not None else "") or ""
    history_safety_flags = dict(decision.safety or {})
    corrected_safety, downgraded_flags = validate_safety_flags(
        inbound_text_for_safety,
        decision.safety,
    )
    if downgraded_flags:
        # Mutate in place: ChatAgentDecision is frozen, but its safety
        # dict is a regular dict. Replace contents so the rest of the
        # pipeline (and the audit payload below) sees the corrected
        # values.
        decision.safety.clear()
        decision.safety.update(corrected_safety)
        write_event(
            kind="whatsapp.ai.safety_downgraded",
            text=(
                f"Safety flags downgraded · {', '.join(downgraded_flags)} "
                f"· no matching signal in latest inbound"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "conversation_id": convo.id,
                "downgraded_flags": list(downgraded_flags),
                # Latest-inbound safety isolation snapshot.
                "latest_inbound_message_id": (
                    inbound.id if inbound is not None else ""
                ),
                "inbound_message_id": inbound.id if inbound is not None else "",
                "inbound_body_preview": inbound_text_for_safety[:160],
                "history_safety_flags": history_safety_flags,
                "latest_inbound_safety_flags": dict(corrected_safety),
                "history_safety_ignored_for_current_safe_query": True,
                "corrected_safety": dict(corrected_safety),
            },
        )

    # ---- Safety gates ----
    blocker = _safety_block(decision)
    if blocker:
        # Phase 5F-Gate Real Inbound Deterministic Fallback Fix —
        # claim_vault_not_used is a SOFT blocker (the LLM said it
        # didn't ground its answer, despite the backend having full
        # grounding). For real auto-reply runs we now attempt the same
        # deterministic Claim-Vault-grounded fallback the controlled
        # CLI uses, before finalizing as a block.
        fallback_outcome = _attempt_deterministic_grounded_fallback(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason=blocker,
            actor_role=actor_role,
            force_auto_reply=force_auto_reply,
        )
        if fallback_outcome is not None:
            return fallback_outcome
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason=blocker,
            handoff_reason=decision.handoff_reason or blocker,
        )

    # ---- Discount discipline (if the model proposed one) ----
    if decision.order_draft.get("discountPct", 0) > 0:
        rescue_trigger = (ai_state.get("refusalTrigger") or "").strip()
        eval_result = evaluate_whatsapp_discount(
            proposed_pct=decision.order_draft.get("discountPct", 0),
            current_total_pct=ai_state.get("totalDiscountPct") or 0,
            discount_ask_count=ai_state.get("discountAskCount") or 0,
            refusal_trigger=rescue_trigger,
            actor_role="operations",
        )
        # Phase 5E — also persist a DiscountOfferLog row so the order
        # surface and analytics see the offer regardless of channel.
        _record_phase5e_offer_log(
            convo,
            ai_state,
            decision,
            eval_result=eval_result,
        )
        if not eval_result.allowed:
            kind = (
                "whatsapp.ai.discount_blocked"
                if eval_result.handoff_required or eval_result.band == "blocked"
                else "whatsapp.ai.discount_objection_handled"
            )
            write_event(
                kind=kind,
                text=f"Discount evaluation · {eval_result.reason}",
                tone=AuditEvent.Tone.WARNING,
                payload={
                    "conversation_id": convo.id,
                    "proposed_pct": eval_result.proposed_pct,
                    "current_total_pct": eval_result.current_total_pct,
                    "final_total_pct": eval_result.final_total_pct,
                    "band": eval_result.band,
                    "notes": list(eval_result.notes),
                },
            )
            if eval_result.handoff_required:
                return _finalize_run(
                    convo,
                    outcome,
                    ai_state,
                    inbound,
                    decision=decision,
                    blocked_reason="discount_blocked",
                    handoff_reason=eval_result.reason,
                )
            # Strip the offer from the order draft and let the agent
            # continue without offering.
            decision.order_draft["discountPct"] = 0
        else:
            write_event(
                kind="whatsapp.ai.discount_offered",
                text=(
                    f"Discount offered · {eval_result.proposed_pct}% "
                    f"(total {eval_result.final_total_pct}%)"
                ),
                tone=AuditEvent.Tone.INFO,
                payload={
                    "conversation_id": convo.id,
                    "proposed_pct": eval_result.proposed_pct,
                    "current_total_pct": eval_result.current_total_pct,
                    "final_total_pct": eval_result.final_total_pct,
                    "band": eval_result.band,
                },
            )

    # ---- Auto-send rate gate ----
    rate_block = _rate_limit_block(convo)
    if rate_block:
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason=rate_block,
            handoff_reason=f"Rate limit hit: {rate_block}",
        )

    # ---- Confidence + auto-send config ----
    threshold = float(
        getattr(settings, "WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD", 0.75)
    )
    auto_enabled = bool(
        getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
    ) or bool(force_auto_reply)
    confidence_ok = decision.confidence >= threshold

    if not auto_enabled:
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason="auto_reply_disabled",
            handoff_reason=(
                "Auto reply disabled in settings; suggestion stored for "
                "operator review."
            ),
        )
    if not confidence_ok:
        # Phase 5F-Gate Real Inbound Deterministic Fallback Fix —
        # attempt the deterministic grounded fallback before finalizing
        # as low-confidence. The LLM may be returning a low confidence
        # on a normal grounded inquiry simply because of conservative
        # bias; the deterministic builder's reply has confidence 1.0
        # by construction (it is a literal Claim Vault assembly).
        fallback_outcome = _attempt_deterministic_grounded_fallback(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason="low_confidence",
            actor_role=actor_role,
            force_auto_reply=force_auto_reply,
        )
        if fallback_outcome is not None:
            return fallback_outcome
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason="low_confidence",
            handoff_reason=(
                f"AI confidence {decision.confidence:.2f} below threshold "
                f"{threshold:.2f}; suggestion stored."
            ),
        )

    # ---- Reply path (after all gates) ----
    if decision.action == "send_reply" or decision.action == "ask_question":
        return _send_freeform_reply(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            actor_role=actor_role,
        )

    if decision.action == "book_order":
        return _attempt_book_order(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            actor_role=actor_role,
        )

    if decision.action == "handoff":
        # Phase 5F-Gate Real Inbound Deterministic Fallback Fix —
        # attempt the deterministic fallback first. The controlled
        # CLI command short-circuits a true human-request handoff
        # BEFORE invoking the orchestrator (so the orchestrator never
        # sees one); on the real-inbound path the eligibility check
        # inside the fallback (normal product-info inquiry, no live
        # safety flag, mapped category) keeps human-call requests on
        # the original handoff path.
        fallback_outcome = _attempt_deterministic_grounded_fallback(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason="ai_handoff_requested",
            actor_role=actor_role,
            force_auto_reply=force_auto_reply,
        )
        if fallback_outcome is not None:
            return fallback_outcome
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason="ai_handoff_requested",
            handoff_reason=decision.handoff_reason or "AI requested handoff.",
        )

    # action == 'no_action' or unknown — attempt deterministic fallback
    # first, then store + done.
    fallback_outcome = _attempt_deterministic_grounded_fallback(
        convo,
        outcome,
        ai_state,
        inbound,
        decision=decision,
        blocked_reason="no_action",
        actor_role=actor_role,
        force_auto_reply=force_auto_reply,
    )
    if fallback_outcome is not None:
        return fallback_outcome
    outcome.notes.append("no_action_from_ai")
    return _finalize_run(
        convo,
        outcome,
        ai_state,
        inbound,
        decision=decision,
        blocked_reason="no_action",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _ClaimVaultMissingError(Exception):
    """Internal — raised when product context lacks an approved Claim row."""


def _is_ai_enabled(
    convo: WhatsAppConversation, ai_state: Mapping[str, Any]
) -> bool:
    enabled = ai_state.get("aiEnabled")
    if enabled is None:
        return True  # default-on for new conversations
    return bool(enabled)


def _looks_like_greeting(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return False
    if len(cleaned) <= 3 and any(ch.isalpha() for ch in cleaned):
        return True
    for kw in GREETING_TRIGGER_KEYWORDS:
        if cleaned == kw or cleaned.startswith(kw + " ") or cleaned == f"{kw}!":
            return True
    return False


def _read_ai_state(convo: WhatsAppConversation) -> dict[str, Any]:
    """Return a defensive copy of the conversation's ai metadata."""
    metadata = dict(convo.metadata or {})
    ai = dict(metadata.get("ai") or {})
    ai.setdefault("aiEnabled", True)
    ai.setdefault("aiMode", "auto")
    ai.setdefault("stage", "greeting")
    ai.setdefault("discountAskCount", 0)
    ai.setdefault("totalDiscountPct", 0)
    ai.setdefault("offeredDiscountPct", 0)
    ai.setdefault("processedMessageIds", [])
    ai.setdefault("handoffRequired", False)
    return ai


def _write_ai_state(
    convo: WhatsAppConversation, ai_state: Mapping[str, Any]
) -> None:
    metadata = dict(convo.metadata or {})
    metadata["ai"] = dict(ai_state)
    convo.metadata = metadata
    convo.save(update_fields=["metadata", "updated_at"])


def _send_greeting(
    convo: WhatsAppConversation,
    outcome: OrchestrationOutcome,
    ai_state: dict[str, Any],
    inbound: WhatsAppMessage | None,
    *,
    language: str,
    triggered_by: str,
    actor_role: str,
) -> OrchestrationOutcome:
    """Send the locked greeting template — fail closed if it isn't synced."""
    template_lang = language_to_template_tag(language)
    try:
        template = get_template_for_action(
            action_key="whatsapp.greeting",
            language=template_lang,
            connection=convo.connection,
        )
    except TemplateRegistryError as exc:
        write_event(
            kind="whatsapp.ai.greeting_blocked",
            text=f"Greeting template missing · {exc}",
            tone=AuditEvent.Tone.DANGER,
            payload={
                "conversation_id": convo.id,
                "language": language,
                "template_lang": template_lang,
            },
        )
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            blocked_reason="greeting_template_missing",
            handoff_reason=str(exc),
        )

    try:
        queued = services.queue_template_message(
            customer=convo.customer,
            action_key="whatsapp.greeting",
            template=template,
            variables={},
            triggered_by=triggered_by or "ai_greeting",
            actor_role=actor_role,
            actor_agent="ai_chat",
            extra_metadata={
                "ai_generated": True,
                "ai_stage": "greeting",
                "language": language,
            },
        )
    except services.WhatsAppServiceError as exc:
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            blocked_reason=f"greeting_send_blocked:{exc.block_reason}",
            handoff_reason=str(exc),
        )

    # Schedule the actual send (eager-mode dev runs sync).
    from .tasks import send_whatsapp_message

    send_whatsapp_message.delay(queued.message.id)

    write_event(
        kind="whatsapp.ai.greeting_sent",
        text=f"Greeting sent · conversation={convo.id} · language={language}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "conversation_id": convo.id,
            "message_id": queued.message.id,
            "language": language,
            "template_id": template.id,
        },
    )

    ai_state["stage"] = "discovery"
    ai_state.setdefault("processedMessageIds", [])
    if inbound and inbound.id not in ai_state["processedMessageIds"]:
        ai_state["processedMessageIds"].append(inbound.id)
    ai_state["lastGreetingAt"] = timezone.now().isoformat()
    ai_state["lastAiAction"] = "greeting"
    ai_state["lastAiConfidence"] = 1.0
    ai_state["aiMode"] = "auto"
    _write_ai_state(convo, ai_state)

    outcome.action = "send_reply"
    outcome.sent = True
    outcome.sent_message_id = queued.message.id
    outcome.stage = "discovery"
    outcome.confidence = 1.0
    outcome.notes.append("greeting_sent")

    write_event(
        kind="whatsapp.ai.run_completed",
        text=f"AI run completed · conversation={convo.id} · greeting",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "conversation_id": convo.id,
            "action": "greeting",
            "stage": "discovery",
        },
    )
    return outcome


def _safety_block(decision: ChatAgentDecision) -> str:
    safety = decision.safety
    if safety.get("medicalEmergency"):
        return "medical_emergency"
    if safety.get("sideEffectComplaint"):
        return "side_effect_complaint"
    if safety.get("legalThreat"):
        return "legal_threat"
    if safety.get("angryCustomer") and decision.action != "handoff":
        return "angry_customer"
    if not safety.get("claimVaultUsed"):
        # If the model says it didn't ground the answer, demand handoff.
        return "claim_vault_not_used"
    blocked = reply_contains_blocked_phrase(decision.reply_text)
    if blocked:
        return f"blocked_phrase:{blocked}"
    return ""


def _rate_limit_block(convo: WhatsAppConversation) -> str:
    """Cheap rate limit using AuditEvent counts.

    Phase 5C uses the audit ledger as the rate-limit oracle (already
    persisted, already indexed). Production can swap in Redis later.
    """
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)
    max_turns = int(
        getattr(settings, "WHATSAPP_AI_MAX_TURNS_PER_CONVERSATION_PER_HOUR", 10)
    )
    max_msgs = int(
        getattr(settings, "WHATSAPP_AI_MAX_MESSAGES_PER_CUSTOMER_PER_DAY", 30)
    )

    convo_turns = AuditEvent.objects.filter(
        kind="whatsapp.ai.reply_auto_sent",
        occurred_at__gte=hour_ago,
        payload__conversation_id=convo.id,
    ).count()
    if convo_turns >= max_turns:
        return "conversation_hourly_cap"

    customer_msgs = AuditEvent.objects.filter(
        kind="whatsapp.ai.reply_auto_sent",
        occurred_at__gte=day_ago,
        payload__customer_id=convo.customer_id,
    ).count()
    if customer_msgs >= max_msgs:
        return "customer_daily_cap"
    return ""


def _send_freeform_reply(
    convo: WhatsAppConversation,
    outcome: OrchestrationOutcome,
    ai_state: dict[str, Any],
    inbound: WhatsAppMessage | None,
    *,
    decision: ChatAgentDecision,
    actor_role: str,
) -> OrchestrationOutcome:
    """Persist + send the freeform AI reply through the WhatsApp service."""
    if not decision.reply_text:
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason="empty_reply_text",
            handoff_reason="AI returned send_reply with empty body.",
        )

    # We do NOT call queue_template_message for freeform — the message
    # is a Type.TEXT outbound. We persist directly via service helpers
    # so consent, idempotency, and CAIO guards all stay in force.
    try:
        message = services.send_freeform_text_message(
            customer=convo.customer,
            conversation=convo,
            body=decision.reply_text,
            actor_role=actor_role,
            actor_agent="ai_chat",
            ai_generated=True,
            metadata={
                "ai_stage": ai_state.get("stage"),
                "language": decision.language,
                "category": decision.category,
                "confidence": decision.confidence,
            },
        )
    except services.WhatsAppServiceError as exc:
        # Phase 5F-Gate Limited Auto-Reply Flag Plan — emit a typed
        # diagnostic when the auto-reply path was refused at the
        # final-send guard (limited test mode, consent, allow-list,
        # CAIO). Helps the operator distinguish "LLM proposed nothing"
        # from "LLM proposed but service-layer guard refused".
        from django.conf import settings as _settings

        write_event(
            kind="whatsapp.ai.auto_reply_guard_blocked",
            text=(
                f"Auto-reply guard blocked send · conversation={convo.id} "
                f"· reason={exc.block_reason}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "conversation_id": convo.id,
                "customer_id": convo.customer_id,
                "block_reason": exc.block_reason,
                "limited_test_mode": bool(
                    getattr(
                        _settings, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE", False
                    )
                ),
                "auto_reply_enabled": bool(
                    getattr(
                        _settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False
                    )
                ),
                "category": decision.category,
            },
        )
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason=f"freeform_send_blocked:{exc.block_reason}",
            handoff_reason=str(exc),
        )

    write_event(
        kind="whatsapp.ai.reply_auto_sent",
        text=f"AI reply auto-sent · conversation={convo.id}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "conversation_id": convo.id,
            "customer_id": convo.customer_id,
            "message_id": message.id,
            "language": decision.language,
            "category": decision.category,
            "confidence": decision.confidence,
            "preview": decision.reply_text[:160],
        },
    )

    # Phase 5F-Gate Limited Auto-Reply Flag Plan — additional typed
    # diagnostic when the global flag is what enabled this real
    # webhook-driven send (i.e. NOT a CLI-forced run). Helps the
    # operator audit the cohort soak ("is the flag actually firing
    # real auto-replies, and to which allow-listed numbers?").
    from django.conf import settings as _settings

    flag_enabled = bool(
        getattr(_settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
    )
    force_auto_reply_used = bool((ai_state or {}).get("lastForceAutoReply"))
    if flag_enabled and not force_auto_reply_used:
        from .meta_one_number_test import _digits_only

        digits = _digits_only(getattr(convo.customer, "phone", "") or "")
        write_event(
            kind="whatsapp.ai.auto_reply_flag_path_used",
            text=(
                f"WHATSAPP_AI_AUTO_REPLY_ENABLED auto-reply sent · "
                f"conversation={convo.id} · message={message.id}"
            ),
            tone=AuditEvent.Tone.SUCCESS,
            payload={
                "conversation_id": convo.id,
                "customer_id": convo.customer_id,
                "message_id": message.id,
                "phone_suffix": digits[-4:] if digits else "",
                "category": decision.category,
                "confidence": decision.confidence,
                "claim_vault_used": bool(
                    decision.safety.get("claimVaultUsed", False)
                ),
                "limited_test_mode": bool(
                    getattr(
                        _settings, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE", False
                    )
                ),
            },
        )

    # Update sales stage based on action.
    next_stage = ai_state.get("stage") or "discovery"
    if decision.action == "ask_question":
        if decision.category != "unknown":
            next_stage = "discovery"
    elif decision.action == "send_reply":
        if decision.category != "unknown" and ai_state.get("stage") in {
            "greeting",
            "discovery",
        }:
            next_stage = "category_detection"
    ai_state["stage"] = next_stage
    ai_state["lastAiAction"] = decision.action
    ai_state["lastAiConfidence"] = decision.confidence
    ai_state["lastReplyPreview"] = decision.reply_text[:240]
    ai_state.setdefault("processedMessageIds", [])
    if inbound and inbound.id not in ai_state["processedMessageIds"]:
        ai_state["processedMessageIds"].append(inbound.id)
    _write_ai_state(convo, ai_state)

    outcome.action = decision.action
    outcome.sent = True
    outcome.sent_message_id = message.id
    outcome.stage = next_stage

    write_event(
        kind="whatsapp.ai.run_completed",
        text=f"AI run completed · conversation={convo.id}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "conversation_id": convo.id,
            "action": decision.action,
            "stage": next_stage,
            "confidence": decision.confidence,
        },
    )
    return outcome


def _attempt_book_order(
    convo: WhatsAppConversation,
    outcome: OrchestrationOutcome,
    ai_state: dict[str, Any],
    inbound: WhatsAppMessage | None,
    *,
    decision: ChatAgentDecision,
    actor_role: str,
) -> OrchestrationOutcome:
    inbound_text = (inbound.body if inbound else "").strip().lower()
    confirmation_words = {
        "yes",
        "ok",
        "okay",
        "confirm",
        "haan",
        "han",
        "ji haan",
        "ji",
        "book",
        "book it",
        "book kar",
        "book karo",
        "order",
        "order karo",
        "order kar do",
        "kar do",
    }
    has_confirmation = any(w in inbound_text for w in confirmation_words)
    if not has_confirmation:
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason="missing_explicit_confirmation",
            handoff_reason=(
                "AI proposed book_order but customer has not explicitly "
                "confirmed in this turn."
            ),
        )

    try:
        booking = book_order_from_decision(
            conversation=convo,
            decision=decision,
            actor_role=actor_role,
        )
    except OrderBookingError as exc:
        return _finalize_run(
            convo,
            outcome,
            ai_state,
            inbound,
            decision=decision,
            blocked_reason=f"order_booking_blocked:{exc.code}",
            handoff_reason=str(exc),
        )

    ai_state["stage"] = "order_booked"
    ai_state["orderId"] = booking.order_id
    ai_state["lastAiAction"] = "book_order"
    ai_state.setdefault("processedMessageIds", [])
    if inbound and inbound.id not in ai_state["processedMessageIds"]:
        ai_state["processedMessageIds"].append(inbound.id)
    if booking.payment_id:
        ai_state["paymentId"] = booking.payment_id
        ai_state["paymentLink"] = booking.payment_url
    elif decision.payment.get("shouldCreateAdvanceLink"):
        ai_state["paymentLinkPending"] = True
    _write_ai_state(convo, ai_state)

    outcome.action = "book_order"
    outcome.order_id = booking.order_id
    outcome.payment_id = booking.payment_id
    outcome.payment_url = booking.payment_url
    outcome.stage = "order_booked"
    outcome.sent = bool(booking.confirmation_message_id)
    outcome.sent_message_id = booking.confirmation_message_id

    write_event(
        kind="whatsapp.ai.run_completed",
        text=f"AI run completed · order booked · {booking.order_id}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "conversation_id": convo.id,
            "action": "book_order",
            "order_id": booking.order_id,
            "payment_id": booking.payment_id,
        },
    )
    return outcome


_BLOCKED_REASON_TO_CALL_REASON: dict[str, str] = {
    "ai_handoff_requested": "ai_handoff_requested",
    "low_confidence": "low_confidence_repeated",
    "medical_emergency": "medical_emergency",
    "side_effect_complaint": "side_effect_complaint",
    "legal_threat": "legal_threat",
}


def _maybe_trigger_vapi_call(
    convo: WhatsAppConversation,
    inbound: WhatsAppMessage | None,
    *,
    blocked_reason: str,
    decision: ChatAgentDecision | None,
) -> None:
    """Phase 5D — route safe handoff reasons through the Vapi call service.

    Wrapped in a defensive try/except: a Vapi failure never breaks the
    orchestrator's audit + state-finalisation path. The handoff service
    itself records a handoff row in every outcome (failed / skipped /
    triggered) so operations always have a paper trail.
    """
    if not getattr(settings, "WHATSAPP_CALL_HANDOFF_ENABLED", False):
        return
    call_reason = _BLOCKED_REASON_TO_CALL_REASON.get(blocked_reason)
    if not call_reason and decision is not None:
        # Look at the LLM's handoff_reason text for the "customer asked
        # for a call" intent. The schema validator does not enumerate
        # this — the LLM emits a free-text reason and we pattern-match.
        text = (decision.handoff_reason or "").lower()
        if any(kw in text for kw in ("call me", "phone call", "call please", "talk on call")):
            call_reason = "customer_requested_call"
    if not call_reason:
        return
    try:
        from .call_handoff import trigger_vapi_call_from_whatsapp

        trigger_vapi_call_from_whatsapp(
            conversation=convo,
            reason=call_reason,
            inbound_message=inbound,
            trigger_source=WhatsAppHandoffToCall_TRIGGER_AI,
        )
    except Exception as exc:  # noqa: BLE001 - never fail the AI run
        logger.warning(
            "WhatsApp Vapi handoff trigger failed for %s: %s", convo.id, exc
        )


# Local alias so we don't have to import the full enum at module scope —
# the call_handoff module owns the value and accepts the literal string.
WhatsAppHandoffToCall_TRIGGER_AI = "ai"


_AI_STAGE_TO_OFFER_STAGE: dict[str, str] = {
    "greeting": "order_booking",
    "discovery": "order_booking",
    "category_detection": "order_booking",
    "product_explanation": "order_booking",
    "objection_handling": "order_booking",
    "price_presented": "order_booking",
    "discount_negotiation": "order_booking",
    "address_collection": "order_booking",
    "order_confirmation": "confirmation",
    "order_booked": "confirmation",
    "handoff_required": "customer_success",
}


def _record_phase5e_offer_log(
    convo: WhatsAppConversation,
    ai_state: Mapping[str, Any],
    decision: ChatAgentDecision,
    *,
    eval_result: Any,
) -> None:
    """Persist a Phase 5E :class:`DiscountOfferLog` row from a chat decision.

    Best-effort — never raises. The orchestrator's existing audit
    writes still fire; this row is a richer cross-channel record so the
    orders / analytics surfaces don't have to parse the audit ledger.
    """
    try:
        from apps.orders.models import DiscountOfferLog, Order
        from apps.orders.rescue_discount import (
            create_rescue_discount_offer,
        )

        proposed = int(decision.order_draft.get("discountPct") or 0)
        if proposed <= 0:
            return

        # Find the order, if any. The AI may propose discount before
        # the order is booked — that's fine; the log row records
        # ``order=None`` and surfaces in analytics by customer.
        order_id = (ai_state.get("orderId") or "").strip()
        order: Order | None = None
        if order_id:
            order = Order.objects.filter(pk=order_id).first()
        if order is None and convo.customer:
            order = (
                Order.objects.filter(phone=convo.customer.phone)
                .order_by("-created_at")
                .first()
            )
        if order is None:
            return

        stage_key = (ai_state.get("stage") or "").lower()
        offer_stage = _AI_STAGE_TO_OFFER_STAGE.get(stage_key, "order_booking")

        create_rescue_discount_offer(
            order=order,
            stage=offer_stage,
            source_channel=DiscountOfferLog.SourceChannel.WHATSAPP_AI,
            trigger_reason=str(ai_state.get("refusalTrigger") or "ai_discount_offer"),
            refusal_count=int(ai_state.get("discountAskCount") or 1),
            risk_level=str(ai_state.get("riskLevel") or ""),
            requested_pct=proposed,
            actor_role="operations",
            actor_agent="ai_chat",
            conversation=convo,
            metadata={
                "decision_band": getattr(eval_result, "band", ""),
                "decision_allowed": getattr(eval_result, "allowed", False),
                "decision_reason": getattr(eval_result, "reason", "")[:240],
                "current_total_pct": getattr(eval_result, "current_total_pct", 0),
                "final_total_pct": getattr(eval_result, "final_total_pct", 0),
            },
        )
    except Exception as exc:  # noqa: BLE001 - never break the orchestrator
        logger.warning(
            "Phase 5E DiscountOfferLog record failed for %s: %s",
            convo.id,
            exc,
        )


# ---------------------------------------------------------------------------
# Phase 5F-Gate Real Inbound Deterministic Fallback Fix
# ---------------------------------------------------------------------------


# Soft, non-safety blockers where the deterministic grounded fallback may
# produce a Claim-Vault-grounded reply for the real inbound webhook path.
# Hard safety blockers (medical / side-effect / legal / blocked-phrase /
# angry / discount / consent) never reach this branch.
_FALLBACK_ELIGIBLE_BLOCK_REASONS: frozenset[str] = frozenset(
    {
        "claim_vault_not_used",
        "low_confidence",
        "ai_handoff_requested",
        "no_action",
    }
)


def _attempt_deterministic_grounded_fallback(
    convo: WhatsAppConversation,
    outcome: OrchestrationOutcome,
    ai_state: dict[str, Any],
    inbound: WhatsAppMessage | None,
    *,
    decision: ChatAgentDecision,
    blocked_reason: str,
    actor_role: str,
    force_auto_reply: bool,
) -> OrchestrationOutcome | None:
    """Phase 5F-Gate Real Inbound Deterministic Fallback Fix.

    When the LLM blocked the auto-reply with a soft non-safety reason
    AND the backend has valid grounding (mapped category + approved
    Claim Vault entries) AND the latest inbound is a normal product-
    info inquiry with no live safety signal, build a deterministic
    Claim-Vault-grounded reply and dispatch it through the same final-
    send path the LLM would have used.

    Returns the orchestration outcome on success, or ``None`` when the
    fallback was skipped — the caller then emits the original block
    path through ``_finalize_run`` exactly as before.

    LOCKED rules:

    - Eligibility set is the same as the controlled CLI command's
      :data:`_FALLBACK_ELIGIBLE_BLOCK_REASONS`. Hard safety blockers
      (medical / side-effect / legal / blocked-phrase / consent /
      limited-mode-guard) never reach this helper.
    - Auto-reply must be enabled (env flag OR ``force_auto_reply=True``);
      otherwise the operator wanted a stored suggestion, not an
      auto-send. The fallback respects that.
    - The fallback NEVER bypasses consent, the limited-mode allow-list
      guard, CAIO, or idempotency. Send goes through
      :func:`apps.whatsapp.services.send_freeform_text_message` exactly
      like the LLM path.
    - The fallback NEVER mutates ``Order`` / ``Payment`` / ``Shipment``
      / ``DiscountOfferLog``.
    - ``claimVaultUsed=true`` is set ONLY because the validator inside
      :func:`build_grounded_product_reply` confirmed the reply text
      literally embeds an approved phrase.
    """
    if blocked_reason not in _FALLBACK_ELIGIBLE_BLOCK_REASONS:
        return None

    auto_reply_enabled = bool(
        getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
    ) or bool(force_auto_reply)
    if not auto_reply_enabled:
        # Auto-reply globally off and not forced → preserve existing
        # suggestion-only behaviour. The operator wants a stored
        # suggestion they can review, not a deterministic auto-send.
        return None

    if inbound is None:
        return None
    inbound_body = (inbound.body or "").strip()
    if not inbound_body:
        return None

    category = decision.category or ""
    if not category or category == "unknown":
        return None

    # Latest-inbound safety isolation: even though validate_safety_flags
    # already corrected the LLM's flags against the latest inbound text
    # earlier in the pipeline, defence-in-depth — refuse to fall back if
    # any blocking safety flag is still set.
    safety_flags = dict(decision.safety or {})
    blocking_flags = ("medicalEmergency", "sideEffectComplaint", "legalThreat")
    for flag in blocking_flags:
        if bool(safety_flags.get(flag)):
            return None

    # Look up approved + disallowed phrases for the mapped product.
    claims = _claims_for_category(category, convo.customer)
    approved_phrases: list[str] = []
    disallowed_phrases: list[str] = []
    for claim in claims:
        approved_phrases.extend(claim.approved or [])
        disallowed_phrases.extend(claim.disallowed or [])

    # Phase 5F-Gate Objection & Handoff Reason Refinement —
    # discount/price-objection inbounds get the objection-aware reply
    # ahead of the standard grounded reply. The objection builder
    # opens with a price-concern acknowledgement, embeds the first
    # approved phrase + ₹3000/30-capsules/₹499 advance, and explicitly
    # states no upfront concession. Unsafe inbounds (cure / guarantee
    # / side-effect inside an objection sentence) refuse outright —
    # the safety stack handles them.
    intent = classify_inbound_intent(inbound_body)
    fallback_kind = "deterministic_grounded_builder"
    fallback_note = "deterministic_grounded_fallback_used"

    if intent.discount_objection and not intent.unsafe:
        objection_eligibility = can_build_objection_reply(
            category=category,
            inbound_text=inbound_body,
            safety_flags=safety_flags,
            approved_claims=approved_phrases,
        )
        if objection_eligibility.eligible:
            objection_result = build_objection_aware_reply(
                normalized_product=objection_eligibility.normalized_product,
                approved_claims=approved_phrases,
                inbound_text=inbound_body,
                purchase_intent=bool(intent.purchase_intent),
            )
            if objection_result.ok:
                write_event(
                    kind="whatsapp.ai.objection_detected",
                    text=(
                        f"Objection detected · category={category} "
                        f"· type={intent.objection_type or 'discount'}"
                    ),
                    tone=AuditEvent.Tone.INFO,
                    payload={
                        "conversation_id": convo.id,
                        "customer_id": convo.customer_id,
                        "category": category,
                        "objection_type": intent.objection_type or "discount",
                        "purchase_intent": bool(intent.purchase_intent),
                    },
                )
                return _dispatch_deterministic_fallback(
                    convo,
                    outcome,
                    ai_state,
                    inbound,
                    decision=decision,
                    blocked_reason=blocked_reason,
                    actor_role=actor_role,
                    eligibility=objection_eligibility,
                    result=objection_result,
                    claims=claims,
                    fallback_kind="deterministic_objection_reply",
                    fallback_note="deterministic_objection_fallback_used",
                    success_audit_kind="whatsapp.ai.objection_reply_used",
                    failure_audit_kind="whatsapp.ai.objection_reply_blocked",
                )
            # Objection result was not ok — emit the failure and fall
            # through to the standard grounded path (defence-in-depth).
            write_event(
                kind="whatsapp.ai.objection_reply_blocked",
                text=(
                    f"Objection reply build failed · category={category} "
                    f"· reason={objection_result.fallback_reason}"
                ),
                tone=AuditEvent.Tone.WARNING,
                payload={
                    "conversation_id": convo.id,
                    "customer_id": convo.customer_id,
                    "category": category,
                    "normalized_claim_product": (
                        objection_eligibility.normalized_product
                    ),
                    "fallback_reason": objection_result.fallback_reason,
                    "validation": dict(objection_result.validation or {}),
                    "llm_blocked_reason": blocked_reason,
                },
            )

    eligibility = can_build_grounded_product_reply(
        category=category,
        inbound_text=inbound_body,
        safety_flags=safety_flags,
        approved_claims=approved_phrases,
        disallowed_phrases=disallowed_phrases,
    )
    if not eligibility.eligible:
        return None

    # Build the deterministic reply.
    result = build_grounded_product_reply(
        normalized_product=eligibility.normalized_product,
        approved_claims=approved_phrases,
        inbound_text=inbound_body,
        customer_name=convo.customer.name or "",
    )
    if not result.ok:
        write_event(
            kind="whatsapp.ai.deterministic_grounded_reply_blocked",
            text=(
                f"Deterministic grounded reply build failed · "
                f"category={category} · reason={result.fallback_reason}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "conversation_id": convo.id,
                "customer_id": convo.customer_id,
                "category": category,
                "normalized_claim_product": eligibility.normalized_product,
                "approved_claim_count": eligibility.approved_claim_count,
                "fallback_reason": result.fallback_reason,
                "validation": dict(result.validation or {}),
                "llm_blocked_reason": blocked_reason,
            },
        )
        return None

    return _dispatch_deterministic_fallback(
        convo,
        outcome,
        ai_state,
        inbound,
        decision=decision,
        blocked_reason=blocked_reason,
        actor_role=actor_role,
        eligibility=eligibility,
        result=result,
        claims=claims,
        fallback_kind=fallback_kind,
        fallback_note=fallback_note,
        success_audit_kind="whatsapp.ai.deterministic_grounded_reply_used",
        failure_audit_kind="whatsapp.ai.deterministic_grounded_reply_blocked",
    )

def _dispatch_deterministic_fallback(
    convo: WhatsAppConversation,
    outcome: OrchestrationOutcome,
    ai_state: dict[str, Any],
    inbound: WhatsAppMessage | None,
    *,
    decision: ChatAgentDecision,
    blocked_reason: str,
    actor_role: str,
    eligibility: Any,
    result: Any,
    claims: list,
    fallback_kind: str,
    fallback_note: str,
    success_audit_kind: str,
    failure_audit_kind: str,
) -> OrchestrationOutcome | None:
    """Internal dispatch for both grounded + objection deterministic
    fallbacks. Owns the final-send call, audit emits, and outcome /
    ai_state updates. Returns the orchestrator outcome on success or
    ``None`` when the final-send guard refused.

    ``fallback_kind`` is the value the CLI / monitor consumes for
    ``finalReplySource`` (``deterministic_grounded_builder`` or
    ``deterministic_objection_reply``). ``fallback_note`` is the entry
    appended to ``outcome.notes`` so the CLI can detect which path
    fired without re-deriving from audit rows.
    """
    category = decision.category or ""
    try:
        message = services.send_freeform_text_message(
            customer=convo.customer,
            conversation=convo,
            body=result.reply_text,
            actor_role=actor_role,
            actor_agent="ai_chat",
            ai_generated=True,
            metadata={
                "deterministic_grounded_fallback": True,
                "fallback_kind": fallback_kind,
                "category": category,
                "normalized_product": eligibility.normalized_product,
                "fallback_reason_for_llm_block": blocked_reason,
                "ai_stage": ai_state.get("stage"),
                "language": decision.language,
                "confidence": decision.confidence,
            },
        )
    except services.WhatsAppServiceError as exc:
        # The final-send guard refused (limited-mode allow-list,
        # consent, CAIO, idempotency). Emit the same guard-blocked
        # audit the LLM path emits, plus the deterministic-blocked
        # audit so the soak monitor can correlate the two failure
        # modes.
        write_event(
            kind="whatsapp.ai.auto_reply_guard_blocked",
            text=(
                f"Auto-reply guard blocked deterministic fallback · "
                f"conversation={convo.id} · reason={exc.block_reason}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "conversation_id": convo.id,
                "customer_id": convo.customer_id,
                "block_reason": exc.block_reason,
                "limited_test_mode": bool(
                    getattr(
                        settings,
                        "WHATSAPP_LIVE_META_LIMITED_TEST_MODE",
                        False,
                    )
                ),
                "auto_reply_enabled": bool(
                    getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
                ),
                "category": category,
                "deterministic_fallback": True,
                "fallback_kind": fallback_kind,
            },
        )
        write_event(
            kind=failure_audit_kind,
            text=(
                f"Deterministic fallback send refused · "
                f"kind={fallback_kind} · category={category} · "
                f"{exc.block_reason}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "conversation_id": convo.id,
                "customer_id": convo.customer_id,
                "category": category,
                "normalized_claim_product": eligibility.normalized_product,
                "fallback_reason": f"send_refused:{exc.block_reason}",
                "llm_blocked_reason": blocked_reason,
                "fallback_kind": fallback_kind,
            },
        )
        return None

    # Success — flip claimVaultUsed=True on the decision so downstream
    # consumers (CLI report, audit payload, OrchestrationOutcome
    # readers) see the corrected flag. The validator inside the
    # builder already confirmed the reply text literally embeds at
    # least one approved phrase, so this flip is truthful.
    if isinstance(decision.safety, dict):
        decision.safety["claimVaultUsed"] = True

    from .meta_one_number_test import _digits_only

    digits = _digits_only(getattr(convo.customer, "phone", "") or "")
    phone_suffix = digits[-4:] if digits else ""

    write_event(
        kind=success_audit_kind,
        text=(
            f"Deterministic fallback used · kind={fallback_kind} · "
            f"category={category} · product={eligibility.normalized_product} "
            f"· llm_block={blocked_reason}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "conversation_id": convo.id,
            "customer_id": convo.customer_id,
            "category": category,
            "normalized_claim_product": eligibility.normalized_product,
            "claim_row_count": len(claims),
            "approved_claim_count": eligibility.approved_claim_count,
            "fallback_reason": blocked_reason,
            "final_reply_source": fallback_kind,
            "fallback_kind": fallback_kind,
            "phone_suffix": phone_suffix,
            "outbound_message_id": message.id,
            "inbound_message_id": inbound.id if inbound else "",
            "used_approved_phrases": list(
                getattr(result, "used_approved_phrases", ()) or ()
            ),
            "triggered_by": ai_state.get("lastTriggeredBy") or "",
            "force_auto_reply": bool(
                (ai_state or {}).get("lastForceAutoReply")
            ),
            "trigger_path": "real_inbound_webhook",
        },
    )

    write_event(
        kind="whatsapp.ai.reply_auto_sent",
        text=(
            f"AI reply auto-sent ({fallback_kind}) · "
            f"conversation={convo.id}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "conversation_id": convo.id,
            "customer_id": convo.customer_id,
            "message_id": message.id,
            "language": decision.language,
            "category": decision.category,
            "confidence": decision.confidence,
            "preview": (result.reply_text or "")[:160],
            "final_reply_source": fallback_kind,
            "deterministic_fallback_used": True,
            "fallback_for_llm_block": blocked_reason,
        },
    )

    # Phase 5F-Gate Limited Auto-Reply Flag Plan emit — only when the
    # real env flag (NOT force_auto_reply) drove the auto-send. The
    # CLI controlled-test command sets force_auto_reply=True; that
    # path must NEVER appear in the soak monitor's flag-path counter.
    flag_enabled = bool(
        getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
    )
    force_auto_reply_used = bool((ai_state or {}).get("lastForceAutoReply"))
    if flag_enabled and not force_auto_reply_used:
        write_event(
            kind="whatsapp.ai.auto_reply_flag_path_used",
            text=(
                f"WHATSAPP_AI_AUTO_REPLY_ENABLED auto-reply sent "
                f"({fallback_kind}) · conversation={convo.id} · "
                f"message={message.id}"
            ),
            tone=AuditEvent.Tone.SUCCESS,
            payload={
                "conversation_id": convo.id,
                "customer_id": convo.customer_id,
                "message_id": message.id,
                "outbound_message_id": message.id,
                "inbound_message_id": inbound.id if inbound else "",
                "phone_suffix": phone_suffix,
                "category": decision.category,
                "normalized_claim_product": eligibility.normalized_product,
                "confidence": decision.confidence,
                "claim_vault_used": True,
                "deterministic_fallback_used": True,
                "final_reply_source": fallback_kind,
                "limited_test_mode": bool(
                    getattr(
                        settings,
                        "WHATSAPP_LIVE_META_LIMITED_TEST_MODE",
                        False,
                    )
                ),
            },
        )

    # Stage update — same as LLM send_reply path.
    next_stage = ai_state.get("stage") or "discovery"
    if decision.category != "unknown" and ai_state.get("stage") in {
        "greeting",
        "discovery",
    }:
        next_stage = "category_detection"
    ai_state["stage"] = next_stage
    ai_state["lastAiAction"] = "send_reply"
    threshold = float(
        getattr(settings, "WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD", 0.75)
    )
    ai_state["lastAiConfidence"] = max(decision.confidence, threshold)
    ai_state["lastReplyPreview"] = (result.reply_text or "")[:240]
    ai_state["lastDeterministicFallbackUsed"] = True
    ai_state["lastFallbackReason"] = blocked_reason
    ai_state["lastFallbackKind"] = fallback_kind
    ai_state.setdefault("processedMessageIds", [])
    if inbound and inbound.id not in ai_state["processedMessageIds"]:
        ai_state["processedMessageIds"].append(inbound.id)
    _write_ai_state(convo, ai_state)

    outcome.action = "send_reply"
    outcome.sent = True
    outcome.sent_message_id = message.id
    outcome.stage = next_stage
    outcome.notes.append(fallback_note)
    outcome.notes.append(f"fallback_for:{blocked_reason}")

    write_event(
        kind="whatsapp.ai.run_completed",
        text=(
            f"AI run completed · conversation={convo.id} · "
            f"{fallback_kind}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "conversation_id": convo.id,
            "action": "send_reply",
            "stage": next_stage,
            "confidence": decision.confidence,
            "final_reply_source": fallback_kind,
            "deterministic_fallback_used": True,
        },
    )
    return outcome


def _finalize_run(
    convo: WhatsAppConversation,
    outcome: OrchestrationOutcome,
    ai_state: dict[str, Any],
    inbound: WhatsAppMessage | None,
    *,
    decision: ChatAgentDecision | None = None,
    blocked_reason: str = "",
    handoff_reason: str = "",
) -> OrchestrationOutcome:
    """Mark a run finished. Stores suggestion + handoff state when applicable."""
    handoff = bool(blocked_reason and blocked_reason not in {"no_action"})
    if blocked_reason in {
        "ai_disabled",
        "ai_provider_disabled",
        "auto_reply_disabled",
        "low_confidence",
        "no_action",
    }:
        handoff = blocked_reason in {
            "ai_disabled",
            "ai_provider_disabled",
        }
        # low_confidence + auto_reply_disabled = suggestion stored,
        # but conversation stays open (no human escalation).

    if decision is not None:
        outcome.confidence = decision.confidence
        outcome.detection_language = decision.language
        outcome.detected_category = decision.category
        write_event(
            kind="whatsapp.ai.suggestion_stored",
            text=(
                f"AI suggestion stored · conversation={convo.id} · "
                f"reason={blocked_reason or 'unknown'}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "conversation_id": convo.id,
                "blocked_reason": blocked_reason,
                "confidence": decision.confidence,
                "action": decision.action,
                "preview": decision.reply_text[:160],
                "language": decision.language,
                "category": decision.category,
            },
        )
        ai_state["lastSuggestion"] = {
            "action": decision.action,
            "replyText": decision.reply_text[:1024],
            "category": decision.category,
            "language": decision.language,
            "confidence": decision.confidence,
            "blockedReason": blocked_reason,
        }

    if handoff:
        ai_state["handoffRequired"] = True
        ai_state["handoffReason"] = handoff_reason or blocked_reason
        # Phase 5F-Gate Claim Vault Grounding Fix — surface grounding
        # context on handoff audits too. claim_vault_not_used routes
        # through this branch, not reply_blocked, so the operator
        # needs the same diagnostics.
        category_for_audit = (
            decision.category if decision is not None else ""
        )
        normalized_product_for_audit = category_to_claim_product(
            category_for_audit
        )
        counts_for_audit = _claim_grounding_counts(category_for_audit)
        write_event(
            kind="whatsapp.ai.handoff_required",
            text=f"AI handoff · conversation={convo.id} · {blocked_reason}",
            tone=AuditEvent.Tone.WARNING,
            payload={
                "conversation_id": convo.id,
                "reason": blocked_reason,
                "handoff_reason": handoff_reason,
                "category": category_for_audit,
                "normalized_claim_product": normalized_product_for_audit,
                "claim_row_count": counts_for_audit["claim_row_count"],
                "approved_claim_count": counts_for_audit["approved_claim_count"],
                "disallowed_phrase_count": counts_for_audit[
                    "disallowed_phrase_count"
                ],
                # Backward-compat alias.
                "claim_count": counts_for_audit["approved_claim_count"],
                "confidence": (
                    decision.confidence if decision is not None else 0.0
                ),
            },
        )
        # Bump conversation status to escalated_to_human only for the
        # serious safety blocks; soft blocks keep status=open so ops
        # can still reply manually.
        if blocked_reason in {
            "medical_emergency",
            "side_effect_complaint",
            "legal_threat",
        }:
            convo.status = WhatsAppConversation.Status.ESCALATED
            convo.save(update_fields=["status", "updated_at"])
        # Phase 5D — opportunistic Vapi handoff for safe call reasons
        # (customer asked for a call, low confidence, AI requested
        # handoff). Safety reasons (medical / side-effect / legal)
        # write a skipped handoff row so a human picks it up.
        _maybe_trigger_vapi_call(
            convo,
            inbound,
            blocked_reason=blocked_reason,
            decision=decision,
        )
    elif blocked_reason:
        # auto_reply_disabled / low_confidence / no_action → record but
        # don't escalate. Phase 5F-Gate Claim Vault Grounding Fix —
        # carry the grounding context so log readers can see why.
        category_for_audit = (
            decision.category if decision is not None else ""
        )
        normalized_product = category_to_claim_product(category_for_audit)
        counts = _claim_grounding_counts(category_for_audit)
        write_event(
            kind="whatsapp.ai.reply_blocked",
            text=f"AI reply blocked · conversation={convo.id} · {blocked_reason}",
            tone=AuditEvent.Tone.INFO,
            payload={
                "conversation_id": convo.id,
                "reason": blocked_reason,
                "category": category_for_audit,
                "normalized_claim_product": normalized_product,
                "claim_row_count": counts["claim_row_count"],
                "approved_claim_count": counts["approved_claim_count"],
                "disallowed_phrase_count": counts["disallowed_phrase_count"],
                # Backward-compat alias.
                "claim_count": counts["approved_claim_count"],
                "confidence": (
                    decision.confidence if decision is not None else 0.0
                ),
            },
        )

    if inbound is not None:
        ai_state.setdefault("processedMessageIds", [])
        if inbound.id not in ai_state["processedMessageIds"]:
            ai_state["processedMessageIds"].append(inbound.id)
    _write_ai_state(convo, ai_state)

    outcome.handoff_required = handoff
    outcome.handoff_reason = handoff_reason
    outcome.blocked_reason = blocked_reason

    if blocked_reason and blocked_reason not in {"no_action"}:
        write_event(
            kind="whatsapp.ai.run_completed",
            text=f"AI run completed · {blocked_reason}",
            tone=AuditEvent.Tone.WARNING if handoff else AuditEvent.Tone.INFO,
            payload={
                "conversation_id": convo.id,
                "blocked_reason": blocked_reason,
                "handoff": handoff,
            },
        )
    return outcome


def _build_context(
    convo: WhatsAppConversation,
    inbound: WhatsAppMessage | None,
    language: str,
    ai_state: Mapping[str, Any],
) -> dict[str, Any]:
    customer = convo.customer
    recent_qs = (
        WhatsAppMessage.objects.filter(conversation=convo)
        .order_by("-created_at")[:8]
    )
    history = [
        {
            "id": m.id,
            "direction": m.direction,
            "body": (m.body or "")[:400],
            "at": m.created_at.isoformat() if m.created_at else "",
        }
        for m in reversed(list(recent_qs))
    ]

    last_order = None
    try:
        from apps.orders.models import Order  # local to avoid app cycles

        order_qs = (
            Order.objects.filter(phone=customer.phone)
            .order_by("-created_at")[:1]
        )
        if order_qs:
            o = order_qs[0]
            last_order = {
                "id": o.id,
                "stage": o.stage,
                "amount": int(o.amount or 0),
                "discount_pct": int(o.discount_pct or 0),
                "product": o.product,
                "city": o.city,
                "state": o.state,
            }
    except Exception:  # noqa: BLE001 - defensive
        last_order = None

    detected_category = ai_state.get("detectedCategory") or "unknown"
    claims = _claims_for_category(detected_category, customer)
    if not claims:
        # Phase 5C — only enforce Claim Vault grounding when we actually
        # need product text. The greeting fast-path already returned
        # before we get here, so the orchestration is heading toward
        # discovery / product explanation. If the customer hasn't named
        # a product yet, allow discovery questions WITHOUT a vault row.
        if detected_category != "unknown":
            raise _ClaimVaultMissingError(
                f"No approved Claim Vault entry for category '{detected_category}'."
            )

    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "city": customer.city,
            "state": customer.state,
            "language": language,
            "product_interest": customer.product_interest,
            "consent_whatsapp": bool(customer.consent_whatsapp),
        },
        "conversation": {
            "id": convo.id,
            "status": convo.status,
            "stage": ai_state.get("stage"),
            "discountAskCount": ai_state.get("discountAskCount") or 0,
            "totalDiscountPct": ai_state.get("totalDiscountPct") or 0,
            "language": language,
            "addressCollection": ai_state.get("addressCollection") or {},
        },
        "history": history,
        "inbound": (
            {
                "id": inbound.id,
                "body": (inbound.body or "")[:1000],
            }
            if inbound is not None
            else None
        ),
        "lastOrder": last_order,
        "claims": [
            {
                "product": c.product,
                "approved": list(c.approved or []),
                "disallowed": list(c.disallowed or []),
            }
            for c in claims
        ],
        "settings": {
            "standardPriceInr": 3000,
            "standardCapsuleCount": 30,
            "advanceAmountInr": 499,
            "totalDiscountCapPct": TOTAL_DISCOUNT_HARD_CAP_PCT,
            "currency": "INR",
            "discountDiscipline": (
                "no upfront discount; only after 2+ asks AND objection "
                "handling; per-stage band 0–20% (auto up to 10%); "
                "cumulative across all stages must never exceed 50%"
            ),
            "businessFactsAllowed": [
                "Standard price ₹3000 / 30 capsules",
                "Fixed advance ₹499",
                "Conservative usage guidance: use as directed on label / qualified practitioner",
                "Consult doctor for pregnancy / serious illness / allergies / existing medication",
            ],
        },
    }


def _claim_grounding_counts(category: str) -> dict[str, int]:
    """Phase 5F-Gate Controlled Reply Confidence Fix.

    Returns a structured count of Claim Vault grounding for the given
    AI category slug. Distinguishes:

    - ``claim_row_count`` — number of ``Claim`` rows whose
      ``product`` matches the normalized label (usually 0 or 1).
    - ``approved_claim_count`` — total entries across all
      ``Claim.approved`` lists for those rows.
    - ``disallowed_phrase_count`` — total entries across all
      ``Claim.disallowed`` lists for those rows.

    Defaults to all zeros when the category does not normalize. The
    helper is intentionally cheap so it can run on every audit emit.
    """
    normalized = category_to_claim_product(category) if category else ""
    if not normalized:
        return {
            "claim_row_count": 0,
            "approved_claim_count": 0,
            "disallowed_phrase_count": 0,
        }
    rows = list(
        Claim.objects.filter(product__iexact=normalized).only(
            "approved", "disallowed"
        )
    )
    approved_total = sum(len(r.approved or []) for r in rows)
    disallowed_total = sum(len(r.disallowed or []) for r in rows)
    return {
        "claim_row_count": len(rows),
        "approved_claim_count": approved_total,
        "disallowed_phrase_count": disallowed_total,
    }


def _claims_for_category(category: str, customer: Customer) -> list[Claim]:
    """Resolve a category slug → live ``Claim`` rows.

    Phase 5F-Gate Claim Vault Grounding Fix: the prior implementation
    filtered ``Claim.product`` with the **slug** (``weight-management``)
    via ``icontains`` — never matched ``Weight Management``, then fell
    through to ``product__icontains=customer.product_interest or ""``
    which silently returned **every** claim row when the customer's
    ``product_interest`` was blank. The orchestrator then either had
    zero relevant claims (LLM safely returned ``claimVaultUsed=false``)
    or a kitchen-sink prompt (LLM still returned
    ``claimVaultUsed=false`` because the grounding was incoherent).

    Now: the slug runs through the deterministic
    :func:`apps.whatsapp.claim_mapping.category_to_claim_product` table
    and the lookup is on ``Claim.product__iexact``. Customer
    ``product_interest`` is treated as an exact-match fallback only —
    never an empty-string substring match.
    """
    qs = Claim.objects.all()
    if category and category != "unknown":
        normalized = category_to_claim_product(category)
        if normalized:
            primary = list(qs.filter(product__iexact=normalized))
            if primary:
                return primary
        # Fall back to the customer's stored product_interest, but ONLY
        # when it is non-empty — never let "" become a substring match.
        interest = (customer.product_interest or "").strip()
        if interest:
            return list(qs.filter(product__iexact=interest))
        return []

    # category is unknown / empty.
    interest = (customer.product_interest or "").strip()
    if interest:
        return list(qs.filter(product__iexact=interest))
    return []


def _build_prompt(
    convo: WhatsAppConversation,
    inbound: WhatsAppMessage | None,
    context: Mapping[str, Any],
) -> list[dict[str, str]]:
    system_policy = (
        "You are the Nirogidhara WhatsApp Sales AI Agent. You are a "
        "customer-facing chat agent for an Ayurvedic medicine D2C "
        "company. You operate under Master Blueprint v2.0 hard stops:\n"
        "\n"
        "1) APPROVED CLAIM VAULT ONLY. Speak about products only using "
        "the approved phrases in the 'claims' block. Never use any of: "
        "'Guaranteed cure', 'Permanent solution', 'No side effects for "
        "everyone', 'Doctor ki zarurat nahi', '100% cure', or any "
        "'cures X disease' wording. If a claim isn't in the vault, do "
        "not say it.\n"
        "2) NEVER OFFER A DISCOUNT UPFRONT. Lead with the standard "
        "₹3000 / 30 capsule price. Only after the customer has asked "
        "for a discount at least 2 times AND objection-handling has "
        "been tried, you may offer one within 0–20%. Total discount "
        "across all stages must NEVER exceed 50%.\n"
        "3) ORDER BOOKING needs an explicit customer 'yes / haan / "
        "confirm / order' AND complete address + pincode + phone.\n"
        "4) HANDOFF on medical emergency, side-effect complaint, "
        "very angry customer, legal/refund threat, or repeated "
        "address/payment confusion. Set safety flags + action='handoff'.\n"
        "5) REPLY LANGUAGE matches the conversation 'language' "
        "({hindi, hinglish, english}). Keep replies short (1–3 short "
        "lines) and friendly.\n"
        "\n"
        "SAFETY FLAG DISCIPLINE (read carefully — false positives "
        "break the chat):\n"
        " - 'sideEffectComplaint' = TRUE only if the customer reports "
        "an actual adverse reaction AFTER consuming the product. "
        "Vocabulary that justifies it: 'side effect', 'reaction', "
        "'allergy / allergic', 'rash', 'swelling', 'itching', "
        "'vomiting', 'loose motion', 'discomfort', 'ulta asar', "
        "'problem ho gayi', 'dikkat ho gayi', 'medicine khane ke "
        "baad', 'tablet lene ke baad', 'capsule lene ke baad'. "
        "A customer asking about a product, asking the price, asking "
        "what it does, or asking for benefits is NOT a side-effect "
        "complaint. Set sideEffectComplaint=false in that case.\n"
        " - 'medicalEmergency' = TRUE only if the customer mentions "
        "an active emergency: 'chest pain', 'cannot breathe', "
        "'unconscious', 'bleeding', 'ambulance', 'hospital', "
        "'seene me dard', 'saans nahi', 'behosh', 'chakkar'.\n"
        " - 'legalThreat' = TRUE only if the customer explicitly "
        "mentions lawyer, court, police, FIR, consumer forum, fraud "
        "complaint, or a public review threat. A complaint about "
        "delivery delay is NOT a legal threat.\n"
        " - 'angryCustomer' = TRUE only on clearly hostile tone. "
        "Generic price negotiation or 'discount do' is NOT anger.\n"
        " - When in doubt and the inbound is a normal product / "
        "price / availability question, ALL safety flags are FALSE "
        "and you continue the sales conversation.\n"
        "\n"
        "BUSINESS FACTS YOU MAY STATE FREELY (these are business "
        "facts, NOT medical claims, so they do NOT need a Claim "
        "Vault entry):\n"
        " - Standard price: ₹3000 for one bottle of 30 capsules.\n"
        " - Fixed advance amount on order booking: ₹499.\n"
        " - Free / standard delivery and the order workflow can be "
        "described in plain operational language (e.g. 'aapko home "
        "delivery hogi', 'order confirm hone ke baad shipment 24-48 "
        "hours me chalu hota hai').\n"
        " - Conservative usage guidance: 'use as directed on the "
        "label or as advised by a qualified Ayurvedic practitioner'. "
        "Do not invent a dosage. If the customer asks for a specific "
        "dosage or treatment plan, say it must come from a doctor / "
        "qualified practitioner.\n"
        " - Lifestyle support (diet + activity) can be mentioned in "
        "GENERAL terms only when the Claim Vault for the product "
        "actually carries a lifestyle phrase. Do not invent any.\n"
        " - For pregnancy, serious illness, allergies, existing "
        "medication, or adverse reaction → ALWAYS suggest "
        "consulting their doctor and use action='handoff' with "
        "safety.medicalEmergency=false unless a medical emergency "
        "vocabulary trip fires.\n"
        "\n"
        "ACTION SELECTION DECISION TREE — read carefully. The "
        "controlled gate test BLOCKS replies with low confidence or "
        "action=handoff on grounded inquiries, so this discipline "
        "matters.\n"
        " A. Normal product / price / capsule-quantity / general "
        "safe-use inquiry, AND the 'claims' block below has at "
        "least one APPROVED phrase for the detected category, AND "
        "every safety flag is FALSE, AND the inbound contains no "
        "blocked-phrase trigger (cure, guarantee, 100%, side-effect, "
        "etc.):\n"
        "    → action='send_reply'\n"
        "    → confidence ≥ 0.85\n"
        "    → safety.claimVaultUsed=true\n"
        "    → replyText must literally include at least one phrase "
        "from the matching APPROVED Claim Vault entry, plus the "
        "₹3000 / 30 capsule price when the customer asked about "
        "price/quantity, plus the ₹499 advance when booking is "
        "discussed.\n"
        " B. Customer asks an open question for which there is NO "
        "approved Claim Vault entry yet (e.g. specific cure, "
        "diabetes guarantee, dosage exact mg):\n"
        "    → action='handoff'\n"
        "    → confidence may be low\n"
        "    → safety.claimVaultUsed=false\n"
        " C. Category is 'unknown' AND the customer has not named "
        "the product yet:\n"
        "    → action='ask_question'\n"
        "    → confidence reflects how well the next question helps\n"
        " D. Customer has explicitly confirmed booking (haan / yes / "
        "confirm / book) AND complete address + pincode + phone are "
        "present in the conversation context:\n"
        "    → action='book_order'\n"
        " E. Any of the safety vocabulary (medical emergency, side "
        "effect, legal threat) is in the inbound text:\n"
        "    → action='handoff'\n"
        "    → set the matching safety flag to true\n"
        "Use action='handoff' ONLY for cases B, E (and overflow "
        "cases like repeated address/payment confusion). Do NOT use "
        "handoff just because you feel cautious; the operator "
        "stands in for handoff and the customer experience suffers "
        "if every grounded inquiry ends in handoff.\n"
    )

    schema_instructions = (
        "Return a SINGLE JSON OBJECT (no prose) with this exact shape:\n"
        "{\n"
        '  "action": "send_reply" | "ask_question" | "book_order" | '
        '"handoff" | "no_action",\n'
        '  "language": "hindi" | "hinglish" | "english",\n'
        '  "category": '
        "\"weight-management\" | \"blood-purification\" | \"men-wellness\""
        " | \"women-wellness\" | \"immunity\" | \"lungs-detox\""
        " | \"body-detox\" | \"joint-care\" | \"unknown\",\n"
        '  "confidence": <float 0.0..1.0>,\n'
        '  "replyText": "<the message you would send to the customer>",\n'
        '  "needsTemplate": false,\n'
        '  "handoffReason": "<short reason if action=handoff>",\n'
        '  "orderDraft": {\n'
        '    "customerName": "...", "phone": "...", "product": "...",\n'
        '    "skuId": "", "quantity": 1, "address": "...",\n'
        '    "pincode": "...", "city": "...", "state": "...",\n'
        '    "landmark": "", "discountPct": 0, "amount": 3000\n'
        "  },\n"
        '  "payment": {"shouldCreateAdvanceLink": false, "amount": 499},\n'
        '  "safety": {\n'
        '    "claimVaultUsed": true, "medicalEmergency": false,\n'
        '    "sideEffectComplaint": false, "legalThreat": false,\n'
        '    "angryCustomer": false\n'
        "  }\n"
        "}\n"
        "If you are uncertain about ANY safety check, prefer "
        "action='handoff' WITHOUT inventing a safety flag. Only set a "
        "safety flag to true when the inbound text contains the "
        "vocabulary listed in 'SAFETY FLAG DISCIPLINE' above. A "
        "normal product / price / availability inquiry leaves all "
        "safety flags false.\n"
        "\n"
        "FINAL CHECK before you emit the JSON: if the 'claims' block "
        "above has at least one APPROVED phrase for the detected "
        "category AND every safety flag is false AND the inbound is "
        "a normal product/price/quantity/use-guidance question, then "
        "you MUST use action='send_reply', confidence ≥ 0.85, and "
        "safety.claimVaultUsed=true. You MUST also literally include "
        "one of the APPROVED phrases from the 'claims' block in "
        "replyText (verbatim or with minor punctuation). Defaulting "
        "to action='handoff' on a grounded inquiry is a defect."
    )

    claims_block = "\n".join(
        f"- {c['product']}: APPROVED {'; '.join(c['approved']) or '(none)'}; "
        f"DISALLOWED {'; '.join(c['disallowed']) or '(none)'}"
        for c in context["claims"]
    ) or "(no Claim Vault entries surfaced for this conversation yet)"

    user_block = (
        "Conversation context (JSON):\n"
        + json.dumps(
            {
                "customer": context["customer"],
                "conversation": context["conversation"],
                "lastOrder": context["lastOrder"],
                "history": context["history"],
                "inbound": context["inbound"],
                "settings": context["settings"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n\nApproved Claim Vault for this conversation:\n"
        + claims_block
        + "\n\n"
        + schema_instructions
    )

    return [
        {"role": "system", "content": system_policy},
        {"role": "user", "content": user_block},
    ]


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extractor — most providers wrap JSON in code fences."""
    if not text:
        raise ValueError("Empty AI response.")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    if not cleaned:
        raise ValueError("Empty JSON body.")
    # Locate the outermost {...} if there is leading prose.
    if cleaned[0] != "{":
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object in AI response.")
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


__all__ = (
    "GREETING_TRIGGER_KEYWORDS",
    "OrchestrationOutcome",
    "run_whatsapp_ai_agent",
)
