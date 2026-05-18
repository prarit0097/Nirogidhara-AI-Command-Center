"""Phase 12B - Classify call outcomes from Phase 2D transcript rows.

CLI-only. Never sends WhatsApp / makes a call / dispatches a shipment.
The only side effect on real runs is `CallOutcomeRecord` row creation
+ `call_outcome.classified` audit rows. `--dry-run` skips both.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.calls.outcome_classifier import (
    _classify_text,
    classify_call,
    classify_campaign_calls,
    classify_recent_calls,
)
from apps.calls.models import Call, CallTranscriptLine


def _summarise_dry_run(calls) -> dict:
    summary = {
        "total": 0,
        "connected_converted": 0,
        "connected_callback": 0,
        "connected_not_interested": 0,
        "connected_unclear": 0,
        "not_connected": 0,
        "no_transcript": 0,
    }
    for call in calls:
        lines = list(
            CallTranscriptLine.objects.filter(call=call).order_by("order")
        )
        customer_text_parts: list[str] = []
        for line in lines:
            who_lower = (line.who or "").lower()
            if any(t in who_lower for t in ("customer", "user", "human")):
                customer_text_parts.append((line.text or "").strip())
        result = _classify_text(
            call_status=call.status,
            customer_text=" ".join(customer_text_parts),
            line_count=sum(1 for line in lines if (line.text or "").strip()),
        )
        summary["total"] += 1
        summary[result.outcome] = summary.get(result.outcome, 0) + 1
    return summary


class Command(BaseCommand):
    help = (
        "Phase 12B - Classify call outcomes. Pass --call-id to score one "
        "Call, --campaign-id for every Call linked to a Phase 12A "
        "campaign gate, or default to recent calls in the --hours "
        "window. --dry-run skips persistence. NEVER auto-applies any "
        "Lead.status update."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--call-id",
            default="",
            help="Classify this single Call.id only.",
        )
        parser.add_argument(
            "--campaign-id",
            type=int,
            default=0,
            help="Classify every Call linked to this Phase 12A gate.",
        )
        parser.add_argument(
            "--hours",
            type=int,
            default=24,
            help="Lookback hours for the default recent-calls sweep.",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        call_id = (options.get("call_id") or "").strip()
        campaign_id = int(options.get("campaign_id") or 0)
        hours = int(options.get("hours") or 24)
        dry_run = bool(options.get("dry_run"))

        try:
            if dry_run:
                if call_id:
                    calls = list(Call.objects.filter(pk=call_id))
                elif campaign_id:
                    from apps.calls.models import AiCallCampaignGate

                    gate = AiCallCampaignGate.objects.filter(
                        pk=campaign_id
                    ).first()
                    lead_ids = (
                        list(gate.leads_attempted or []) if gate else []
                    )
                    calls = [
                        Call.objects.filter(lead_id=lid)
                        .order_by("-created_at")
                        .first()
                        for lid in lead_ids
                    ]
                    calls = [c for c in calls if c is not None]
                else:
                    from django.utils import timezone
                    from datetime import timedelta

                    cutoff = timezone.now() - timedelta(hours=hours)
                    calls = list(
                        Call.objects.filter(created_at__gte=cutoff)
                    )
                summary = _summarise_dry_run(calls)
                summary["dry_run"] = True
            elif call_id:
                record = classify_call(call_id)
                summary = {
                    "dry_run": False,
                    "total": 1,
                    "outcome_record_id": record.pk,
                    "detected_outcome": record.detected_outcome,
                    "confidence": record.confidence,
                    "suggested_lead_status": record.suggested_lead_status,
                }
            elif campaign_id:
                summary = classify_campaign_calls(campaign_id)
                summary["dry_run"] = False
            else:
                summary = classify_recent_calls(hours=hours)
                summary["dry_run"] = False
        except ValueError as exc:
            payload = {"ok": False, "error": str(exc)}
            if options.get("json"):
                self.stdout.write(json.dumps(payload, default=str))
            else:
                self.stderr.write(f"REFUSED: {exc}")
            sys.exit(1)

        if options.get("json"):
            self.stdout.write(json.dumps(summary, default=str))
            return
        self.stdout.write(
            f"Phase 12B - classify (dry_run={summary.get('dry_run', False)}):"
        )
        for key, value in summary.items():
            self.stdout.write(f"  {key:<28} : {value}")
