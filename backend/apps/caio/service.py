"""Phase 11C — CAIO Audit Agent V1 deterministic governance audit.

CAIO has NO direct execution power. This module:

- READS Phase 11B call quality scores → compliance risk + trend.
- READS Phase 11A transcript backlog → ingestion gap signal.
- READS Phase 9A-9F Tier-2 agent snapshots → audit upstream agents
  (including CEO AI Orchestration).
- WRITES a single :class:`apps.caio.models.CaioAuditSnapshot` row per
  daily run (plus one ``AgentRun`` + audit events).

It NEVER imports the outbound send / call / shipment paths, NEVER
mutates `Order` / `Payment` / `Customer` / `Lead` / `Shipment` /
`DiscountOfferLog` / any Phase 9 snapshot row, NEVER changes any
agent's prompts or configurations, NEVER creates an
`ApprovalRequest` or executes any `ApprovalMatrix` action.

Deterministic V1 — no LLM call. Model identifier:
``"deterministic_v1"``, provider ``"disabled"``, cost ``0``,
``dry_run=True``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.agents.calling_team_leader.models import (
    CallingTeamLeaderSnapshot,
)
from apps.agents.ceo_orchestration.models import CeoOrchestrationSnapshot
from apps.agents.cfo.models import CfoFinancialSnapshot
from apps.agents.data_analyst.models import DataAnalystSnapshot
from apps.agents.rto_prevention.models import RtoRiskSnapshot
from apps.calls.models import CallQualityScore
from apps.calls.transcript_ingestion import get_backlog_overview

from .models import CaioAuditSnapshot


logger = logging.getLogger(__name__)


AGENT_NAME = "caio_v1"
MODEL_USED = "deterministic_v1"

# Phase 9 stale threshold: a snapshot is considered missing/stale when
# the most-recent row is older than this. 48h covers a single missed
# daily run + one extra day of grace.
AGENT_STALE_HOURS = 48

# Trend thresholds for the call quality 7-day rolling comparison.
TREND_UP_PCT = 0.05
TREND_DOWN_PCT = -0.05
TREND_MIN_SAMPLES = 3

# Severity-trigger rule thresholds.
TRANSCRIPT_BACKLOG_AMBER_THRESHOLD = 20
AGENT_DATA_GAP_RED_THRESHOLD = 3

# Anomaly codes CAIO listens for inside each agent's ``alerts`` field.
_CFO_ANOMALIES = {
    "revenue_drop_24h",
    "rto_spike",
    "high_pending_payments",
    "low_order_volume",
}
_CALLING_ANOMALIES = {
    "low_connection_rate",
    "high_transcript_backlog",
    "no_calls_today",
    "agent_concentration_risk",
}
_DATA_ANALYST_ANOMALIES = {
    "conversion_drop",
    "lead_volume_drop",
    "dead_end_calls",
    "geographic_concentration_shift",
}
# CEO orchestration emits ``data_gap`` + agent-specific codes in alerts.
_CEO_ANOMALIES = {"data_gap"}


# Phase 9 agent registry — used by ``gather_agent_snapshots`` and the
# stale check. The tuple is (agent_name, model_class).
PHASE9_AGENTS: tuple[tuple[str, type], ...] = (
    ("ceo_orchestration", CeoOrchestrationSnapshot),
    ("cfo", CfoFinancialSnapshot),
    ("data_analyst", DataAnalystSnapshot),
    ("calling_team_leader", CallingTeamLeaderSnapshot),
    ("rto_prevention", RtoRiskSnapshot),
)


# ---------------------------------------------------------------------------
# Dataclasses + gather helpers
# ---------------------------------------------------------------------------


@dataclass
class AgentSnapshots:
    ceo: CeoOrchestrationSnapshot | None = None
    cfo: CfoFinancialSnapshot | None = None
    data_analyst: DataAnalystSnapshot | None = None
    calling_team_leader: CallingTeamLeaderSnapshot | None = None
    rto_prevention: RtoRiskSnapshot | None = None
    stale_agents: list[str] = field(default_factory=list)


def gather_compliance_risk(window_days: int = 30) -> dict[str, Any]:
    """Phase 11B compliance violations grouped by Call.agent."""
    now = timezone.now()
    cutoff = now - timedelta(days=max(1, int(window_days)))
    qs = CallQualityScore.objects.filter(scored_at__gte=cutoff)
    # Iterating over rows here is cheap — V1 sees <100 scored calls
    # per window. The DB has no easy way to filter a JSON contains
    # across all engines we support, so do it in Python.
    risky_labels: list[str] = []
    risky_count = 0
    for row in qs.values("agent_label", "flags"):
        flags = row.get("flags") or []
        if "compliance_violation" in flags:
            risky_count += 1
            label = (row.get("agent_label") or "unattributed").strip()
            if label and label not in risky_labels:
                risky_labels.append(label)
    return {"count": risky_count, "agent_labels": risky_labels}


def gather_transcript_backlog(window_days: int = 30) -> dict[str, Any]:
    """Phase 11A transcript backlog summary (read-only)."""
    try:
        overview = get_backlog_overview(window_days=window_days)
    except Exception as exc:  # noqa: BLE001 - non-fatal
        logger.warning("phase11c: transcript backlog read failed: %s", exc)
        return {
            "backlog_count": 0,
            "total_calls_in_window": 0,
            "error": str(exc),
        }
    return {
        "backlog_count": int(overview.get("backlog_count") or 0),
        "total_calls_in_window": int(
            overview.get("total_calls_in_window") or 0
        ),
        "ingested_count": int(overview.get("ingested_count") or 0),
    }


def gather_call_quality_trend(window_days: int = 30) -> str:
    """Compare this week's avg composite to the prior week's.

    Returns one of ``up`` / ``flat`` / ``down`` / ``no_data``.
    Requires ``TREND_MIN_SAMPLES`` scored calls in BOTH windows.
    """
    now = timezone.now()
    this_start = now - timedelta(days=7)
    prior_start = now - timedelta(days=14)
    this_qs = CallQualityScore.objects.filter(scored_at__gte=this_start)
    prior_qs = CallQualityScore.objects.filter(
        scored_at__gte=prior_start, scored_at__lt=this_start
    )
    this_count = this_qs.count()
    prior_count = prior_qs.count()
    if this_count < TREND_MIN_SAMPLES or prior_count < TREND_MIN_SAMPLES:
        return CaioAuditSnapshot.Trend.NO_DATA.value
    this_avg = (
        sum(this_qs.values_list("composite_score", flat=True))
        / max(1, this_count)
    )
    prior_avg = (
        sum(prior_qs.values_list("composite_score", flat=True))
        / max(1, prior_count)
    )
    if prior_avg <= 0:
        return CaioAuditSnapshot.Trend.NO_DATA.value
    delta_ratio = (this_avg - prior_avg) / prior_avg
    if delta_ratio > TREND_UP_PCT:
        return CaioAuditSnapshot.Trend.UP.value
    if delta_ratio < TREND_DOWN_PCT:
        return CaioAuditSnapshot.Trend.DOWN.value
    return CaioAuditSnapshot.Trend.FLAT.value


def _snapshot_is_stale(snapshot, *, now=None) -> bool:
    if snapshot is None:
        return True
    now = now or timezone.now()
    # ``RtoRiskSnapshot`` has no ``snapshot_at`` field — it's per-order
    # and orders itself by ``-created_at``. Use whichever field exists.
    candidate = (
        getattr(snapshot, "snapshot_at", None)
        or getattr(snapshot, "created_at", None)
    )
    if candidate is None:
        return True
    return (now - candidate) > timedelta(hours=AGENT_STALE_HOURS)


def gather_agent_snapshots() -> AgentSnapshots:
    """Pull the latest row per Phase 9 agent + flag stale ones."""
    now = timezone.now()
    bundle = AgentSnapshots()
    bundle.ceo = (
        CeoOrchestrationSnapshot.objects.order_by("-snapshot_at").first()
    )
    bundle.cfo = CfoFinancialSnapshot.objects.order_by("-snapshot_at").first()
    bundle.data_analyst = (
        DataAnalystSnapshot.objects.order_by("-snapshot_at").first()
    )
    bundle.calling_team_leader = (
        CallingTeamLeaderSnapshot.objects.order_by("-snapshot_at").first()
    )
    # RtoRiskSnapshot is per-order, no ``snapshot_at`` — most recent row
    # represents the most recent daily sweep.
    bundle.rto_prevention = (
        RtoRiskSnapshot.objects.order_by("-created_at").first()
    )

    pairs = (
        ("ceo_orchestration", bundle.ceo),
        ("cfo", bundle.cfo),
        ("data_analyst", bundle.data_analyst),
        ("calling_team_leader", bundle.calling_team_leader),
        ("rto_prevention", bundle.rto_prevention),
    )
    bundle.stale_agents = [
        name for name, snap in pairs if _snapshot_is_stale(snap, now=now)
    ]
    return bundle


def _alerts(snapshot) -> list[str]:
    if snapshot is None:
        return []
    return list(getattr(snapshot, "alerts", None) or [])


def compute_agent_anomaly_flags(
    snapshots: AgentSnapshots,
) -> dict[str, list[str]]:
    """Per-agent anomaly codes lifted from each snapshot's alerts."""
    flags: dict[str, list[str]] = {}

    # CFO
    cfo_alerts = [a for a in _alerts(snapshots.cfo) if a in _CFO_ANOMALIES]
    if cfo_alerts:
        flags["cfo"] = cfo_alerts

    # Calling Team Leader
    ctl_alerts = [
        a
        for a in _alerts(snapshots.calling_team_leader)
        if a in _CALLING_ANOMALIES
    ]
    if ctl_alerts:
        flags["calling_team_leader"] = ctl_alerts

    # Data Analyst — alerts + funnel conversion drop heuristic.
    da_codes: list[str] = [
        a
        for a in _alerts(snapshots.data_analyst)
        if a in _DATA_ANALYST_ANOMALIES
    ]
    da_snap = snapshots.data_analyst
    if da_snap is not None:
        rate = float(getattr(da_snap, "call_to_confirmed_rate", 0.0) or 0.0)
        call_count = int(getattr(da_snap, "call_count_30d", 0) or 0)
        # Only emit the funnel-low code when there were enough calls to
        # make the rate statistically meaningful.
        if call_count >= 5 and rate < 0.10:
            if "funnel_conversion_low" not in da_codes:
                da_codes.append("funnel_conversion_low")
    if da_codes:
        flags["data_analyst"] = da_codes

    # CEO Orchestration — health tier + cross-cutting data gaps.
    ceo_snap = snapshots.ceo
    if ceo_snap is not None:
        ceo_codes: list[str] = []
        tier = (getattr(ceo_snap, "health_tier", "") or "").lower()
        if tier == "critical":
            ceo_codes.append("ceo_health_critical")
        elif tier == "poor":
            ceo_codes.append("ceo_health_poor")
        if any(a == "data_gap" for a in _alerts(ceo_snap)):
            ceo_codes.append("data_gap")
        if ceo_codes:
            flags["ceo_orchestration"] = ceo_codes

    # RTO Prevention — aggregate high/critical tier count from the
    # most recent 24h cohort.
    if snapshots.rto_prevention is not None:
        now = timezone.now()
        cohort = RtoRiskSnapshot.objects.filter(
            created_at__gte=now - timedelta(hours=24)
        )
        high_critical = cohort.filter(
            risk_tier__in=("high", "critical")
        ).count()
        if high_critical > 0:
            flags["rto_prevention"] = ["high_rto_risk_orders"]

    return flags


def compute_weak_learning_indicators(
    *,
    transcript_backlog_count: int,
    quality_backlog_count: int,
    call_quality_trend: str,
    snapshots: AgentSnapshots,
    window_days: int,
) -> list[str]:
    """Rule-based detection of learning gap codes."""
    indicators: list[str] = []
    if transcript_backlog_count > TRANSCRIPT_BACKLOG_AMBER_THRESHOLD:
        indicators.append("transcript_ingestion_stalled")
    if quality_backlog_count > 0:
        indicators.append("no_calls_being_scored")

    # Inspect the % of scored calls in the window that had
    # zero_agent_utterances — high ratio suggests transcript ingestion
    # is dropping the agent side somehow.
    cutoff = timezone.now() - timedelta(days=max(1, int(window_days)))
    qs = CallQualityScore.objects.filter(scored_at__gte=cutoff)
    total = qs.count()
    if total >= 4:
        zero_agent = sum(
            1
            for row in qs.values_list("flags", flat=True)
            if "zero_agent_utterances" in (row or [])
        )
        if zero_agent / total > 0.50:
            indicators.append("all_agent_utterances_missing")

    if call_quality_trend == CaioAuditSnapshot.Trend.DOWN.value:
        indicators.append("declining_call_quality")

    ctl = snapshots.calling_team_leader
    if ctl is not None:
        if int(getattr(ctl, "call_count_7d", 0) or 0) == 0:
            indicators.append("no_recent_calls")

    # Dedupe preserving order.
    deduped: list[str] = []
    for code in indicators:
        if code not in deduped:
            deduped.append(code)
    return deduped


def audit_ceo_ai(ceo_snapshot) -> list[str]:
    """Structured observations about the latest CEO Orchestration run."""
    if ceo_snapshot is None:
        return ["CEO AI snapshot not found - data gap"]
    notes: list[str] = []
    tier = (getattr(ceo_snapshot, "health_tier", "") or "").lower()
    score = int(getattr(ceo_snapshot, "business_health_score", 0) or 0)
    priorities = list(getattr(ceo_snapshot, "top_3_priorities", []) or [])
    priority_summaries: list[str] = []
    for entry in priorities[:3]:
        issue = ""
        if isinstance(entry, dict):
            issue = (
                entry.get("issue")
                or entry.get("priority")
                or entry.get("recommended_action")
                or ""
            )
        elif isinstance(entry, str):
            issue = entry
        if issue:
            priority_summaries.append(str(issue)[:80])
    priority_str = ", ".join(priority_summaries) or "none"
    notes.append(
        f"CEO health tier is {tier or 'unknown'} (score {score}). "
        f"Top priorities: {priority_str}."
    )

    alerts = _alerts(ceo_snapshot)
    data_gap_alerts = [a for a in alerts if a == "data_gap"]
    if data_gap_alerts:
        notes.append(
            f"data_gap_count: {len(data_gap_alerts)} agent(s) missing"
        )

    # Lift every non-trivial alert into a per-line CEO note so the
    # Director can spot issues without reading the full snapshot.
    summary = getattr(ceo_snapshot, "agent_status_summary", {}) or {}
    if isinstance(summary, dict):
        for agent_name, payload in summary.items():
            if not isinstance(payload, dict):
                continue
            status = (payload.get("status") or "").lower()
            if status in {"alert", "missing"}:
                summary_text = str(payload.get("summary") or "")[:80]
                notes.append(
                    f"Agent anomaly: {agent_name} is {status} - {summary_text}"
                )

    return notes


def compute_severity(
    *,
    compliance_risk_count: int,
    agent_data_gaps: int,
    weak_learning_indicators: list[str],
    agent_anomaly_flags: dict[str, list[str]],
    transcript_backlog_count: int,
    call_quality_trend: str,
) -> str:
    """Apply the severity rule cascade."""
    if (
        compliance_risk_count > 0
        or agent_data_gaps >= AGENT_DATA_GAP_RED_THRESHOLD
    ):
        return CaioAuditSnapshot.Severity.RED.value
    amber = (
        bool(weak_learning_indicators)
        or any(agent_anomaly_flags.values())
        or transcript_backlog_count > TRANSCRIPT_BACKLOG_AMBER_THRESHOLD
        or call_quality_trend == CaioAuditSnapshot.Trend.DOWN.value
    )
    if amber:
        return CaioAuditSnapshot.Severity.AMBER.value
    return CaioAuditSnapshot.Severity.GREEN.value


def generate_recommendation_text(
    *,
    severity: str,
    compliance_risk: dict[str, Any],
    agent_data_gap_names: list[str],
    agent_anomaly_flags: dict[str, list[str]],
    weak_learning_indicators: list[str],
    call_quality_trend: str,
    transcript_backlog_count: int,
    ceo_audit_notes: list[str],
) -> str:
    """Structured internal Director briefing. NEVER customer-facing."""
    lines: list[str] = []
    lines.append(f"CAIO severity: {severity.upper()}")
    if severity == CaioAuditSnapshot.Severity.RED.value:
        lines.append("Why RED: urgent review required.")
    elif severity == CaioAuditSnapshot.Severity.AMBER.value:
        lines.append("Why AMBER: see weak learning / agent anomalies below.")
    else:
        lines.append("Why GREEN: no compliance risk, no agent gaps, no anomalies.")

    lines.append("")
    lines.append(
        f"Compliance risk: {compliance_risk['count']} call(s) with "
        f"violations in last 30 days."
    )
    if compliance_risk.get("agent_labels"):
        labels = ", ".join(compliance_risk["agent_labels"][:5])
        lines.append(f"  Agents involved: {labels}")

    lines.append(
        f"Transcript backlog: {transcript_backlog_count} call(s) awaiting "
        f"ingestion."
    )
    lines.append(f"Call quality trend (7d vs prior 7d): {call_quality_trend}")

    if agent_data_gap_names:
        lines.append("")
        lines.append(
            f"Agent data gaps: {', '.join(agent_data_gap_names)} (no snapshot "
            f"in last {AGENT_STALE_HOURS}h)."
        )

    if agent_anomaly_flags:
        lines.append("")
        lines.append("Agent anomalies:")
        for agent_name, codes in agent_anomaly_flags.items():
            lines.append(f"  - {agent_name}: {', '.join(codes)}")

    if weak_learning_indicators:
        lines.append("")
        lines.append("Weak learning indicators:")
        for code in weak_learning_indicators:
            lines.append(f"  - {code}")

    if ceo_audit_notes:
        lines.append("")
        lines.append("CEO AI audit:")
        for note in ceo_audit_notes:
            lines.append(f"  - {note}")

    lines.append("")
    lines.append("Recommended Director actions (no auto-execution):")
    if compliance_risk["count"] > 0:
        lines.append(
            "  - Review call quality logs; provide coaching to flagged "
            "agent(s)."
        )
    if agent_data_gap_names:
        lines.append(
            "  - Check Celery beat is running on VPS; verify the "
            f"{len(agent_data_gap_names)} stale agent(s) ran their daily task."
        )
    if severity == CaioAuditSnapshot.Severity.RED.value:
        lines.append(
            "  - Urgent review required - see compliance_risk_agents + "
            "agent_data_gap_names above."
        )
    if (
        not compliance_risk["count"]
        and not agent_data_gap_names
        and severity != CaioAuditSnapshot.Severity.RED.value
        and not weak_learning_indicators
    ):
        lines.append("  - Continue monitoring; no action needed today.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Snapshot builder + sandbox helper
# ---------------------------------------------------------------------------


def _sandbox_active() -> bool:
    try:
        from apps.ai_governance.sandbox import is_sandbox_enabled
    except Exception:  # noqa: BLE001
        return False
    try:
        return bool(is_sandbox_enabled())
    except Exception:  # noqa: BLE001
        return False


def build_snapshot(*, window_days: int = 30) -> CaioAuditSnapshot:
    """Assemble a CaioAuditSnapshot instance WITHOUT persisting it.

    The caller (Celery task / manual command) decides whether to
    persist and link to an AgentRun.
    """
    started_ms = time.monotonic()
    now = timezone.now()
    sandbox = _sandbox_active()

    compliance_risk = gather_compliance_risk(window_days=window_days)
    transcript_backlog = gather_transcript_backlog(window_days=window_days)
    call_quality_trend = gather_call_quality_trend(window_days=window_days)
    snapshots = gather_agent_snapshots()
    agent_anomaly_flags = compute_agent_anomaly_flags(snapshots)

    # Compute Phase 11B scoring backlog count for the weak-learning
    # rule WITHOUT importing the scorer (avoids circular weight). The
    # backlog is small and cheap to count inline.
    from apps.calls.quality_scorer import get_scoring_backlog

    quality_backlog_count = get_scoring_backlog().count()

    weak_learning = compute_weak_learning_indicators(
        transcript_backlog_count=transcript_backlog["backlog_count"],
        quality_backlog_count=quality_backlog_count,
        call_quality_trend=call_quality_trend,
        snapshots=snapshots,
        window_days=window_days,
    )

    ceo_audit_notes = audit_ceo_ai(snapshots.ceo)

    severity = compute_severity(
        compliance_risk_count=compliance_risk["count"],
        agent_data_gaps=len(snapshots.stale_agents),
        weak_learning_indicators=weak_learning,
        agent_anomaly_flags=agent_anomaly_flags,
        transcript_backlog_count=transcript_backlog["backlog_count"],
        call_quality_trend=call_quality_trend,
    )

    recommendation_text = generate_recommendation_text(
        severity=severity,
        compliance_risk=compliance_risk,
        agent_data_gap_names=snapshots.stale_agents,
        agent_anomaly_flags=agent_anomaly_flags,
        weak_learning_indicators=weak_learning,
        call_quality_trend=call_quality_trend,
        transcript_backlog_count=transcript_backlog["backlog_count"],
        ceo_audit_notes=ceo_audit_notes,
    )

    snapshot = CaioAuditSnapshot(
        snapshot_at=now,
        window_days=int(window_days),
        severity=severity,
        compliance_risk_call_count=compliance_risk["count"],
        compliance_risk_agent_labels=compliance_risk["agent_labels"],
        transcript_backlog_count=transcript_backlog["backlog_count"],
        call_quality_trend=call_quality_trend,
        agent_data_gaps=len(snapshots.stale_agents),
        agent_data_gap_names=snapshots.stale_agents,
        agent_anomaly_flags=agent_anomaly_flags,
        weak_learning_indicators=weak_learning,
        ceo_audit_notes=ceo_audit_notes,
        recommendation_text=recommendation_text,
        audited_agents=[
            "phase9a_customer_success",
            "phase9b_rto_prevention",
            "phase9c_cfo",
            "phase9d_data_analyst",
            "phase9e_calling_team_leader",
            "phase9f_ceo_orchestration",
            "phase11a_transcript_ingestion",
            "phase11b_call_quality_scorer",
        ],
        sandbox=sandbox,
    )

    # Tracking note for the caller — not persisted.
    snapshot._duration_ms = int((time.monotonic() - started_ms) * 1000)  # type: ignore[attr-defined]
    return snapshot


__all__ = (
    "AGENT_NAME",
    "MODEL_USED",
    "AgentSnapshots",
    "PHASE9_AGENTS",
    "gather_compliance_risk",
    "gather_transcript_backlog",
    "gather_call_quality_trend",
    "gather_agent_snapshots",
    "compute_agent_anomaly_flags",
    "compute_weak_learning_indicators",
    "audit_ceo_ai",
    "compute_severity",
    "generate_recommendation_text",
    "build_snapshot",
)
