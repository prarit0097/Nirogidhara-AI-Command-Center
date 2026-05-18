"""Phase 11D — Director approve/reject CLI for a LearningProposal.

CLI-only. NEVER auto-implements a change; only flips the proposal
row's status + writes one audit event. Director still has to manually
implement and then run ``implement_learning_proposal``.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.learning.service import (
    LearningProposalStateError,
    approve_proposal,
    reject_proposal,
)


class Command(BaseCommand):
    help = (
        "Phase 11D - Director approve or reject a LearningProposal. "
        "NEVER auto-implements; this only records Director's decision. "
        "Implementation is recorded via implement_learning_proposal."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "proposal_id",
            type=int,
            help="LearningProposal.id to review.",
        )
        parser.add_argument(
            "--decision",
            choices=("approved", "rejected"),
            required=True,
            help="Director's decision.",
        )
        parser.add_argument(
            "--operator-name",
            required=True,
            help="Director name (e.g. 'Prarit Sidana').",
        )
        parser.add_argument(
            "--note",
            default="",
            help=(
                "Optional explanation of the decision (recorded on the "
                "audit row + director_note field)."
            ),
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON.",
        )

    def handle(self, *args, **options) -> None:
        decision = options["decision"]
        try:
            if decision == "approved":
                proposal = approve_proposal(
                    proposal_id=int(options["proposal_id"]),
                    operator_name=options["operator_name"],
                    director_note=options.get("note") or "",
                )
            else:
                proposal = reject_proposal(
                    proposal_id=int(options["proposal_id"]),
                    operator_name=options["operator_name"],
                    director_note=options.get("note") or "",
                )
        except LearningProposalStateError as exc:
            payload = {"ok": False, "error": str(exc)}
            if options.get("json"):
                self.stdout.write(json.dumps(payload))
            else:
                self.stderr.write(f"REFUSED: {exc}")
            sys.exit(1)

        payload = {
            "ok": True,
            "proposal_id": proposal.pk,
            "status": proposal.status,
            "decision": proposal.director_decision,
            "reviewed_by": proposal.reviewed_by,
            "reviewed_at": (
                proposal.reviewed_at.isoformat()
                if proposal.reviewed_at
                else None
            ),
        }
        if options.get("json"):
            self.stdout.write(json.dumps(payload, default=str))
            return
        self.stdout.write(
            f"Phase 11D - LearningProposal {proposal.pk} {proposal.status}."
        )
        self.stdout.write(f"  decision    : {proposal.director_decision}")
        self.stdout.write(f"  reviewed_by : {proposal.reviewed_by}")
        self.stdout.write(f"  reviewed_at : {proposal.reviewed_at}")
        if decision == "approved":
            self.stdout.write("")
            self.stdout.write(
                "Next: implement the change manually, then record it:"
            )
            self.stdout.write(
                f"  python manage.py implement_learning_proposal "
                f"{proposal.pk} --operator-name '<NAME>' "
                "--implementation-note '<what you did>'"
            )
