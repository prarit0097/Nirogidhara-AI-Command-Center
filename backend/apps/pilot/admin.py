from __future__ import annotations

from django.contrib import admin

from .models import PilotDecision, PilotDryRun


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
