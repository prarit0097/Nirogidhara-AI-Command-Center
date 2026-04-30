"""``python manage.py run_meta_one_number_test``.

Phase 5E-Smoke-Fix-3 → Phase 5F-Gate management command.

Verifies real Meta WhatsApp Cloud API sending against exactly one
allowed test number, without enabling AI auto-reply, broadcasts,
lifecycle automation, or rescue / RTO / reorder automation.

Default behaviour:

- ``--dry-run`` is **on** unless ``--send`` is explicitly passed.
- ``--send`` actually dispatches the approved template through the
  configured Meta Cloud provider — ONLY if every safety gate passes.
- ``--verify-only`` runs the precondition stack and exits without
  attempting any send.
- ``--check-webhook-config`` prints the expected webhook callback URL
  + verify-token presence summary so the operator can wire up the
  Meta Developer Console.

All hard stops live in :mod:`apps.whatsapp.meta_one_number_test` and
:mod:`apps.whatsapp.services` — the command is a thin CLI shim.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.whatsapp import services
from apps.whatsapp.consent import has_whatsapp_consent
from apps.whatsapp.integrations.whatsapp.base import ProviderError
from apps.whatsapp.meta_one_number_test import (
    MetaOneNumberTestResult,
    _digits_only,
    _normalize_phone,
    check_waba_subscription,
    emit_blocked_number,
    emit_completed,
    emit_config_failed,
    emit_config_ok,
    emit_duplicate_idempotency,
    emit_failed,
    emit_sent,
    emit_started,
    emit_template_missing,
    emit_webhook_subscription_checked,
    find_existing_message_by_idempotency_key,
    get_allowed_test_numbers,
    is_number_allowed_for_live_meta_test,
    resolve_test_template,
    verify_provider_and_credentials,
    webhook_url_summary,
)
from apps.whatsapp.models import WhatsAppConsent
from apps.whatsapp.services import WhatsAppServiceError


class Command(BaseCommand):
    help = (
        "Run the Limited Live Meta WhatsApp One-Number Test. "
        "Default is dry-run; pass --send to actually dispatch (still "
        "blocked unless every safety gate passes)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--to", default="", help="Destination MSISDN (E.164 or digits).")
        parser.add_argument(
            "--template",
            default="",
            help="Meta-approved template name. Default: greeting template.",
        )
        parser.add_argument(
            "--action-key",
            default="",
            help="Optional action_key to resolve a template (e.g. whatsapp.greeting).",
        )
        parser.add_argument(
            "--language",
            default="hi",
            help="Template language code (hi/en). Default: hi.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Force dry-run.")
        parser.add_argument(
            "--send",
            action="store_true",
            help="Actually dispatch the template through Meta Cloud.",
        )
        parser.add_argument(
            "--verify-only",
            action="store_true",
            help="Run precondition checks and exit without sending.",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
        parser.add_argument(
            "--check-webhook-config",
            action="store_true",
            help="Print expected Meta webhook URL + verify-token presence summary.",
        )

    def handle(self, *args, **options) -> None:
        # `--send` wins only if `--dry-run` is NOT also passed.
        send_flag: bool = bool(options.get("send"))
        dry_run_flag: bool = bool(options.get("dry_run"))
        if send_flag and dry_run_flag:
            send_flag = False  # dry-run wins.

        result = MetaOneNumberTestResult(
            dry_run=not send_flag,
            send_attempted=False,
        )

        verification = verify_provider_and_credentials()
        result.provider = verification.provider
        result.limited_test_mode = verification.limited_test_mode

        if options.get("check_webhook_config"):
            result.next_action = "webhook_config_summary"
            waba_status = check_waba_subscription()
            emit_webhook_subscription_checked(status=waba_status)
            result.audit_events.append(
                "whatsapp.meta_test.webhook_subscription_checked"
            )
            if waba_status.active is False:
                # Definitely empty — flip the recommendation.
                result.warnings.append(
                    waba_status.warning
                    or "WABA subscribed_apps is empty — Meta will NOT deliver inbound webhooks."
                )
                result.next_action = "subscribe_waba_to_app_webhooks"
            elif waba_status.warning:
                # Skipped (missing creds) — surface as a warning but
                # leave nextAction as the existing summary.
                result.warnings.append(waba_status.warning)
            if waba_status.error:
                result.warnings.append(waba_status.error)

            webhook = webhook_url_summary()
            webhook.update(waba_status.to_dict())
            webhook["overrideCallbackExpected"] = (
                "https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/"
            )
            webhook["recommendedSubscribeCommandHint"] = (
                "POST https://graph.facebook.com/{api_version}/"
                "{META_WA_BUSINESS_ACCOUNT_ID}/subscribed_apps "
                "with Authorization: Bearer <META_WA_ACCESS_TOKEN> "
                "(token, app secret, and verify token NEVER printed here)."
            )
            webhook["recommendedOverrideCallbackHint"] = (
                "POST https://graph.facebook.com/{api_version}/"
                "{META_WA_BUSINESS_ACCOUNT_ID}/subscribed_apps?"
                "override_callback_uri=https://ai.nirogidhara.com/"
                "api/webhooks/whatsapp/meta/&verify_token=<META_WA_VERIFY_TOKEN> "
                "(value not printed)."
            )

            self._emit_output(
                options,
                result,
                extra={"webhook": webhook},
                preface_lines=[
                    "Meta webhook configuration summary",
                    "----------------------------------",
                    "Callback URL : https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/",
                    f"verifyTokenSet     : {verification.verify_token_set}",
                    f"appSecretSet       : {verification.app_secret_set}",
                    f"apiVersion         : {verification.api_version}",
                    f"wabaChecked        : {waba_status.checked}",
                    f"wabaActive         : {waba_status.active}",
                    f"wabaSubscribedApps : {waba_status.subscribed_app_count}",
                    "Subscribe to: messages (and message_template_status_update in prod).",
                ],
            )
            return

        # ----- Pre-flight: verification + allow-list + template -----

        target_phone = options.get("to") or ""
        normalized = _normalize_phone(target_phone)
        digits = _digits_only(target_phone)
        result.to_normalized = normalized
        template_name = options.get("template") or ""
        result.template = template_name

        emit_started(
            to_normalized=normalized,
            template_name=template_name,
            dry_run=result.dry_run,
            send=send_flag,
        )
        result.audit_events.append("whatsapp.meta_test.started")

        # 1. Provider + credential gate.
        if verification.missing_keys or verification.provider != "meta_cloud":
            emit_config_failed(missing_keys=verification.missing_keys)
            result.audit_events.append("whatsapp.meta_test.config_failed")
            result.errors.append(
                f"Provider/credential check failed: missing="
                f"{','.join(verification.missing_keys) or 'none'}; "
                f"provider={verification.provider}"
            )
            result.next_action = "fix_provider_credentials"
            self._finalize(options, result)
            return

        if not verification.limited_test_mode:
            emit_config_failed(missing_keys=["WHATSAPP_LIVE_META_LIMITED_TEST_MODE"])
            result.audit_events.append("whatsapp.meta_test.config_failed")
            result.errors.append(
                "WHATSAPP_LIVE_META_LIMITED_TEST_MODE must be true before "
                "running the one-number test."
            )
            result.next_action = "enable_limited_test_mode"
            self._finalize(options, result)
            return

        if verification.automation_warnings:
            result.warnings.append(
                "Automation flags must remain OFF during the one-number test: "
                + ", ".join(verification.automation_warnings)
            )
            # Refuse to send — but allow verify-only to continue reporting.
            if send_flag:
                emit_config_failed(missing_keys=verification.automation_warnings)
                result.audit_events.append("whatsapp.meta_test.config_failed")
                result.errors.append(
                    "Refusing to --send while automation flags are ON: "
                    + ", ".join(verification.automation_warnings)
                )
                result.next_action = "disable_automation_flags"
                self._finalize(options, result)
                return

        emit_config_ok(
            provider=verification.provider,
            api_version=verification.api_version,
            app_secret_set=verification.app_secret_set,
            verify_token_set=verification.verify_token_set,
        )
        result.audit_events.append("whatsapp.meta_test.config_ok")

        # 2. Allow-list gate.
        allow_list = get_allowed_test_numbers()
        if not target_phone:
            result.errors.append("--to is required for verify/send (skip with --check-webhook-config).")
            emit_blocked_number(to_digits=digits, allow_list_size=len(allow_list))
            result.audit_events.append("whatsapp.meta_test.blocked_number")
            result.next_action = "supply_destination_number"
            self._finalize(options, result)
            return

        result.to_allowed = is_number_allowed_for_live_meta_test(target_phone)
        if not result.to_allowed:
            emit_blocked_number(to_digits=digits, allow_list_size=len(allow_list))
            result.audit_events.append("whatsapp.meta_test.blocked_number")
            result.errors.append(
                "Destination is not in WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS "
                f"(allow_list_size={len(allow_list)}). Refusing to proceed."
            )
            result.next_action = "add_number_to_allowed_list"
            self._finalize(options, result)
            return

        # 3. Template gate.
        connection = services.get_active_connection()
        template, reason = resolve_test_template(
            template_name=template_name,
            action_key=options.get("action_key") or "",
            language=options.get("language") or "hi",
            connection=connection,
        )
        if template is None:
            emit_template_missing(
                template_name=template_name or "(default greeting)",
                action_key=options.get("action_key") or "",
                language=options.get("language") or "hi",
                reason=reason,
            )
            result.audit_events.append("whatsapp.meta_test.template_missing")
            result.errors.append(
                f"Template gate failed: {reason}. Sync templates from Meta and "
                "ensure status=APPROVED, is_active=True, category=UTILITY."
            )
            result.next_action = "sync_or_approve_template"
            self._finalize(options, result)
            return

        result.template = template.name
        result.template_language = template.language
        result.template_approved = True

        # 4. Verify-only mode short-circuits before any send.
        if options.get("verify_only") or not send_flag:
            result.passed = True
            result.next_action = (
                "ready_to_send"
                if not options.get("verify_only")
                else "verify_only_passed"
            )
            self._finalize(options, result)
            return

        # 5. Real send path. Find / build the Customer record so the
        #    standard service stack runs (consent, matrix, idempotency,
        #    Claim Vault if the template demands it).
        customer = self._resolve_or_create_test_customer(target_phone)
        if not has_whatsapp_consent(customer):
            result.errors.append(
                f"Customer {customer.id} has no WhatsApp consent — refusing to send. "
                "Grant consent on the test number BEFORE running --send."
            )
            emit_template_missing(
                template_name=template.name,
                action_key=template.action_key,
                language=template.language,
                reason="consent_missing_for_test_customer",
            )
            result.audit_events.append("whatsapp.meta_test.template_missing")
            result.next_action = "grant_consent_on_test_number"
            self._finalize(options, result)
            return

        # The send goes through `queue_template_message` → Celery task →
        # `send_queued_message`. We dispatch synchronously here so the
        # command returns with a deterministic outcome (eager mode is
        # the default in production for one-shot jobs).
        result.send_attempted = True
        try:
            queued = services.queue_template_message(
                customer=customer,
                action_key=template.action_key or "whatsapp.greeting",
                template=template,
                triggered_by="meta_one_number_test",
                actor_role="director",
                actor_agent="cli",
            )
        except WhatsAppServiceError as exc:
            emit_failed(
                error_code=exc.block_reason or "service_error",
                error_message=str(exc),
                template_name=template.name,
            )
            result.audit_events.append("whatsapp.meta_test.failed")
            result.errors.append(f"Service-layer refused: {exc} ({exc.block_reason})")
            result.next_action = "inspect_audit_blocked_send"
            self._finalize(options, result)
            return
        except IntegrityError as exc:
            # Phase 5F-Gate Hardening Hotfix — duplicate idempotency_key
            # under the same-day fingerprint used to crash the CLI with a
            # full traceback. Recover cleanly + point at the existing row.
            return self._handle_duplicate_idempotency(
                exc=exc,
                customer=customer,
                template=template,
                options=options,
                result=result,
            )

        try:
            sent = services.send_queued_message(queued.message.id)
        except ProviderError as exc:
            emit_failed(
                error_code=exc.error_code or "provider_error",
                error_message=str(exc),
                template_name=template.name,
            )
            result.audit_events.append("whatsapp.meta_test.failed")
            result.message_id = queued.message.id
            result.errors.append(f"Provider rejected the send: {exc}")
            result.next_action = "inspect_provider_response"
            self._finalize(options, result)
            return

        result.message_id = sent.id
        result.provider_message_id = sent.provider_message_id or ""
        emit_sent(
            message_id=sent.id,
            provider_message_id=sent.provider_message_id or "",
            template_name=template.name,
        )
        result.audit_events.append("whatsapp.meta_test.sent")
        result.passed = True
        result.next_action = "verify_inbound_webhook_callback"
        self._finalize(options, result)

    # ---------- helpers ----------

    def _handle_duplicate_idempotency(
        self,
        *,
        exc: IntegrityError,
        customer: Customer,
        template,
        options,
        result: MetaOneNumberTestResult,
    ) -> None:
        """Translate the unique-constraint crash into clean JSON.

        We rebuild the same idempotency key the service layer uses
        (``apps.whatsapp.services._build_idempotency_key``) and look up
        the row that already won the race. The CLI returns
        ``passed=false`` + ``duplicateIdempotencyKey=true`` plus the
        existing ``messageId`` / status so the operator knows whether
        the prior attempt already queued or already sent.
        """
        from apps.whatsapp import services as whatsapp_services
        from apps.whatsapp.models import WhatsAppMessage

        idempotency_key = whatsapp_services._build_idempotency_key(  # noqa: SLF001
            customer=customer,
            template=template,
            variables={},
            action_key=template.action_key or "whatsapp.greeting",
        )
        existing = find_existing_message_by_idempotency_key(idempotency_key)
        if existing is None:
            # Could not locate the row that triggered the conflict — still
            # report cleanly without a traceback.
            result.duplicate_idempotency_key = True
            result.errors.append(
                "Duplicate idempotency_key detected, but the prior row "
                "could not be located. Inspect WhatsAppMessage manually."
            )
            emit_duplicate_idempotency(
                idempotency_key=idempotency_key,
                existing_message_id="",
                existing_status="unknown",
                template_name=template.name,
            )
            result.audit_events.append("whatsapp.meta_test.duplicate_idempotency")
            result.next_action = "inspect_existing_message"
            self._finalize(options, result)
            return

        result.duplicate_idempotency_key = True
        result.existing_message_id = existing.id
        result.message_id = existing.id
        result.provider_message_id = existing.provider_message_id or ""
        result.already_queued = existing.status == WhatsAppMessage.Status.QUEUED
        result.already_sent = existing.status in {
            WhatsAppMessage.Status.SENT,
            WhatsAppMessage.Status.DELIVERED,
            WhatsAppMessage.Status.READ,
        }
        emit_duplicate_idempotency(
            idempotency_key=idempotency_key,
            existing_message_id=existing.id,
            existing_status=existing.status,
            template_name=template.name,
        )
        result.audit_events.append("whatsapp.meta_test.duplicate_idempotency")
        result.warnings.append(
            f"Duplicate idempotency_key — existing message {existing.id} "
            f"is in status={existing.status}. Retry tomorrow or send via "
            "a different template / customer."
        )
        result.next_action = "inspect_existing_message"
        self._finalize(options, result)

    def _resolve_or_create_test_customer(self, target_phone: str) -> Customer:
        """Find a Customer by phone — never auto-grant consent.

        If no Customer exists, create a minimal record marked as a test
        customer; the consent gate inside ``queue_template_message`` then
        decides whether the send actually proceeds.
        """
        normalized = _normalize_phone(target_phone)
        digits = _digits_only(target_phone)
        candidates = {normalized, digits, target_phone, digits[-10:]}
        for needle in candidates:
            if not needle:
                continue
            found = Customer.objects.filter(phone__iexact=needle).first()
            if found is not None:
                return found

        from apps._id import next_id

        customer = Customer.objects.create(
            id=next_id("NRG-CUST", Customer, base=900001),
            name="Meta One-Number Test",
            phone=normalized or target_phone,
            state="",
            city="",
            language="hi",
            product_interest="",
            consent_whatsapp=False,
        )
        WhatsAppConsent.objects.update_or_create(
            customer=customer,
            defaults={
                "consent_state": WhatsAppConsent.State.UNKNOWN,
                "source": "meta_one_number_test",
            },
        )
        return customer

    def _finalize(self, options, result: MetaOneNumberTestResult) -> None:
        emit_completed(
            passed=result.passed,
            dry_run=result.dry_run,
            send_attempted=result.send_attempted,
        )
        result.audit_events.append("whatsapp.meta_test.completed")
        self._emit_output(options, result)

    def _emit_output(
        self,
        options,
        result: MetaOneNumberTestResult,
        *,
        extra: dict[str, Any] | None = None,
        preface_lines: list[str] | None = None,
    ) -> None:
        if options.get("json"):
            payload: dict[str, Any] = result.to_dict()
            if extra:
                payload.update(extra)
            self.stdout.write(_json.dumps(payload, default=str))
            return

        if preface_lines:
            for line in preface_lines:
                self.stdout.write(line)
            self.stdout.write("")

        self.stdout.write(self.style.MIGRATE_HEADING("Meta One-Number Test"))
        self.stdout.write(f"  passed         : {result.passed}")
        self.stdout.write(f"  dryRun         : {result.dry_run}")
        self.stdout.write(f"  sendAttempted  : {result.send_attempted}")
        self.stdout.write(f"  provider       : {result.provider}")
        self.stdout.write(f"  limitedTestMode: {result.limited_test_mode}")
        self.stdout.write(f"  to             : {result.to_normalized}")
        self.stdout.write(f"  toAllowed      : {result.to_allowed}")
        self.stdout.write(f"  template       : {result.template}")
        self.stdout.write(f"  templateLang   : {result.template_language}")
        self.stdout.write(f"  templateApproved: {result.template_approved}")
        if result.message_id:
            self.stdout.write(f"  messageId      : {result.message_id}")
        if result.provider_message_id:
            self.stdout.write(f"  providerMsgId  : {result.provider_message_id}")
        if result.warnings:
            self.stdout.write(self.style.WARNING("warnings:"))
            for w in result.warnings:
                self.stdout.write(f"  - {w}")
        if result.errors:
            self.stdout.write(self.style.ERROR("errors:"))
            for e in result.errors:
                self.stdout.write(f"  - {e}")
        if result.next_action:
            self.stdout.write(f"nextAction: {result.next_action}")
