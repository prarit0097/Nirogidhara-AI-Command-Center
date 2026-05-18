"""Phase 11D — List LearningProposal rows for Director review.

Read-only. Never mutates anything; never calls a provider.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.learning.models import LearningProposal


class Command(BaseCommand):
    help = (
        "Phase 11D - List LearningProposal rows. Director uses this to "
        "find pending proposals before reviewing. Read-only."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--status",
            default="",
            help=(
                "Filter by status. One of: pending / approved / rejected "
                "/ implemented / cancelled. Default: all statuses."
            ),
        )
        parser.add_argument(
            "--type",
            dest="proposal_type",
            default="",
            help="Filter by proposal_type (e.g. compliance_remediation).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Max rows to show. Default 20.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON.",
        )

    def handle(self, *args, **options) -> None:
        qs = LearningProposal.objects.all()
        status = (options.get("status") or "").strip()
        proposal_type = (options.get("proposal_type") or "").strip()
        if status:
            qs = qs.filter(status=status)
        if proposal_type:
            qs = qs.filter(proposal_type=proposal_type)
        limit = max(1, min(200, int(options.get("limit") or 20)))
        rows = list(qs.order_by("-created_at")[:limit])

        if options.get("json"):
            self.stdout.write(
                json.dumps(
                    [
                        {
                            "id": r.pk,
                            "title": r.title,
                            "proposal_type": r.proposal_type,
                            "status": r.status,
                            "impact_scope": r.impact_scope,
                            "source_agent": r.source_agent,
                            "created_at": r.created_at.isoformat(),
                            "reviewed_by": r.reviewed_by,
                            "reviewed_at": (
                                r.reviewed_at.isoformat()
                                if r.reviewed_at
                                else None
                            ),
                            "caio_snapshot_id": r.caio_snapshot_id,
                        }
                        for r in rows
                    ],
                    default=str,
                )
            )
            return

        self.stdout.write(
            f"Phase 11D - LearningProposal listing ({len(rows)} row(s); "
            f"status={status or 'any'}; type={proposal_type or 'any'}):"
        )
        if not rows:
            self.stdout.write("  (none)")
            return
        for r in rows:
            reviewed = (
                f"{r.reviewed_by}@{r.reviewed_at:%Y-%m-%d %H:%M}"
                if r.reviewed_at
                else "-"
            )
            self.stdout.write(
                f"  #{r.pk:<5} {r.status:<12} {r.impact_scope:<6} "
                f"{r.proposal_type:<24} src={r.source_agent[:24]:<24} "
                f"reviewed={reviewed}"
            )
            self.stdout.write(f"         title : {r.title}")
