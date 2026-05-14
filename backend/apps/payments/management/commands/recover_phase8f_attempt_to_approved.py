"""``python manage.py recover_phase8f_attempt_to_approved
--attempt-id <ID> --director-signoff "phase8f_attempt_id_<ID>
phase8f_gate_id_<ID> phase8fHotfix3AttemptRecovery"
--operator-name "..." --confirm-phase8f-attempt-recovery [--json]``.

Phase 8F-Hotfix-3 governance-only recovery for an attempt blocked by
a failed pre-execute signoff check. This command never touches Order,
Payment, Customer, Lead, Shipment, WhatsApp, provider clients, or
``.env*`` files. It only promotes a blocked Phase 8F attempt back to
``approved_for_one_shot_real_mutation`` after narrow prechecks pass.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.payments.models import (
    RazorpayRealCustomerPaymentOrderControlledMutationAttempt,
    RazorpayRealCustomerPaymentOrderControlledMutationGate,
)
from apps.payments.phase8f_real_customer_controlled_mutation import (
    AUDIT_KIND_APPROVED,
    _audit_gate_payload,
    _flag_phase8f_gate_enabled,
    _kill_switch_state,
)


RECOVERY_MARKER = "phase8fHotfix3Recovery_recovered_from_blocked"
SIGNOFF_MARKER = "phase8fHotfix3AttemptRecovery"


def _attempt_payload(
    attempt: RazorpayRealCustomerPaymentOrderControlledMutationAttempt,
) -> dict[str, Any]:
    return {
        "id": attempt.pk,
        "status": attempt.status,
        "blockers": list(attempt.blockers or []),
    }


def _phase8f_recovery_kill_switch_enabled() -> bool:
    state = _kill_switch_state()
    if not state.get("enabled", True):
        return False
    try:
        from apps.saas.models import RuntimeKillSwitch

        row = (
            RuntimeKillSwitch.objects.filter(
                scope=RuntimeKillSwitch.Scope.GLOBAL
            )
            .order_by("-pk")
            .first()
        )
        if row is not None:
            return bool(row.enabled)
    except Exception:  # pragma: no cover - defensive fallback
        pass
    return True


def recover_phase8f_attempt_to_approved(
    *,
    attempt_id: int,
    director_signoff: str,
    operator_name: str,
    confirm_phase8f_attempt_recovery: bool,
) -> dict[str, Any]:
    blockers: list[str] = []
    operator = (operator_name or "").strip()
    signoff = (director_signoff or "").strip()

    if not _flag_phase8f_gate_enabled():
        blockers.append(
            "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
        )
    if not _phase8f_recovery_kill_switch_enabled():
        blockers.append("runtime_kill_switch_disabled")
    if not confirm_phase8f_attempt_recovery:
        blockers.append(
            "phase8fHotfix3_confirm_phase8f_attempt_recovery_required"
        )
    if not operator:
        blockers.append("phase8fHotfix3_operator_name_required")

    attempt = (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects
        .filter(pk=attempt_id)
        .select_related("gate")
        .first()
    )
    if attempt is None:
        blockers.append("phase8fHotfix3_attempt_not_found")
        return {
            "phase": "8F-Hotfix-3",
            "ok": False,
            "attemptRecovered": None,
            "blockers": blockers,
            "nextAction": "fix_phase8fHotfix3_blockers",
        }

    gate = attempt.gate
    if (
        attempt.status
        != RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.BLOCKED
    ):
        blockers.append(
            f"phase8fHotfix3_attempt_status_{attempt.status}_not_recoverable"
        )
    if (
        gate.status
        != RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.APPROVED_FOR_ONE_SHOT_REAL_CUSTOMER_MUTATION
    ):
        blockers.append("phase8fHotfix3_gate_not_in_approved_status")
    if gate.attempts.filter(
        status=(
            RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.EXECUTED
        )
    ).exists():
        blockers.append("phase8fHotfix3_gate_already_has_executed_attempt")

    required_phrases = {
        f"phase8f_attempt_id_{attempt.pk}": (
            "phase8fHotfix3_director_signoff_must_reference_phase8f_attempt_id"
        ),
        f"phase8f_gate_id_{gate.pk}": (
            "phase8fHotfix3_director_signoff_must_reference_phase8f_gate_id"
        ),
        SIGNOFF_MARKER: (
            "phase8fHotfix3_director_signoff_must_reference_recovery_marker"
        ),
    }
    for phrase, blocker in required_phrases.items():
        if phrase not in signoff:
            blockers.append(blocker)

    if blockers:
        return {
            "phase": "8F-Hotfix-3",
            "ok": False,
            "attemptRecovered": _attempt_payload(attempt),
            "blockers": blockers,
            "nextAction": "fix_phase8fHotfix3_blockers",
        }

    attempt.status = (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.APPROVED_FOR_ONE_SHOT_REAL_MUTATION
    )
    attempt.blockers = list(attempt.blockers or []) + [RECOVERY_MARKER]
    attempt.save(update_fields=["status", "blockers", "updated_at"])
    write_event(
        kind=AUDIT_KIND_APPROVED,
        text=(
            "Phase 8F-Hotfix-3 attempt recovery "
            f"attempt_id={attempt.pk} gate_id={gate.pk} "
            "recovered_from_blocked"
        ),
        tone=AuditEvent.Tone.INFO,
        payload=_audit_gate_payload(
            gate,
            extra={
                "attempt_id": attempt.pk,
                "operator_name": operator,
                "recovery": SIGNOFF_MARKER,
            },
        ),
    )
    return {
        "phase": "8F-Hotfix-3",
        "ok": True,
        "attemptRecovered": _attempt_payload(attempt),
        "blockers": [],
        "nextAction": "run_execute_phase8f_with_proper_director_directive",
    }


class Command(BaseCommand):
    help = (
        "Phase 8F-Hotfix-3 - governance-only recovery of a blocked "
        "Phase 8F attempt back to approved_for_one_shot_real_mutation. "
        "Does not touch Order, Payment, providers, WhatsApp, migrations, "
        "models, or .env files."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--attempt-id",
            type=int,
            required=True,
            help="Blocked Phase 8F attempt id to recover.",
        )
        parser.add_argument(
            "--director-signoff",
            type=str,
            required=True,
            help=(
                "Director sign-off text. Must reference "
                "phase8f_attempt_id_<ID>, phase8f_gate_id_<ID>, and "
                "phase8fHotfix3AttemptRecovery."
            ),
        )
        parser.add_argument(
            "--operator-name",
            type=str,
            required=True,
            help="Non-empty name of the human operator running this.",
        )
        parser.add_argument(
            "--confirm-phase8f-attempt-recovery",
            action="store_true",
            help="Required confirmation for this governance recovery.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        attempt_id = int(options.get("attempt_id") or 0)
        if attempt_id <= 0:
            raise CommandError("attempt_id must be a positive integer.")
        report = recover_phase8f_attempt_to_approved(
            attempt_id=attempt_id,
            director_signoff=options.get("director_signoff") or "",
            operator_name=options.get("operator_name") or "",
            confirm_phase8f_attempt_recovery=bool(
                options.get("confirm_phase8f_attempt_recovery")
            ),
        )
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Phase 8F-Hotfix-3 attempt recovery"
            )
        )
        self.stdout.write(f"  ok        : {report['ok']}")
        self.stdout.write(
            f"  nextAction: {report.get('nextAction')}"
        )
        if report.get("attemptRecovered"):
            self.stdout.write(
                f"  attemptId : {report['attemptRecovered']['id']}"
            )
            self.stdout.write(
                f"  status    : {report['attemptRecovered']['status']}"
            )
        if report.get("blockers"):
            self.stdout.write(self.style.ERROR("blockers:"))
            for blocker in report["blockers"]:
                self.stdout.write(f"  - {blocker}")
