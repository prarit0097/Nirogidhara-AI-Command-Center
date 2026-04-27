from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AdsAnalyzeView,
    AgentBudgetViewSet,
    AgentRunViewSet,
    AgentRuntimeStatusView,
    ApprovalMatrixView,
    CaioAuditSweepView,
    CaioAuditViewSet,
    CeoBriefingView,
    CeoDailyBriefView,
    CfoAnalyzeView,
    ComplianceAnalyzeView,
    PromptVersionActivateView,
    PromptVersionRollbackView,
    PromptVersionViewSet,
    RtoAnalyzeView,
    SalesGrowthAnalyzeView,
    SandboxStatusView,
    SchedulerStatusView,
)

router = DefaultRouter()
router.register("agent-runs", AgentRunViewSet, basename="agent-run")
router.register("prompt-versions", PromptVersionViewSet, basename="prompt-version")
router.register("budgets", AgentBudgetViewSet, basename="agent-budget")

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
    # Phase 3D — sandbox toggle + prompt version activate / rollback.
    path(
        "sandbox/status/",
        SandboxStatusView.as_view(),
        name="ai-sandbox-status",
    ),
    path(
        "prompt-versions/<str:pk>/activate/",
        PromptVersionActivateView.as_view(),
        name="prompt-version-activate",
    ),
    path(
        "prompt-versions/<str:pk>/rollback/",
        PromptVersionRollbackView.as_view(),
        name="prompt-version-rollback",
    ),
    # Phase 3E — approval matrix policy snapshot.
    path(
        "approval-matrix/",
        ApprovalMatrixView.as_view(),
        name="ai-approval-matrix",
    ),
] + router.urls
