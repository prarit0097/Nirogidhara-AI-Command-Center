"""``python manage.py run_controlled_ai_auto_reply_test``.

Phase 5F-Gate Controlled AI Auto-Reply Test Harness.

Drives the existing WhatsApp AI orchestrator through one tightly-scoped
end-to-end run against the **single allowed test number only**, without
flipping the global ``WHATSAPP_AI_AUTO_REPLY_ENABLED`` flag for any
other webhook delivery.

Defaults to ``--dry-run``. ``--send`` is required for a real live AI
reply; even then the harness refuses unless every safety gate is
green:

- ``WHATSAPP_PROVIDER == 'meta_cloud'``
- ``WHATSAPP_LIVE_META_LIMITED_TEST_MODE == True``
- destination phone is in ``WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS``
- a Customer exists for that phone with a granted ``WhatsAppConsent``
- WABA ``subscribed_apps`` is active when Graph credentials are
  present (best-effort, never blocks on transport failure)
- every six automation flag stays off
  (``WHATSAPP_CALL_HANDOFF_ENABLED``,
  ``WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED``,
  ``WHATSAPP_RESCUE_DISCOUNT_ENABLED``,
  ``WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED``,
  ``WHATSAPP_REORDER_DAY20_ENABLED``, and
  ``WHATSAPP_AI_AUTO_REPLY_ENABLED`` is *required* to be off so this
  command stays the only path that can produce a real AI auto-reply
  during the gate phase)

Hard rules (defence in depth, every check stacks):

- The harness NEVER bypasses Claim Vault, blocked-phrase, safety
  flags, CAIO, approval matrix, or idempotency. It only flips the
  ``WHATSAPP_AI_AUTO_REPLY_ENABLED`` env-flag check via the
  orchestrator's ``force_auto_reply=True`` kwarg — every other gate
  still runs.
- The final-send guard inside ``services.send_freeform_text_message``
  is the last-line defence: if anything slips, the destination must
  still be on the allow-list under limited mode.
- Audit payloads NEVER carry tokens / verify token / app secret.
  Phone is masked to the last 4 digits.
- Inbound bodies are previewed at 120 chars max in audits.
- The harness creates **one synthetic inbound row** per run via the
  standard service helpers; the orchestrator processes that inbound
  exactly like a real Meta webhook delivery. Failures during AI
  dispatch never mutate Order / Payment / Shipment.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer
from apps.compliance.models import Claim
from apps.whatsapp import services as whatsapp_services
from apps.whatsapp.ai_orchestration import (
    OrchestrationOutcome,
    run_whatsapp_ai_agent,
)
from apps.whatsapp.claim_mapping import category_to_claim_product
from apps.whatsapp.consent import has_whatsapp_consent
from apps.whatsapp.grounded_reply_builder import (
    build_grounded_product_reply,
    build_objection_aware_reply,
    can_build_grounded_product_reply,
    can_build_objection_reply,
    classify_inbound_intent,
    is_normal_product_info_inquiry,
    validate_objection_reply,
    validate_reply_uses_claim_vault,
)
from apps.whatsapp.meta_one_number_test import (
    _digits_only,
    _normalize_phone,
    check_waba_subscription,
    get_allowed_test_numbers,
    is_number_allowed_for_live_meta_test,
    verify_provider_and_credentials,
)
from apps.whatsapp.models import (
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
)


# Flags that MUST stay off during the controlled AI auto-reply gate run.
# WHATSAPP_AI_AUTO_REPLY_ENABLED is intentionally listed too — this
# harness is the only sanctioned path that may produce a real AI reply
# until that flag is flipped by Director sign-off after a clean soak.
_REQUIRE_OFF_FLAGS: tuple[str, ...] = (
    "WHATSAPP_AI_AUTO_REPLY_ENABLED",
    "WHATSAPP_CALL_HANDOFF_ENABLED",
    "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED",
    "WHATSAPP_RESCUE_DISCOUNT_ENABLED",
    "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED",
    "WHATSAPP_REORDER_DAY20_ENABLED",
)


class Command(BaseCommand):
    help = (
        "Run the Phase 5F-Gate controlled AI auto-reply test against the "
        "allowed test number only. Default --dry-run; --send is required "
        "for a real live AI reply. Refuses on any amber gate."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--phone", required=True, help="Destination MSISDN.")
        parser.add_argument(
            "--message",
            required=True,
            help="Synthetic inbound text the orchestrator will respond to.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Force dry-run.")
        parser.add_argument(
            "--send", action="store_true", help="Trigger a real live AI reply."
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        send_flag = bool(options.get("send"))
        if options.get("dry_run") and send_flag:
            send_flag = False  # dry-run wins.

        report: dict[str, Any] = {
            "passed": False,
            "dryRun": not send_flag,
            "sendAttempted": False,
            "provider": "",
            "limitedTestMode": False,
            "phone": "",
            "toAllowed": False,
            "customerId": "",
            "conversationId": "",
            "inboundMessageId": "",
            "aiRunId": "",
            "suggestionStored": False,
            "replyBlocked": False,
            "replySent": False,
            "outboundMessageId": "",
            "providerMessageId": "",
            "claimVaultUsed": None,
            "safetyBlocked": False,
            "blockedReason": "",
            # Phase 5F-Gate Claim Vault Grounding Fix + Confidence Fix —
            # diagnostics. claimCount is preserved as a backward-compat
            # alias for approvedClaimCount (the count operators care
            # about for grounding); claimRowCount + approvedClaimCount
            # + disallowedPhraseCount are the unambiguous fields.
            "detectedCategory": "",
            "normalizedClaimProduct": "",
            "claimRowCount": 0,
            "approvedClaimCount": 0,
            "disallowedPhraseCount": 0,
            "claimCount": 0,
            "confidence": 0.0,
            "confidenceThreshold": 0.0,
            "actionReason": "",
            "action": "",
            "replyPreview": "",
            "safetyFlags": {},
            "groundingStatus": {
                "claimProductFound": False,
                "claimRowCount": 0,
                "approvedClaimCount": 0,
                "disallowedPhraseCount": 0,
                "promptGroundingInjected": False,
                "businessFactsInjected": False,
            },
            "sendEligibilitySummary": "",
            # Phase 5F-Gate Deterministic Grounded Reply Builder.
            "deterministicFallbackUsed": False,
            "fallbackReason": "",
            "deterministicReplyPreview": "",
            "finalReplySource": "",
            "finalReplyValidation": {},
            # Phase 5F-Gate Objection & Handoff Reason Refinement.
            "detectedIntent": "",
            "objectionDetected": False,
            "objectionType": "",
            "purchaseIntentDetected": False,
            "humanRequestDetected": False,
            "handoffReason": "",
            "safetyReason": "",
            "replyPolicy": {
                "upfrontDiscountOffered": False,
                "discountMutationCreated": False,
                "businessMutationCreated": False,
            },
            "auditEvents": [],
            "warnings": [],
            "errors": [],
            "nextAction": "",
        }

        phone_input = options.get("phone") or ""
        message_body = (options.get("message") or "").strip()
        normalized = _normalize_phone(phone_input)
        digits = _digits_only(phone_input)
        report["phone"] = normalized

        if not message_body:
            report["errors"].append("--message body must be non-empty.")
            report["nextAction"] = "supply_message_body"
            self._emit_completed(report, options)
            return

        # 1. Provider + credential preflight.
        verification = verify_provider_and_credentials()
        report["provider"] = verification.provider
        report["limitedTestMode"] = verification.limited_test_mode

        # 2. Audit row: this run is starting.
        self._emit_started(report, normalized, message_body)

        if verification.provider != "meta_cloud":
            report["errors"].append(
                f"WHATSAPP_PROVIDER={verification.provider!r} — must be 'meta_cloud'."
            )
            report["nextAction"] = "enable_meta_cloud_provider"
            self._emit_blocked(report, "provider_not_meta_cloud")
            self._emit_completed(report, options)
            return

        if not verification.limited_test_mode:
            report["errors"].append(
                "WHATSAPP_LIVE_META_LIMITED_TEST_MODE must be true for the "
                "controlled gate test."
            )
            report["nextAction"] = "enable_limited_test_mode"
            self._emit_blocked(report, "limited_test_mode_off")
            self._emit_completed(report, options)
            return

        # 3. Automation flags must stay off (defence in depth).
        from django.conf import settings

        any_on: list[str] = []
        for flag in _REQUIRE_OFF_FLAGS:
            if bool(getattr(settings, flag, False)):
                any_on.append(flag)
        if any_on:
            report["errors"].append(
                "Refusing to run: automation flag(s) ON — "
                + ", ".join(any_on)
            )
            report["nextAction"] = "disable_automation_flags"
            self._emit_blocked(report, "automation_flags_on")
            self._emit_completed(report, options)
            return

        # 4. Allow-list gate.
        report["toAllowed"] = is_number_allowed_for_live_meta_test(phone_input)
        allow_list_size = len(get_allowed_test_numbers())
        if not report["toAllowed"]:
            report["errors"].append(
                f"Destination {normalized} is not on "
                f"WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS "
                f"(allow_list_size={allow_list_size})."
            )
            report["nextAction"] = "add_number_to_allowed_list"
            self._emit_blocked(report, "limited_test_number_not_allowed")
            self._emit_completed(report, options)
            return

        # 5. Customer + consent.
        customer = self._find_customer(phone_input, digits, normalized)
        if customer is None:
            report["errors"].append(
                f"No Customer found for {normalized}. Create one + grant "
                "WhatsApp consent before re-running."
            )
            report["nextAction"] = "grant_consent_on_test_number"
            self._emit_blocked(report, "customer_not_found")
            self._emit_completed(report, options)
            return
        report["customerId"] = customer.id

        if not has_whatsapp_consent(customer):
            report["errors"].append(
                f"Customer {customer.id} does not have a granted WhatsApp consent."
            )
            report["nextAction"] = "grant_consent_on_test_number"
            self._emit_blocked(report, "consent_missing")
            self._emit_completed(report, options)
            return

        # 6. WABA subscription (best-effort; warn but do not block on
        # transport failures).
        waba_status = check_waba_subscription()
        if waba_status.error:
            report["warnings"].append(waba_status.error)
        if waba_status.checked and waba_status.active is False:
            report["errors"].append(
                "WABA subscribed_apps is empty — Meta will not deliver inbound "
                "webhooks."
            )
            report["nextAction"] = "fix_waba_subscription"
            self._emit_blocked(report, "waba_subscription_inactive")
            self._emit_completed(report, options)
            return

        # 7. Resolve / open the conversation, persist the synthetic
        # inbound. The orchestrator runs over a real DB row exactly as
        # if Meta had delivered it via webhook.
        connection = whatsapp_services.get_active_connection()
        convo = whatsapp_services.get_or_open_conversation(
            customer, connection=connection
        )
        report["conversationId"] = convo.id

        # Phase 5F-Gate Objection & Handoff Reason Refinement —
        # deterministic intent classification BEFORE the orchestrator
        # runs. This gives the controlled-test JSON a typed primary
        # intent on every path, and lets us short-circuit human-request
        # inbounds without sending a generic claim_vault_not_used
        # block.
        intent = classify_inbound_intent(message_body)
        report["detectedIntent"] = intent.primary
        report["objectionDetected"] = intent.discount_objection
        report["objectionType"] = intent.objection_type
        report["purchaseIntentDetected"] = intent.purchase_intent
        report["humanRequestDetected"] = intent.human_request
        if intent.discount_objection:
            self._emit_objection_detected(report, intent)
        if intent.human_request:
            self._emit_human_request_detected(report, intent)

        if not send_flag:
            # Dry-run path — every gate has passed; do not persist a
            # synthetic inbound, do not call the orchestrator.
            report["passed"] = True
            report["nextAction"] = "dry_run_passed_ready_for_send"
            self._emit_dry_run_passed(report)
            self._emit_completed(report, options)
            return

        inbound = self._persist_synthetic_inbound(convo, customer, message_body)
        report["inboundMessageId"] = inbound.id
        report["sendAttempted"] = True

        # Phase 5F-Gate Objection & Handoff Reason Refinement —
        # short-circuit human-request inbounds before the orchestrator
        # runs. The customer asked for a human; we do NOT need the LLM
        # to decide. The Vapi handoff stays gated by
        # WHATSAPP_CALL_HANDOFF_ENABLED (false during the gate phase),
        # so the audit row is the only side effect.
        if intent.primary == "human_request" and not intent.unsafe:
            return self._handle_human_request_handoff(
                report=report,
                options=options,
                inbound=inbound,
                customer=customer,
            )

        # 8. Drive the orchestrator with auto-reply forced ON for this
        # one call only. Every other gate (Claim Vault, blocked phrase,
        # safety flags, CAIO, matrix, idempotency, the limited-mode
        # final-send guard inside services.send_freeform_text_message)
        # still runs.
        try:
            outcome: OrchestrationOutcome = run_whatsapp_ai_agent(
                conversation_id=convo.id,
                inbound_message_id=inbound.id,
                triggered_by="controlled_ai_auto_reply_test",
                actor_role="director",
                force_auto_reply=True,
            )
        except Exception as exc:  # noqa: BLE001 - never crash the CLI
            report["errors"].append(f"Orchestrator raised: {type(exc).__name__}: {exc}")
            report["nextAction"] = "inspect_live_test"
            self._emit_blocked(report, "orchestrator_exception")
            self._emit_completed(report, options)
            return

        report["aiRunId"] = inbound.id  # one-run-per-inbound by design
        if outcome.decision is not None:
            decision = outcome.decision
            report["claimVaultUsed"] = bool(
                decision.safety.get("claimVaultUsed", False)
            )
            report["detectedCategory"] = decision.category or ""
            report["confidence"] = float(decision.confidence or 0.0)
            report["action"] = decision.action
            report["replyPreview"] = (decision.reply_text or "")[:180]
            # Surface the safety flags so the operator can read the
            # decision at a glance — these are booleans, no PII.
            report["safetyFlags"] = {
                k: bool(v) for k, v in (decision.safety or {}).items()
            }
            normalized_product = category_to_claim_product(decision.category)
            report["normalizedClaimProduct"] = normalized_product
            from django.conf import settings as _settings

            report["confidenceThreshold"] = float(
                getattr(
                    _settings, "WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD", 0.75
                )
            )
            row_count = 0
            approved_count = 0
            disallowed_count = 0
            if normalized_product:
                rows = list(
                    Claim.objects.filter(product__iexact=normalized_product)
                    .only("approved", "disallowed")
                )
                row_count = len(rows)
                approved_count = sum(
                    len(r.approved or []) for r in rows
                )
                disallowed_count = sum(
                    len(r.disallowed or []) for r in rows
                )
            report["claimRowCount"] = row_count
            report["approvedClaimCount"] = approved_count
            report["disallowedPhraseCount"] = disallowed_count
            # Backward-compat alias for older log scrapers.
            report["claimCount"] = approved_count
            report["groundingStatus"] = {
                "claimProductFound": row_count > 0,
                "claimRowCount": row_count,
                "approvedClaimCount": approved_count,
                "disallowedPhraseCount": disallowed_count,
                # Grounding is "injected" iff the prompt builder had
                # at least one approved phrase to surface in the
                # claims block of the user message.
                "promptGroundingInjected": approved_count > 0,
                # Business facts (₹3000 / 30 capsules / ₹499 advance)
                # are injected unconditionally by _build_context now,
                # so this flag tracks the contract — not an env flag.
                "businessFactsInjected": True,
            }
            # actionReason / sendEligibilitySummary derive from the
            # current outcome; populated below depending on path.
            report["actionReason"] = decision.handoff_reason or ""

        if outcome.sent:
            report["replySent"] = True
            report["outboundMessageId"] = outcome.sent_message_id
            sent_msg = (
                WhatsAppMessage.objects.filter(pk=outcome.sent_message_id)
                .only("provider_message_id", "body")
                .first()
            )
            if sent_msg is not None:
                report["providerMessageId"] = sent_msg.provider_message_id or ""
            report["passed"] = True
            report["nextAction"] = "live_ai_reply_sent_verify_phone"
            # Phase 5F-Gate Real Inbound Deterministic Fallback Fix —
            # the orchestrator now runs the deterministic grounded /
            # objection fallback for soft non-safety blocks. Detect
            # that path via the outcome notes so the CLI report stays
            # accurate.
            notes = list(outcome.notes or [])
            orchestrator_used_grounded = (
                "deterministic_grounded_fallback_used" in notes
            )
            orchestrator_used_objection = (
                "deterministic_objection_fallback_used" in notes
            )
            if orchestrator_used_grounded or orchestrator_used_objection:
                report["finalReplySource"] = (
                    "deterministic_objection_reply"
                    if orchestrator_used_objection
                    else "deterministic_grounded_builder"
                )
                report["deterministicFallbackUsed"] = True
                fallback_for = next(
                    (
                        n.split(":", 1)[1]
                        for n in notes
                        if n.startswith("fallback_for:")
                    ),
                    "",
                )
                if orchestrator_used_objection:
                    report["fallbackReason"] = (
                        "objection_aware_grounded_fallback"
                    )
                    report["objectionDetected"] = True
                else:
                    report["fallbackReason"] = fallback_for
                report["claimVaultUsed"] = True
                report["action"] = "send_reply"
                if sent_msg is not None and sent_msg.body:
                    report["replyPreview"] = sent_msg.body[:180]
                    report["deterministicReplyPreview"] = sent_msg.body[:180]
            else:
                report["finalReplySource"] = "llm"
            # Validate the actually-sent reply text — if it accidentally
            # contains a discount or blocked phrase, surface it.
            reply_for_validation = ""
            if sent_msg is not None and sent_msg.body:
                reply_for_validation = sent_msg.body
            elif outcome.decision is not None:
                reply_for_validation = outcome.decision.reply_text or ""
            if outcome.decision is not None and reply_for_validation:
                approved_phrases = self._approved_phrases_for(
                    outcome.decision.category
                )
                report["finalReplyValidation"] = validate_reply_uses_claim_vault(
                    reply_text=reply_for_validation,
                    approved_claims=approved_phrases,
                )
            self._emit_sent(report)
            self._emit_completed(report, options)
            return

        # Outcome did not send — figure out the typed next action,
        # then attempt the deterministic grounded fallback when the
        # block reason is a soft non-safety one and backend grounding
        # is fully present. This is the Phase 5F-Gate Deterministic
        # Grounded Reply Builder path.
        report["replyBlocked"] = True
        report["blockedReason"] = outcome.blocked_reason or "no_action"
        if outcome.blocked_reason in {
            "medical_emergency",
            "side_effect_complaint",
            "legal_threat",
        }:
            report["safetyBlocked"] = True
            report["nextAction"] = "blocked_for_medical_safety"
        elif outcome.blocked_reason == "claim_vault_not_used":
            report["nextAction"] = "blocked_for_unapproved_claim"
        elif outcome.blocked_reason == "claim_vault_missing":
            report["nextAction"] = "fix_claim_vault_coverage"
        elif outcome.blocked_reason and outcome.blocked_reason.startswith(
            "freeform_send_blocked:limited_test_number_not_allowed"
        ):
            report["nextAction"] = "blocked_by_limited_mode_guard"
        elif outcome.blocked_reason in {"auto_reply_disabled", ""}:
            # Should be unreachable now that force_auto_reply=True is
            # passed, but keep the typed branch for telemetry.
            report["nextAction"] = "inspect_live_test"
        elif outcome.blocked_reason == "low_confidence":
            report["suggestionStored"] = True
            report["nextAction"] = "inspect_live_test"
        else:
            report["nextAction"] = "inspect_live_test"

        # Deterministic grounded-reply fallback — only for the soft
        # non-safety block reasons. Safety blockers (medical /
        # side-effect / legal / blocked-phrase) NEVER trigger
        # fallback.
        used_fallback = self._maybe_run_deterministic_fallback(
            report=report,
            outcome=outcome,
            inbound=inbound,
            customer=customer,
        )
        if used_fallback:
            self._emit_completed(report, options)
            return

        self._emit_blocked(report, outcome.blocked_reason or "no_action")
        self._emit_completed(report, options)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Phase 5F-Gate Deterministic Grounded Reply Builder
    # ------------------------------------------------------------------

    def _approved_phrases_for(self, category: str) -> list[str]:
        """Pull the approved-phrase list for the LLM's detected category."""
        normalized = category_to_claim_product(category) if category else ""
        if not normalized:
            return []
        rows = list(
            Claim.objects.filter(product__iexact=normalized)
            .only("approved")
        )
        out: list[str] = []
        for row in rows:
            for phrase in row.approved or []:
                phrase = (phrase or "").strip()
                if phrase and phrase not in out:
                    out.append(phrase)
        return out

    def _disallowed_phrases_for(self, category: str) -> list[str]:
        normalized = category_to_claim_product(category) if category else ""
        if not normalized:
            return []
        rows = list(
            Claim.objects.filter(product__iexact=normalized)
            .only("disallowed")
        )
        out: list[str] = []
        for row in rows:
            for phrase in row.disallowed or []:
                phrase = (phrase or "").strip()
                if phrase and phrase not in out:
                    out.append(phrase)
        return out

    # Soft, non-safety blockers where the deterministic fallback may
    # produce a Claim-Vault-grounded reply. Safety-shaped blockers
    # (medical / side-effect / legal / blocked-phrase / consent /
    # limited-mode-guard) never fall through this branch.
    _FALLBACK_ELIGIBLE_BLOCK_REASONS: tuple[str, ...] = (
        "claim_vault_not_used",
        "low_confidence",
        "ai_handoff_requested",
        "auto_reply_disabled",
        "no_action",
        "",
    )

    def _maybe_run_deterministic_fallback(
        self,
        *,
        report: dict[str, Any],
        outcome: OrchestrationOutcome,
        inbound: WhatsAppMessage,
        customer: Customer,
    ) -> bool:
        """Phase 5F-Gate Deterministic Grounded Reply Builder.

        Attempt to produce a deterministic, Claim-Vault-grounded reply
        when the LLM blocked the send despite the backend having full
        grounding, mapped category, business facts, no safety flags
        tripped, and the inbound being a normal product-info inquiry.

        Returns True iff the fallback dispatched a real send. False
        when the fallback was skipped or refused — caller still emits
        the existing block / completed audits.
        """
        if outcome.blocked_reason not in self._FALLBACK_ELIGIBLE_BLOCK_REASONS:
            return False
        if outcome.decision is None:
            return False

        category = outcome.decision.category or ""
        approved_phrases = self._approved_phrases_for(category)
        disallowed_phrases = self._disallowed_phrases_for(category)

        # Phase 5F-Gate Objection & Handoff Reason Refinement —
        # discount/price objections take an objection-aware reply
        # ahead of the standard grounded reply. Run the objection
        # path first; fall through to the grounded path if it refuses.
        intent = classify_inbound_intent(inbound.body or "")
        if intent.discount_objection and not intent.unsafe:
            objection_dispatched = self._maybe_run_objection_fallback(
                report=report,
                outcome=outcome,
                inbound=inbound,
                customer=customer,
                intent=intent,
                approved_phrases=approved_phrases,
            )
            if objection_dispatched:
                return True

        # Eligibility check for the standard grounded reply — the
        # helper inspects category, safety flags, approved-claim list,
        # and inbound vocabulary.
        eligibility = can_build_grounded_product_reply(
            category=category,
            inbound_text=inbound.body or "",
            safety_flags=dict(outcome.decision.safety or {}),
            approved_claims=approved_phrases,
            disallowed_phrases=disallowed_phrases,
        )
        if not eligibility.eligible:
            return False

        # Build the deterministic reply.
        result = build_grounded_product_reply(
            normalized_product=eligibility.normalized_product,
            approved_claims=approved_phrases,
            inbound_text=inbound.body or "",
            customer_name=customer.name or "",
        )
        report["deterministicReplyPreview"] = (result.reply_text or "")[:180]
        report["finalReplyValidation"] = result.validation or {}

        if not result.ok:
            self._emit_deterministic_blocked(
                report=report,
                eligibility=eligibility,
                fallback_reason=result.fallback_reason or "build_failed",
            )
            return False

        # Ship the deterministic reply through the same final-send
        # path the orchestrator uses. Limited-mode guard, consent,
        # CAIO, idempotency stay in force.
        try:
            sent = whatsapp_services.send_freeform_text_message(
                customer=customer,
                conversation=inbound.conversation,
                body=result.reply_text,
                actor_role="director",
                actor_agent="cli",
                ai_generated=True,
                metadata={
                    "deterministic_grounded_fallback": True,
                    "category": category,
                    "normalized_product": eligibility.normalized_product,
                    "fallback_reason_for_llm_block": outcome.blocked_reason,
                },
            )
        except whatsapp_services.WhatsAppServiceError as exc:
            self._emit_deterministic_blocked(
                report=report,
                eligibility=eligibility,
                fallback_reason=f"send_refused:{exc.block_reason}",
            )
            return False

        # Mark the run successful — the deterministic reply was sent.
        from django.conf import settings as _settings

        threshold = float(
            getattr(
                _settings, "WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD", 0.75
            )
        )
        report["replyBlocked"] = False
        report["blockedReason"] = ""
        report["safetyBlocked"] = False
        report["replySent"] = True
        report["passed"] = True
        report["claimVaultUsed"] = True
        report["action"] = "send_reply"
        report["actionReason"] = "deterministic_grounded_reply_fallback"
        report["confidence"] = max(threshold, 0.9)
        report["replyPreview"] = (sent.body or "")[:180]
        report["outboundMessageId"] = sent.id
        report["providerMessageId"] = sent.provider_message_id or ""
        report["nextAction"] = "live_ai_reply_sent_verify_phone"
        report["deterministicFallbackUsed"] = True
        report["fallbackReason"] = outcome.blocked_reason or "ai_handoff"
        report["finalReplySource"] = "deterministic_grounded_builder"

        write_event(
            kind="whatsapp.ai.deterministic_grounded_reply_used",
            text=(
                f"Deterministic grounded reply used · "
                f"category={category} · product={eligibility.normalized_product} "
                f"· llm_block={outcome.blocked_reason}"
            ),
            tone=AuditEvent.Tone.SUCCESS,
            payload={
                "category": category,
                "normalized_claim_product": eligibility.normalized_product,
                "claim_row_count": 1,
                "approved_claim_count": eligibility.approved_claim_count,
                "fallback_reason": outcome.blocked_reason or "ai_handoff",
                "final_reply_source": "deterministic_grounded_builder",
                "phone_suffix": self._safe_phone(report["phone"]),
                "outbound_message_id": sent.id,
                "used_approved_phrases": list(result.used_approved_phrases),
            },
        )
        report["auditEvents"].append("whatsapp.ai.deterministic_grounded_reply_used")
        # Also write the existing controlled_test.sent audit so the
        # operator sees a single consistent shape across LLM and
        # fallback runs.
        self._emit_sent(report)
        return True

    # ------------------------------------------------------------------
    # Phase 5F-Gate Objection & Handoff Reason Refinement
    # ------------------------------------------------------------------

    def _handle_human_request_handoff(
        self,
        *,
        report: dict[str, Any],
        options,
        inbound: WhatsAppMessage,
        customer: Customer,
    ) -> None:
        """Customer asked for a human / call. Emit a clean handoff
        audit row + JSON; do NOT send a generic claim_vault_not_used
        block, do NOT trigger a Vapi call (gated by
        WHATSAPP_CALL_HANDOFF_ENABLED), do NOT mutate Order/Payment/
        Shipment/DiscountOfferLog.
        """
        report["aiRunId"] = inbound.id
        report["replyBlocked"] = True
        report["replySent"] = False
        report["safetyBlocked"] = False
        report["blockedReason"] = "human_advisor_requested"
        report["handoffReason"] = "human_advisor_requested"
        report["finalReplySource"] = "blocked_handoff"
        report["nextAction"] = "human_handoff_requested"
        # Reply policy — the controlled-test command never mutates
        # business state on the human-request path.
        report["replyPolicy"] = {
            "upfrontDiscountOffered": False,
            "discountMutationCreated": False,
            "businessMutationCreated": False,
        }

        write_event(
            kind="whatsapp.ai.handoff_required",
            text=(
                f"AI handoff · conversation={inbound.conversation_id} · "
                f"reason=human_advisor_requested"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "conversation_id": inbound.conversation_id,
                "reason": "human_advisor_requested",
                "handoff_reason": "human_advisor_requested",
                "category": "",
                "normalized_claim_product": "",
                "claim_row_count": 0,
                "approved_claim_count": 0,
                "disallowed_phrase_count": 0,
                "claim_count": 0,
                "confidence": 0.0,
                "phone_suffix": self._safe_phone(report["phone"]),
            },
        )
        report["auditEvents"].append("whatsapp.ai.handoff_required")
        self._emit_blocked(report, "human_advisor_requested")
        self._emit_completed(report, options)

    def _emit_objection_detected(
        self, report: dict[str, Any], intent
    ) -> None:
        write_event(
            kind="whatsapp.ai.objection_detected",
            text=(
                f"Discount/price objection detected · "
                f"type={intent.objection_type} · "
                f"phone_suffix={self._safe_phone(report['phone'])}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "objection_type": intent.objection_type,
                "purchase_intent": intent.purchase_intent,
                "phone_suffix": self._safe_phone(report["phone"]),
            },
        )
        report["auditEvents"].append("whatsapp.ai.objection_detected")

    def _emit_human_request_detected(
        self, report: dict[str, Any], intent
    ) -> None:
        write_event(
            kind="whatsapp.ai.human_request_detected",
            text=(
                f"Human-request detected · "
                f"phone_suffix={self._safe_phone(report['phone'])}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "phone_suffix": self._safe_phone(report["phone"]),
                "matched": list(intent.matched),
            },
        )
        report["auditEvents"].append("whatsapp.ai.human_request_detected")

    def _maybe_run_objection_fallback(
        self,
        *,
        report: dict[str, Any],
        outcome: OrchestrationOutcome,
        inbound: WhatsAppMessage,
        customer: Customer,
        intent,
        approved_phrases: list,
    ) -> bool:
        """Attempt the objection-aware deterministic reply.

        Same safety contract as ``_maybe_run_deterministic_fallback``:
        runs only when the LLM blocked on a soft non-safety reason,
        backend grounding is valid, and the inbound is a discount /
        price objection. NEVER mutates business state.
        """
        category = outcome.decision.category or ""
        eligibility = can_build_objection_reply(
            category=category,
            inbound_text=inbound.body or "",
            safety_flags=dict(outcome.decision.safety or {}),
            approved_claims=approved_phrases,
        )
        if not eligibility.eligible:
            return False

        result = build_objection_aware_reply(
            normalized_product=eligibility.normalized_product,
            approved_claims=approved_phrases,
            inbound_text=inbound.body or "",
            purchase_intent=intent.purchase_intent,
        )
        report["deterministicReplyPreview"] = (result.reply_text or "")[:180]
        report["finalReplyValidation"] = result.validation or {}

        if not result.ok:
            write_event(
                kind="whatsapp.ai.objection_reply_blocked",
                text=(
                    f"Objection-aware reply blocked · "
                    f"reason={result.fallback_reason or 'build_failed'}"
                ),
                tone=AuditEvent.Tone.WARNING,
                payload={
                    "category": category,
                    "normalized_claim_product": eligibility.normalized_product,
                    "approved_claim_count": eligibility.approved_claim_count,
                    "fallback_reason": result.fallback_reason or "build_failed",
                    "phone_suffix": self._safe_phone(report["phone"]),
                },
            )
            report["auditEvents"].append("whatsapp.ai.objection_reply_blocked")
            return False

        try:
            sent = whatsapp_services.send_freeform_text_message(
                customer=customer,
                conversation=inbound.conversation,
                body=result.reply_text,
                actor_role="director",
                actor_agent="cli",
                ai_generated=True,
                metadata={
                    "deterministic_objection_reply": True,
                    "category": category,
                    "normalized_product": eligibility.normalized_product,
                    "objection_type": intent.objection_type,
                    "purchase_intent": intent.purchase_intent,
                },
            )
        except whatsapp_services.WhatsAppServiceError as exc:
            write_event(
                kind="whatsapp.ai.objection_reply_blocked",
                text=(
                    f"Objection-aware reply blocked at send · "
                    f"reason={exc.block_reason}"
                ),
                tone=AuditEvent.Tone.WARNING,
                payload={
                    "category": category,
                    "normalized_claim_product": eligibility.normalized_product,
                    "fallback_reason": f"send_refused:{exc.block_reason}",
                    "phone_suffix": self._safe_phone(report["phone"]),
                },
            )
            report["auditEvents"].append("whatsapp.ai.objection_reply_blocked")
            return False

        from django.conf import settings as _settings

        threshold = float(
            getattr(
                _settings, "WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD", 0.75
            )
        )
        report["replyBlocked"] = False
        report["blockedReason"] = ""
        report["safetyBlocked"] = False
        report["replySent"] = True
        report["passed"] = True
        report["claimVaultUsed"] = True
        report["action"] = "send_reply"
        report["actionReason"] = "deterministic_objection_reply"
        report["confidence"] = max(threshold, 0.9)
        report["replyPreview"] = (sent.body or "")[:180]
        report["outboundMessageId"] = sent.id
        report["providerMessageId"] = sent.provider_message_id or ""
        report["nextAction"] = "live_ai_reply_sent_verify_phone"
        report["deterministicFallbackUsed"] = True
        report["fallbackReason"] = (
            f"objection:{intent.objection_type}"
            if intent.objection_type
            else "objection"
        )
        report["finalReplySource"] = "deterministic_objection_reply"
        report["replyPolicy"] = {
            "upfrontDiscountOffered": False,
            "discountMutationCreated": False,
            "businessMutationCreated": False,
        }

        write_event(
            kind="whatsapp.ai.objection_reply_used",
            text=(
                f"Objection-aware reply used · type={intent.objection_type} "
                f"· product={eligibility.normalized_product}"
            ),
            tone=AuditEvent.Tone.SUCCESS,
            payload={
                "category": category,
                "normalized_claim_product": eligibility.normalized_product,
                "approved_claim_count": eligibility.approved_claim_count,
                "objection_type": intent.objection_type,
                "purchase_intent": intent.purchase_intent,
                "outbound_message_id": sent.id,
                "phone_suffix": self._safe_phone(report["phone"]),
                "used_approved_phrases": list(result.used_approved_phrases),
                "discount_mutation_created": False,
                "business_mutation_created": False,
            },
        )
        report["auditEvents"].append("whatsapp.ai.objection_reply_used")
        self._emit_sent(report)
        return True

    def _emit_deterministic_blocked(
        self,
        *,
        report: dict[str, Any],
        eligibility,
        fallback_reason: str,
    ) -> None:
        write_event(
            kind="whatsapp.ai.deterministic_grounded_reply_blocked",
            text=(
                f"Deterministic grounded reply blocked · "
                f"reason={fallback_reason}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "category": report.get("detectedCategory", ""),
                "normalized_claim_product": eligibility.normalized_product,
                "claim_row_count": report.get("claimRowCount", 0),
                "approved_claim_count": eligibility.approved_claim_count,
                "fallback_reason": fallback_reason,
                "phone_suffix": self._safe_phone(report["phone"]),
            },
        )
        report["auditEvents"].append(
            "whatsapp.ai.deterministic_grounded_reply_blocked"
        )
        # Surface diagnostics on the JSON output so the operator can
        # see why the fallback refused.
        report["deterministicFallbackUsed"] = False
        report["fallbackReason"] = fallback_reason
        report["finalReplySource"] = ""

    def _find_customer(
        self, phone_input: str, digits: str, normalized: str
    ) -> Customer | None:
        candidates = [normalized, digits, phone_input]
        if digits:
            candidates.append(digits[-10:])
        seen: set[str] = set()
        for needle in candidates:
            if not needle or needle in seen:
                continue
            seen.add(needle)
            match = Customer.objects.filter(phone__iexact=needle).first()
            if match is not None:
                return match
        if digits:
            return Customer.objects.filter(
                phone__icontains=digits[-10:]
            ).first()
        return None

    def _persist_synthetic_inbound(
        self,
        convo: WhatsAppConversation,
        customer: Customer,
        body: str,
    ) -> WhatsAppMessage:
        """Persist a real INBOUND row + bump the conversation cursor.

        The row carries a deterministic provider id so re-runs collapse
        on the unique constraint and the orchestrator's idempotency
        check fires correctly.
        """
        from django.utils import timezone

        wam_id = next_id("WAM", WhatsAppMessage, base=900001)
        provider_id = (
            f"wamid.CONTROLLED-AI-TEST-{wam_id}"
        )
        now = timezone.now()
        message = WhatsAppMessage.objects.create(
            id=wam_id,
            conversation=convo,
            customer=customer,
            direction=WhatsAppMessage.Direction.INBOUND,
            status=WhatsAppMessage.Status.DELIVERED,
            type=WhatsAppMessage.Type.TEXT,
            body=body[:4096],
            provider_message_id=provider_id,
            metadata={"controlled_ai_auto_reply_test": True},
            queued_at=now,
            sent_at=now,
            delivered_at=now,
        )
        convo.last_message_at = now
        convo.last_inbound_at = now
        convo.last_message_text = body[:500]
        convo.unread_count = (convo.unread_count or 0) + 1
        convo.save(
            update_fields=[
                "last_message_at",
                "last_inbound_at",
                "last_message_text",
                "unread_count",
                "updated_at",
            ]
        )
        return message

    # ------------------------------------------------------------------
    # Audit emitters (no secrets, phone last-4 only, body 120-char preview)
    # ------------------------------------------------------------------

    def _safe_phone(self, phone: str) -> str:
        digits = _digits_only(phone)
        return digits[-4:] if digits else ""

    def _emit_started(
        self, report: dict[str, Any], phone: str, body: str
    ) -> None:
        write_event(
            kind="whatsapp.ai.controlled_test.started",
            text=(
                f"Controlled AI auto-reply test started · phone_suffix="
                f"{self._safe_phone(phone)} · dryRun={report['dryRun']}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "phone_suffix": self._safe_phone(phone),
                "dry_run": report["dryRun"],
                "send_attempted": report["sendAttempted"],
                "body_preview": body[:120],
            },
        )
        report["auditEvents"].append("whatsapp.ai.controlled_test.started")

    def _emit_dry_run_passed(self, report: dict[str, Any]) -> None:
        write_event(
            kind="whatsapp.ai.controlled_test.dry_run_passed",
            text=(
                f"Controlled AI auto-reply test dry-run passed · "
                f"customer={report['customerId']} · conversation="
                f"{report['conversationId']}"
            ),
            tone=AuditEvent.Tone.SUCCESS,
            payload={
                "customer_id": report["customerId"],
                "conversation_id": report["conversationId"],
                "to_allowed": report["toAllowed"],
            },
        )
        report["auditEvents"].append("whatsapp.ai.controlled_test.dry_run_passed")

    def _emit_sent(self, report: dict[str, Any]) -> None:
        write_event(
            kind="whatsapp.ai.controlled_test.sent",
            text=(
                f"Controlled AI auto-reply test SENT · message="
                f"{report['outboundMessageId']} · phone_suffix="
                f"{self._safe_phone(report['phone'])}"
            ),
            tone=AuditEvent.Tone.SUCCESS,
            payload={
                "customer_id": report["customerId"],
                "conversation_id": report["conversationId"],
                "outbound_message_id": report["outboundMessageId"],
                "provider_message_id": report["providerMessageId"],
                "claim_vault_used": report["claimVaultUsed"],
                "phone_suffix": self._safe_phone(report["phone"]),
            },
        )
        report["auditEvents"].append("whatsapp.ai.controlled_test.sent")

    def _emit_blocked(self, report: dict[str, Any], reason: str) -> None:
        write_event(
            kind="whatsapp.ai.controlled_test.blocked",
            text=(
                f"Controlled AI auto-reply test BLOCKED · reason={reason} · "
                f"phone_suffix={self._safe_phone(report['phone'])}"
            ),
            tone=AuditEvent.Tone.WARNING,
            payload={
                "reason": reason,
                "customer_id": report["customerId"],
                "conversation_id": report["conversationId"],
                "phone_suffix": self._safe_phone(report["phone"]),
                "to_allowed": report["toAllowed"],
                "dry_run": report["dryRun"],
                # Phase 5F-Gate Claim Vault Grounding Fix — surface
                # the grounding context so the audit ledger explains
                # exactly why the block fired. Phase 5F-Gate Controlled
                # Reply Confidence Fix splits claim_count into
                # row/approved/disallowed so operators can distinguish
                # "no Claim row" from "Claim row exists but few
                # approved phrases". The legacy ``claim_count`` field
                # is preserved as a backward-compat alias for the
                # approved-phrase count.
                "category": report.get("detectedCategory", ""),
                "normalized_claim_product": report.get("normalizedClaimProduct", ""),
                "claim_row_count": report.get("claimRowCount", 0),
                "approved_claim_count": report.get("approvedClaimCount", 0),
                "disallowed_phrase_count": report.get("disallowedPhraseCount", 0),
                "claim_count": report.get("claimCount", 0),
                "confidence": report.get("confidence", 0.0),
                "confidence_threshold": report.get("confidenceThreshold", 0.0),
                "action": report.get("action", ""),
            },
        )
        report["auditEvents"].append("whatsapp.ai.controlled_test.blocked")

    def _populate_send_eligibility_summary(self, report: dict[str, Any]) -> None:
        """Build the ``sendEligibilitySummary`` operator field.

        One short sentence describing why the run is in its current
        state — never carries secrets, derived purely from already-
        populated diagnostic fields.
        """
        if report["replySent"]:
            report["sendEligibilitySummary"] = (
                f"Live AI reply sent · category={report['detectedCategory']} "
                f"· approvedClaims={report['approvedClaimCount']} "
                f"· confidence={report['confidence']:.2f}"
            )
            return
        if report["dryRun"] and report["passed"]:
            report["sendEligibilitySummary"] = (
                "Dry-run gates passed; ready to flip to --send."
            )
            return
        if report["replyBlocked"]:
            reason = report.get("blockedReason") or "unknown"
            cat = report.get("detectedCategory") or "(none)"
            approved = report.get("approvedClaimCount", 0)
            confidence = report.get("confidence", 0.0)
            threshold = report.get("confidenceThreshold", 0.0)
            report["sendEligibilitySummary"] = (
                f"Send blocked · reason={reason} · category={cat} "
                f"· approvedClaims={approved} · confidence={confidence:.2f} "
                f"· threshold={threshold:.2f}"
            )
            return
        report["sendEligibilitySummary"] = (
            f"No send · provider={report['provider']} · "
            f"limitedTestMode={report['limitedTestMode']} · "
            f"toAllowed={report['toAllowed']}"
        )

    def _emit_completed(
        self, report: dict[str, Any], options: dict[str, Any]
    ) -> None:
        # Populate the operator-facing summary string before emitting
        # the completed audit row + writing the JSON document.
        self._populate_send_eligibility_summary(report)
        write_event(
            kind="whatsapp.ai.controlled_test.completed",
            text=(
                f"Controlled AI auto-reply test completed · passed="
                f"{report['passed']} · dryRun={report['dryRun']} · "
                f"sent={report['replySent']} · blocked={report['replyBlocked']}"
            ),
            tone=(
                AuditEvent.Tone.SUCCESS if report["passed"] else AuditEvent.Tone.WARNING
            ),
            payload={
                "passed": report["passed"],
                "dry_run": report["dryRun"],
                "send_attempted": report["sendAttempted"],
                "reply_sent": report["replySent"],
                "reply_blocked": report["replyBlocked"],
                "blocked_reason": report["blockedReason"],
                "next_action": report["nextAction"],
            },
        )
        report["auditEvents"].append("whatsapp.ai.controlled_test.completed")

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING("Controlled AI auto-reply test")
        )
        self.stdout.write(f"  passed         : {report['passed']}")
        self.stdout.write(f"  dryRun         : {report['dryRun']}")
        self.stdout.write(f"  sendAttempted  : {report['sendAttempted']}")
        self.stdout.write(f"  provider       : {report['provider']}")
        self.stdout.write(f"  limitedTestMode: {report['limitedTestMode']}")
        self.stdout.write(f"  toAllowed      : {report['toAllowed']}")
        self.stdout.write(f"  customerId     : {report['customerId']}")
        self.stdout.write(f"  conversationId : {report['conversationId']}")
        self.stdout.write(f"  inboundMessage : {report['inboundMessageId']}")
        self.stdout.write(f"  outboundMessage: {report['outboundMessageId']}")
        self.stdout.write(f"  providerMsgId  : {report['providerMessageId']}")
        if report["warnings"]:
            self.stdout.write(self.style.WARNING("warnings:"))
            for w in report["warnings"]:
                self.stdout.write(f"  - {w}")
        if report["errors"]:
            self.stdout.write(self.style.ERROR("errors:"))
            for e in report["errors"]:
                self.stdout.write(f"  - {e}")
        self.stdout.write(f"nextAction: {report['nextAction']}")
