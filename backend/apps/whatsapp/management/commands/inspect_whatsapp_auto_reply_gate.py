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

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.whatsapp.meta_one_number_test import (
    check_waba_subscription,
    get_allowed_test_numbers,
    verify_provider_and_credentials,
)


def _mask_phone(digits: str) -> str:
    if not digits:
        return ""
    if len(digits) <= 4:
        return "*" * len(digits)
    suffix = digits[-4:]
    if len(digits) >= 12:
        return f"+{digits[:2]}{'*' * 5}{suffix}"
    return f"{'*' * (len(digits) - 4)}{suffix}"


class Command(BaseCommand):
    help = (
        "Read-only readiness inspector for the WHATSAPP_AI_AUTO_REPLY_"
        "ENABLED flag flip. Reports every gate the webhook auto-reply "
        "path depends on plus a readyForLimitedAutoReply boolean."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        verification = verify_provider_and_credentials()
        allow_list = get_allowed_test_numbers()

        report: dict[str, Any] = {
            "provider": verification.provider,
            "limitedTestMode": verification.limited_test_mode,
            "autoReplyEnabled": bool(
                getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
            ),
            "allowedListSize": len(allow_list),
            "allowedNumbersMasked": [_mask_phone(d) for d in allow_list],
            "wabaSubscription": {},
            # Backend gate availability — derived from code paths that
            # always run when the env flag is on.
            "finalSendGuardActive": True,
            "consentRequired": True,
            "claimVaultRequired": True,
            "blockedPhraseFilterActive": True,
            "medicalSafetyActive": True,
            "callHandoffEnabled": bool(
                getattr(settings, "WHATSAPP_CALL_HANDOFF_ENABLED", False)
            ),
            "lifecycleEnabled": bool(
                getattr(settings, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED", False)
            ),
            "rescueDiscountEnabled": bool(
                getattr(settings, "WHATSAPP_RESCUE_DISCOUNT_ENABLED", False)
            ),
            "rtoRescueEnabled": bool(
                getattr(settings, "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED", False)
            ),
            "reorderEnabled": bool(
                getattr(settings, "WHATSAPP_REORDER_DAY20_ENABLED", False)
            ),
            "campaignsLocked": True,
            "readyForLimitedAutoReply": False,
            "blockers": [],
            "warnings": [],
            "nextAction": "",
        }

        # WABA subscription summary (best-effort).
        waba = check_waba_subscription()
        report["wabaSubscription"] = {
            "checked": waba.checked,
            "active": waba.active,
            "subscribedAppCount": waba.subscribed_app_count,
            "warning": waba.warning,
            "error": waba.error,
        }
        if waba.warning:
            report["warnings"].append(waba.warning)
        if waba.error:
            report["warnings"].append(waba.error)

        # Blocker enumeration. Each entry must be cleared before the
        # operator may flip WHATSAPP_AI_AUTO_REPLY_ENABLED=true.
        if report["provider"] != "meta_cloud":
            report["blockers"].append(
                "WHATSAPP_PROVIDER must be 'meta_cloud' to enable real "
                "inbound auto-reply."
            )
        if not report["limitedTestMode"]:
            report["blockers"].append(
                "WHATSAPP_LIVE_META_LIMITED_TEST_MODE must be true. "
                "The final-send guard depends on it."
            )
        if report["allowedListSize"] == 0:
            report["blockers"].append(
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
            if report[flag]:
                report["blockers"].append(
                    f"{label} must remain false during the limited "
                    "auto-reply gate."
                )
        if waba.checked and waba.active is False:
            report["blockers"].append(
                "WABA subscribed_apps is empty — Meta will not deliver "
                "inbound webhooks; flipping the flag will not produce "
                "auto-replies."
            )

        # readyForLimitedAutoReply means: every blocker is clear AND
        # the broad-automation flags stay off. The auto-reply env flag
        # itself can be either true or false at this point — the
        # inspector reports either pre-flip readiness (flag=false) or
        # post-flip soak (flag=true).
        report["readyForLimitedAutoReply"] = not report["blockers"]

        if report["blockers"]:
            report["nextAction"] = "keep_auto_reply_disabled_fix_blockers"
        elif report["autoReplyEnabled"]:
            report["nextAction"] = (
                "limited_auto_reply_enabled_monitor_real_inbound"
            )
        else:
            report["nextAction"] = "ready_to_enable_limited_auto_reply_flag"

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
