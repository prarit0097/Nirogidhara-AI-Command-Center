"""Phase 11D — Record Director's manual implementation of a LearningProposal.

This command DOES NOT auto-apply any change. Director must already have
implemented the change manually (updated a script, coached an agent,
fixed a process, etc.). This command only flips the proposal row from
APPROVED -> IMPLEMENTED and records what Director did.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from apps.learning.service import (
    LearningProposalStateError,
    implement_proposal,
)


class Command(BaseCommand):
    help = (
        "Phase 11D - Record Director's manual implementation of an "
        "approved LearningProposal. NEVER auto-applies any change to "
        "prompts / playbooks / agent configs - only flips the row's "
        "status and records the note. Requires non-empty "
        "--implementation-note."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "proposal_id",
            type=int,
            help="LearningProposal.id to mark implemented.",
        )
        parser.add_argument(
            "--operator-name",
            required=True,
            help="Director name (e.g. 'Prarit Sidana').",
        )
        parser.add_argument(
            "--implementation-note",
            required=True,
            help=(
                "What Director actually did. REQUIRED non-empty. "
                "Example: 'Updated Anil's call window to 10am-2pm, "
                "added compliance reminder line to script v3.2.'"
            ),
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON.",
        )

    def handle(self, *args, **options) -> None:
        note = (options.get("implementation_note") or "").strip()
        operator_name = (options.get("operator_name") or "").strip()
        if not note:
            err = (
                "REFUSED: --implementation-note cannot be blank. "
                "Director must record what was actually done."
            )
            if options.get("json"):
                self.stdout.write(
                    json.dumps(
                        {"ok": False, "error": err},
                        default=str,
                    )
                )
            else:
                self.stderr.write(err)
            sys.exit(1)

        try:
            proposal = implement_proposal(
                proposal_id=int(options["proposal_id"]),
                operator_name=operator_name,
                implementation_note=note,
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
            "implemented_by": proposal.implemented_by,
            "implemented_at": (
                proposal.implemented_at.isoformat()
                if proposal.implemented_at
                else None
            ),
        }
        if options.get("json"):
            self.stdout.write(json.dumps(payload, default=str))
            return
        self.stdout.write(
            f"Phase 11D - LearningProposal {proposal.pk} marked "
            "IMPLEMENTED."
        )
        self.stdout.write(
            f"  implemented_by : {proposal.implemented_by}"
        )
        self.stdout.write(
            f"  implemented_at : {proposal.implemented_at}"
        )
        self.stdout.write(
            "  note recorded  : "
            f"{proposal.implementation_note[:160]}..."
            if len(proposal.implementation_note) > 160
            else f"  note recorded  : {proposal.implementation_note}"
        )
