"""Phase 9F — CEO AI Orchestration V1 deterministic synthesis.

All functions in this module are pure given the database state at
the moment of the call and emit no side effects. The Celery task
layer is responsible for persistence and audit emission.

Phase 9F intentionally avoids any reference to the legacy
``ai_governance.CeoBriefing`` model or its scheduled tasks
(``ai-daily-briefing-morning`` / ``ai-daily-briefing-evening``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from apps.agents.calling_team_leader.models import (
    CallingTeamLeaderSnapshot,
)
from apps.agents.cfo.models import CfoFinancialSnapshot
from apps.agents.customer_success.models import CustomerSuccessSnapshot
from apps.agents.data_analyst.models import DataAnalystSnapshot
from apps.agents.rto_prevention.models import RtoRiskSnapshot

from .models import CeoOrchestrationSnapshot


AGENT_NAME = "ceo_orchestration_v1"
MODEL_USED = "deterministic_v1"

ROLLUP_WINDOW_HOURS = 24

# Severity map shared by the alert rollup and the priority picker.
# "low" entries are informational only and stay out of the top-3
# priority list (e.g. ``no_agent_attribution_field``, ``all_clear``).
SEVERITY_MAP: dict[str, str] = {
    # CFO
    "revenue_drop_24h": "critical",
    "rto_spike": "high",
    "high_pending_payments": "high",
    "low_order_volume": "medium",
    # Data Analyst
    "conversion_drop": "high",
    "geographic_concentration_shift": "medium",
    "dead_end_calls": "high",
    "lead_volume_drop": "critical",
    # Calling Team Leader
    "low_connection_rate": "high",
    "high_transcript_backlog": "medium",
    "no_calls_today": "high",
    "agent_concentration_risk": "medium",
    "no_agent_attribution_field": "low",
    # Phase 9F-native
    "data_gap": "high",
    "all_clear": "low",
}

# Severity ordering for sorting + priority selection.
SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

# Internal-only recommended actions (NEVER customer-facing).
RECOMMENDED_ACTION: dict[str, str] = {
    "revenue_drop_24h": (
        "Review last 24h revenue drop; check campaign performance and "
        "dispatch flow."
    ),
    "rto_spike": (
        "Audit RTO prevention queue; escalate critical-tier orders to "
        "team lead."
    ),
    "high_pending_payments": (
        "Review pending Razorpay links and follow up with customers."
    ),
    "low_order_volume": (
        "Check ad spend and lead pipeline; verify campaign delivery."
    ),
    "conversion_drop": (
        "Audit funnel step with lowest conversion; review handoff "
        "scripts."
    ),
    "geographic_concentration_shift": (
        "Diversify ad targeting; investigate state-level concentration."
    ),
    "dead_end_calls": (
        "Audit call scripts; review agent training; check lead quality."
    ),
    "lead_volume_drop": (
        "Check Meta Lead Ads webhook and ad delivery; verify campaign "
        "budgets."
    ),
    "low_connection_rate": (
        "Audit dialer and call routing; review agent call windows."
    ),
    "high_transcript_backlog": (
        "Increase transcript ingestion throughput or backfill Vapi "
        "exports."
    ),
    "no_calls_today": (
        "Verify Vapi credentials and Celery worker; check call queue."
    ),
    "agent_concentration_risk": (
        "Distribute call load; review per-agent caps."
    ),
    "data_gap": (
        "Verify scheduled agent task ran today; check Celery beat and "
        "worker."
    ),
}

AGENT_KEYS = (
    "customer_success",
    "rto_prevention",
    "cfo",
    "data_analyst",
    "calling_team_leader",
)


@dataclass
class LatestSnapshots:
    """Bundle of latest snapshots from each Phase 9A-9E agent."""

    customer_success: CustomerSuccessSnapshot | None = None
    rto_prevention: RtoRiskSnapshot | None = None
    cfo: CfoFinancialSnapshot | None = None
    data_analyst: DataAnalystSnapshot | None = None
    calling_team_leader: CallingTeamLeaderSnapshot | None = None
    customer_success_rollup: dict[str, int] = field(default_factory=dict)
    rto_rollup: dict[str, int] = field(default_factory=dict)


def fetch_latest_snapshots(
    *, now: datetime | None = None
) -> LatestSnapshots:
    """Read each Phase 9A-9E latest row + cohort rollups for 9A/9B.

    Phase 9A and 9B write per-customer / per-order rows; the FK is a
    representative pointer to the latest row, and the rollup dicts
    aggregate the last 24h cohort. Phase 9C / 9D / 9E write one
    business-level row per task invocation, so the latest row IS the
    full snapshot.
    """
    now = now or timezone.now()
    rollup_cutoff = now - timedelta(hours=ROLLUP_WINDOW_HOURS)

    cs_latest = (
        CustomerSuccessSnapshot.objects.order_by("-created_at").first()
    )
    cs_rollup: dict[str, int] = {}
    if cs_latest is not None:
        recent = CustomerSuccessSnapshot.objects.filter(
            created_at__gte=rollup_cutoff
        )
        cs_rollup = {
            "snapshot_count": recent.count(),
            "reorder_candidate_count": recent.filter(
                reorder_candidate=True
            ).count(),
            "at_risk_count": recent.filter(at_risk=True).count(),
        }

    rto_latest = RtoRiskSnapshot.objects.order_by("-created_at").first()
    rto_rollup: dict[str, int] = {}
    if rto_latest is not None:
        recent = RtoRiskSnapshot.objects.filter(
            created_at__gte=rollup_cutoff
        )
        rto_rollup = {
            "snapshot_count": recent.count(),
            "critical_count": recent.filter(risk_tier="critical").count(),
            "high_count": recent.filter(risk_tier="high").count(),
            "medium_count": recent.filter(risk_tier="medium").count(),
            "low_count": recent.filter(risk_tier="low").count(),
        }

    return LatestSnapshots(
        customer_success=cs_latest,
        rto_prevention=rto_latest,
        cfo=CfoFinancialSnapshot.objects.order_by("-snapshot_at").first(),
        data_analyst=DataAnalystSnapshot.objects.order_by(
            "-snapshot_at"
        ).first(),
        calling_team_leader=CallingTeamLeaderSnapshot.objects.order_by(
            "-snapshot_at"
        ).first(),
        customer_success_rollup=cs_rollup,
        rto_rollup=rto_rollup,
    )


def _is_missing(snapshots: LatestSnapshots, key: str) -> bool:
    return getattr(snapshots, key) is None


def compute_health_score(snapshots: LatestSnapshots) -> int:
    base = 70

    # CFO factor.
    if snapshots.cfo is not None:
        alerts = list(snapshots.cfo.alerts or [])
        if "revenue_drop_24h" in alerts:
            base -= 15
        if "high_pending_payments" in alerts:
            base -= 10
        if "low_order_volume" in alerts:
            base -= 10
        if "rto_spike" in alerts:
            base -= 10
        if alerts == ["all_clear"]:
            base += 5
    else:
        base -= 5

    # RTO factor.
    if snapshots.rto_prevention is not None:
        critical = int(snapshots.rto_rollup.get("critical_count", 0))
        high = int(snapshots.rto_rollup.get("high_count", 0))
        base -= min(critical * 3, 20)
        base -= min(high * 1, 10)
    else:
        base -= 5

    # Customer Success factor.
    if snapshots.customer_success is not None:
        at_risk = int(snapshots.customer_success_rollup.get("at_risk_count", 0))
        reorder = int(
            snapshots.customer_success_rollup.get("reorder_candidate_count", 0)
        )
        base -= min(at_risk, 10)
        base += min(reorder // 5, 5)  # small bonus
    else:
        base -= 5

    # Data Analyst factor.
    if snapshots.data_analyst is not None:
        alerts = [
            a for a in (snapshots.data_analyst.alerts or []) if a != "all_clear"
        ]
        base -= min(len(alerts) * 10, 30)
    else:
        base -= 5

    # Calling Team Leader factor.
    if snapshots.calling_team_leader is not None:
        alerts = [
            a
            for a in (snapshots.calling_team_leader.alerts or [])
            if a not in ("all_clear", "no_agent_attribution_field")
        ]
        base -= min(len(alerts) * 5, 20)
    else:
        base -= 5

    return max(0, min(100, base))


def compute_health_tier(score: int) -> str:
    if score <= 19:
        return CeoOrchestrationSnapshot.HealthTier.CRITICAL.value
    if score <= 39:
        return CeoOrchestrationSnapshot.HealthTier.POOR.value
    if score <= 59:
        return CeoOrchestrationSnapshot.HealthTier.FAIR.value
    if score <= 79:
        return CeoOrchestrationSnapshot.HealthTier.GOOD.value
    return CeoOrchestrationSnapshot.HealthTier.EXCELLENT.value


def _alert_entry(
    code: str, *, source_agent: str, rationale: str
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": SEVERITY_MAP.get(code, "medium"),
        "source_agent": source_agent,
        "rationale": rationale,
    }


def roll_up_alerts(
    snapshots: LatestSnapshots, *, missing: list[str] | None = None
) -> list[dict[str, Any]]:
    """Union of every agent's alerts, severity-sorted."""
    rolled: list[dict[str, Any]] = []
    if snapshots.cfo is not None:
        for code in snapshots.cfo.alerts or []:
            if code == "all_clear":
                continue
            rolled.append(
                _alert_entry(
                    code,
                    source_agent="cfo",
                    rationale=snapshots.cfo.alert_text
                    or f"CFO snapshot alert: {code}",
                )
            )
    if snapshots.data_analyst is not None:
        for code in snapshots.data_analyst.alerts or []:
            if code == "all_clear":
                continue
            rolled.append(
                _alert_entry(
                    code,
                    source_agent="data_analyst",
                    rationale=snapshots.data_analyst.alert_text
                    or f"Data Analyst alert: {code}",
                )
            )
    if snapshots.calling_team_leader is not None:
        for code in snapshots.calling_team_leader.alerts or []:
            if code == "all_clear":
                continue
            rolled.append(
                _alert_entry(
                    code,
                    source_agent="calling_team_leader",
                    rationale=snapshots.calling_team_leader.alert_text
                    or f"Calling Team Leader alert: {code}",
                )
            )
    # Phase 9A / 9B cohort signals -> synthetic alerts only when
    # cohort rollups indicate active risk.
    rto_critical = int(snapshots.rto_rollup.get("critical_count", 0))
    if snapshots.rto_prevention is not None and rto_critical > 0:
        rolled.append(
            _alert_entry(
                "rto_spike",
                source_agent="rto_prevention",
                rationale=(
                    f"{rto_critical} critical-tier RTO snapshot(s) in the "
                    "last 24h."
                ),
            )
        )
    at_risk = int(
        snapshots.customer_success_rollup.get("at_risk_count", 0)
    )
    if snapshots.customer_success is not None and at_risk > 0:
        rolled.append(
            _alert_entry(
                "customer_at_risk_cohort",
                source_agent="customer_success",
                rationale=(
                    f"{at_risk} customer(s) flagged at-risk in the last 24h."
                ),
            )
        )
    # data_gap alerts from missing snapshots.
    for missing_key in missing or []:
        rolled.append(
            _alert_entry(
                "data_gap",
                source_agent=missing_key,
                rationale=(
                    f"No {missing_key} snapshot found in the last "
                    f"{ROLLUP_WINDOW_HOURS}h."
                ),
            )
        )
    rolled.sort(
        key=lambda entry: SEVERITY_ORDER.get(entry["severity"], 99)
    )
    return rolled


def compute_top_3_priorities(
    alerts: list[dict[str, Any]], snapshots: LatestSnapshots
) -> list[dict[str, Any]]:
    actionable = [
        entry
        for entry in alerts
        if entry["code"]
        not in {"all_clear", "no_agent_attribution_field"}
    ]
    if not actionable:
        return [
            {
                "priority": "1",
                "issue": "all_clear",
                "source_agent": "none",
                "recommended_action": "Continue monitoring.",
            }
        ]
    top: list[dict[str, Any]] = []
    for rank, entry in enumerate(actionable[:3], start=1):
        top.append(
            {
                "priority": str(rank),
                "issue": entry["code"],
                "source_agent": entry["source_agent"],
                "recommended_action": RECOMMENDED_ACTION.get(
                    entry["code"],
                    "Review the source agent snapshot and confirm.",
                ),
            }
        )
    return top


def compute_agent_status_summary(
    snapshots: LatestSnapshots,
) -> dict[str, dict[str, str]]:
    summary: dict[str, dict[str, str]] = {}
    if snapshots.customer_success is None:
        summary["customer_success"] = {
            "status": "missing",
            "summary": "No Customer Success snapshot in the last 24h.",
        }
    else:
        reorder = int(
            snapshots.customer_success_rollup.get(
                "reorder_candidate_count", 0
            )
        )
        at_risk = int(
            snapshots.customer_success_rollup.get("at_risk_count", 0)
        )
        summary["customer_success"] = {
            "status": "alert" if at_risk > 0 else "ok",
            "summary": (
                f"{reorder} reorder candidate(s), {at_risk} at risk."
            ),
        }

    if snapshots.rto_prevention is None:
        summary["rto_prevention"] = {
            "status": "missing",
            "summary": "No RTO Prevention snapshot in the last 24h.",
        }
    else:
        critical = int(snapshots.rto_rollup.get("critical_count", 0))
        high = int(snapshots.rto_rollup.get("high_count", 0))
        summary["rto_prevention"] = {
            "status": "alert" if critical + high > 0 else "ok",
            "summary": (
                f"{critical} critical, {high} high-tier order(s)."
            ),
        }

    if snapshots.cfo is None:
        summary["cfo"] = {
            "status": "missing",
            "summary": "No CFO snapshot in the last 24h.",
        }
    else:
        cfo_alerts = [
            a for a in (snapshots.cfo.alerts or []) if a != "all_clear"
        ]
        summary["cfo"] = {
            "status": "alert" if cfo_alerts else "ok",
            "summary": (
                f"24h revenue ₹{snapshots.cfo.revenue_24h}, "
                f"30d revenue ₹{snapshots.cfo.revenue_30d}."
            ),
        }

    if snapshots.data_analyst is None:
        summary["data_analyst"] = {
            "status": "missing",
            "summary": "No Data Analyst snapshot in the last 24h.",
        }
    else:
        da_alerts = [
            a
            for a in (snapshots.data_analyst.alerts or [])
            if a != "all_clear"
        ]
        summary["data_analyst"] = {
            "status": "alert" if da_alerts else "ok",
            "summary": (
                f"leads {snapshots.data_analyst.lead_count_30d} -> "
                f"calls {snapshots.data_analyst.call_count_30d} -> "
                f"confirmed {snapshots.data_analyst.confirmed_order_count_30d}."
            ),
        }

    if snapshots.calling_team_leader is None:
        summary["calling_team_leader"] = {
            "status": "missing",
            "summary": "No Calling Team Leader snapshot in the last 24h.",
        }
    else:
        ctl_alerts = [
            a
            for a in (snapshots.calling_team_leader.alerts or [])
            if a not in {"all_clear", "no_agent_attribution_field"}
        ]
        summary["calling_team_leader"] = {
            "status": "alert" if ctl_alerts else "ok",
            "summary": (
                f"calls 30d={snapshots.calling_team_leader.call_count_30d}, "
                f"connection={snapshots.calling_team_leader.connection_rate_30d:.2f}, "
                f"avg_duration={snapshots.calling_team_leader.avg_duration_seconds_30d:.0f}s."
            ),
        }
    return summary


def generate_briefing_text(
    snapshots: LatestSnapshots,
    *,
    score: int,
    tier: str,
    alerts: list[dict[str, Any]],
    priorities: list[dict[str, Any]],
    summary: dict[str, dict[str, str]],
) -> str:
    """Deterministic factual briefing. Internal-only."""
    lines: list[str] = []
    lines.append(
        f"Daily Director Briefing — health_score={score} tier={tier}."
    )
    lines.append("Agent status:")
    for key in AGENT_KEYS:
        entry = summary.get(key, {})
        lines.append(
            f"  - {key}: status={entry.get('status', 'missing')} - "
            f"{entry.get('summary', 'n/a')}"
        )
    if priorities:
        lines.append("Top priorities:")
        for entry in priorities:
            lines.append(
                f"  {entry['priority']}. {entry['issue']} "
                f"(source={entry['source_agent']}) -> "
                f"{entry['recommended_action']}"
            )
    else:
        lines.append("Top priorities: none.")
    actionable_alerts = [
        entry
        for entry in alerts
        if entry["code"]
        not in {"all_clear", "no_agent_attribution_field"}
    ]
    lines.append(
        f"Cross-cutting alerts: {len(actionable_alerts)} actionable."
    )
    return "\n".join(lines)


def build_snapshot(
    *,
    now: datetime | None = None,
    sandbox: bool = False,
) -> tuple[CeoOrchestrationSnapshot, LatestSnapshots]:
    """Build an unsaved snapshot + the source bundle for persistence."""
    now = now or timezone.now()
    snapshots = fetch_latest_snapshots(now=now)
    missing = [
        key for key in AGENT_KEYS if _is_missing(snapshots, key)
    ]
    score = compute_health_score(snapshots)
    tier = compute_health_tier(score)
    alerts = roll_up_alerts(snapshots, missing=missing)
    priorities = compute_top_3_priorities(alerts, snapshots)
    status_summary = compute_agent_status_summary(snapshots)
    briefing = generate_briefing_text(
        snapshots,
        score=score,
        tier=tier,
        alerts=alerts,
        priorities=priorities,
        summary=status_summary,
    )
    snapshot_alerts: list[str] = []
    if missing:
        snapshot_alerts.append(
            CeoOrchestrationSnapshot.Alert.DATA_GAP.value
        )
    actionable = [
        entry
        for entry in alerts
        if entry["code"]
        not in {"all_clear", "no_agent_attribution_field", "data_gap"}
    ]
    if not actionable:
        snapshot_alerts.append(
            CeoOrchestrationSnapshot.Alert.ALL_CLEAR.value
        )
    snapshot = CeoOrchestrationSnapshot(
        snapshot_at=now,
        business_health_score=score,
        health_tier=tier,
        customer_success_snapshot=snapshots.customer_success,
        rto_snapshot=snapshots.rto_prevention,
        cfo_snapshot=snapshots.cfo,
        data_analyst_snapshot=snapshots.data_analyst,
        calling_team_leader_snapshot=snapshots.calling_team_leader,
        cross_cutting_alerts=list(alerts),
        top_3_priorities=list(priorities),
        agent_status_summary=dict(status_summary),
        briefing_text=briefing,
        alerts=snapshot_alerts,
        sandbox=sandbox,
    )
    return snapshot, snapshots
