"""Phase 8F-Hotfix-3 attempt-level recovery command tests."""
from __future__ import annotations

import io
import json

import pytest
from django.core.management import call_command
from django.utils import timezone as django_timezone

from apps.audit.models import AuditEvent
from apps.payments.management.commands.recover_phase8f_attempt_to_approved import (
    RECOVERY_MARKER,
    SIGNOFF_MARKER,
)
from apps.payments.models import (
    RazorpayRealCustomerPaymentOrderControlledMutationAttempt,
    RazorpayRealCustomerPaymentOrderControlledMutationGate,
)
from apps.payments.phase8f_real_customer_controlled_mutation import (
    AUDIT_KIND_APPROVED,
    execute_phase8f_real_customer_controlled_mutation,
)
from tests.test_phase7i_final_audit_lock import _row_counts
from tests.test_phase8f_real_customer_controlled_mutation import (
    _make_approved_phase8e_gate,
    _phase8f_enabled,
    _phase8f_partial_enabled,
    _structured_signoff,
)


def _make_blocked_attempt(*, source_event_id: str):
    phase8e_gate, order, payment = _make_approved_phase8e_gate(
        source_event_id=source_event_id
    )
    from apps.payments.phase8f_real_customer_controlled_mutation import (
        approve_phase8f_real_customer_controlled_mutation,
        prepare_phase8f_real_customer_controlled_mutation,
    )

    with _phase8f_partial_enabled():
        prep = prepare_phase8f_real_customer_controlled_mutation(
            phase8e_gate_id=phase8e_gate.pk
        )
        approved = approve_phase8f_real_customer_controlled_mutation(
            prep["gate"]["id"],
            reason="Director Phase 8F approve for Hotfix-3 fixture.",
        )
    gate = RazorpayRealCustomerPaymentOrderControlledMutationGate.objects.get(
        pk=prep["gate"]["id"]
    )
    attempt = (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects.get(
            pk=approved["attempt"]["id"]
        )
    )
    attempt.status = (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.BLOCKED
    )
    attempt.blockers = [
        "phase8f_director_signoff_malformed_structured_utc_window"
    ]
    attempt.save(update_fields=["status", "blockers", "updated_at"])
    return gate, attempt, phase8e_gate, order, payment


def _recovery_signoff(
    attempt: RazorpayRealCustomerPaymentOrderControlledMutationAttempt,
    *,
    include_attempt: bool = True,
    include_gate: bool = True,
    include_marker: bool = True,
) -> str:
    parts = ["Director Phase 8F-Hotfix-3 recovery."]
    if include_attempt:
        parts.append(f"phase8f_attempt_id_{attempt.pk}")
    if include_gate:
        parts.append(f"phase8f_gate_id_{attempt.gate_id}")
    if include_marker:
        parts.append(SIGNOFF_MARKER)
    return " ".join(parts)


def _run_recovery_command(
    attempt_id: int,
    *,
    signoff: str,
    operator_name: str = "Prarit Sidana",
    confirm: bool = True,
) -> dict:
    buf = io.StringIO()
    args = [
        "recover_phase8f_attempt_to_approved",
        "--attempt-id",
        str(attempt_id),
        "--director-signoff",
        signoff,
        "--operator-name",
        operator_name,
        "--json",
    ]
    if confirm:
        args.append("--confirm-phase8f-attempt-recovery")
    call_command(*args, stdout=buf)
    return json.loads(buf.getvalue())


@pytest.mark.django_db
def test_phase8f_hotfix3_recovery_attempt_not_found() -> None:
    with _phase8f_partial_enabled():
        out = _run_recovery_command(
            999999,
            signoff=(
                "phase8f_attempt_id_999999 "
                f"{SIGNOFF_MARKER}"
            ),
        )
    assert out["ok"] is False
    assert "phase8fHotfix3_attempt_not_found" in out["blockers"]
    assert out["attemptRecovered"] is None


@pytest.mark.django_db
def test_phase8f_hotfix3_recovery_refuses_attempt_not_blocked() -> None:
    _, attempt, _, _, _ = _make_blocked_attempt(
        source_event_id="phase8f_h3_not_blocked"
    )
    attempt.status = (
        RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.APPROVED_FOR_ONE_SHOT_REAL_MUTATION
    )
    attempt.save(update_fields=["status", "updated_at"])
    with _phase8f_partial_enabled():
        out = _run_recovery_command(
            attempt.pk, signoff=_recovery_signoff(attempt)
        )
    assert out["ok"] is False
    assert (
        "phase8fHotfix3_attempt_status_approved_for_one_shot_real_mutation_not_recoverable"
        in out["blockers"]
    )
    attempt.refresh_from_db()
    assert (
        attempt.status
        == RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.APPROVED_FOR_ONE_SHOT_REAL_MUTATION
    )


@pytest.mark.django_db
def test_phase8f_hotfix3_recovery_refuses_gate_not_approved() -> None:
    gate, attempt, _, _, _ = _make_blocked_attempt(
        source_event_id="phase8f_h3_gate_status"
    )
    gate.status = (
        RazorpayRealCustomerPaymentOrderControlledMutationGate.Status.BLOCKED
    )
    gate.save(update_fields=["status", "updated_at"])
    with _phase8f_partial_enabled():
        out = _run_recovery_command(
            attempt.pk, signoff=_recovery_signoff(attempt)
        )
    assert out["ok"] is False
    assert "phase8fHotfix3_gate_not_in_approved_status" in out["blockers"]
    attempt.refresh_from_db()
    assert (
        attempt.status
        == RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.BLOCKED
    )


@pytest.mark.django_db
def test_phase8f_hotfix3_recovery_refuses_when_gate_has_executed_attempt() -> None:
    gate, attempt, _, _, _ = _make_blocked_attempt(
        source_event_id="phase8f_h3_executed"
    )
    RazorpayRealCustomerPaymentOrderControlledMutationAttempt.objects.create(
        gate=gate,
        target_order_id=attempt.target_order_id,
        target_payment_id=attempt.target_payment_id,
        status=(
            RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.EXECUTED
        ),
    )
    with _phase8f_partial_enabled():
        out = _run_recovery_command(
            attempt.pk, signoff=_recovery_signoff(attempt)
        )
    assert out["ok"] is False
    assert (
        "phase8fHotfix3_gate_already_has_executed_attempt"
        in out["blockers"]
    )
    attempt.refresh_from_db()
    assert (
        attempt.status
        == RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.BLOCKED
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("include_attempt", "include_gate", "include_marker", "expected"),
    (
        (
            False,
            True,
            True,
            "phase8fHotfix3_director_signoff_must_reference_phase8f_attempt_id",
        ),
        (
            True,
            False,
            True,
            "phase8fHotfix3_director_signoff_must_reference_phase8f_gate_id",
        ),
        (
            True,
            True,
            False,
            "phase8fHotfix3_director_signoff_must_reference_recovery_marker",
        ),
    ),
)
def test_phase8f_hotfix3_recovery_refuses_missing_signoff_phrase(
    include_attempt: bool,
    include_gate: bool,
    include_marker: bool,
    expected: str,
) -> None:
    _, attempt, _, _, _ = _make_blocked_attempt(
        source_event_id=f"phase8f_h3_signoff_{expected[-8:]}"
    )
    signoff = _recovery_signoff(
        attempt,
        include_attempt=include_attempt,
        include_gate=include_gate,
        include_marker=include_marker,
    )
    with _phase8f_partial_enabled():
        out = _run_recovery_command(attempt.pk, signoff=signoff)
    assert out["ok"] is False
    assert expected in out["blockers"]
    attempt.refresh_from_db()
    assert (
        attempt.status
        == RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.BLOCKED
    )


@pytest.mark.django_db
def test_phase8f_hotfix3_recovery_refuses_missing_confirm_flag() -> None:
    _, attempt, _, _, _ = _make_blocked_attempt(
        source_event_id="phase8f_h3_confirm"
    )
    with _phase8f_partial_enabled():
        out = _run_recovery_command(
            attempt.pk,
            signoff=_recovery_signoff(attempt),
            confirm=False,
        )
    assert out["ok"] is False
    assert (
        "phase8fHotfix3_confirm_phase8f_attempt_recovery_required"
        in out["blockers"]
    )
    attempt.refresh_from_db()
    assert (
        attempt.status
        == RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.BLOCKED
    )


@pytest.mark.django_db
def test_phase8f_hotfix3_recovery_refuses_empty_operator_name() -> None:
    _, attempt, _, _, _ = _make_blocked_attempt(
        source_event_id="phase8f_h3_operator"
    )
    with _phase8f_partial_enabled():
        out = _run_recovery_command(
            attempt.pk,
            signoff=_recovery_signoff(attempt),
            operator_name="   ",
        )
    assert out["ok"] is False
    assert "phase8fHotfix3_operator_name_required" in out["blockers"]
    attempt.refresh_from_db()
    assert (
        attempt.status
        == RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.BLOCKED
    )


@pytest.mark.django_db
def test_phase8f_hotfix3_recovery_refuses_when_gate_flag_off() -> None:
    _, attempt, _, _, _ = _make_blocked_attempt(
        source_event_id="phase8f_h3_flag"
    )
    out = _run_recovery_command(
        attempt.pk, signoff=_recovery_signoff(attempt)
    )
    assert out["ok"] is False
    assert (
        "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED_must_be_true"
        in out["blockers"]
    )
    attempt.refresh_from_db()
    assert (
        attempt.status
        == RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.BLOCKED
    )


@pytest.mark.django_db
def test_phase8f_hotfix3_recovery_refuses_when_kill_switch_disabled() -> None:
    from apps.saas.models import RuntimeKillSwitch

    _, attempt, _, _, _ = _make_blocked_attempt(
        source_event_id="phase8f_h3_kill"
    )
    kill, _ = RuntimeKillSwitch.objects.get_or_create(
        scope=RuntimeKillSwitch.Scope.GLOBAL,
        defaults={"enabled": False, "reason": "test"},
    )
    kill.enabled = False
    kill.save(update_fields=["enabled", "updated_at"])
    with _phase8f_partial_enabled():
        out = _run_recovery_command(
            attempt.pk, signoff=_recovery_signoff(attempt)
        )
    assert out["ok"] is False
    assert "runtime_kill_switch_disabled" in out["blockers"]
    attempt.refresh_from_db()
    assert (
        attempt.status
        == RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.BLOCKED
    )


@pytest.mark.django_db
def test_phase8f_hotfix3_recovery_success_and_attempt_can_execute() -> None:
    gate, attempt, phase8e_gate, order, payment = _make_blocked_attempt(
        source_event_id="phase8f_h3_success"
    )
    before = _row_counts()
    with _phase8f_partial_enabled():
        out = _run_recovery_command(
            attempt.pk, signoff=_recovery_signoff(attempt)
        )
    after = _row_counts()
    assert out["ok"] is True
    assert (
        out["nextAction"]
        == "run_execute_phase8f_with_proper_director_directive"
    )
    attempt.refresh_from_db()
    order.refresh_from_db()
    payment.refresh_from_db()
    assert (
        attempt.status
        == RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.APPROVED_FOR_ONE_SHOT_REAL_MUTATION
    )
    assert RECOVERY_MARKER in attempt.blockers
    assert order.payment_status == "Partial"
    assert payment.status == "Pending"
    assert before == after
    audit = AuditEvent.objects.filter(
        kind=AUDIT_KIND_APPROVED,
        payload__recovery=SIGNOFF_MARKER,
        payload__attempt_id=attempt.pk,
    ).first()
    assert audit is not None
    assert audit.tone == AuditEvent.Tone.INFO

    now = django_timezone.now()
    execute_signoff = _structured_signoff(
        attempt_id=attempt.pk,
        gate_id=gate.pk,
        phase8e_gate_id=phase8e_gate.pk,
        target_order_id=order.id,
        target_payment_id=payment.id,
        now=now,
    )
    with _phase8f_enabled():
        executed = execute_phase8f_real_customer_controlled_mutation(
            attempt.pk,
            director_signoff=execute_signoff,
            operator_name="Prarit Sidana",
            confirm_one_shot_real_mutation=True,
            now=now,
        )
    assert executed["ok"] is True
    attempt.refresh_from_db()
    order.refresh_from_db()
    payment.refresh_from_db()
    assert (
        attempt.status
        == RazorpayRealCustomerPaymentOrderControlledMutationAttempt.Status.EXECUTED
    )
    assert order.payment_status == "Paid"
    assert payment.status == "Paid"
