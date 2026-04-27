from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AdsAnalyzeView,
    AgentRunViewSet,
    AgentRuntimeStatusView,
    CaioAuditSweepView,
    CaioAuditViewSet,
    CeoBriefingView,
    CeoDailyBriefView,
    CfoAnalyzeView,
    ComplianceAnalyzeView,
    RtoAnalyzeView,
    SalesGrowthAnalyzeView,
    SchedulerStatusView,
)

router = DefaultRouter()
router.register("agent-runs", AgentRunViewSet, basename="agent-run")

urlpatterns = [
    path("ceo-briefing/", CeoBriefingView.as_view(), name="ceo-briefing"),
    path("caio-audits/", CaioAuditViewSet.as_view({"get": "list"}), name="caio-audits"),
    # Phase 3B — per-agent runtime endpoints (admin/director only).
    path(
        "agent-runtime/status/",
        AgentRuntimeStatusView.as_view(),
        name="agent-runtime-status",
    ),
    path(
        "agent-runtime/ceo/daily-brief/",
        CeoDailyBriefView.as_view(),
        name="agent-runtime-ceo",
    ),
    path(
        "agent-runtime/caio/audit-sweep/",
        CaioAuditSweepView.as_view(),
        name="agent-runtime-caio",
    ),
    path(
        "agent-runtime/ads/analyze/",
        AdsAnalyzeView.as_view(),
        name="agent-runtime-ads",
    ),
    path(
        "agent-runtime/rto/analyze/",
        RtoAnalyzeView.as_view(),
        name="agent-runtime-rto",
    ),
    path(
        "agent-runtime/sales-growth/analyze/",
        SalesGrowthAnalyzeView.as_view(),
        name="agent-runtime-sales-growth",
    ),
    path(
        "agent-runtime/cfo/analyze/",
        CfoAnalyzeView.as_view(),
        name="agent-runtime-cfo",
    ),
    path(
        "agent-runtime/compliance/analyze/",
        ComplianceAnalyzeView.as_view(),
        name="agent-runtime-compliance",
    ),
    # Phase 3C — Celery / scheduler / cost snapshot.
    path(
        "scheduler/status/",
        SchedulerStatusView.as_view(),
        name="ai-scheduler-status",
    ),
] + router.urls
