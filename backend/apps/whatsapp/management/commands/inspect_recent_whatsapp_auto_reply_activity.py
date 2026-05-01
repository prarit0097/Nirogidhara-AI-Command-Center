"""``python manage.py inspect_recent_whatsapp_auto_reply_activity --hours 2 --json``.

Phase 5F-Gate Limited Auto-Reply Flag Plan.

Read-only soak-monitor for the limited auto-reply flag flip. Counts
inbound + outbound WhatsApp activity, AI orchestration audits, and
business-state mutation across the last ``--hours`` window. Lets the
operator verify that:

- Auto-replies only fired for the allowed cohort.
- The deterministic / objection / human-request paths fired with
  expected proportions.
- No ``Order`` / ``Payment`` / ``Shipment`` / ``DiscountOfferLog`` row
  was created during the soak.
- No outbound landed at a phone outside the allow-list (the
  ``whatsapp.ai.auto_reply_guard_blocked`` audit count vs the
  ``whatsapp.ai.auto_reply_flag_path_used`` audit count tells the
  story).

LOCKED rules:

- Read-only. No DB write, no audit row, no provider call.
- Phone numbers masked to last-4 in the latest-events block.
- No tokens / verify token / app secret in output.
"""
from __future__ import annotations

import json as _json
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment
from apps.whatsapp.dashboard import get_recent_auto_reply_activity
from apps.whatsapp.meta_one_number_test import (
    _digits_only,
    get_allowed_test_numbers,
    is_number_allowed_for_live_meta_test,
)
from apps.whatsapp.models import WhatsAppMessage


def _mask_phone(value: str) -> str:
    digits = _digits_only(value or "")
    if not digits:
        return ""
    if len(digits) <= 4:
        return "*" * len(digits)
    suffix = digits[-4:]
    if len(digits) >= 12:
        return f"+{digits[:2]}{'*' * 5}{suffix}"
    return f"{'*' * (len(digits) - 4)}{suffix}"


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# Audit kinds counted by category.
_AI_INBOUND_AUDIT = "whatsapp.ai.run_started"
_AI_REPLY_SENT_AUDIT = "whatsapp.ai.reply_auto_sent"
_AI_REPLY_BLOCKED_AUDIT = "whatsapp.ai.reply_blocked"
_AI_SUGGESTION_STORED_AUDIT = "whatsapp.ai.suggestion_stored"
_AI_HANDOFF_REQUIRED_AUDIT = "whatsapp.ai.handoff_required"
_AI_DETERMINISTIC_USED_AUDIT = "whatsapp.ai.deterministic_grounded_reply_used"
_AI_OBJECTION_USED_AUDIT = "whatsapp.ai.objection_reply_used"
_AI_AUTO_REPLY_FLAG_USED_AUDIT = "whatsapp.ai.auto_reply_flag_path_used"
_AI_AUTO_REPLY_GUARD_BLOCKED_AUDIT = "whatsapp.ai.auto_reply_guard_blocked"
_MESSAGE_DELIVERED_AUDIT = "whatsapp.message.delivered"
_MESSAGE_READ_AUDIT = "whatsapp.message.read"


class Command(BaseCommand):
    help = (
        "Read-only soak monitor for the limited WhatsApp auto-reply "
        "flag flip. Counts AI activity + business-state mutation "
        "deltas in the last --hours window."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--hours",
            type=float,
            default=2.0,
            help="Window size in hours (default 2).",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        # Phase 5F-Gate Auto-Reply Monitoring Dashboard — selector
        # owns the read-only logic. The CLI command keeps the same
        # JSON shape and adds the latestEvents block (which the
        # dashboard surfaces via the audit endpoint instead).
        hours = max(0.0833, float(options.get("hours") or 2.0))
        report: dict[str, Any] = get_recent_auto_reply_activity(hours=hours)

        # Append the latest 25 audit events for human-readable CLI
        # context (the dashboard exposes this via /monitoring/audit/).
        now = timezone.now()
        since = now - timedelta(hours=hours)
        latest_events: list[dict[str, Any]] = []
        ai_audits = AuditEvent.objects.filter(
            kind__startswith="whatsapp.",
            occurred_at__gte=since,
        ).order_by("-occurred_at")[:25]
        for event in ai_audits:
            payload = event.payload or {}
            latest_events.append(
                {
                    "occurred_at": _iso(event.occurred_at),
                    "kind": event.kind,
                    "tone": event.tone,
                    "text": (event.text or "")[:200],
                    "phone_suffix": payload.get("phone_suffix") or "",
                    "customer_id": payload.get("customer_id") or "",
                    "category": payload.get("category", ""),
                    "block_reason": (
                        payload.get("block_reason")
                        or payload.get("reason", "")
                    ),
                }
            )
        report["latestEvents"] = latest_events

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "WhatsApp auto-reply soak activity (last "
                f"{report['windowHours']}h)"
            )
        )
        self.stdout.write(
            f"  inboundAiRunStarted          : {report['inboundAiRunStartedCount']}"
        )
        self.stdout.write(
            f"  replyAutoSent                : {report['replyAutoSentCount']}"
        )
        self.stdout.write(
            f"  replyBlocked                 : {report['replyBlockedCount']}"
        )
        self.stdout.write(
            f"  suggestionStored             : {report['suggestionStoredCount']}"
        )
        self.stdout.write(
            f"  handoffRequired              : {report['handoffRequiredCount']}"
        )
        self.stdout.write(
            f"  deterministicBuilderUsed     : {report['deterministicBuilderUsedCount']}"
        )
        self.stdout.write(
            f"  objectionReplyUsed           : {report['objectionReplyUsedCount']}"
        )
        self.stdout.write(
            f"  autoReplyFlagPathUsed        : {report['autoReplyFlagPathUsedCount']}"
        )
        self.stdout.write(
            f"  autoReplyGuardBlocked        : {report['autoReplyGuardBlockedCount']}"
        )
        self.stdout.write(
            f"  messageDelivered             : {report['messageDeliveredCount']}"
        )
        self.stdout.write(
            f"  messageRead                  : {report['messageReadCount']}"
        )
        self.stdout.write(
            f"  unexpectedNonAllowedSends    : {report['unexpectedNonAllowedSendsCount']}"
        )
        self.stdout.write(
            f"  ordersCreated                : {report['ordersCreatedInWindow']}"
        )
        self.stdout.write(
            f"  paymentsCreated              : {report['paymentsCreatedInWindow']}"
        )
        self.stdout.write(
            f"  shipmentsCreated             : {report['shipmentsCreatedInWindow']}"
        )
        self.stdout.write(
            f"  discountOfferLogsCreated     : {report['discountOfferLogsCreatedInWindow']}"
        )
        if report["warnings"]:
            self.stdout.write(self.style.WARNING("warnings:"))
            for w in report["warnings"]:
                self.stdout.write(f"  - {w}")
        self.stdout.write(f"nextAction: {report['nextAction']}")
