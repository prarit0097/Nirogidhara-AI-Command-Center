"""``python manage.py inspect_whatsapp_live_test --phone +91XXXXXXXXXX --json``.

Phase 5F-Gate Hardening Hotfix — read-only diagnostics dashboard for the
limited live Meta one-number test. Tells the operator at a glance:

- Is the destination on the allow-list?
- Does a Customer + WhatsAppConsent + WhatsAppConversation exist for it?
- What outbound + inbound messages are on file?
- What webhook envelopes have arrived (signature_verified counts)?
- What WhatsAppMessageStatusEvent rows have arrived?
- What `whatsapp.*` audit rows are recent?
- Is the WABA actually subscribed to receive webhooks?

LOCKED rules:

- Read-only — never sends, never mutates a row.
- Never prints the access token, verify token, or app secret.
- Gracefully handles missing credentials (skips Graph check with a
  warning instead of crashing).
- Gracefully handles every "no rows" path (empty lists, not nulls).
- Always exits with a JSON document when ``--json`` is passed so a CI
  / log-scrape pipeline can consume the output.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
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
    WhatsAppMessageStatusEvent,
    WhatsAppWebhookEvent,
)


_BODY_PREVIEW_LEN = 160
_LATEST_LIST_LEN = 5
_AUDIT_LATEST_LEN = 25


class Command(BaseCommand):
    help = (
        "Read-only diagnostics for the limited live Meta one-number test. "
        "Inspects Customer, consent, conversation, outbound/inbound "
        "messages, webhook events, status events, audit ledger, and the "
        "WABA subscribed_apps Graph state. Never sends, never mutates."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--phone",
            required=True,
            help="Destination MSISDN to inspect (E.164 or digits).",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        phone_input = options.get("phone") or ""
        normalized = _normalize_phone(phone_input)
        digits = _digits_only(phone_input)

        verification = verify_provider_and_credentials()
        report: dict[str, Any] = {
            "phoneInput": phone_input,
            "normalizedDigits": digits,
            "isAllowedTestNumber": is_number_allowed_for_live_meta_test(phone_input),
            "limitedTestMode": verification.limited_test_mode,
            "provider": verification.provider,
            "allowedListSize": len(get_allowed_test_numbers()),
            "customer": _empty_customer(),
            "whatsappConsent": _empty_consent(),
            "conversation": _empty_conversation(),
            "messages": {"latestOutbound": [], "latestInbound": []},
            "webhookEvents": {"count": 0, "latest": []},
            "statusEvents": {"count": 0, "latest": []},
            "auditEvents": {"count": 0, "latest": []},
            "wabaSubscription": {},
            "latestProviderMessageId": "",
            "warnings": [],
            "errors": [],
            "nextAction": "",
        }

        # --- Customer + Consent -------------------------------------------------
        customer = _find_customer(phone_input, digits, normalized)
        if customer is not None:
            report["customer"] = {
                "found": True,
                "id": customer.id,
                "phone": customer.phone,
                "consent_whatsapp": bool(customer.consent_whatsapp),
            }
            consent = (
                WhatsAppConsent.objects.filter(customer=customer).first()
            )
            if consent is not None:
                report["whatsappConsent"] = {
                    "found": True,
                    "consent_state": consent.consent_state,
                    "source": consent.source,
                    "granted_at": _iso(consent.granted_at),
                    "revoked_at": _iso(consent.revoked_at),
                    "last_inbound_at": _iso(getattr(consent, "last_inbound_at", None)),
                }
            convo = (
                WhatsAppConversation.objects.filter(customer=customer)
                .order_by("-updated_at")
                .first()
            )
            if convo is not None:
                report["conversation"] = {
                    "found": True,
                    "id": convo.id,
                    "status": convo.status,
                    "unread_count": convo.unread_count,
                    "updated_at": _iso(convo.updated_at),
                }

        # --- Messages -----------------------------------------------------------
        if customer is not None:
            outbound_qs = (
                WhatsAppMessage.objects.filter(
                    customer=customer,
                    direction=WhatsAppMessage.Direction.OUTBOUND,
                )
                .order_by("-created_at")[:_LATEST_LIST_LEN]
            )
            inbound_qs = (
                WhatsAppMessage.objects.filter(
                    customer=customer,
                    direction=WhatsAppMessage.Direction.INBOUND,
                )
                .order_by("-created_at")[:_LATEST_LIST_LEN]
            )
            report["messages"] = {
                "latestOutbound": [_message_view(m) for m in outbound_qs],
                "latestInbound": [_message_view(m) for m in inbound_qs],
            }
            latest_outbound_with_provider = (
                WhatsAppMessage.objects.filter(
                    customer=customer,
                    direction=WhatsAppMessage.Direction.OUTBOUND,
                )
                .exclude(provider_message_id="")
                .order_by("-created_at")
                .first()
            )
            if latest_outbound_with_provider is not None:
                report["latestProviderMessageId"] = (
                    latest_outbound_with_provider.provider_message_id
                )

        # --- Webhook envelopes (global; no customer scope on the row) ----------
        webhook_qs = WhatsAppWebhookEvent.objects.order_by("-received_at")
        report["webhookEvents"] = {
            "count": webhook_qs.count(),
            "latest": [_webhook_view(w) for w in webhook_qs[:_LATEST_LIST_LEN]],
        }

        # --- Status events ------------------------------------------------------
        status_qs = WhatsAppMessageStatusEvent.objects.order_by("-received_at")
        if customer is not None:
            status_qs = status_qs.filter(message__customer=customer)
        report["statusEvents"] = {
            "count": status_qs.count(),
            "latest": [_status_view(s) for s in status_qs[:_LATEST_LIST_LEN]],
        }

        # --- Audit (whatsapp.* only) -------------------------------------------
        audit_qs = AuditEvent.objects.filter(
            kind__startswith="whatsapp."
        ).order_by("-occurred_at")[:_AUDIT_LATEST_LEN]
        latest_audit = [_audit_view(a) for a in audit_qs]
        report["auditEvents"] = {
            "count": len(latest_audit),
            "latest": latest_audit,
        }

        # --- WABA subscription -------------------------------------------------
        waba_status = check_waba_subscription()
        report["wabaSubscription"] = waba_status.to_dict()
        if waba_status.warning:
            report["warnings"].append(waba_status.warning)
        if waba_status.error:
            report["errors"].append(waba_status.error)

        # --- Next action -------------------------------------------------------
        report["nextAction"] = _suggest_next_action(report)

        # Inspector is strictly read-only — never writes audit rows.

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("WhatsApp live-test inspector"))
        self.stdout.write(f"  phoneInput         : {report['phoneInput']}")
        self.stdout.write(f"  normalizedDigits   : {report['normalizedDigits']}")
        self.stdout.write(f"  isAllowedTestNumber: {report['isAllowedTestNumber']}")
        self.stdout.write(f"  limitedTestMode    : {report['limitedTestMode']}")
        self.stdout.write(f"  provider           : {report['provider']}")
        self.stdout.write(f"  customer           : {report['customer']['found']} ({report['customer'].get('id', '')})")
        self.stdout.write(f"  conversation       : {report['conversation']['found']}")
        self.stdout.write(f"  outboundMessages   : {len(report['messages']['latestOutbound'])}")
        self.stdout.write(f"  inboundMessages    : {len(report['messages']['latestInbound'])}")
        self.stdout.write(f"  webhookEvents      : {report['webhookEvents']['count']}")
        self.stdout.write(f"  statusEvents       : {report['statusEvents']['count']}")
        sub = report["wabaSubscription"]
        self.stdout.write(
            f"  wabaActive         : {sub.get('wabaSubscriptionActive')} "
            f"(count={sub.get('wabaSubscribedAppCount')})"
        )
        if report["warnings"]:
            self.stdout.write(self.style.WARNING("warnings:"))
            for w in report["warnings"]:
                self.stdout.write(f"  - {w}")
        if report["errors"]:
            self.stdout.write(self.style.ERROR("errors:"))
            for e in report["errors"]:
                self.stdout.write(f"  - {e}")
        self.stdout.write(f"nextAction: {report['nextAction']}")


# ---------------------------------------------------------------------------
# Helpers (module-level for testability)
# ---------------------------------------------------------------------------


def _empty_customer() -> dict[str, Any]:
    return {"found": False, "id": "", "phone": "", "consent_whatsapp": False}


def _empty_consent() -> dict[str, Any]:
    return {
        "found": False,
        "consent_state": "",
        "source": "",
        "granted_at": None,
        "revoked_at": None,
        "last_inbound_at": None,
    }


def _empty_conversation() -> dict[str, Any]:
    return {
        "found": False,
        "id": "",
        "status": "",
        "unread_count": 0,
        "updated_at": None,
    }


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _find_customer(
    phone_input: str, digits: str, normalized: str
) -> Customer | None:
    candidates = [normalized, digits, phone_input]
    if digits:
        candidates.append(digits[-10:])
    seen: set[str] = set()
    for raw in candidates:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        match = Customer.objects.filter(phone__iexact=raw).first()
        if match is not None:
            return match
    if digits:
        return Customer.objects.filter(phone__icontains=digits[-10:]).first()
    return None


def _message_view(message: WhatsAppMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "direction": message.direction,
        "type": message.type,
        "status": message.status,
        "bodyPreview": (message.body or "")[:_BODY_PREVIEW_LEN],
        "provider_message_id": message.provider_message_id or "",
        "created_at": _iso(message.created_at),
    }


def _webhook_view(event: WhatsAppWebhookEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "processing_status": event.processing_status,
        "signature_verified": event.signature_verified,
        "received_at": _iso(event.received_at),
        "processed_at": _iso(event.processed_at),
        "error_message": (event.error_message or "")[:240],
    }


def _status_view(status: WhatsAppMessageStatusEvent) -> dict[str, Any]:
    return {
        "id": status.id,
        "messageId": status.message_id,
        "status": status.status,
        "event_at": _iso(status.event_at),
        "received_at": _iso(status.received_at),
    }


def _audit_view(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "kind": event.kind,
        "tone": event.tone,
        "occurred_at": _iso(event.occurred_at),
        "text": (event.text or "")[:240],
    }


def _suggest_next_action(report: dict[str, Any]) -> str:
    """Map the report state to a single-token recommendation string.

    The order matters — most-blocking signal first.
    """
    waba = report.get("wabaSubscription", {})
    waba_active = waba.get("wabaSubscriptionActive")
    waba_checked = waba.get("wabaSubscriptionChecked", False)

    outbound = report["messages"]["latestOutbound"]
    inbound = report["messages"]["latestInbound"]
    status_count = report["statusEvents"]["count"]

    if waba_checked and waba_active is False:
        return "subscribe_waba_to_app_webhooks"
    if not outbound:
        return "run_one_number_send"
    if not inbound:
        return "verify_inbound_webhook_callback"
    if outbound and inbound and status_count == 0:
        return "observe_status_events_optional"
    if waba_active in (True, None) and outbound and inbound:
        return "gate_hardened_ready_for_limited_ai_auto_reply_plan"
    return "review_warnings"
