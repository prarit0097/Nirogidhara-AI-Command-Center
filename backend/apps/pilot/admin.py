from __future__ import annotations

from django.contrib import admin

from .models import (
    PilotDecision,
    PilotDryRun,
    PilotPlan,
    PilotPlanEvent,
    PilotPlanReview,
    PilotTask,
    PilotTaskEvent,
)


@admin.register(PilotDryRun)
class PilotDryRunAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "scenario_type", "status", "provider_actions_blocked", "created_at")
    list_filter = ("scenario_type", "status", "provider_actions_blocked")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(PilotDecision)
class PilotDecisionAdmin(admin.ModelAdmin):
    list_display = ("id", "dry_run", "decision", "decided_by", "created_at")
    list_filter = ("decision",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(PilotPlan)
class PilotPlanAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "pilot_type", "status", "owner_team",
        "provider_actions_blocked", "created_at",
    )
    list_filter = ("pilot_type", "status", "provider_actions_blocked")
    search_fields = ("name", "owner_team", "problem_category")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PilotPlanEvent)
class PilotPlanEventAdmin(admin.ModelAdmin):
    list_display = ("id", "pilot_plan", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    readonly_fields = ("created_at",)


@admin.register(PilotPlanReview)
class PilotPlanReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "pilot_plan", "decision", "decided_by", "created_at")
    list_filter = ("decision",)
    readonly_fields = ("created_at",)


@admin.register(PilotTask)
class PilotTaskAdmin(admin.ModelAdmin):
    list_display = (
        "id", "pilot_plan", "team_role", "title", "status",
        "assigned_to", "provider_actions_blocked", "created_at",
    )
    list_filter = ("team_role", "status", "priority", "provider_actions_blocked")
    search_fields = ("title", "assigned_team_label")
    readonly_fields = ("created_at", "updated_at", "started_at", "completed_at")


@admin.register(PilotTaskEvent)
class PilotTaskEventAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    readonly_fields = ("created_at",)
