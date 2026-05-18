"""Phase 11D — Learning Loop Gate V1 tests.

Defensive contract: across every path (service / CAIO integration /
CLI / API), every outbound entrypoint is patched and asserted
`assert_not_called`. Crucially `PromptVersion` row counts stay
constant — Phase 11D NEVER auto-modifies a prompt.
"""
from __future__ import annotations

from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.ai_governance.models import PromptVersion
from apps.audit.models import AuditEvent
from apps.caio.models import CaioAuditSnapshot
from apps.learning.models import LearningProposal
from apps.learning.service import (
    LearningProposalStateError,
    approve_proposal,
    cancel_proposal,
    create_proposal,
    create_proposals_from_audit,
    get_proposals_summary,
    implement_proposal,
    reject_proposal,
)


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    *,
    severity: str = "red",
    compliance_risk_call_count: int = 0,
    compliance_risk_agent_labels=None,
    weak_learning_indicators=None,
    agent_anomaly_flags=None,
    sandbox: bool = False,
) -> CaioAuditSnapshot:
    return CaioAuditSnapshot.objects.create(
        snapshot_at=timezone.now(),
        window_days=30,
        severity=severity,
        compliance_risk_call_count=compliance_risk_call_count,
        compliance_risk_agent_labels=list(
            compliance_risk_agent_labels or []
        ),
        transcript_backlog_count=0,
        call_quality_trend="no_data",
        agent_data_gaps=0,
        agent_data_gap_names=[],
        agent_anomaly_flags=dict(agent_anomaly_flags or {}),
        weak_learning_indicators=list(weak_learning_indicators or []),
        ceo_audit_notes=[],
        recommendation_text="",
        audited_agents=[],
        sandbox=sandbox,
    )


@pytest.fixture
def patched_outbound():
    with (
        mock.patch(
            "apps.whatsapp.services.queue_template_message"
        ) as wa_queue,
        mock.patch(
            "apps.whatsapp.services.send_freeform_text_message"
        ) as wa_freeform,
        mock.patch(
            "apps.calls.services.trigger_call_for_lead"
        ) as call_trigger,
        mock.patch(
            "apps.shipments.services.create_shipment"
        ) as ship_create,
    ):
        yield {
            "wa_queue": wa_queue,
            "wa_freeform": wa_freeform,
            "call_trigger": call_trigger,
            "ship_create": ship_create,
        }


# ---------------------------------------------------------------------------
# create_proposal
# ---------------------------------------------------------------------------


def test_create_proposal_new_writes_audit(patched_outbound):
    proposal, was_new = create_proposal(
        source_agent="director",
        proposal_type=LearningProposal.ProposalType.SCRIPT_REVIEW.value,
        title="Review intro greeting line",
        proposed_change_text="Update intro line in script v3.2.",
    )
    assert was_new is True
    assert proposal.status == "pending"
    assert proposal.impact_scope == "medium"
    assert AuditEvent.objects.filter(
        kind="learning.proposal.created",
        payload__proposal_id=proposal.pk,
    ).exists()


def test_create_proposal_duplicate_pending_is_reused(patched_outbound):
    first, was_new_1 = create_proposal(
        source_agent="caio_v1",
        proposal_type=LearningProposal.ProposalType.COMPLIANCE_REMEDIATION.value,
        title="Compliance issue",
        proposed_change_text="x",
    )
    second, was_new_2 = create_proposal(
        source_agent="caio_v1",
        proposal_type=LearningProposal.ProposalType.COMPLIANCE_REMEDIATION.value,
        title="Compliance issue again",
        proposed_change_text="y",
    )
    assert was_new_1 is True
    assert was_new_2 is False
    assert first.pk == second.pk
    assert LearningProposal.objects.count() == 1


def test_create_proposal_rejects_blank_text(patched_outbound):
    with pytest.raises(LearningProposalStateError):
        create_proposal(
            source_agent="caio_v1",
            proposal_type=LearningProposal.ProposalType.SCRIPT_REVIEW.value,
            title="x",
            proposed_change_text="",
        )


def test_create_proposal_rejects_unknown_type(patched_outbound):
    with pytest.raises(LearningProposalStateError):
        create_proposal(
            source_agent="caio_v1",
            proposal_type="not_a_real_type",
            title="x",
            proposed_change_text="y",
        )


# ---------------------------------------------------------------------------
# approve / reject / implement / cancel
# ---------------------------------------------------------------------------


def _seed_pending() -> LearningProposal:
    proposal, _ = create_proposal(
        source_agent="caio_v1",
        proposal_type=LearningProposal.ProposalType.SCRIPT_REVIEW.value,
        title="seed",
        proposed_change_text="seed text",
    )
    return proposal


def test_approve_pending_transitions_and_audits(patched_outbound):
    proposal = _seed_pending()
    out = approve_proposal(
        proposal_id=proposal.pk,
        operator_name="Prarit Sidana",
        director_note="Looks good.",
    )
    assert out.status == "approved"
    assert out.director_decision == "approved"
    assert out.reviewed_by == "Prarit Sidana"
    assert out.reviewed_at is not None
    assert AuditEvent.objects.filter(
        kind="learning.proposal.approved",
        payload__proposal_id=proposal.pk,
    ).exists()


def test_approve_non_pending_raises(patched_outbound):
    proposal = _seed_pending()
    approve_proposal(proposal_id=proposal.pk, operator_name="P")
    with pytest.raises(LearningProposalStateError):
        approve_proposal(proposal_id=proposal.pk, operator_name="P")


def test_reject_pending_transitions(patched_outbound):
    proposal = _seed_pending()
    out = reject_proposal(
        proposal_id=proposal.pk,
        operator_name="Prarit Sidana",
        director_note="Out of scope.",
    )
    assert out.status == "rejected"
    assert out.director_decision == "rejected"
    assert AuditEvent.objects.filter(
        kind="learning.proposal.rejected",
        payload__proposal_id=proposal.pk,
    ).exists()


def test_reject_non_pending_raises(patched_outbound):
    proposal = _seed_pending()
    approve_proposal(proposal_id=proposal.pk, operator_name="P")
    with pytest.raises(LearningProposalStateError):
        reject_proposal(proposal_id=proposal.pk, operator_name="P")


def test_implement_approved_transitions(patched_outbound):
    proposal = _seed_pending()
    approve_proposal(proposal_id=proposal.pk, operator_name="P")
    out = implement_proposal(
        proposal_id=proposal.pk,
        operator_name="Prarit Sidana",
        implementation_note=(
            "Updated agent script v3.2 lines 14-22; coached Anil 1:1."
        ),
    )
    assert out.status == "implemented"
    assert out.implemented_by == "Prarit Sidana"
    assert out.implemented_at is not None
    assert "Anil" in out.implementation_note
    assert AuditEvent.objects.filter(
        kind="learning.proposal.implemented",
        payload__proposal_id=proposal.pk,
    ).exists()


def test_implement_requires_nonblank_note(patched_outbound):
    proposal = _seed_pending()
    approve_proposal(proposal_id=proposal.pk, operator_name="P")
    with pytest.raises(LearningProposalStateError):
        implement_proposal(
            proposal_id=proposal.pk,
            operator_name="P",
            implementation_note="   ",
        )


def test_implement_pending_raises(patched_outbound):
    proposal = _seed_pending()  # still pending, not approved
    with pytest.raises(LearningProposalStateError):
        implement_proposal(
            proposal_id=proposal.pk,
            operator_name="P",
            implementation_note="x",
        )


def test_cancel_pending(patched_outbound):
    proposal = _seed_pending()
    out = cancel_proposal(
        proposal_id=proposal.pk, operator_name="P", reason="dup"
    )
    assert out.status == "cancelled"


def test_cancel_approved(patched_outbound):
    proposal = _seed_pending()
    approve_proposal(proposal_id=proposal.pk, operator_name="P")
    out = cancel_proposal(
        proposal_id=proposal.pk, operator_name="P", reason="resolved"
    )
    assert out.status == "cancelled"


def test_cancel_implemented_raises(patched_outbound):
    proposal = _seed_pending()
    approve_proposal(proposal_id=proposal.pk, operator_name="P")
    implement_proposal(
        proposal_id=proposal.pk,
        operator_name="P",
        implementation_note="done",
    )
    with pytest.raises(LearningProposalStateError):
        cancel_proposal(proposal_id=proposal.pk, operator_name="P")


# ---------------------------------------------------------------------------
# create_proposals_from_audit
# ---------------------------------------------------------------------------


def test_create_proposals_from_audit_compliance_violation(patched_outbound):
    snap = _make_snapshot(
        severity="red",
        compliance_risk_call_count=2,
        compliance_risk_agent_labels=["Calling AI . Vapi"],
    )
    summary = create_proposals_from_audit(snap, sandbox=False)
    assert summary["skipped"] is False
    assert summary["created_count"] == 1
    proposal = LearningProposal.objects.first()
    assert proposal.proposal_type == "compliance_remediation"
    assert proposal.impact_scope == "high"
    assert proposal.caio_snapshot_id == snap.pk


def test_create_proposals_from_audit_clean_creates_nothing(patched_outbound):
    snap = _make_snapshot(severity="green")
    summary = create_proposals_from_audit(snap, sandbox=False)
    assert summary["created_count"] == 0
    assert summary["reused_count"] == 0
    assert LearningProposal.objects.count() == 0


def test_create_proposals_from_audit_idempotent(patched_outbound):
    snap = _make_snapshot(
        severity="red",
        compliance_risk_call_count=1,
        compliance_risk_agent_labels=["Agent-A"],
    )
    create_proposals_from_audit(snap, sandbox=False)
    create_proposals_from_audit(snap, sandbox=False)
    assert (
        LearningProposal.objects.filter(
            proposal_type="compliance_remediation",
            status="pending",
        ).count()
        == 1
    )


def test_create_proposals_from_audit_sandbox_skips(patched_outbound):
    snap = _make_snapshot(
        severity="red",
        compliance_risk_call_count=5,
        sandbox=True,
    )
    summary = create_proposals_from_audit(snap, sandbox=True)
    assert summary["skipped"] is True
    assert summary["created_count"] == 0
    assert LearningProposal.objects.count() == 0
    assert AuditEvent.objects.filter(
        kind="learning.proposal.skipped_sandbox"
    ).exists()


def test_create_proposals_from_audit_declining_quality(patched_outbound):
    snap = _make_snapshot(
        severity="amber",
        weak_learning_indicators=["declining_call_quality"],
    )
    summary = create_proposals_from_audit(snap, sandbox=False)
    assert summary["created_count"] == 1
    proposal = LearningProposal.objects.first()
    assert proposal.proposal_type == "script_review"


def test_create_proposals_from_audit_no_recent_calls(patched_outbound):
    snap = _make_snapshot(
        severity="amber",
        weak_learning_indicators=["no_recent_calls"],
    )
    summary = create_proposals_from_audit(snap, sandbox=False)
    assert summary["created_count"] == 1
    proposal = LearningProposal.objects.first()
    assert proposal.proposal_type == "process_improvement"


def test_create_proposals_from_audit_zero_utterances(patched_outbound):
    snap = _make_snapshot(
        severity="amber",
        weak_learning_indicators=["all_agent_utterances_missing"],
    )
    summary = create_proposals_from_audit(snap, sandbox=False)
    assert summary["created_count"] == 1
    proposal = LearningProposal.objects.first()
    assert proposal.proposal_type == "agent_coaching"


# ---------------------------------------------------------------------------
# CAIO task integration
# ---------------------------------------------------------------------------


def test_caio_task_creates_proposal_on_compliance_violation(
    patched_outbound,
):
    from apps.caio.tasks import run_caio_audit_agent_daily
    from apps.calls.models import (
        Call,
        CallQualityScore,
        CallTranscriptLine,
    )

    # Seed a Phase 11B compliance_violation so CAIO actually flags it.
    call = Call.objects.create(
        id="CL-LP-1",
        lead_id="LD-LP-1",
        customer="Test",
        phone="+919999990000",
        agent="Calling AI . Vapi",
        language="Hindi",
        provider=Call.Provider.VAPI,
        provider_call_id="vapi_lp_1",
        status=Call.Status.COMPLETED,
        duration="2:00",
        transcript_line_count=1,
        transcript_ingested_at=timezone.now(),
    )
    CallTranscriptLine.objects.create(
        call=call, order=0, who="agent", text="x"
    )
    CallQualityScore.objects.create(
        call=call,
        scored_at=timezone.now(),
        scoring_version="deterministic_v1",
        line_count=1,
        agent_label="Calling AI . Vapi",
        duration_raw="2:00",
        connection_score=80,
        product_knowledge_score=60,
        compliance_score=40,
        objection_handling_score=70,
        tonality_score=80,
        composite_score=60,
        flags=["compliance_violation"],
        raw_signals={},
    )

    result = run_caio_audit_agent_daily()
    assert result["status"] == "completed"
    assert result["learning_proposals"]["created_count"] >= 1
    assert (
        LearningProposal.objects.filter(
            proposal_type="compliance_remediation",
            status="pending",
        ).count()
        == 1
    )


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def test_cli_list_pending_proposals(patched_outbound):
    _seed_pending()
    out = StringIO()
    call_command(
        "list_learning_proposals",
        "--status",
        "pending",
        stdout=out,
    )
    text = out.getvalue()
    assert "LearningProposal listing" in text
    assert "pending" in text.lower()


def test_cli_review_approves(patched_outbound):
    proposal = _seed_pending()
    out = StringIO()
    call_command(
        "review_learning_proposal",
        str(proposal.pk),
        "--decision",
        "approved",
        "--operator-name",
        "Prarit Sidana",
        "--note",
        "ok",
        stdout=out,
    )
    proposal.refresh_from_db()
    assert proposal.status == "approved"
    assert "approved" in out.getvalue()


def test_cli_review_rejects(patched_outbound):
    proposal = _seed_pending()
    out = StringIO()
    call_command(
        "review_learning_proposal",
        str(proposal.pk),
        "--decision",
        "rejected",
        "--operator-name",
        "Prarit Sidana",
        stdout=out,
    )
    proposal.refresh_from_db()
    assert proposal.status == "rejected"


def test_cli_review_already_decided_exits_1(patched_outbound):
    proposal = _seed_pending()
    approve_proposal(proposal_id=proposal.pk, operator_name="P")
    err = StringIO()
    with pytest.raises(SystemExit) as exc:
        call_command(
            "review_learning_proposal",
            str(proposal.pk),
            "--decision",
            "approved",
            "--operator-name",
            "P",
            stderr=err,
        )
    assert exc.value.code == 1
    assert "REFUSED" in err.getvalue()


def test_cli_implement_happy_path(patched_outbound):
    proposal = _seed_pending()
    approve_proposal(proposal_id=proposal.pk, operator_name="P")
    out = StringIO()
    call_command(
        "implement_learning_proposal",
        str(proposal.pk),
        "--operator-name",
        "Prarit Sidana",
        "--implementation-note",
        "Updated script v3.2",
        stdout=out,
    )
    proposal.refresh_from_db()
    assert proposal.status == "implemented"


def test_cli_implement_blank_note_exits_1(patched_outbound):
    proposal = _seed_pending()
    approve_proposal(proposal_id=proposal.pk, operator_name="P")
    err = StringIO()
    with pytest.raises(SystemExit) as exc:
        call_command(
            "implement_learning_proposal",
            str(proposal.pk),
            "--operator-name",
            "P",
            "--implementation-note",
            "   ",
            stderr=err,
        )
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_anonymous_blocked():
    from rest_framework.test import APIClient

    client = APIClient()
    url = reverse("learning-proposals-list")
    response = client.get(url)
    assert response.status_code in {401, 403}


def test_api_admin_can_read_list_pending_detail_summary(
    auth_client, admin_user, patched_outbound
):
    proposal = _seed_pending()
    approve_proposal(proposal_id=proposal.pk, operator_name="P")
    _seed_pending()  # second pending of a different type below to differ
    # Make the second proposal a different type so it can co-exist as pending.
    create_proposal(
        source_agent="director",
        proposal_type=LearningProposal.ProposalType.AGENT_COACHING.value,
        title="coach",
        proposed_change_text="coach Anil",
        impact_scope=LearningProposal.ImpactScope.HIGH.value,
    )

    client = auth_client(admin_user)

    list_resp = client.get(reverse("learning-proposals-list"))
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["count"] >= 2

    pending_resp = client.get(reverse("learning-proposals-pending"))
    assert pending_resp.status_code == 200
    assert all(
        r["status"] == "pending"
        for r in pending_resp.json()["results"]
    )

    detail_resp = client.get(
        reverse("learning-proposal-detail", args=[proposal.pk])
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == proposal.pk

    summary_resp = client.get(reverse("learning-proposals-summary"))
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["approved"] == 1
    assert summary["highImpactPending"] >= 1
    assert summary["total"] >= 2


def test_api_detail_404(auth_client, admin_user):
    client = auth_client(admin_user)
    url = reverse("learning-proposal-detail", args=[99999])
    assert client.get(url).status_code == 404


def test_api_post_returns_405(auth_client, admin_user):
    client = auth_client(admin_user)
    url = reverse("learning-proposals-list")
    assert client.post(url).status_code == 405
    assert client.patch(url).status_code == 405
    assert client.delete(url).status_code == 405


# ---------------------------------------------------------------------------
# Defensive integration — NO auto-implementation, NO prompt mutation
# ---------------------------------------------------------------------------


def test_no_outbound_no_prompt_mutation_under_full_flow(patched_outbound):
    from apps.caio.tasks import run_caio_audit_agent_daily
    from apps.calls.models import (
        Call,
        CallQualityScore,
        CallTranscriptLine,
    )
    from apps.crm.models import Customer, Lead
    from apps.orders.models import Order
    from apps.payments.models import Payment

    # Seed a compliance_violation to trigger proposal creation.
    call = Call.objects.create(
        id="CL-DEF-1",
        lead_id="LD-DEF-1",
        customer="Test",
        phone="+919999990000",
        agent="Calling AI . Vapi",
        language="Hindi",
        provider=Call.Provider.VAPI,
        provider_call_id="vapi_def_1",
        status=Call.Status.COMPLETED,
        duration="2:00",
        transcript_line_count=1,
        transcript_ingested_at=timezone.now(),
    )
    CallTranscriptLine.objects.create(
        call=call, order=0, who="agent", text="x"
    )
    CallQualityScore.objects.create(
        call=call,
        scored_at=timezone.now(),
        scoring_version="deterministic_v1",
        line_count=1,
        agent_label="Calling AI . Vapi",
        duration_raw="2:00",
        connection_score=80,
        product_knowledge_score=60,
        compliance_score=40,
        objection_handling_score=70,
        tonality_score=80,
        composite_score=60,
        flags=["compliance_violation"],
        raw_signals={},
    )
    # Seed a baseline PromptVersion to verify count stays constant.
    PromptVersion.objects.create(
        id="PV-DEF-1",
        agent="ceo",
        version="v1.0-baseline",
        title="baseline",
        system_policy="x",
        role_prompt="y",
    )

    pre = {
        "Customer": Customer.objects.count(),
        "Lead": Lead.objects.count(),
        "Order": Order.objects.count(),
        "Payment": Payment.objects.count(),
        "PromptVersion": PromptVersion.objects.count(),
    }

    # Run full flow: CAIO daily → creates proposal.
    run_caio_audit_agent_daily()
    proposal = LearningProposal.objects.filter(
        proposal_type="compliance_remediation"
    ).first()
    assert proposal is not None
    # Director approves + implements.
    approve_proposal(
        proposal_id=proposal.pk, operator_name="P", director_note="ok"
    )
    implement_proposal(
        proposal_id=proposal.pk,
        operator_name="P",
        implementation_note="Updated script v3.2 line 14.",
    )

    # NO outbound triggered.
    patched_outbound["wa_queue"].assert_not_called()
    patched_outbound["wa_freeform"].assert_not_called()
    patched_outbound["call_trigger"].assert_not_called()
    patched_outbound["ship_create"].assert_not_called()

    # NO business or prompt row created/modified.
    assert Customer.objects.count() == pre["Customer"]
    assert Lead.objects.count() == pre["Lead"]
    assert Order.objects.count() == pre["Order"]
    assert Payment.objects.count() == pre["Payment"]
    assert PromptVersion.objects.count() == pre["PromptVersion"]


# ---------------------------------------------------------------------------
# Beat schedule sanity — Phase 11D adds NO new beat entry
# ---------------------------------------------------------------------------


def test_beat_schedule_unchanged_at_11():
    from config.celery import build_beat_schedule

    schedule = build_beat_schedule()
    assert len(schedule) == 11
    assert "caio-audit-daily" in schedule


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------


def test_get_proposals_summary_counts(patched_outbound):
    p1 = _seed_pending()
    p2 = _seed_pending()  # reused — same source/type, so still 1 proposal
    assert p1.pk == p2.pk
    # Create one of a different type, approve, then implement.
    other, _ = create_proposal(
        source_agent="director",
        proposal_type=LearningProposal.ProposalType.AGENT_COACHING.value,
        title="t",
        proposed_change_text="x",
        impact_scope=LearningProposal.ImpactScope.HIGH.value,
    )
    approve_proposal(proposal_id=other.pk, operator_name="P")
    implement_proposal(
        proposal_id=other.pk,
        operator_name="P",
        implementation_note="done",
    )
    summary = get_proposals_summary()
    assert summary["pending"] == 1
    assert summary["implemented"] == 1
    assert summary["total"] == 2
