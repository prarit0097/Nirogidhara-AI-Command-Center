from __future__ import annotations

from django.contrib import admin

from .models import (
    AiActionWorkEvent,
    AiApprovedAction,
    AiApprovedActionEvent,
    AiCopilotReviewEvent,
    AiCopilotSuggestion,
)


@admin.register(AiCopilotSuggestion)
class AiCopilotSuggestionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "suggestion_type", "source_type", "status", "ai_mode",
        "external_action_taken", "created_at",
    )
    list_filter = (
        "suggestion_type", "source_type", "status", "ai_mode",
        "external_action_taken",
    )
    search_fields = ("title", "source_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AiCopilotReviewEvent)
class AiCopilotReviewEventAdmin(admin.ModelAdmin):
    list_display = ("id", "suggestion", "action", "actor", "created_at")
    list_filter = ("action",)
    readonly_fields = ("created_at",)


@admin.register(AiApprovedAction)
class AiApprovedActionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "action_type", "source_type", "status", "work_status",
        "department", "priority", "external_action_taken",
        "provider_action_taken", "created_at",
    )
    list_filter = (
        "action_type", "source_type", "status", "work_status", "department",
        "priority", "external_action_taken", "provider_action_taken",
    )
    search_fields = ("title", "source_id", "assigned_team")
    readonly_fields = ("created_at", "updated_at", "applied_at")


@admin.register(AiApprovedActionEvent)
class AiApprovedActionEventAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    readonly_fields = ("created_at",)


@admin.register(AiActionWorkEvent)
class AiActionWorkEventAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    readonly_fields = ("created_at",)
