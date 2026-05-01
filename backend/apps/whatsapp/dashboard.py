"""Phase 5F-Gate Auto-Reply Monitoring Dashboard — read-only selectors.

This module is the single source of truth for the WhatsApp auto-reply
monitoring dashboard. It owns the same logic the existing inspector
management commands already execute, but extracts it into composable
selector functions so:

- The Django management commands keep working (they delegate here).
- The DRF API endpoints under ``/api/whatsapp/monitoring/`` consume
  the same shapes the operator sees on the CLI.
- Tests pin the read-only contract once.

LOCKED rules:

- Every function in this module is **strictly read-only**: no DB
  writes, no audit rows, no provider calls, no LLM dispatch.
- Phone numbers are masked to last-4 by default
  (``+91*****99001`` shape).
- Tokens / verify token / app secret never appear in any return value.
- Audit payloads surfaced to the dashboard run through
  :func:`_safe_audit_payload` to scrub any sensitive keys before
  reaching the API consumer.
- The selectors do NOT depend on Django settings beyond what the
  existing management commands already read; they are env-driven and
  safe to call repeatedly.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterable, Mapping

from django.conf import settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.crm.models import Customer
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment

from .meta_one_number_test import (
    _digits_only,
    check_waba_subscription,
    get_allowed_test_numbers,
    is_number_allowed_for_live_meta_test,
    verify_provider_and_credentials,
)
from .models import (
    WhatsAppConsent,
    WhatsAppConversation,
    WhatsAppMessage,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Audit kinds the dashboard counts. Mirrored from the existing
# ``inspect_recent_whatsapp_auto_reply_activity`` command so the soak
# monitor and the dashboard stay aligned.
_AI_INBOUND_AUDIT = "whatsapp.ai.run_started"
_AI_REPLY_SENT_AUDIT = "whatsapp.ai.reply_auto_sent"
_AI_REPLY_BLOCKED_AUDIT = "whatsapp.ai.reply_blocked"
_AI_SUGGESTION_STORED_AUDIT = "whatsapp.ai.suggestion_stored"
_AI_HANDOFF_REQUIRED_AUDIT = "whatsapp.ai.handoff_required"
_AI_DETERMINISTIC_USED_AUDIT = "whatsapp.ai.deterministic_grounded_reply_used"
_AI_DETERMINISTIC_BLOCKED_AUDIT = (
    "whatsapp.ai.deterministic_grounded_reply_blocked"
)
_AI_OBJECTION_USED_AUDIT = "whatsapp.ai.objection_reply_used"
_AI_OBJECTION_BLOCKED_AUDIT = "whatsapp.ai.objection_reply_blocked"
_AI_AUTO_REPLY_FLAG_USED_AUDIT = "whatsapp.ai.auto_reply_flag_path_used"
_AI_AUTO_REPLY_GUARD_BLOCKED_AUDIT = "whatsapp.ai.auto_reply_guard_blocked"
_AI_SAFETY_DOWNGRADED_AUDIT = "whatsapp.ai.safety_downgraded"
_MESSAGE_DELIVERED_AUDIT = "whatsapp.message.delivered"
_MESSAGE_READ_AUDIT = "whatsapp.message.read"
_SEND_BLOCKED_AUDIT = "whatsapp.send.blocked"


# Keys we strip from any audit payload before exposing it on the API.
# The orchestrator already masks phones to last-4 in the canonical
# emit shape, but defence-in-depth: anything that smells like a token
# or a full phone is dropped.
_SENSITIVE_AUDIT_KEYS: frozenset[str] = frozenset(
    {
        "token",
        "access_token",
        "verify_token",
        "app_secret",
        "META_WA_ACCESS_TOKEN",
        "META_WA_VERIFY_TOKEN",
        "META_WA_APP_SECRET",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask_phone(value: str) -> str:
    """``+91 89498 79990`` / ``919XXXXXX9990`` → ``+91*****99001``."""
    digits = _digits_only(value or "")
    if not digits:
        return ""
    if len(digits) <= 4:
        return "*" * len(digits)
    suffix = digits[-4:]
    if len(digits) >= 12:
        return f"+{digits[:2]}{'*' * 5}{suffix}"
    return f"{'*' * (len(digits) - 4)}{suffix}"


def _phone_suffix(value: str) -> str:
    digits = _digits_only(value or "")
    return digits[-4:] if digits else ""


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _safe_audit_payload(
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Drop sensitive keys. Truncate every string to keep dashboards
    snappy and avoid accidental token leaks even if the orchestrator
    grows a new audit shape we haven't seen yet."""
    if not isinstance(payload, Mapping):
        return {}
    safe: dict[str, Any] = {}
    for key, raw_value in payload.items():
        if key in _SENSITIVE_AUDIT_KEYS:
            continue
        if isinstance(raw_value, str):
            safe[key] = raw_value[:240]
        elif isinstance(raw_value, Mapping):
            safe[key] = _safe_audit_payload(raw_value)
        elif isinstance(raw_value, (list, tuple)):
            safe[key] = [
                (
                    _safe_audit_payload(item)
                    if isinstance(item, Mapping)
                    else (item[:240] if isinstance(item, str) else item)
                )
                for item in list(raw_value)[:25]
            ]
        else:
            safe[key] = raw_value
    return safe


def _settings_flag(name: str) -> bool:
    return bool(getattr(settings, name, False))


def _clamp_hours(hours: float | int | None, *, default: float = 2.0) -> float:
    """Clamp to [5 minutes, 7 days]."""
    if hours is None:
        return default
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return default
    if h < (5 / 60):
        return 5 / 60
    if h > 168.0:
        return 168.0
    return h


def _clamp_limit(limit: int | None, *, default: int = 100) -> int:
    if limit is None:
        return default
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    if n < 1:
        return 1
    if n > 500:
        return 500
    return n


def _find_customer(digits: str) -> Customer | None:
    if not digits:
        return None
    candidates = {
        f"+{digits}",
        digits,
        digits[-10:] if len(digits) >= 10 else digits,
    }
    for needle in candidates:
        if not needle:
            continue
        match = Customer.objects.filter(phone__iexact=needle).first()
        if match is not None:
            return match
    return Customer.objects.filter(phone__icontains=digits[-10:]).first()


# ---------------------------------------------------------------------------
# Selector 1 — auto-reply gate summary
# ---------------------------------------------------------------------------


def get_auto_reply_gate_summary() -> dict[str, Any]:
    """Phase 5F-Gate Limited Auto-Reply Flag Plan parity.

    Returns the same shape ``inspect_whatsapp_auto_reply_gate --json``
    emits, computed from settings + provider verification + WABA
    subscription. Phones masked to last-4. Secrets never returned.
    """
    verification = verify_provider_and_credentials()
    allow_list = get_allowed_test_numbers()

    summary: dict[str, Any] = {
        "provider": verification.provider,
        "limitedTestMode": verification.limited_test_mode,
        "autoReplyEnabled": _settings_flag("WHATSAPP_AI_AUTO_REPLY_ENABLED"),
        "allowedListSize": len(allow_list),
        "allowedNumbersMasked": [_mask_phone(d) for d in allow_list],
        "wabaSubscription": {},
        "finalSendGuardActive": True,
        "consentRequired": True,
        "claimVaultRequired": True,
        "blockedPhraseFilterActive": True,
        "medicalSafetyActive": True,
        "callHandoffEnabled": _settings_flag("WHATSAPP_CALL_HANDOFF_ENABLED"),
        "lifecycleEnabled": _settings_flag(
            "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED"
        ),
        "rescueDiscountEnabled": _settings_flag(
            "WHATSAPP_RESCUE_DISCOUNT_ENABLED"
        ),
        "rtoRescueEnabled": _settings_flag(
            "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED"
        ),
        "reorderEnabled": _settings_flag("WHATSAPP_REORDER_DAY20_ENABLED"),
        "campaignsLocked": True,
        "readyForLimitedAutoReply": False,
        "blockers": [],
        "warnings": [],
        "nextAction": "",
    }

    waba = check_waba_subscription()
    summary["wabaSubscription"] = {
        "checked": waba.checked,
        "active": waba.active,
        "subscribedAppCount": waba.subscribed_app_count,
        "warning": waba.warning,
        "error": waba.error,
    }
    if waba.warning:
        summary["warnings"].append(waba.warning)
    if waba.error:
        summary["warnings"].append(waba.error)

    if summary["provider"] != "meta_cloud":
        summary["blockers"].append(
            "WHATSAPP_PROVIDER must be 'meta_cloud' to enable real "
            "inbound auto-reply."
        )
    if not summary["limitedTestMode"]:
        summary["blockers"].append(
            "WHATSAPP_LIVE_META_LIMITED_TEST_MODE must be true. The "
            "final-send guard depends on it."
        )
    if summary["allowedListSize"] == 0:
        summary["blockers"].append(
            "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS is empty. The "
            "final-send guard would refuse every send."
        )
    for flag, label in (
        ("callHandoffEnabled", "WHATSAPP_CALL_HANDOFF_ENABLED"),
        ("lifecycleEnabled", "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED"),
        ("rescueDiscountEnabled", "WHATSAPP_RESCUE_DISCOUNT_ENABLED"),
        ("rtoRescueEnabled", "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED"),
        ("reorderEnabled", "WHATSAPP_REORDER_DAY20_ENABLED"),
    ):
        if summary[flag]:
            summary["blockers"].append(
                f"{label} must remain false during the limited "
                "auto-reply gate."
            )
    if waba.checked and waba.active is False:
        summary["blockers"].append(
            "WABA subscribed_apps is empty — Meta will not deliver "
            "inbound webhooks; flipping the flag will not produce "
            "auto-replies."
        )

    summary["readyForLimitedAutoReply"] = not summary["blockers"]

    if summary["blockers"]:
        summary["nextAction"] = "keep_auto_reply_disabled_fix_blockers"
    elif summary["autoReplyEnabled"]:
        summary["nextAction"] = (
            "limited_auto_reply_enabled_monitor_real_inbound"
        )
    else:
        summary["nextAction"] = "ready_to_enable_limited_auto_reply_flag"

    return summary


# ---------------------------------------------------------------------------
# Selector 2 — recent auto-reply activity
# ---------------------------------------------------------------------------


def get_recent_auto_reply_activity(hours: float | int | None = 2) -> dict[str, Any]:
    """Phase 5F-Gate Limited Auto-Reply Flag Plan soak monitor parity.

    Counts AI activity audit kinds + business-state mutation deltas in
    the trailing window. Same shape as
    ``inspect_recent_whatsapp_auto_reply_activity --json``.
    """
    h = _clamp_hours(hours, default=2.0)
    now = timezone.now()
    since = now - timedelta(hours=h)
    allow_list = set(get_allowed_test_numbers())

    ai_audits = AuditEvent.objects.filter(
        kind__startswith="whatsapp.",
        occurred_at__gte=since,
    ).order_by("-occurred_at")
    kind_counts: dict[str, int] = {}
    for kind in ai_audits.values_list("kind", flat=True):
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    outbound_qs = (
        WhatsAppMessage.objects.filter(
            direction=WhatsAppMessage.Direction.OUTBOUND,
            sent_at__gte=since,
        )
        .exclude(provider_message_id="")
        .select_related("customer")
    )
    inbound_qs = WhatsAppMessage.objects.filter(
        direction=WhatsAppMessage.Direction.INBOUND,
        created_at__gte=since,
    )

    unexpected_non_allowed_sends = 0
    unexpected_send_phone_suffixes: list[str] = []
    for msg in outbound_qs:
        customer_phone = getattr(msg.customer, "phone", "") or ""
        if customer_phone and not is_number_allowed_for_live_meta_test(
            customer_phone
        ):
            unexpected_non_allowed_sends += 1
            suffix = _phone_suffix(customer_phone)
            if suffix and suffix not in unexpected_send_phone_suffixes:
                unexpected_send_phone_suffixes.append(suffix)

    activity: dict[str, Any] = {
        "windowHours": h,
        "since": _iso(since),
        "now": _iso(now),
        "allowedListSize": len(allow_list),
        # Message flow.
        "inboundMessageCount": inbound_qs.count(),
        "outboundMessageCount": outbound_qs.count(),
        # AI activity counts (audit kinds).
        "inboundAiRunStartedCount": kind_counts.get(_AI_INBOUND_AUDIT, 0),
        "replyAutoSentCount": kind_counts.get(_AI_REPLY_SENT_AUDIT, 0),
        "replyBlockedCount": kind_counts.get(_AI_REPLY_BLOCKED_AUDIT, 0),
        "suggestionStoredCount": kind_counts.get(
            _AI_SUGGESTION_STORED_AUDIT, 0
        ),
        "handoffRequiredCount": kind_counts.get(
            _AI_HANDOFF_REQUIRED_AUDIT, 0
        ),
        "deterministicBuilderUsedCount": kind_counts.get(
            _AI_DETERMINISTIC_USED_AUDIT, 0
        ),
        "deterministicBuilderBlockedCount": kind_counts.get(
            _AI_DETERMINISTIC_BLOCKED_AUDIT, 0
        ),
        "objectionReplyUsedCount": kind_counts.get(
            _AI_OBJECTION_USED_AUDIT, 0
        ),
        "objectionReplyBlockedCount": kind_counts.get(
            _AI_OBJECTION_BLOCKED_AUDIT, 0
        ),
        "autoReplyFlagPathUsedCount": kind_counts.get(
            _AI_AUTO_REPLY_FLAG_USED_AUDIT, 0
        ),
        "autoReplyGuardBlockedCount": kind_counts.get(
            _AI_AUTO_REPLY_GUARD_BLOCKED_AUDIT, 0
        ),
        "safetyDowngradedCount": kind_counts.get(
            _AI_SAFETY_DOWNGRADED_AUDIT, 0
        ),
        "messageDeliveredCount": kind_counts.get(_MESSAGE_DELIVERED_AUDIT, 0),
        "messageReadCount": kind_counts.get(_MESSAGE_READ_AUDIT, 0),
        "sendBlockedCount": kind_counts.get(_SEND_BLOCKED_AUDIT, 0),
        # Forensic outbound check.
        "unexpectedNonAllowedSendsCount": unexpected_non_allowed_sends,
        "unexpectedNonAllowedSendSuffixes": unexpected_send_phone_suffixes,
        # Business-state mutation deltas.
        "ordersCreatedInWindow": Order.objects.filter(
            created_at__gte=since
        ).count(),
        "paymentsCreatedInWindow": Payment.objects.filter(
            created_at__gte=since
        ).count(),
        "shipmentsCreatedInWindow": Shipment.objects.filter(
            created_at__gte=since
        ).count(),
        "discountOfferLogsCreatedInWindow": (
            DiscountOfferLog.objects.filter(created_at__gte=since).count()
        ),
        "warnings": [],
        "nextAction": "",
    }

    if unexpected_non_allowed_sends > 0:
        activity["warnings"].append(
            f"{unexpected_non_allowed_sends} outbound message(s) landed at "
            "a phone outside WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS in "
            "the window. Investigate immediately and consider rolling "
            "back the auto-reply flag."
        )
    if (
        activity["ordersCreatedInWindow"]
        or activity["paymentsCreatedInWindow"]
        or activity["shipmentsCreatedInWindow"]
        or activity["discountOfferLogsCreatedInWindow"]
    ):
        activity["warnings"].append(
            "New Order / Payment / Shipment / DiscountOfferLog rows "
            "created in the window. Confirm they were intentional."
        )

    if unexpected_non_allowed_sends > 0:
        activity["nextAction"] = "rollback_auto_reply_flag"
    elif activity["replyAutoSentCount"] > 0 and not activity["warnings"]:
        activity["nextAction"] = (
            "limited_auto_reply_enabled_monitor_real_inbound"
        )
    elif activity["inboundAiRunStartedCount"] == 0:
        activity["nextAction"] = "no_recent_ai_activity_in_window"
    else:
        activity["nextAction"] = "review_blocked_or_suggestion_paths"

    return activity


# ---------------------------------------------------------------------------
# Selector 3 — internal cohort summary
# ---------------------------------------------------------------------------


def get_internal_cohort_summary() -> dict[str, Any]:
    """Phase 5F-Gate Internal Allowed-Number Cohort Tooling parity.

    Strictly read-only per-allowed-number readiness report. Phones are
    ALWAYS masked by this selector; the operator-only
    ``--show-full-numbers`` flag is intentionally NOT exposed via the
    API surface — full numbers must never travel the dashboard wire.
    """
    verification = verify_provider_and_credentials()
    summary: dict[str, Any] = {
        "provider": verification.provider,
        "limitedTestMode": verification.limited_test_mode,
        "autoReplyEnabled": _settings_flag("WHATSAPP_AI_AUTO_REPLY_ENABLED"),
        "callHandoffEnabled": _settings_flag(
            "WHATSAPP_CALL_HANDOFF_ENABLED"
        ),
        "lifecycleEnabled": _settings_flag(
            "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED"
        ),
        "rescueDiscountEnabled": _settings_flag(
            "WHATSAPP_RESCUE_DISCOUNT_ENABLED"
        ),
        "rtoRescueEnabled": _settings_flag(
            "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED"
        ),
        "reorderEnabled": _settings_flag("WHATSAPP_REORDER_DAY20_ENABLED"),
        "allowedListSize": 0,
        "cohort": [],
        "wabaSubscription": {},
        "warnings": [],
        "errors": [],
        "nextAction": "",
    }

    allow_list = get_allowed_test_numbers()
    summary["allowedListSize"] = len(allow_list)

    waba = check_waba_subscription()
    summary["wabaSubscription"] = {
        "checked": waba.checked,
        "active": waba.active,
        "subscribedAppCount": waba.subscribed_app_count,
        "warning": waba.warning,
        "error": waba.error,
    }
    if waba.warning:
        summary["warnings"].append(waba.warning)
    if waba.error:
        summary["errors"].append(waba.error)

    for digits in allow_list:
        entry: dict[str, Any] = {
            "maskedPhone": _mask_phone(digits),
            "suffix": digits[-4:] if digits else "",
            "customerFound": False,
            "customerId": "",
            "customerPhoneMasked": "",
            "consentFound": False,
            "consentState": "",
            "consentSource": "",
            "conversationFound": False,
            "latestInboundId": "",
            "latestInboundAt": None,
            "latestOutboundId": "",
            "latestOutboundStatus": "",
            "latestOutboundAt": None,
            "latestAuditAt": None,
            "readyForControlledTest": False,
            "missingSetup": [],
        }
        customer = _find_customer(digits)
        if customer is not None:
            entry["customerFound"] = True
            entry["customerId"] = customer.id
            entry["customerPhoneMasked"] = _mask_phone(
                _digits_only(customer.phone)
            )
            consent = (
                WhatsAppConsent.objects.filter(customer=customer).first()
            )
            if consent is not None:
                entry["consentFound"] = True
                entry["consentState"] = consent.consent_state
                entry["consentSource"] = consent.source
            else:
                entry["missingSetup"].append("whatsapp_consent_row")
            convo = (
                WhatsAppConversation.objects.filter(customer=customer)
                .order_by("-updated_at")
                .first()
            )
            if convo is not None:
                entry["conversationFound"] = True
                latest_in = (
                    WhatsAppMessage.objects.filter(
                        customer=customer,
                        direction=WhatsAppMessage.Direction.INBOUND,
                    )
                    .order_by("-created_at")
                    .first()
                )
                if latest_in is not None:
                    entry["latestInboundId"] = latest_in.id
                    entry["latestInboundAt"] = _iso(
                        latest_in.delivered_at or latest_in.created_at
                    )
                latest_out = (
                    WhatsAppMessage.objects.filter(
                        customer=customer,
                        direction=WhatsAppMessage.Direction.OUTBOUND,
                    )
                    .order_by("-created_at")
                    .first()
                )
                if latest_out is not None:
                    entry["latestOutboundId"] = latest_out.id
                    entry["latestOutboundStatus"] = latest_out.status
                    entry["latestOutboundAt"] = _iso(
                        latest_out.sent_at or latest_out.created_at
                    )
            latest_audit = (
                AuditEvent.objects.filter(
                    kind__startswith="whatsapp.",
                    payload__customer_id=customer.id,
                )
                .order_by("-occurred_at")
                .first()
            )
            if latest_audit is not None:
                entry["latestAuditAt"] = _iso(latest_audit.occurred_at)
        else:
            entry["missingSetup"].append("customer_row")
            entry["missingSetup"].append("whatsapp_consent_row")

        ready = (
            is_number_allowed_for_live_meta_test(f"+{digits}")
            and entry["customerFound"]
            and entry["consentState"] == "granted"
        )
        entry["readyForControlledTest"] = ready
        if (
            not ready
            and entry["customerFound"]
            and entry["consentState"] != "granted"
            and "consent_state_granted" not in entry["missingSetup"]
        ):
            entry["missingSetup"].append("consent_state_granted")
        summary["cohort"].append(entry)

    if not allow_list:
        summary["nextAction"] = "add_numbers_to_allowed_list"
    elif waba.checked and waba.active is False:
        summary["nextAction"] = "fix_waba_subscription"
    elif summary["autoReplyEnabled"]:
        summary["nextAction"] = "monitor_real_inbound_auto_reply"
    elif any(not e["readyForControlledTest"] for e in summary["cohort"]):
        summary["nextAction"] = "register_missing_customers_or_consent"
    else:
        summary["nextAction"] = "cohort_ready_for_manual_scenario_tests"

    return summary


# ---------------------------------------------------------------------------
# Selector 4 — recent WhatsApp audit events
# ---------------------------------------------------------------------------


def get_recent_whatsapp_audit_events(
    hours: float | int | None = 2,
    limit: int | None = 100,
    *,
    kinds: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Latest WhatsApp-prefixed audit events, scrubbed for sensitive
    keys. Defaults to the most recent 100 events from the trailing
    ``hours`` window.
    """
    h = _clamp_hours(hours, default=2.0)
    n = _clamp_limit(limit, default=100)
    now = timezone.now()
    since = now - timedelta(hours=h)

    qs = AuditEvent.objects.filter(
        kind__startswith="whatsapp.",
        occurred_at__gte=since,
    )
    if kinds:
        kind_list = [k for k in (kinds or []) if k]
        if kind_list:
            qs = qs.filter(kind__in=kind_list)
    qs = qs.order_by("-occurred_at")[:n]

    events: list[dict[str, Any]] = []
    for event in qs:
        payload = _safe_audit_payload(event.payload)
        events.append(
            {
                "id": event.id,
                "occurredAt": _iso(event.occurred_at),
                "kind": event.kind,
                "tone": event.tone,
                "text": (event.text or "")[:240],
                "icon": event.icon,
                # Stable IDs that ops needs to triage without exposing
                # any sensitive payload value.
                "conversationId": payload.get("conversation_id", ""),
                "customerId": payload.get("customer_id", ""),
                "messageId": (
                    payload.get("message_id")
                    or payload.get("outbound_message_id")
                    or ""
                ),
                "inboundMessageId": payload.get("inbound_message_id", ""),
                "phoneSuffix": payload.get("phone_suffix", ""),
                "category": payload.get("category", ""),
                "blockReason": (
                    payload.get("block_reason")
                    or payload.get("reason")
                    or payload.get("blocked_reason")
                    or ""
                ),
                "finalReplySource": payload.get("final_reply_source", ""),
                "deterministicFallbackUsed": bool(
                    payload.get("deterministic_fallback_used", False)
                ),
                "claimVaultUsed": bool(payload.get("claim_vault_used", False)),
            }
        )

    return {
        "windowHours": h,
        "since": _iso(since),
        "now": _iso(now),
        "limit": n,
        "count": len(events),
        "events": events,
    }


# ---------------------------------------------------------------------------
# Selector 5 — mutation safety summary
# ---------------------------------------------------------------------------


def get_whatsapp_mutation_safety_summary(
    hours: float | int | None = 2,
) -> dict[str, Any]:
    """Counts every business-state row created in the trailing window.
    Phase 5F-Gate Real Inbound Deterministic Fallback Fix invariant:
    auto-reply path NEVER mutates Order / Payment / Shipment /
    DiscountOfferLog. This selector is the operator's at-a-glance proof.
    """
    h = _clamp_hours(hours, default=2.0)
    now = timezone.now()
    since = now - timedelta(hours=h)

    orders_created = Order.objects.filter(created_at__gte=since).count()
    payments_created = Payment.objects.filter(created_at__gte=since).count()
    shipments_created = Shipment.objects.filter(created_at__gte=since).count()
    discount_logs_created = DiscountOfferLog.objects.filter(
        created_at__gte=since
    ).count()

    # Phase 5D added lifecycle + handoff models. Import lazily so the
    # selector keeps working even if the migrations for those tables
    # haven't run in older deploys.
    lifecycle_events = 0
    handoff_events = 0
    try:
        from .models import WhatsAppLifecycleEvent, WhatsAppHandoffToCall

        lifecycle_events = WhatsAppLifecycleEvent.objects.filter(
            created_at__gte=since
        ).count()
        handoff_events = WhatsAppHandoffToCall.objects.filter(
            created_at__gte=since
        ).count()
    except Exception:  # noqa: BLE001 - never break the dashboard
        lifecycle_events = 0
        handoff_events = 0

    total = (
        orders_created
        + payments_created
        + shipments_created
        + discount_logs_created
        + lifecycle_events
        + handoff_events
    )
    return {
        "windowHours": h,
        "since": _iso(since),
        "now": _iso(now),
        "ordersCreatedInWindow": orders_created,
        "paymentsCreatedInWindow": payments_created,
        "shipmentsCreatedInWindow": shipments_created,
        "discountOfferLogsCreatedInWindow": discount_logs_created,
        "lifecycleEventsInWindow": lifecycle_events,
        "handoffEventsInWindow": handoff_events,
        "totalMutations": total,
        "allClean": total == 0,
    }


# ---------------------------------------------------------------------------
# Selector 6 — unexpected outbound summary
# ---------------------------------------------------------------------------


def get_unexpected_outbound_summary(
    hours: float | int | None = 2,
) -> dict[str, Any]:
    """Forensic check: any outbound that landed at a phone outside the
    live ``WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`` allow-list inside
    the trailing window. Healthy soak shows 0.

    Phones are masked to last-4 (suffix only) in the per-message
    breakdown.
    """
    h = _clamp_hours(hours, default=2.0)
    now = timezone.now()
    since = now - timedelta(hours=h)

    qs = (
        WhatsAppMessage.objects.filter(
            direction=WhatsAppMessage.Direction.OUTBOUND,
            sent_at__gte=since,
        )
        .exclude(provider_message_id="")
        .select_related("customer")
        .order_by("-sent_at")
    )

    breakdown: list[dict[str, Any]] = []
    count = 0
    for msg in qs[:50]:
        customer_phone = getattr(msg.customer, "phone", "") or ""
        if not customer_phone:
            continue
        if is_number_allowed_for_live_meta_test(customer_phone):
            continue
        count += 1
        breakdown.append(
            {
                "messageId": msg.id,
                "phoneSuffix": _phone_suffix(customer_phone),
                "status": msg.status,
                "sentAt": _iso(msg.sent_at),
                "providerMessageId": (msg.provider_message_id or "")[:60],
            }
        )

    return {
        "windowHours": h,
        "since": _iso(since),
        "now": _iso(now),
        "unexpectedSendsCount": count,
        "breakdown": breakdown,
        "rollbackRecommended": count > 0,
    }


# ---------------------------------------------------------------------------
# Selector 7 — combined dashboard
# ---------------------------------------------------------------------------


def get_whatsapp_monitoring_dashboard(
    hours: float | int | None = 2,
) -> dict[str, Any]:
    """Single-shot composer for the dashboard overview.

    Returns gate / activity / cohort / mutation summaries plus a
    derived ``status`` ∈ {``safe_off``, ``limited_auto_reply_on``,
    ``danger``} so the frontend can render a top-level badge without
    re-deriving safety logic.
    """
    h = _clamp_hours(hours, default=2.0)
    gate = get_auto_reply_gate_summary()
    activity = get_recent_auto_reply_activity(hours=h)
    cohort = get_internal_cohort_summary()
    mutation = get_whatsapp_mutation_safety_summary(hours=h)
    unexpected = get_unexpected_outbound_summary(hours=h)

    # Derive a single top-level status. The frontend renders the
    # corresponding badge — it MUST NOT re-derive this.
    status = "safe_off"
    if (
        unexpected["unexpectedSendsCount"] > 0
        or activity["unexpectedNonAllowedSendsCount"] > 0
        or not mutation["allClean"]
    ):
        status = "danger"
    elif gate["autoReplyEnabled"] and gate["readyForLimitedAutoReply"]:
        status = "limited_auto_reply_on"
    elif gate["autoReplyEnabled"] and not gate["readyForLimitedAutoReply"]:
        # Flag is on but a gate slipped — surface as danger so the
        # operator notices.
        status = "danger"
    elif not gate["readyForLimitedAutoReply"]:
        status = "needs_attention"
    else:
        status = "safe_off"

    next_action = activity.get("nextAction") or gate.get("nextAction") or ""
    if status == "danger":
        next_action = "rollback_auto_reply_flag"

    rollback_ready = (
        gate.get("provider") == "meta_cloud"
        and bool(gate.get("limitedTestMode"))
    )

    return {
        "windowHours": h,
        "generatedAt": _iso(timezone.now()),
        "status": status,
        "nextAction": next_action,
        "rollbackReady": rollback_ready,
        "gate": gate,
        "activity": activity,
        "cohort": cohort,
        "mutationSafety": mutation,
        "unexpectedOutbound": unexpected,
    }


__all__ = (
    "get_auto_reply_gate_summary",
    "get_recent_auto_reply_activity",
    "get_internal_cohort_summary",
    "get_recent_whatsapp_audit_events",
    "get_whatsapp_mutation_safety_summary",
    "get_unexpected_outbound_summary",
    "get_whatsapp_monitoring_dashboard",
)
