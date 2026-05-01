"""``python manage.py inspect_whatsapp_auto_reply_gate --json``.

Phase 5F-Gate Limited Auto-Reply Flag Plan.

Read-only readiness inspector for the
``WHATSAPP_AI_AUTO_REPLY_ENABLED`` flag flip. Reports every gate
that the real-inbound webhook auto-reply path depends on, plus a
``readyForLimitedAutoReply`` boolean and a typed ``nextAction`` so
the operator knows whether it's safe to flip the flag.

LOCKED rules:

- Read-only. No DB write, no audit row, no provider call, no LLM
  dispatch.
- Phone numbers masked to last-4 by default.
- No tokens / verify token / app secret in output.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand

from apps.whatsapp.dashboard import get_auto_reply_gate_summary


class Command(BaseCommand):
    help = (
        "Read-only readiness inspector for the WHATSAPP_AI_AUTO_REPLY_"
        "ENABLED flag flip. Reports every gate the webhook auto-reply "
        "path depends on plus a readyForLimitedAutoReply boolean."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        # Phase 5F-Gate Auto-Reply Monitoring Dashboard — selector
        # owns the read-only logic. The CLI delegates so the dashboard
        # API and the management command share one source of truth.
        report: dict[str, Any] = get_auto_reply_gate_summary()

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING("WhatsApp auto-reply gate inspector")
        )
        self.stdout.write(f"  provider               : {report['provider']}")
        self.stdout.write(f"  limitedTestMode        : {report['limitedTestMode']}")
        self.stdout.write(f"  autoReplyEnabled       : {report['autoReplyEnabled']}")
        self.stdout.write(f"  allowedListSize        : {report['allowedListSize']}")
        sub = report["wabaSubscription"]
        self.stdout.write(
            f"  wabaActive             : {sub.get('active')} "
            f"(count={sub.get('subscribedAppCount')})"
        )
        self.stdout.write(f"  callHandoffEnabled     : {report['callHandoffEnabled']}")
        self.stdout.write(f"  lifecycleEnabled       : {report['lifecycleEnabled']}")
        self.stdout.write(f"  rescueDiscountEnabled  : {report['rescueDiscountEnabled']}")
        self.stdout.write(f"  rtoRescueEnabled       : {report['rtoRescueEnabled']}")
        self.stdout.write(f"  reorderEnabled         : {report['reorderEnabled']}")
        self.stdout.write(f"  finalSendGuardActive   : {report['finalSendGuardActive']}")
        self.stdout.write(f"  consentRequired        : {report['consentRequired']}")
        self.stdout.write(f"  claimVaultRequired     : {report['claimVaultRequired']}")
        self.stdout.write(f"  blockedPhraseFilter    : {report['blockedPhraseFilterActive']}")
        self.stdout.write(f"  medicalSafetyActive    : {report['medicalSafetyActive']}")
        self.stdout.write(f"  campaignsLocked        : {report['campaignsLocked']}")
        self.stdout.write(f"  readyForLimitedAutoReply: {report['readyForLimitedAutoReply']}")
        if report["blockers"]:
            self.stdout.write(self.style.ERROR("blockers:"))
            for b in report["blockers"]:
                self.stdout.write(f"  - {b}")
        if report["warnings"]:
            self.stdout.write(self.style.WARNING("warnings:"))
            for w in report["warnings"]:
                self.stdout.write(f"  - {w}")
        self.stdout.write(f"nextAction: {report['nextAction']}")
