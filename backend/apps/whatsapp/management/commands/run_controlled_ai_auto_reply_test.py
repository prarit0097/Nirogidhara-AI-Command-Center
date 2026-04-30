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
from apps.whatsapp import services as whatsapp_services
from apps.whatsapp.ai_orchestration import (
    OrchestrationOutcome,
    run_whatsapp_ai_agent,
)
from apps.whatsapp.consent import has_whatsapp_consent
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
            report["claimVaultUsed"] = bool(
                outcome.decision.safety.get("claimVaultUsed", False)
            )

        if outcome.sent:
            report["replySent"] = True
            report["outboundMessageId"] = outcome.sent_message_id
            sent_msg = (
                WhatsAppMessage.objects.filter(pk=outcome.sent_message_id)
                .only("provider_message_id")
                .first()
            )
            if sent_msg is not None:
                report["providerMessageId"] = sent_msg.provider_message_id or ""
            report["passed"] = True
            report["nextAction"] = "live_ai_reply_sent_verify_phone"
            self._emit_sent(report)
            self._emit_completed(report, options)
            return

        # Outcome did not send — figure out the typed next action.
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

        self._emit_blocked(report, outcome.blocked_reason or "no_action")
        self._emit_completed(report, options)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
            },
        )
        report["auditEvents"].append("whatsapp.ai.controlled_test.blocked")

    def _emit_completed(
        self, report: dict[str, Any], options: dict[str, Any]
    ) -> None:
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
